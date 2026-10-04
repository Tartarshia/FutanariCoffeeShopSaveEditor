"""Loopback-only local editor. No external dependencies or remote assets."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit
import webbrowser
import codec
import model

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / '.local'
TOKEN = secrets.token_urlsafe(32)
JOBS = {}
LOCK = threading.Lock()

def discover():
    bases = [Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Steam']
    for base in list(bases):
        manifest = base / 'steamapps/libraryfolders.vdf'
        if manifest.exists():
            for p in re.findall(r'"path"\s+"([^"]+)"', manifest.read_text(encoding='utf-8')):
                bases.append(Path(p.replace('\\\\', '\\')))
    found = []
    for base in bases:
        folder = base / 'steamapps/common/Futanari_CoffeeShop/cs_player_files'
        if folder.exists():
            found.extend(str(p) for p in folder.glob('cs_save_datas#*.sd'))
    return sorted(set(found))

def launch(request):
    with LOCK:
        if sum(p.poll() is None for p in JOBS.values()) >= 2:
            raise ValueError('已有两项任务正在运行，请稍后重试')
        job_id = secrets.token_hex(16)
        folder = LOCAL / job_id
        folder.mkdir(parents=True)
        (folder / 'request.json').write_text(json.dumps(request), encoding='utf-8')
        (folder / 'status.json').write_text('{"state":"running"}', encoding='utf-8')
        # Native Steam diagnostic output can contain account IDs. Keep it local.
        with open(folder / 'worker.log', 'ab') as log:
            JOBS[job_id] = subprocess.Popen([sys.executable, str(ROOT / 'tasks.py'), str(folder)],
                cwd=ROOT, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return job_id

def job_path(job_id):
    if not re.fullmatch('[a-f0-9]{32}', job_id) or job_id not in JOBS:
        raise ValueError('Unknown session')
    return LOCAL / job_id

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def guard(self, write=False):
        host = self.headers.get('Host', '')
        if host != f'127.0.0.1:{self.server.server_port}':
            raise ValueError('Invalid Host')
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + host:
            raise ValueError('Invalid Origin')
        if self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
            raise ValueError('Cross-site request refused')
        supplied = self.headers.get('X-Editor-Token', '')
        if urlsplit(self.path).path == '/api/download' and not write:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            supplied = cookie['editor_token'].value if 'editor_token' in cookie else ''
        if (write or self.path.startswith('/api/')) and not secrets.compare_digest(supplied, TOKEN):
            raise ValueError('Invalid session token')

    def send(self, data, kind='application/json; charset=utf-8', status=200):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=True).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        if urlsplit(self.path).path == '/':
            self.send_header('Set-Cookie', f'editor_token={TOKEN}; HttpOnly; SameSite=Strict; Path=/api/download')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            self.guard()
            u = urlsplit(self.path)
            q = parse_qs(u.query)
            if u.path == '/':
                html = (ROOT / 'web/index.html').read_bytes().replace(b'__TOKEN__', TOKEN.encode())
                self.send(html, 'text/html; charset=utf-8')
            elif u.path in ('/app.js', '/style.css'):
                self.send((ROOT / 'web' / u.path[1:]).read_bytes(),
                          'text/javascript; charset=utf-8' if u.path.endswith('.js') else 'text/css; charset=utf-8')
            elif u.path == '/api/saves':
                self.send({'saves': discover()})
            elif u.path == '/api/status':
                job_id = q.get('job', [''])[0]
                job = job_path(job_id)
                status = json.loads((job / 'status.json').read_text(encoding='utf-8'))
                if status['state'] == 'running' and JOBS[job_id].poll() is not None:
                    status = {'state': 'error', 'error': 'Worker exited without a result'}
                self.send(status)
            elif u.path == '/api/fields':
                folder = job_path(q.get('job', [''])[0]) / 'save'
                page = int(q.get('page', ['0'])[0])
                if not 0 <= page <= 10000000:
                    raise ValueError('Invalid page')
                self.send(codec.rows(folder, page, q.get('q', [''])[0][:300]))
            elif u.path in ('/api/overview','/api/view','/api/catalogue'):
                folder=job_path(q.get('job',[''])[0])/'save'
                page=int(q.get('page',['0'])[0])
                idx=int(q.get('id',['0'])[0])
                if not 0<=page<=100000 or not 0<=idx<=1000:
                    raise ValueError('Invalid index or page')
                query=q.get('q',[''])[0][:300]
                if u.path=='/api/overview':
                    self.send(model.overview(folder))
                elif u.path=='/api/view':
                    self.send(model.view(folder,q.get('section',['shop'])[0],idx,page,query))
                else:
                    self.send(model.catalogue_page(folder,query,page))
            elif u.path == '/api/download':
                job = job_path(q.get('job', [''])[0])
                status = json.loads((job / 'status.json').read_text(encoding='utf-8'))
                if status['state'] != 'done' or 'file' not in status['result']:
                    raise ValueError('No export')
                path = Path(status['result']['file'])
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(path.stat().st_size))
                self.send_header('Content-Disposition', 'attachment; filename="CoffeeShop_edited.sd"')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                with open(path, 'rb') as f:
                    shutil.copyfileobj(f, self.wfile, 1048576)
            else:
                self.send({'error': 'Not found'}, status=404)
        except (ValueError, OSError, KeyError) as e:
            self.send({'error': str(e)}, status=400)

    def do_POST(self):
        try:
            self.guard(True)
            length = int(self.headers.get('Content-Length', '-1'))
            if self.headers.get('Transfer-Encoding') or length < 0:
                raise ValueError('Content-Length required')
            if urlsplit(self.path).path == '/api/upload':
                if length > 128 * 1024 * 1024:
                    raise ValueError('Upload limit: 128 MiB')
                upload = LOCAL / 'uploads'
                upload.mkdir(parents=True, exist_ok=True)
                path = upload / (secrets.token_hex(16) + '.sd')
                with open(path, 'xb') as out:
                    while length:
                        b = self.rfile.read(min(length, 1048576))
                        if not b:
                            raise ValueError('Incomplete upload')
                        out.write(b)
                        length -= len(b)
                game=parse_qs(urlsplit(self.path).query).get('game',[''])[0]
                self.send({'job': launch({'action': 'open', 'source': str(path),'game':game or None})})
                return
            if length > 2*1048576:
                raise ValueError('Request too large')
            data = json.loads(self.rfile.read(length))
            if self.path == '/api/open':
                source = Path(data['source'])
                if not source.is_file() or source.suffix.lower() != '.sd':
                    raise ValueError('Select an existing .sd save')
                self.send({'job': launch({'action': 'open', 'source': str(source),'game':data.get('game') or None})})
            elif self.path == '/api/export':
                folder = job_path(data['job']) / 'save'
                target = ROOT / 'exports' / (secrets.token_hex(8) + '_CoffeeShop_edited.sd')
                if not isinstance(data['changes'], dict):
                    raise ValueError('Invalid edits')
                self.send({'job': launch({'action': 'export', 'folder': str(folder),
                                         'target': str(target), 'changes': data['changes']})})
            elif self.path == '/api/steam':
                import steam_achievements
                steam_achievements.validate_request(data.get('operation'),
                    data.get('achievement'), data.get('confirmed', False))
                self.send({'job': launch({'action': 'steam', 'operation': data['operation'],
                    'game': data.get('game') or None, 'achievement': data.get('achievement'),
                    'confirmed': data.get('confirmed', False)})})
            else:
                self.send({'error': 'Not found'}, status=404)
        except (ValueError, OSError, KeyError, TypeError) as e:
            self.send({'error': str(e)}, status=400)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    url = f'http://127.0.0.1:{server.server_port}/'
    print('本地存档编辑器：' + url, flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
