"""Trusted synthetic/live-state composite wiring fixtures; never model-facing."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.request import Request,urlopen


def sql(query):
    return subprocess.check_output(['/usr/lib/postgresql/16/bin/psql','-X','-w','-v','ON_ERROR_STOP=1',
        os.environ['TESTBED_PG_DSN'],'-At','-c',query],text=True).strip()


def main():
    task,negative=sys.argv[1:]
    if task=='composite_1':
        year='1907' if negative=='true' else '1906'
        url='https://example.invalid/synthetic-composite-verifier-fixture'
        data={'fact':'birth_year_grace_hopper','value':year,'sources':[
            {'url':url,'quote':'Synthetic verifier fixture, not web evidence: birth year '+year}]}
        Path('evidence.json').write_text(json.dumps(data)+'\n')
        sql("INSERT INTO public.facts(label,value,source_url) VALUES ('birth_year_grace_hopper','"+year+"','"+url+"')")
        return
    row=json.loads(sql("SELECT row_to_json(q) FROM (SELECT product,SUM(units)::bigint AS units FROM public.product_sales GROUP BY product ORDER BY units DESC,product ASC LIMIT 1) q"))
    text='wrong\n0\n' if negative=='true' else str(row['product'])+'\n'+str(row['units'])+'\n'
    repo=os.environ['TESTBED_GH_REPO']
    data={'message':'Publish top seller','content':base64.b64encode(text.encode()).decode(),'branch':'main'}
    req=Request('https://api.github.com/repos/'+repo+'/contents/TOP_SELLER.md',method='PUT',data=json.dumps(data).encode(),
        headers={'Authorization':'Bearer '+os.environ['STUDY_GITHUB_TOKEN'],
                 'Accept':'application/vnd.github+json','Content-Type':'application/json'})
    with urlopen(req,timeout=60) as r:
        if r.status!=201:raise RuntimeError('Expected fresh repository file creation')


if __name__=='__main__':main()
