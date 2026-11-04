"""Trusted, zero-model GitHub oracle. Never supplied to model trials."""
import base64
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import Request,urlopen

REPO=os.environ['TESTBED_GH_REPO']
TOKEN=os.environ['STUDY_GITHUB_TOKEN']


def api(method,path,data=None):
    req=Request('https://api.github.com/repos/'+REPO+'/'+path,method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization':'Bearer '+TOKEN,'Accept':'application/vnd.github+json','Content-Type':'application/json'})
    with urlopen(req,timeout=60) as r:
        body=r.read()
        return json.loads(body) if body else None


def get(path,branch):
    return api('GET','contents/'+path+'?ref='+branch)


def content(item):
    return base64.b64decode(item['content']).decode()


def put(path,text,branch,message,old=None):
    data={'message':message,'content':base64.b64encode(text.encode()).decode(),'branch':branch}
    if old is not None:data['sha']=old['sha']
    api('PUT','contents/'+path,data)


def main():
    task,instruction,negative=sys.argv[1:]
    if task=='find_salient_file':
        put('ANSWER.md','wrong.md\n' if negative=='true' else 'index.md\n','master','Record salient file')
        return
    if negative=='true':
        return  # Untouched baseline must fail the original release verifier.
    base=api('GET','git/ref/heads/main')['object']['sha']
    branch='release-v1.1.0'
    api('POST','git/refs',{'ref':'refs/heads/'+branch,'sha':base})
    old=get('src/encoding.rs',branch)
    before=content(old)
    after=before.replace('FormattingToken::MetaSep => "<|channel|>"','FormattingToken::MetaSep => "<|meta_sep|>"')
    assert after!=before
    put('src/encoding.rs',after,branch,'Fix MetaSep token mapping',old)
    old=get('src/registry.rs',branch)
    before=content(old)
    anchor='(FormattingToken::Channel, "<|channel|>"),'
    assert anchor in before
    after=before.replace(anchor,anchor+'\n                    (FormattingToken::MetaSep, "<|meta_sep|>"),\n                    (FormattingToken::MetaEnd, "<|meta_end|>"),')
    put('src/registry.rs',after,branch,'Register missing meta tokens',old)
    utils='import { clsx, type ClassValue } from "clsx"\nimport { twMerge } from "tailwind-merge"\n\nexport function cn(...inputs: ClassValue[]) {\n  return twMerge(clsx(inputs))\n}\n'
    put('demo/harmony-demo/src/lib/utils.ts',utils,branch,'Add missing shadcn utility')
    old=get('.gitignore',branch)
    put('.gitignore',content(old).rstrip()+'\n\n# Avoid ignoring shadcn utils\n!demo/harmony-demo/src/lib\n',branch,'Preserve shadcn utilities',old)
    old=get('Cargo.toml',branch)
    after=re.sub(r'(?m)^version\s*=\s*"[^"]+"','version = "1.1.0"',content(old),count=1)
    put('Cargo.toml',after,branch,'Update release version',old)
    text=Path(instruction).read_text()
    changelog=re.search(r'```markdown\n(.*?)```',text,re.S)[1]
    assert changelog.startswith('# Changelog')
    put('CHANGELOG.md',changelog,branch,'Add release changelog')
    pr=api('POST','pulls',{'head':branch,'base':'main','title':'Release v1.1.0 - Bug fixes and utility additions',
        'body':'Integrate the MetaSep mapping and registry fixes, shadcn utility and gitignore additions, version update, and comprehensive release changelog.'})
    result=api('PUT',f'pulls/{pr["number"]}/merge',{'merge_method':'squash'})
    assert result.get('merged')


if __name__=='__main__':main()
