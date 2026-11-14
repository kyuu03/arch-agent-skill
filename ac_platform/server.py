import json
import hashlib
import mimetypes
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from .library import Libraries, LIMIT, preview
from . import __version__

WEB = Path(__file__).resolve().parent / 'web'

def load(p):
    return json.loads(Path(p).read_text('utf-8-sig'))

class Project:
    def __init__(self, config, config_path):
        self.config = config
        self.base = Path(config_path).resolve().parent
        self.root = self.path(config['project_root'])
        self.data = self.path(config['data_root'])
        self.libraries = Libraries(self.data, [self.path(p) for p in config.get('library_mounts', [])],
                                   [dict(m, path=str(self.path(m['path']))) for m in config.get('document_mounts', [])])

    def path(self, p):
        return (self.base / p).resolve()

    def project_file(self, p):
        file = (self.root / p).resolve()
        if not file.is_relative_to(self.root):
            raise ValueError('项目路径越界')
        return file

    def text(self, key):
        p = self.config.get(key)
        return self.project_file(p).read_text('utf-8-sig') if p else '尚未绑定'

    def evidence(self, run_id, event_id, index):
        paths = list(dict.fromkeys([p for p in [self.config.get('run_log'), *self.config.get('run_logs', [])] if p]))
        runs = [load(self.project_file(p)) for p in paths]
        run = next((r for r in runs if r.get('id') == run_id), None)
        if not run:
            raise ValueError('日志未绑定')
        event = next((e for e in run.get('events', []) if e.get('id') == event_id), None)
        if not event or index < 0 or index >= len(event.get('evidence', [])):
            raise ValueError('事件证据不存在')
        entry = event['evidence'][index]
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            raise ValueError('旧记录只有文字定位，未绑定可预览文件')
        p = self.project_file(entry['path'])
        if not p.is_file():
            raise ValueError('证据文件不存在')
        if p.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('证据超过32 MiB，请在本地应用查看')
        raw = p.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        kind = 'image' if p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'} else 'text' if p.suffix.lower() in {'.md', '.txt', '.json', '.jsonl', '.py', '.js', '.css', '.svg', '.csv'} else 'download'
        result = {'label': entry.get('label', p.name), 'path': entry['path'], 'kind': kind,
                  'sha256': sha, 'expectedSHA256': entry.get('sha256'),
                  'matchesExpected': sha == entry['sha256'] if entry.get('sha256') else None,
                  'bytes': len(raw), 'truncated': len(raw) > 128 * 1024}
        if kind == 'text':
            result['content'] = raw[:128 * 1024].decode('utf-8-sig', errors='replace')
        return result, raw, p.suffix.lower()

    def state(self):
        cfg = self.config
        ledger = load(self.project_file(cfg['ledger']))
        return {'appVersion': __version__, 'projectTitle': cfg.get('title', '建筑协作'),
                'notice': cfg.get('notice', '项目记录只读映射，设计操作继续在对话中进行。'),
                'ledger': ledger, 'blackboard': self.text('blackboard'), 'checklist': self.text('checklist'),
                'experts': load(self.project_file(cfg['experts'])) if cfg.get('experts') else {'experts': []},
                'artifacts': cfg.get('artifacts', []), 'legacy': cfg.get('legacy'),
                'runLog': load(self.project_file(cfg['run_log'])) if cfg.get('run_log') else None,
                'runLogs': [load(self.project_file(p)) for p in cfg.get('run_logs', [])],
                'bindings': {k: cfg.get(k) for k in ('ledger', 'blackboard', 'checklist', 'experts')},
                'libraries': self.libraries.catalog(),
                'updatedAt': datetime.now(timezone.utc).isoformat()}

def serve(config_path, port=8850):
    cfg = load(config_path)
    if cfg.get('schemaVersion') != 1:
        raise ValueError('不支持的配置版本')
    project = Project(cfg, config_path)
    project.state()  # Fail visibly before serving if the binding is broken.
    token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def respond(self, code, value, mime='application/json; charset=utf-8', download=None):
            content = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Length', str(len(content)))
            if download:
                self.send_header('Content-Disposition', f'attachment; filename="{download}"')
            self.end_headers()
            self.wfile.write(content)

        def local(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            if not self.local():
                return self.respond(403, {'error': '只接受本机地址'})
            u = urlparse(self.path)
            try:
                if u.path == '/api/state':
                    return self.respond(200, project.state())
                if u.path == '/api/session':
                    return self.respond(200, {'token': token})
                if u.path == '/api/evidence':
                    q = parse_qs(u.query)
                    item, raw, suffix = project.evidence(q.get('run', [''])[0], q.get('event', [''])[0], int(q.get('index', ['-1'])[0]))
                    mode = q.get('mode', ['preview'])[0]
                    if mode == 'download':
                        return self.respond(200, raw, 'application/octet-stream', 'evidence' + suffix)
                    if mode == 'image' and item['kind'] == 'image':
                        return self.respond(200, raw, mimetypes.guess_type('image' + suffix)[0])
                    return self.respond(200, item)
                if u.path == '/health':
                    return self.respond(200, {'app': 'architecture-collaboration', 'version': __version__})
                if u.path == '/file':
                    requested = parse_qs(u.query).get('path', [''])[0]
                    # Only configured artifacts/record files are exposed, never the whole workspace.
                    allowed = [cfg[k] for k in ('ledger', 'blackboard', 'checklist', 'experts') if cfg.get(k)]
                    allowed += [x['path'] for x in cfg.get('artifacts', [])]
                    if requested not in allowed:
                        return self.respond(403, {'error': '文件不在绑定白名单中'})
                    p = project.project_file(requested)
                    # Download arbitrary project HTML, rather than executing it on the management origin.
                    return self.respond(200, p.read_bytes(), 'application/octet-stream', 'project-file' + p.suffix)
                static = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/run-log.js': 'run-log.js'}
                if u.path not in static:
                    return self.respond(404, {'error': '不存在'})
                p = WEB / static[u.path]
                return self.respond(200, p.read_bytes(), (mimetypes.guess_type(p.name)[0] or 'text/plain') + '; charset=utf-8')
            except (ValueError, KeyError, OSError) as e:
                return self.respond(400, {'error': str(e)})

        def do_POST(self):
            if not self.local() or self.headers.get('Origin') != f'http://127.0.0.1:{self.server.server_port}' or self.headers.get('X-AC-Token') != token:
                return self.respond(403, {'error': '管理操作需要本地同源页面与会话令牌'})
            try:
                n = int(self.headers.get('Content-Length', '0'))
                if n <= 0 or n > LIMIT + 65536:
                    return self.respond(413, {'error': '请求体为空或过大'})
                body = json.loads(self.rfile.read(n))
                route = urlparse(self.path).path
                if route == '/api/packs/preview':
                    return self.respond(200, preview(body['pack']))
                if route == '/api/packs/install':
                    if body.get('confirmedSha256') != body['pack'].get('sha256'):
                        raise ValueError('请先预览并确认相同散列的资料包')
                    return self.respond(201, project.libraries.install(body['pack']))
                if route == '/api/packs/export':
                    pack = project.libraries.export(body['keys'], body['metadata'], body.get('allowPrivate') is True)
                    return self.respond(200, {'pack': pack, 'preview': preview(pack)})
                return self.respond(405, {'error': '项目记录只读；仅资料包管理允许写入'})
            except FileExistsError as e:
                return self.respond(409, {'error': str(e)})
            except (ValueError, KeyError, TypeError, OSError) as e:
                return self.respond(400, {'error': str(e)})

        def do_PUT(self):
            self.respond(405, {'error': '项目记录只读'})
        do_DELETE = do_PUT
        do_PATCH = do_PUT

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    project.data.mkdir(parents=True, exist_ok=True)
    (project.data/'runtime.json').write_text(json.dumps({'url': f'http://127.0.0.1:{server.server_port}', 'appVersion': __version__}), 'utf-8')
    print(f'Architecture Collaboration {__version__}: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
