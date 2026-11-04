"""Fresh, private, per-attempt study repositories; public pinned inputs cached once.

Never reset the historical harmony repository. Delete only repositories whose
creation ID and marker were recorded by this attempt, after a complete bundle
and PR evidence have been retained. No credentials in commands or git config.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from harbor_pi.bridge import RIG

BASES = {
 'find_salient_file': ('missing-semester','05c436fbdf0d3d90cfaa86f22bd37ad9bd1608fa','master'),
 'release_management_workflow': ('harmony','f348e7689f5f0599b7cfef7de6d6a597a57615c7','main'),
}
# The constructed publication task has no prescribed source repository. Reuse
# the cached pinned history on a fresh owned target; never reset historical harmony.
BASES['composite_2']=BASES['release_management_workflow']
def evaluation_owner():
    owner = os.environ.get('GITHUB_EVAL_ORG', '')
    if not re.fullmatch(r'[A-Za-z0-9-]{1,39}', owner):
        raise ValueError('Set GITHUB_EVAL_ORG to a disposable GitHub account')
    return owner


def api(method, path, data=None, missing=False):
    token = os.environ.get('STUDY_GITHUB_TOKEN')
    if not token:
        raise ValueError('GitHub capability credential required')
    if not path.startswith('/') or path.startswith('//'):
        raise ValueError('Invalid GitHub API path')
    req = Request('https://api.github.com'+path, method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                 'Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'})
    try:
        with urlopen(req,timeout=60) as response:
            body=response.read()
            return json.loads(body) if body else None
    except HTTPError as exc:
        if missing and exc.code==404:
            return None
        raise RuntimeError('Study GitHub setup/verifier transport HTTP '+str(exc.code)) from None


def git(args):
    env={k:v for k,v in os.environ.items() if not k.startswith(('GIT_CONFIG_','GIT_TRACE')) and k!='GH_DEBUG'}
    env.update(GH_TOKEN=os.environ.get('STUDY_GITHUB_TOKEN',''),GH_CONFIG_DIR=os.environ.get('GH_CONFIG_DIR',str(Path.home()/'.config/gh-study')),
        GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1',GIT_TERMINAL_PROMPT='0',GIT_TRACE='0',GIT_TRACE_CURL='0',GIT_CURL_VERBOSE='0')
    command=['git','-c','credential.helper=!'+str(RIG/'runtime/bin/gh')+' auth git-credential',*map(str,args)]
    proc=subprocess.run(command,env=env,capture_output=True,text=True,timeout=300)
    if proc.returncode:
        raise RuntimeError('Study repository git operation failed; no credential-bearing command emitted')
    return proc.stdout.strip()


def cached_base(task):
    name,sha,branch=BASES[task]
    root=RIG/'runtime/real-task-preparation/github-fixtures'
    root.mkdir(exist_ok=True)
    cache=root/(name+'.git')
    receipt=root/(name+'.json')
    expected={'source':'https://github.com/mcpmark-source/'+name+'.git','commit':sha,'branch':branch}
    if cache.exists():
        if not receipt.is_file() or json.loads(receipt.read_text())!=expected:
            raise ValueError('Unverified existing GitHub fixture cache; refusing reuse or replacement')
        git(['--git-dir',cache,'cat-file','-e',sha+'^{commit}'])
        return cache
    if receipt.exists():
        raise ValueError('Recorded GitHub fixture missing; explicit recovery required')
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        stage=Path(tmp)/'source.git'
        git(['clone','--mirror',expected['source'],stage])
        git(['--git-dir',stage,'cat-file','-e',sha+'^{commit}'])
        shutil.move(stage,cache)
    receipt.write_text(json.dumps(expected,indent=2)+'\n')
    return cache


def repository_for(output):
    # Fixed length, unique per retained attempt directory. No model or task answer.
    return evaluation_owner()+'/pi-'+hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:20]


def provision(task, repository, receipt_path):
    owner = evaluation_owner()
    if not re.fullmatch(re.escape(owner)+r'/pi-[0-9a-f]{20}',repository):
        raise ValueError('Not a disposable repository name for GITHUB_EVAL_ORG')
    if api('GET','/user').get('login')!=owner:
        raise ValueError('Wrong GitHub account; no mutation authorized')
    if api('GET','/repos/'+repository,missing=True) is not None:
        raise ValueError('Attempt repository already exists; no reset or primary replay')
    cache=cached_base(task)
    name,sha,branch=BASES[task]
    marker='Pi real-task disposable attempt '+repository.split('/')[1]
    created=api('POST','/user/repos',{'name':repository.split('/')[1],'private':True,
                'description':marker,'auto_init':False,'has_issues':False,'has_wiki':False})
    receipt={'repository':repository,'repository_id':created['id'],'marker':marker,
             'base_repository':name,'base_commit':sha,'branch':branch,
             'initial_pull_requests':0,'initial_pr_metadata_reproduced':False}
    receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
    git(['--git-dir',cache,'push','https://github.com/'+repository+'.git',sha+':refs/heads/'+branch])
    api('PATCH','/repos/'+repository,{'default_branch':branch,'allow_squash_merge':True,
                                  'delete_branch_on_merge':False})
    if api('GET','/repos/'+repository+'/commits/'+branch)['sha']!=sha:
        raise ValueError('Fresh repository seed commit mismatch')
    if api('GET','/repos/'+repository+'/pulls?state=all&per_page=100'):
        raise ValueError('Fresh repository unexpectedly has PR history')
    return receipt


def archive_and_delete(receipt_path, destination, *, expected_repository):
    """Fail closed: archive failure or identity mismatch leaves the repo intact."""
    receipt=json.loads(receipt_path.read_text())
    repository=receipt['repository']
    if repository != expected_repository or not re.fullmatch(re.escape(evaluation_owner())+r'/pi-[0-9a-f]{20}',repository):
        raise ValueError('Refusing cleanup outside this attempt namespace')
    if receipt['base_repository'] not in {'harmony','missing-semester'}:
        raise ValueError('Unknown source cache')
    current=api('GET','/repos/'+repository)
    if current['id']!=receipt['repository_id'] or current['description']!=receipt['marker'] or not current['private']:
        raise ValueError('Repository identity changed; refusing deletion')
    destination.mkdir(mode=0o700)
    pulls=api('GET','/repos/'+repository+'/pulls?state=all&per_page=100')
    if len(pulls)==100:
        raise ValueError('PR evidence needs pagination; refusing incomplete archive/deletion')
    (destination/'pulls.json').write_text(json.dumps(pulls,indent=2)+'\n')
    with tempfile.TemporaryDirectory() as tmp:
        clone=Path(tmp)/'final.git'
        git(['clone','--bare','--reference-if-able',RIG/'runtime/real-task-preparation/github-fixtures'/(receipt['base_repository']+'.git'),
             'https://github.com/'+repository+'.git',clone])
        for pull in pulls:
            number=pull['number']
            git(['--git-dir',clone,'fetch','origin',f'+refs/pull/{number}/head:refs/pull/{number}/head'])
        git(['--git-dir',clone,'bundle','create',destination.resolve()/'final.bundle','--all'])
    bundle=destination/'final.bundle'
    evidence={'repository':repository,'repository_id':current['id'],
              'bundle_sha256':hashlib.sha256(bundle.read_bytes()).hexdigest(),
              'pulls_sha256':hashlib.sha256((destination/'pulls.json').read_bytes()).hexdigest(),
              'base_commit':receipt['base_commit'],'deleted':False}
    (destination/'receipt.json').write_text(json.dumps(evidence,indent=2)+'\n')
    api('DELETE','/repos/'+repository)
    evidence['deleted']=True
    (destination/'receipt.json').write_text(json.dumps(evidence,indent=2)+'\n')
    return evidence
