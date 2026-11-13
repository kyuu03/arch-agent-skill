import json
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

    def state(self):
        cfg = self.config
        ledger = load(self.project_file(cfg['ledger']))
        return {'appVersion': __version__, 'projectTitle': cfg.get('title', '建筑协作'),
                'notice': cfg.get('notice', '项目记录只读映射，设计操作继续在对话中进行。'),
                'ledger': ledger, 'blackboard': self.text('blackboard'), 'checklist': self.text('checklist'),
                'experts': load(self.project_file(cfg['experts'])) if cfg.get('experts') else {'experts': []},
                'artifacts': cfg.get('artifacts', []), 'legacy': cfg.get('legacy'),
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
                static = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
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
