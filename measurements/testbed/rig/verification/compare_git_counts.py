"""Offline pinned-history merge-diff comparison; does not change task grading."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess

RIG=Path(__file__).resolve().parents[1]
SHA='05c436fbdf0d3d90cfaa86f22bd37ad9bd1608fa'


def compare():
    cache=RIG/'runtime/real-task-preparation/github-fixtures/missing-semester.git'
    if not cache.is_dir():raise ValueError('Verified cached source required; no download')
    env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'}
    rows=[]
    for label,extra in (('git_default',[]),('first_parent_merge_diffs',['--diff-merges=first-parent']),('each_parent_merge_diffs',['-m'])):
        args=['git','--git-dir',str(cache),'log','-100','--format=','--name-only',*extra,SHA]
        text=subprocess.check_output(args,env=env,text=True)
        counts=Counter(p for p in text.split('\n') if p and not p.startswith('.github/'))
        name,count=counts.most_common(1)[0]
        rows.append({'method':label,'options':extra,'top_count':count,
            'top_path_sha256':hashlib.sha256(name.encode()).hexdigest()})
    assert len({r['top_path_sha256'] for r in rows})==1
    return {'provenance':'ours: offline controlled Git comparison, not API reconciliation',
        'model_calls':0,'network_calls':0,'source_commit':SHA,'commit_window':100,
        'excluded_prefix':'.github/','git_version':subprocess.check_output(['git','--version'],text=True).strip(),
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'measurements':rows,
        'limitation':'Reproduces reported count difference; does not independently reconcile every GitHub API response or authorize a counting-rule change.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();data=compare()
    with a.output.open('x') as f:json.dump(data,f,indent=2);f.write('\n')
