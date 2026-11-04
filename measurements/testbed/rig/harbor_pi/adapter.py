"""Run Pi INSIDE Harbor's environment; never nest the native campaign runner.

The legacy smoke supports control_1/required only. An explicit engineering
pilot manifest admits the six migrated tasks and required/full catalogs.
Native events/sessions remain the source of truth; ATIF is a derived view.
"""
from __future__ import annotations

import json
import shlex
import tempfile
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.agents.capabilities import AgentCapabilities
from harbor.models.trajectories.trajectory import Trajectory

import runner

WORK = "/home/study/workspace"
AGENT = "/home/study/.pi-experiment"
LOGS = "/logs/agent"
PI = "/opt/pi/node_modules/.bin/pi"


def cell_id(spec):
    """Stable directory/job identity; retain the one-repetition pilot names."""
    name = '-'.join(str(spec[k]) for k in ('task', 'model', 'mode', 'catalog'))
    return name + (f'-r{spec["rep"]:02d}' if 'rep' in spec else '')


def cell_limits(manifest, spec):
    """Resolve the same per-cell limits for preparation, execution and provenance."""
    budget = manifest.get('budget', {})
    task = manifest['tasks'][spec['task']]
    tokens = budget.get('max_total_tokens', 250000)
    if spec.get('mode') == 'eager' and 'playwright' in task.get('catalog', []):
        tokens = budget.get('browser_eager_max_tokens', tokens)
    deadline = task['deadline_s']
    if type(tokens) is not int or tokens <= 0 or type(deadline) is not int or deadline <= 10:
        raise ValueError('Positive integer token cap and integer deadline >10s required')
    return {'max_total_tokens': tokens, 'deadline_s': deadline,
            'watchdog_deadline_s': deadline - 10}


def checked_spec(manifest, task, mode, model, catalog="required", rep=None):
    spec = {"task": task, "mode": mode, "model": model, "catalog": catalog}
    if rep is not None:
        if type(rep) is not int or not 1 <= rep <= manifest['matrix'].get('reps', 1):
            raise ValueError('Repetition outside manifest range')
        spec['rep'] = rep
    pilot = bool(manifest["harness"].get("harbor_pilot_image"))
    from harbor_pi.pilot_support import TASKS
    allowed = set(TASKS)
    if manifest['harness'].get('harbor_actual_tasks'):
        from harbor_pi.actual_tasks import TASKS as actual_tasks, validate
        allowed |= actual_tasks
        if task in actual_tasks:
            validate(manifest, task)
    if (task not in manifest["tasks"] or task not in (allowed if pilot else {"control_1"})
            or catalog not in (("required", "full") if pilot else ("required",))
            or mode not in runner.MODES or model not in manifest["models"]):
        raise ValueError("Unsupported Harbor task, catalog, mode or model")
    if not pilot and (manifest["tasks"][task]["capabilities"] or manifest["tasks"][task]["catalog"]):
        raise ValueError("Capability tasks require the explicit container pilot manifest")
    if manifest["harness"]["required_version"] != "1.0.4":
        raise ValueError("Only Pi 1.0.4 is supported")
    if manifest["models"][model].get("thinking") != "max":
        raise ValueError("Study model must use max thinking")
    return spec


def to_atif(events, instruction, model):
    """Text/control conversion; preserve raw messages including unmapped blocks.

    No claim to static-token attribution or full session/auxiliary accounting.
    No billing estimate is represented as actual cost.
    """
    steps = [{"step_id": 1, "source": "user", "message": instruction}]
    calls = {}
    usage = []
    errors = []
    for event in events:
        if event.get("type") != "message_end":
            continue
        message = event.get("message", {})
        content = message.get("content", [])
        text = content if isinstance(content, str) else "\n".join(
            block.get("text", "") for block in content if block.get("type") == "text")
        if message.get("role") == "assistant":
            step = {"step_id": len(steps) + 1, "source": "agent", "message": text,
                    "model_name": model, "reasoning_effort": "max",
                    "extra": {"pi_message": message}}
            tools = [b for b in content if isinstance(b, dict) and b.get("type") == "toolCall"]
            if tools:
                step["tool_calls"] = [{"tool_call_id": b["id"], "function_name": b["name"],
                                       "arguments": b["arguments"]} for b in tools]
                for tool in tools:
                    calls[tool["id"]] = step
            steps.append(step)
            if message.get("usage"):
                usage.append(message["usage"])
            if message.get("stopReason") == "error":
                errors.append(message.get("errorMessage") or "provider error")
        elif message.get("role") == "toolResult":
            call_id = message.get("toolCallId")
            if call_id not in calls:
                raise ValueError("Unmatched Pi tool result; raw events retained")
            obs = calls[call_id].setdefault("observation", {"results": []})
            obs["results"].append({"source_call_id": call_id, "content": text,
                                   "extra": {"pi_message": message}})
    trajectory = Trajectory.model_validate({
        "schema_version": "ATIF-v1.8", "agent": {"name": "pi-research", "version": "1.0.4",
        "model_name": model}, "steps": steps,
        "notes": "Derived text/control trajectory. Native events/sessions authoritative; auxiliary usage not summed.",
    })
    return trajectory.model_dump(mode="json", exclude_none=True), usage, errors


class PiAgent(BaseAgent):
    capabilities = AgentCapabilities(atif=True)

    @staticmethod
    def name():
        return "pi-research"

    def version(self):
        return "1.0.4"

    def __init__(self, *, manifest_path, manifest_digest, task, mode, model, catalog="required", rep=None, **kwargs):
        super().__init__(**kwargs)
        if self.mcp_servers or self.skills_dir or self.extra_env:
            raise ValueError("Harbor resource injection is disabled; the study manifest owns resources")
        self.manifest = runner.load_manifest(Path(manifest_path))
        if self.manifest['harness'].get('campaign_execution_authorized', True) is not True:
            raise ValueError('Proposed campaign is not authorized for agent execution')
        from harbor_pi.campaign_freeze import verify_freeze
        verify_freeze(self.manifest, manifest_path)
        if runner.sha256_json(self.manifest) != manifest_digest:
            raise ValueError("Study manifest or source assets changed after preparing this Harbor job")
        self.spec = checked_spec(self.manifest, task, mode, model, catalog, rep)
        selected = self.manifest["models"][model]
        if self.model_name != f"{selected['provider']}/{selected['id']}":
            raise ValueError("Harbor and manifest model selections differ")
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    async def setup(self, environment):
        # Never mount the host home, gh config, Docker socket, or reference tree.
        result = await environment.exec(f"{PI} --version", user="study", timeout_sec=30)
        if result.return_code or (result.stdout or "").strip() != "1.0.4":
            raise RuntimeError("Container Pi version check failed")
        await self._exec(environment, f"mkdir -p {AGENT} {WORK} {LOGS}/sessions; chmod 700 {AGENT}")
        provider = self.manifest["models"][self.spec["model"]]["provider"]
        auth = json.loads(Path(self.manifest["harness"]["auth_source"]).read_text())
        if provider not in auth:
            raise ValueError("Selected provider missing from private auth source")
        self._original_provider_auth = auth[provider]
        with tempfile.TemporaryDirectory(prefix="pi-harbor-config-") as tmp:
            root = Path(tmp)
            auth_source = root / "provider-auth.json"
            auth_source.write_text(json.dumps({provider: auth[provider]}))
            auth_source.chmod(0o600)
            m = json.loads(json.dumps(self.manifest))
            m["harness"].update(auth_source=str(auth_source), auth_mode="copy")
            info = runner.prepare_agent_dir(m, self.spec, {}, root)
            for source in info["agent_dir"].iterdir():
                if source.is_dir():
                    await environment.upload_dir(source, f"{AGENT}/{source.name}")
                else:
                    await environment.upload_file(source, f"{AGENT}/{source.name}")
            permissions = await environment.exec(
                f"chown -R study:study {AGENT} && find {AGENT} -type f -exec chmod 600 {{}} +"
                f" && find {AGENT} -type d -exec chmod 700 {{}} +", user="root")
            if permissions.return_code:
                raise RuntimeError("Failed to restrict uploaded Pi configuration permissions")
        if self.manifest['harness'].get('harbor_pilot_image'):
            from harbor_pi.pilot_support import setup
            await setup(self, environment)
        # This selected-provider file is agent-readable by design. The pilot
        # persists only its refresh via compare-and-swap, never the other logins.

    async def _exec(self, environment, command):
        result = await environment.exec(command, user="study", cwd=WORK)
        if result.return_code:
            raise RuntimeError(f"Pi environment operation failed (exit {result.return_code}); private logs retained")
        return result

    async def run(self, instruction, environment, context):
        m = json.loads(json.dumps(self.manifest))
        from harbor_pi.route_contract import instruction_for
        instruction = instruction_for(m, instruction)
        m["harness"]["binary"] = PI
        argv = runner.build_argv(m, self.spec, instruction, Path(AGENT), Path(LOGS) / "sessions")
        env = {"HOME": "/home/study", "USER": "study", "LOGNAME": "study", "LANG": "C.UTF-8",
               "PATH": "/opt/pi/node_modules/.bin:/usr/local/bin:/usr/bin:/bin",
               "PI_CODING_AGENT_DIR": AGENT, "PI_SKIP_VERSION_CHECK": "1", "PI_OFFLINE": "1"}
        pilot = bool(m['harness'].get('harbor_pilot_image'))
        if pilot:
            argv[-2:-2] = ['-e', '/opt/study/observer.ts']
        prefix = "env -i " + " ".join(shlex.quote(f"{k}={v}") for k, v in env.items())
        if pilot:
            inner = '. /home/study/.trial-env; exec /usr/local/bin/python3 /opt/study/execute.py ' + shlex.join(argv)
            command = prefix + ' /bin/sh -c ' + shlex.quote(inner)
        else:
            command = prefix + " " + shlex.join(argv) + f" > {LOGS}/events.jsonl 2> {LOGS}/stderr.txt"
        if pilot:
            await self._exec(environment, f'touch {LOGS}/events.jsonl')
        try:
            result = await environment.exec(command, cwd=WORK, user="study")
        finally:
            if pilot:
                from harbor_pi.pilot_support import persist_auth
                state = await persist_auth(self, environment)
                (self.logs_dir / 'auth-refresh-status.json').write_text(json.dumps({'status': state}) + '\n')
        with tempfile.TemporaryDirectory(prefix="pi-harbor-events-") as tmp:
            local = Path(tmp) / "events.jsonl"
            await environment.download_file(f"{LOGS}/events.jsonl", local)
            events = [json.loads(line) for line in local.read_text().split('\n') if line.strip()]
        if pilot and self.spec['task'] == 'cap_brave':
            from harbor_pi.search_provenance import derive
            with tempfile.TemporaryDirectory(prefix='pi-brave-provenance-') as tmp:
                root = Path(tmp)
                await environment.download_dir(f'{LOGS}/cli-traces', root / 'traces')
                proof = root / 'provenance.json'
                proof.write_text(json.dumps(derive(events, root / 'traces', self.spec['mode'])))
                await environment.upload_file(proof, '/opt/study/brave-provenance.json')
                permissions = await environment.exec('chown root:root /opt/study/brave-provenance.json && chmod 644 /opt/study/brave-provenance.json', user='root')
                if permissions.return_code:
                    raise RuntimeError('Cannot protect independently observed search provenance')
        trajectory, usage, errors = to_atif(events, instruction, self.model_name)
        (self.logs_dir / "trajectory.json").write_text(json.dumps(trajectory, indent=2) + "\n")
        (self.logs_dir / "usage-scope.json").write_text(json.dumps({
            "scope": "assistant-message usage only; auxiliary/session accounting pending",
            "messages": usage, "complete_run_accounting": False, "actual_billed_cost": None,
        }, indent=2) + "\n")
        if pilot:
            from harbor_pi.pilot_support import session_usage
            with tempfile.TemporaryDirectory(prefix='pi-session-ledger-') as tmp:
                await environment.download_dir(f'{LOGS}/sessions', Path(tmp) / 'sessions')
                ledger = session_usage(Path(tmp) / 'sessions')
            (self.logs_dir / 'session-usage.json').write_text(json.dumps(ledger, indent=2) + '\n')
            context.n_input_tokens = ledger['input_tokens']
            context.n_output_tokens = ledger['output_tokens']
            context.n_cache_tokens = ledger['cache_read_tokens']
        elif usage:
            context.n_input_tokens = sum(u.get("input", 0) + u.get("cacheRead", 0)
                                         + u.get("cacheWrite", 0) for u in usage)
            context.n_output_tokens = sum(u.get("output", 0) for u in usage)
            context.n_cache_tokens = sum(u.get("cacheRead", 0) for u in usage)
        # cost_usd stays None: subscription/catalog estimates are not actual bills.
        if result.return_code or errors or not usage:
            raise RuntimeError("Pi failed or emitted no usage; inspect private native logs (no automatic replay)")
