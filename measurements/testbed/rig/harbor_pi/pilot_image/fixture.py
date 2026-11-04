"""Trusted local engineering fixture; answers exist only in the served page."""
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = 'pilot-browser-click-verified-2037'

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = ('<!doctype html><title>Pilot browser fixture</title>'
                '<button id="reveal">Reveal answer</button><p id="answer"></p>'
                '<script>document.querySelector("#reveal").onclick=()=>'
                f'document.querySelector("#answer").textContent="{TOKEN}";'
                '</script>').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(data)

HTTPServer(('127.0.0.1', 5580), Handler).serve_forever()
