"""Harbor sidecar state transfer, never model-facing UI or reference answers.

Harbor stops main before sidecar collection, then stops the entire agent env.
The separate verifier gets a fresh sidecar and restores only declared DB artifacts.
"""
import hashlib
import shlex
from harbor_pi.shopping_candidate_probe import IMAGE

SQL='/tmp/shopping-state.sql'
CHECKSUM='/tmp/shopping-state.sha256'
MYSQL='mysql -u magentouser -pMyPassword'
BASE='http://shopping/'
DUMP=('set -eu; umask 022; mysqldump --single-transaction --skip-lock-tables '
      '--hex-blob --no-tablespaces --routines --events --add-drop-database '
      '-u magentouser -pMyPassword --databases magentodb > '+SQL+
      '; sha256sum '+SQL+' > '+CHECKSUM)


def marker_for(output):
    return hashlib.sha256(str(output.resolve()).encode()).hexdigest()


def compose(main,*,verifier=False,marker=None):
    main={**main,'networks':['default','appnet']}
    command=['supervisord','-n','-j','/supervisord.pid']
    if verifier:
        if not marker or len(marker)!=64 or any(c not in '0123456789abcdef' for c in marker):
            raise ValueError('Verifier marker must be a path-derived SHA256')
        script=('set -eu; supervisord -n -j /supervisord.pid & supervisor=$!; '
            'n=0; until test -S /run/supervisord.sock; do n=$((n+1)); test "$n" -lt 60; sleep 1; done; '
            'env-ctrl start --wait --timeout 180 > /tmp/restore-start.log 2>&1; '
            'until wget -q -O '+SQL+'.download http://main:8765/shopping-state.sql && '
            'wget -q -O '+CHECKSUM+'.download http://main:8765/shopping-state.sha256; do sleep 1; done; '
            'mv '+SQL+'.download '+SQL+'; mv '+CHECKSUM+'.download '+CHECKSUM+'; '
            'sha256sum -c '+CHECKSUM+' > /tmp/restore-checksum.log 2>&1; '
            'if ! '+MYSQL+' < '+SQL+' > /tmp/restore-db.log 2>&1; then '
            'printf "ERROR: database restore failed\\n" > /var/www/magento2/verifier-ready.txt; '
            'cat /tmp/restore-db.log >> /var/www/magento2/verifier-ready.txt; '
            'cp /var/www/magento2/verifier-ready.txt /var/www/magento2/pub/verifier-ready.txt; wait "$supervisor"; exit 1; fi; '
            'env-ctrl init --base-url '+BASE+' > /tmp/restore-init.log 2>&1; '
            'wget -q --post-data='+shlex.quote(marker)+' -O /tmp/restore-ready-ack http://main:8765/restore-ready; '
            'wait "$supervisor"')
        # Compose interpolates dollar signs even in list-form commands.
        command=['sh','-c',script.replace('$','$$')]
    return {'networks':{'default':{},'appnet':{'internal':True}},'services':{
        'main':main,'shopping':{'image':IMAGE,'command':command,'cpus':2,'mem_limit':'3072m',
        'networks':['appnet'],'environment':{'WA_ENV_CTRL_EXTERNAL_SITE_URL':BASE}}}}


async def start(environment):
    for command in ('env-ctrl start --wait --timeout 180','env-ctrl init --base-url '+BASE):
        result=await environment.service_exec(command,service='shopping',user='root',timeout_sec=240)
        if result.return_code:raise RuntimeError('Disposable shopping setup failed: '+str(result.return_code))
