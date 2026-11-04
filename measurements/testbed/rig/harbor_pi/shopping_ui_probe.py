"""Harbor-owned trusted UI/operation probe. No model calls or task substitution."""
import argparse
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil

from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths
import runner
from harbor_pi.bridge import RIG,docker_env
from harbor_pi.browser_image import image_id
from harbor_pi.shopping_candidate_probe import IMAGE

VERIFIER_IMAGE='pi-real-verifier:2026-10-31-v2'
VERIFIER_ID='sha256:03d8f3d01350ff704df7c43c1fda22d8ef301623cff65f687dd75770cb274469'


async def probe(output,operation,state_negative=False):
    if image_id(VERIFIER_IMAGE)!=VERIFIER_ID or not image_id(IMAGE):
        raise ValueError('Cached images missing/mismatched; no download authorized')
    output=output.resolve();output.mkdir(mode=0o700)
    folder=output/'environment';folder.mkdir()
    sources=output/'frozen-source';sources.mkdir()
    source_hashes={}
    for name in ('shopping_ui_probe.py','shopping_ui_ops.py','shopping_original_verify.py'):
        source=RIG/'harbor_pi'/name
        shutil.copyfile(source,sources/name)
        source_hashes[name]=hashlib.sha256(source.read_bytes()).hexdigest()
    policy=folder/'seccomp.json';shutil.copyfile(RIG/'harbor_pi/pilot_image/seccomp.json',policy)
    (folder/'docker-compose.yaml').write_text(json.dumps({'networks':{'default':{'internal':True}},'services':{
        'main':{'security_opt':['seccomp='+str(policy)],'shm_size':'256m'},
        'shopping':{'image':IMAGE,'command':['supervisord','-n','-j','/supervisord.pid'],
            'cpus':2,'mem_limit':'3072m','environment':{'WA_ENV_CTRL_EXTERNAL_SITE_URL':'http://shopping/'}}
    }}))
    paths=TrialPaths(output/'trial');paths.mkdir()
    session='shopping-ui-'+output.name
    env=DockerEnvironment(environment_dir=folder,environment_name='shopping-ui',session_id=session,
        trial_paths=paths,task_env_config=EnvironmentConfig(docker_image=VERIFIER_IMAGE,cpus=2,memory_mb=2048))
    report={'model_calls':0,'image':IMAGE,'browser':'pinned Chrome, sandbox enabled',
            'operation':operation,'state_negative':state_negative,'source_hashes':source_hashes,
            'application_network_internal':True,'candidate_admitted':False,'task_replaced':False}
    async def command(name,text,service='main',user='root',timeout=240,expected=0):
        result=await env.service_exec(text,service=service,user=user,timeout_sec=timeout)
        (output/(name+'.stdout')).write_text(result.stdout or '')
        (output/(name+'.stderr')).write_text(result.stderr or '')
        if result.return_code!=expected:
            raise RuntimeError(name+' unexpected exit '+str(result.return_code))
        return result
    try:
        await env.start(force_build=False)
        await command('start','env-ctrl start --wait --timeout 180',service='shopping')
        await command('configure','env-ctrl init --base-url http://shopping/',service='shopping')
        await env.upload_file(RIG/'harbor_pi/shopping_ui_ops.py','/home/study/shopping_ui_ops.py')
        ui_operation='inspect' if state_negative else operation
        result=await command('ui','/opt/verifier/bin/python /home/study/shopping_ui_ops.py '+ui_operation,user='study',timeout=600)
        report['ui_exit_code']=result.return_code
        if operation!='inspect':
            task={'segmentation':'customer_segmentation_setup','products':'products_sales_analysis'}[operation]
            reference=RIG/'runtime/real-task-preparation/mcpmark/tasks/playwright_webarena/standard/shopping_admin'/task
            report['reference_hashes']={}
            for name in ('verify.py','label.txt'):
                path=reference/name
                shutil.copyfile(path,sources/name)
                report['reference_hashes'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
            await env.upload_dir(reference,'/home/study/reference-tests')
            await env.upload_file(RIG/'harbor_pi/shopping_original_verify.py','/home/study/shopping_original_verify.py')
            if state_negative:
                await command('synthetic-reference-answer',"""/opt/verifier/bin/python - <<'PY'
import json
from pathlib import Path
text=Path('/home/study/reference-tests/label.txt').read_text()
if '<answer>' not in text:text='<answer>\\n'+text+'\\n</answer>'
Path('/home/study/probe-output/oracle-messages.json').write_text(json.dumps([{'role':'assistant','status':'completed','type':'message','content':[{'type':'output_text','text':text}]}]))
PY""",user='study')
            base='/opt/verifier/bin/python /home/study/shopping_original_verify.py /home/study/reference-tests/verify.py '
            result=await command('original-verifier',base+'/home/study/probe-output/oracle-messages.json',user='study',expected=1 if state_negative else 0)
            report['original_verifier_reward']=0 if result.return_code else 1
            if state_negative:
                verifier_output=(result.stdout or '')+(result.stderr or '')
                if 'Starting Browser Verification' not in verifier_output or 'customer group not found' not in verifier_output:
                    raise RuntimeError('Negative must fail actual state, not response parsing')
                report['state_negative_confirmed']=True
            else:
                await command('wrong-response',"""/opt/verifier/bin/python - <<'PY'
import json
from pathlib import Path
p=Path('/home/study/probe-output/oracle-messages.json')
data=json.loads(p.read_text());data[0]['content'][0]['text']='<answer>incorrect</answer>'
p.with_name('wrong-messages.json').write_text(json.dumps(data))
PY""",user='study')
                await command('original-verifier-negative',base+'/home/study/probe-output/wrong-messages.json',user='study',expected=1)
                report['wrong_response_rejected']=True
    except Exception as exc:
        report['error']=str(exc)
        raise
    finally:
        try:
            await env.download_dir('/home/study/probe-output',output/'ui-output')
        except Exception as exc:
            report['ui_output_collection_error']=type(exc).__name__
        try:
            await env.stop(delete=True)
            report['harbor_cleanup_completed']=True
        except Exception as exc:
            report['harbor_cleanup_completed']=False
            report['cleanup_error']=type(exc).__name__
        report['shared_images_retained']=image_id(VERIFIER_IMAGE)==VERIFIER_ID and bool(image_id(IMAGE))
        runner.atomic_write_json(output/'report.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--operation',choices=['inspect','segmentation','products'],default='inspect')
    p.add_argument('--state-negative',action='store_true',help='Correct synthetic response but untouched application')
    p.add_argument('--execute',action='store_true')
    a=p.parse_args()
    if not a.execute:p.error('--execute required; creates only disposable Harbor environments')
    if a.state_negative and a.operation!='segmentation':p.error('--state-negative requires segmentation')
    os.environ.update(docker_env())
    with (RIG/'runtime/harbor-pilot-controller.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        asyncio.run(probe(a.output,a.operation,a.state_negative))
