"""Prepare one Harbor control trial, inspect readiness, or execute explicitly.

Harbor owns execution/timeout/verification. This module does not invoke the
old campaign loop or retry a failed primary attempt. Docker is mandatory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from harbor.models.job.config import JobConfig
from harbor.models.task.task import Task

import runner
from harbor_pi.adapter import checked_spec

RIG = Path(__file__).resolve().parents[1]
TESTBED = RIG.parent


def prepare(manifest_path, output, mode, model, oracle=False, *, task_name='control_1', catalog='required'):
    m = runner.load_manifest(manifest_path)
    spec = checked_spec(m, task_name, mode, model, catalog)
    if m['harness'].get('harbor_pilot_image'):
        from harbor_pi.pilot import prepare_task
        return prepare_task(manifest_path, output, spec, oracle)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    task = output / "task"
    env = task / "environment"
    shutil.copytree(Path(__file__).parent / "image", env)
    instruction = Path(m["tasks"]["control_1"]["instruction"])
    shutil.copyfile(instruction, task / "instruction.md")
    # Only the environment/ subtree is the Docker build context.
    tests = task / "tests"
    tests.mkdir()
    # Harbor 0.23.0 builds separate verifiers from tests/, not environment/.
    # Give it its own minimal image; never move references into the agent context.
    base = (env / "Dockerfile").read_text().split("WORKDIR /opt/pi", 1)[0]
    (tests / "Dockerfile").write_text(base + "COPY . /tests\nRUN mkdir -p /home/study/workspace\nWORKDIR /home/study/workspace\n")
    source = TESTBED / "controls" / "control_1_filter_sort"
    target = tests / "testbed" / "controls" / "control_1_filter_sort"
    for relative in ("verify.py", "expected/result.json", "fixtures/records.json"):
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, path)
    common = tests / "testbed" / "common"
    common.mkdir(parents=True)
    shutil.copyfile(TESTBED / "common" / "verify_lib.py", common / "verify_lib.py")
    # Keep verifier code 2/3/4 distinct in an exit-code artifact, even though
    # Harbor's scalar reward has only pass/fail. Infrastructure error != wrong answer.
    (tests / "test.sh").write_text('''#!/bin/sh
set -u
python3 /tests/testbed/controls/control_1_filter_sort/verify.py --artifacts /home/study/workspace
rc=$?
printf '%s\\n' "$rc" > /logs/verifier/original-exit-code.txt
case "$rc" in
  0) printf '1\\n' > /logs/verifier/reward.txt ;;
  1|2|3) printf '0\\n' > /logs/verifier/reward.txt ;;
  *) exit "$rc" ;;
esac
''')
    solution = task / "solution"
    solution.mkdir()
    shutil.copyfile(source / "expected" / "result.json", solution / "result.json")
    (solution / "solve.sh").write_text("#!/bin/sh\nset -eu\ncp /solution/result.json /home/study/workspace/result.json\n")
    (task / "task.toml").write_text('''version = "1.0"
[agent]
timeout_sec = 600
user = "study"
[environment]
build_timeout_sec = 900
cpus = 2
memory_mb = 4096
[verifier]
timeout_sec = 120
user = "root"
environment_mode = "separate"
[[artifacts]]
source = "/home/study/workspace/result.json"
destination = "result.json"
''')
    selected = m["models"][model]
    agent = ({"name": "oracle"} if oracle else {
        "import_path": "harbor_pi.adapter:PiAgent",
        "model_name": f"{selected['provider']}/{selected['id']}",
        "kwargs": {"manifest_path": str(manifest_path.resolve()), "manifest_digest": runner.sha256_json(m),
                   **{k: spec[k] for k in ("task", "mode", "model", "catalog")}},
    })
    config = {"job_name": f"control1-{mode}-{model}-{'oracle' if oracle else 'pi'}",
              "jobs_dir": str(output / "jobs"), "n_attempts": 1,
              "n_concurrent_trials": 1, "retry": {"max_retries": 0},
              "environment": {"type": "docker"}, "agents": [agent],
              "tasks": [{"path": str(task)}]}
    JobConfig.model_validate(config)
    Task(task)  # Validate Harbor task format before any container/model work.
    job = output / "job.json"
    job.write_text(json.dumps(config, indent=2) + "\n")
    (output / "scope.json").write_text(json.dumps({
        "status": "prepared, NOT executed", "spec": spec,
        "execution_owner": "Harbor 0.23.0", "primary_attempts": 1,
        "n_concurrent_trials": 1, "automatic_retries": 0,
        "verifier": "separate container, reference data not baked into image",
        "quota_recovery": "outer controller integration pending; preserve failures, do not replay",
        "image_freeze": "base digest + npm lock pinned; apt packages still need final image digest",
    }, indent=2) + "\n")
    return job


def docker_env():
    env = dict(os.environ)
    env.setdefault("DOCKER_CONFIG", str(RIG / "runtime/docker-client"))
    return env


def docker_ready():
    try:
        for command in (["docker", "info", "--format", "{{.ServerVersion}}"],
                        ["docker", "compose", "version"]):
            p = subprocess.run(command, env=docker_env(), capture_output=True,
                               text=True, timeout=15)
            if p.returncode:
                return False
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True


def result_exit_code(path):
    if not path.is_file():
        return 1
    result = json.loads(path.read_text())
    stats = result.get("stats", {})
    return int(stats.get("n_errored_trials", 1) != 0 or
               stats.get("n_completed_trials") != result.get("n_total_trials") or
               not result.get("n_total_trials"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor")
    prep = sub.add_parser("prepare")
    prep.add_argument("--manifest", type=Path, default=RIG / "examples" / "smoke.toml")
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--mode", choices=runner.MODES, default="eager")
    prep.add_argument("--model", default="gpt6luna")
    prep.add_argument("--oracle", action="store_true", help="Zero-model Harbor plumbing test")
    prep.add_argument('--task', default='control_1')
    prep.add_argument('--catalog', choices=('required', 'full'), default='required')
    run = sub.add_parser("run")
    run.add_argument("job", type=Path)
    run.add_argument("--execute", action="store_true", help="Explicit container/model execution consent")
    args = p.parse_args()
    if args.action == "doctor":
        ready = docker_ready()
        print("Harbor 0.23.0 installed; Docker + Compose:", "accessible" if ready else "BLOCKED (missing dependency or permission denied)")
        print("No model calls. Container builds/Chrome sandboxing not established by this check.")
        return 0 if ready else 1
    if args.action == "prepare":
        print(prepare(args.manifest, args.output, args.mode, args.model, args.oracle,
                      task_name=args.task, catalog=args.catalog))
        print("Prepared only; no Docker build, provider call, or verifier execution claimed.")
        return 0
    if not args.execute:
        p.error("run requires --execute; may spend model tokens")
    config = JobConfig.model_validate_json(args.job.read_text())
    if config.n_concurrent_trials != 1 or config.retry.max_retries != 0 or config.n_attempts != 1:
        p.error("Integration trials must be sequential with one attempt and zero retries")
    result_path = config.jobs_dir / config.job_name / "result.json"
    if result_path.parent.exists():
        p.error("Job already has execution artifacts; use a fresh prepared job, never silently replay")
    if not docker_ready():
        print("BLOCKED: Docker/Compose inaccessible. No trial launched or credential uploaded.", file=sys.stderr)
        return 2
    env = docker_env()
    env["PYTHONPATH"] = str(RIG)  # Custom agent import; no personal Python modules.
    process = subprocess.run([str(Path(sys.executable).parent / "harbor"), "run", "--config", str(args.job.resolve())], env=env)
    if process.returncode:
        return process.returncode
    # Harbor can exit 0 even when every trial has an infrastructure exception.
    if not result_path.is_file():
        print("Harbor returned without a result file; execution is not successful", file=sys.stderr)
        return 1
    return result_exit_code(result_path)


if __name__ == "__main__":
    raise SystemExit(main())
