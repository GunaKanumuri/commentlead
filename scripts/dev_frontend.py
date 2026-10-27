"""Serve only frontend/ for independent local development (API on port 8000)."""
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json,os


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(Path(__file__).resolve().parent.parent/'frontend'),**kwargs)
    def do_GET(self):
        if self.path=='/config.js':
            payload=('window.APP_CONFIG='+json.dumps({'apiBaseUrl':os.getenv('DEV_API_BASE_URL','http://localhost:8000')})+';').encode()
            self.send_response(200);self.send_header('Content-Type','application/javascript');self.end_headers();self.wfile.write(payload)
        else:super().do_GET()


if __name__=='__main__':
    print('Frontend: http://localhost:3000 (API: http://localhost:8000)')
    ThreadingHTTPServer(('127.0.0.1',3000),Handler).serve_forever()
