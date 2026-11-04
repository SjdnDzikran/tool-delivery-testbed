"""Offline checks for bounded installation probes (no models/credentials)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability_checks import McpStdio, parse_json_objects, tool_call_is_error


class CapabilityProbeTests(unittest.TestCase):
    def test_json_results(self):
        self.assertEqual(parse_json_objects(' {"url":"a"}\n{"url":"b"} '),
                         [{"url": "a"}, {"url": "b"}])
        with self.assertRaises(json.JSONDecodeError):
            parse_json_objects('not a result')

    def test_tool_error(self):
        self.assertTrue(tool_call_is_error({"result": {"isError": True}}))
        self.assertFalse(tool_call_is_error({"result": {"content": []}}))

    def test_silent_server_timeout(self):
        with McpStdio([sys.executable, '-c', 'import time; time.sleep(30)'],
                      timeout=0.1) as client:
            try:
                with self.assertRaises(TimeoutError):
                    client.initialize()
            finally:
                client.proc.terminate()

    def test_large_stderr_does_not_deadlock(self):
        code = ('import sys,json; sys.stderr.write("x"*200000); '
                'line=json.loads(sys.stdin.readline()); '
                'print(json.dumps({"jsonrpc":"2.0","id":line["id"],'
                '"result":{"serverInfo":{"name":"fake"}}}),flush=True)')
        with McpStdio([sys.executable, '-c', code], timeout=2) as client:
            self.assertEqual(client.initialize()['result']['serverInfo']['name'], 'fake')


if __name__ == '__main__':
    unittest.main()
