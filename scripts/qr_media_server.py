"""Loopback server exposing generated QR JPEGs only, never application routes."""
import argparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import re

class Handler(BaseHTTPRequestHandler):
 def do_HEAD(self):self.serve(False)
 def do_GET(self):self.serve(True)
 def serve(self,body):
  name=self.path.split('?',1)[0].lstrip('/')
  if name=='health':
   data=b'SMH QR media';kind='text/plain'
  elif re.fullmatch(r'[a-f0-9]{32}\.jpg',name):
   path=self.server.qr_root/name
   if not path.is_file():self.send_error(404);return
   data=path.read_bytes();kind='image/jpeg'
  else:self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type',kind)
  self.send_header('Content-Length',str(len(data)))
  self.send_header('Cache-Control','public, max-age=3600' if kind=='image/jpeg' else 'no-store')
  self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
  if body:self.wfile.write(data)
 def log_message(self,*args):pass

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--port',type=int,default=8189)
 args=parser.parse_args();server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
 server.qr_root=Path(args.root).resolve();server.qr_root.mkdir(parents=True,exist_ok=True)
 server.serve_forever()
