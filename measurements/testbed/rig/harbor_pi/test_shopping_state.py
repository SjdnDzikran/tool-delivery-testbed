import io
import unittest
from unittest.mock import Mock,patch
from harbor_pi.shopping_state import compose
from harbor_pi.actual_verify import state_server


class ShoppingStateTests(unittest.TestCase):
    def test_isolated_sidecar_and_compose_dollar_escaping(self):
        config=compose({},verifier=True,marker='a'*64)
        self.assertTrue(config['networks']['appnet']['internal'])
        self.assertEqual(config['services']['shopping']['networks'],['appnet'])
        self.assertNotIn('ports',config['services']['shopping'])
        script=config['services']['shopping']['command'][2]
        self.assertIn('wait "$$supervisor"',script)
        self.assertIn('$$((n+1))',script)
        self.assertIn('sha256sum -c',script)
        with self.assertRaises(ValueError):compose({},verifier=True,marker='../invalid')

    def test_restore_transport_cannot_serve_references(self):
        marker='b'*64
        with patch('harbor_pi.actual_verify.ThreadingHTTPServer') as factory,patch('harbor_pi.actual_verify.threading.Thread'):
            server=state_server(marker)
            handler=factory.call_args.args[1]
        request=object.__new__(handler)
        request.server=server
        request.send_error=Mock();request.send_response=Mock()
        request.send_header=Mock();request.end_headers=Mock()
        request.path='/tests/label.txt';request.do_GET()
        request.send_error.assert_called_with(404)
        request.path='/restore-ready';request.headers={'Content-Length':'64'}
        request.rfile=io.BytesIO(marker.encode());request.do_POST()
        self.assertTrue(server.restore_ready.is_set())
        request.send_response.assert_called_with(200)


if __name__=='__main__':unittest.main()
