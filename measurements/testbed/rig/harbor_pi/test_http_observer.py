"""Zero-network tests of passive HTTP observation; no provider calls."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class HttpObserverTests(unittest.TestCase):
    def test_compaction_driver_stops_on_provider_error(self):
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            helper = root / 'fake_rpc.py'
            helper.write_text('''import json,sys
from pathlib import Path
for line in sys.stdin:
    command = json.loads(line)['type']
    with Path(sys.argv[1]).open('a') as log: log.write(command+'\\n')
    if command == 'get_state':
        value = {'type':'response','id':'get_state','success':True,'data':{'thinkingLevel':'max'}}
    elif command == 'prompt':
        value = {'type':'message_end','message':{'role':'assistant','stopReason':'error'}}
    else: raise AssertionError('Unexpected command after provider failure')
    print(json.dumps(value),flush=True)
''')
            (root / 'rpc-argv.json').write_text(json.dumps([sys.executable, str(helper), str(root / 'commands.txt')]))
            (root / 'rpc-instruction.txt').write_text('Offline error-path check')
            code = Path(__file__).with_name('compaction_probe.py').read_text().replace('/home/study/', tmp + '/').replace('/logs/agent/', tmp + '/')
            result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Provider error during accounting canary', result.stderr)
            self.assertEqual((root / 'commands.txt').read_text().splitlines(), ['get_state', 'prompt'])
            self.assertFalse((root / 'compaction-probe.json').exists())

    def test_installs_after_pinned_dispatcher_without_changing_it(self):
        dispatcher = Path.home() / '.pi/research/node_modules/@earendil-works/pi-coding-agent/dist/core/http-dispatcher.js'
        if not dispatcher.is_file():
            self.skipTest('Pinned Pi dispatcher unavailable')
        module = Path(__file__).with_name('http_observer.mjs').as_uri()
        code = r'''
import assert from 'node:assert/strict';
const {configureHttpDispatcher} = await import(process.argv[2]);
configureHttpDispatcher(1000);
const reply = {status:200};
globalThis.fetch = async () => reply;
const observer = await import(process.argv[1]);
let start;
observer.default({on: (kind, callback) => {assert.equal(kind,'before_agent_start');start=callback;}});
assert.equal(start(), undefined);
const installed = globalThis.fetch;
configureHttpDispatcher(1000);
assert.equal(globalThis.fetch, installed);
start(); assert.equal(globalThis.fetch, installed);
assert.equal(await fetch('https://api.openai.com/v1/responses', {body:'{"model":"test","input":"test"}'}),reply);
'''
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(['node', '--input-type=module', '-e', code, module, dispatcher.as_uri()], env={**os.environ, 'PI_HTTP_OBSERVER_DIR': tmp}, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list(Path(tmp).glob('*.json'))), 1)

    def test_arguments_response_errors_and_header_privacy(self):
        module = Path(__file__).with_name('http_observer.mjs').as_uri()
        code = r'''
import assert from 'node:assert/strict';
const reply = {status: 200, marker: Symbol('unchanged')};
const failure = new Error('unchanged failure');
let expectedInput, expectedOptions;
globalThis.fetch = async function(input, options) {
  assert.equal(input, expectedInput); assert.equal(options, expectedOptions);
  if (options.fail) throw failure;
  return reply;
};
const {installHttpObserver} = await import(process.argv[1]);
installHttpObserver();
for (const url of ['https://api.openai.com/v1/responses?private=fake-query-secret',
                   'https://api.z.ai/api/coding/paas/v4/chat/completions',
                   'https://api.search.brave.com/res/v1/web/search']) {
  expectedInput = url;
  expectedOptions = {method:'POST', headers:{Authorization:'fake-header-secret'}, body:JSON.stringify({model:'test',input:'test'})};
  assert.equal(await fetch(expectedInput, expectedOptions), reply);
}
expectedInput = 'https://api.openai.com/v1/responses';
expectedOptions = {fail:true, body:JSON.stringify({model:'test',input:'test'})};
await assert.rejects(fetch(expectedInput, expectedOptions), e => e === failure);
'''
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(['node', '--input-type=module', '-e', code, module],
                                    env={**os.environ, 'PI_HTTP_OBSERVER_DIR': tmp},
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            files = sorted(Path(tmp).glob('*.json'))
            self.assertEqual(len(files), 3)
            text = '\n'.join(p.read_text() for p in files)
            self.assertNotIn('fake-header-secret', text)
            self.assertNotIn('fake-query-secret', text)
            self.assertEqual(json.loads(files[-1].read_text())['status'], 'transport_error')
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in files))


if __name__ == '__main__':
    unittest.main()
