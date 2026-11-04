"""Zero-model retained-artifact restore diagnostic; Harbor owns both services."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths
from harbor_pi.bridge import RIG,docker_env
from harbor_pi.shopping_state import compose,marker_for,SQL,CHECKSUM,IMAGE
from harbor_pi.shopping_ui_probe import VERIFIER_IMAGE,VERIFIER_ID
from harbor_pi.browser_image import image_id


async def probe(output,artifacts):
    if image_id(VERIFIER_IMAGE)!=VERIFIER_ID or not image_id(IMAGE):raise ValueError('Cached image required')
    output=output.resolve();output.mkdir(mode=0o700)
    folder=output/'environment';folder.mkdir()
    policy=folder/'seccomp.json';shutil.copyfile(RIG/'harbor_pi/pilot_image/seccomp.json',policy)
    marker=marker_for(output)
    (folder/'docker-compose.yaml').write_text(json.dumps(compose({'security_opt':['seccomp='+str(policy)]},verifier=True,marker=marker)))
    paths=TrialPaths(output/'trial');paths.mkdir()
    env=DockerEnvironment(environment_dir=folder,environment_name='restore',session_id='restore-'+output.name,
        trial_paths=paths,task_env_config=EnvironmentConfig(docker_image=VERIFIER_IMAGE,cpus=2,memory_mb=2048))
    report={'model_calls':0,'diagnostic_only':True}
    source=output/'frozen-source';source.mkdir()
    for name in ('shopping_restore_probe.py','shopping_state.py','actual_verify.py'):
        shutil.copyfile(RIG/'harbor_pi'/name,source/name)
    async def command(name,text,service='main',user='root'):
        result=await env.service_exec(text,service=service,user=user,timeout_sec=120)
        (output/(name+'.stdout')).write_text(result.stdout or '')
        (output/(name+'.stderr')).write_text(result.stderr or '')
        return result
    try:
        expected=(artifacts/'shopping-state.sha256').read_text().split()[0]
        if hashlib.sha256((artifacts/'shopping-state.sql').read_bytes()).hexdigest()!=expected:
            raise ValueError('Retained state checksum mismatch')
        await env.start(force_build=False)
        await env.upload_file(artifacts/'shopping-state.sql',SQL)
        await env.upload_file(artifacts/'shopping-state.sha256',CHECKSUM)
        await env.upload_file(RIG/'harbor_pi/actual_verify.py','/home/study/actual_verify.py')
        code="from actual_verify import state_server; import time; s=state_server('"+marker+"'); print(s.restore_ready.wait(110),flush=True); time.sleep(120)"
        await command('server-start','cd /home/study; nohup /opt/verifier/bin/python -u -c '+shlex.quote(code)+' </dev/null >/tmp/state-server.log 2>&1 &',user='study')
        await asyncio.sleep(75)
        await command('shopping-diagnostic',"python3 - <<'PY'\nfrom pathlib import Path\nfor name in ('restore-start.log','restore-checksum.log','restore-db.log','restore-init.log','shopping-state.sha256'):\n p=Path('/tmp')/name; print(name, p.exists()); print(p.read_text()[-10000:] if p.exists() else '')\nprint('sql',Path('/tmp/shopping-state.sql').exists())\nPY",service='shopping')
        result=await command('server-diagnostic',"python3 -c \"from pathlib import Path;print(Path('/tmp/state-server.log').read_text())\"")
        report['restore_ready']='True' in (result.stdout or '').splitlines()
        result=await command('network-diagnostic','wget -S -O - http://main:8765/shopping-state.sha256',service='shopping')
        report['network_exit']=result.return_code

    finally:
        await env.stop(delete=True)
        report['harbor_cleanup_completed']=True
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True)
    a=p.parse_args();os.environ.update(docker_env())
    import fcntl
    with (RIG/'runtime/harbor-pilot-controller.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);asyncio.run(probe(a.output,a.artifacts))
