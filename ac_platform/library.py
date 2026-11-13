"""Portable, text-only libraries. Packages are data, never executable plugins."""
import hashlib
import json
import re
import threading
from pathlib import Path

SCHEMA = 'ac-library-pack/v1'
LIMIT = 8 * 1024 * 1024
ID = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$')
LOCK = threading.Lock()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def seal(pack):
    pack = dict(pack)
    pack.pop('sha256', None)
    pack['sha256'] = digest(pack)
    return pack

def validate(pack):
    if not isinstance(pack, dict) or pack.get('schema') != SCHEMA:
        raise ValueError('不支持的资料包格式；需要 ac-library-pack/v1')
    if len(canonical(pack)) > LIMIT:
        raise ValueError('资料包超过 8 MiB')
    for k in ('id', 'version'):
        if not isinstance(pack.get(k), str) or not ID.fullmatch(pack[k]):
            raise ValueError(f'{k} 只能含字母、数字、点、下划线、连字符，最长80字符')
    for k in ('title', 'author', 'license'):
        if not isinstance(pack.get(k), str) or not pack[k].strip() or len(pack[k]) > 500:
            raise ValueError(f'缺少或无效的 {k}')
    entries = pack.get('entries')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValueError('资料包需含 1–100 个条目')
    ids = set()
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get('id'), str) or not ID.fullmatch(e['id']) or e['id'] in ids:
            raise ValueError('条目 ID 无效或重复')
        ids.add(e['id'])
        if e.get('kind') not in ('knowledge', 'experience', 'expert'):
            raise ValueError('条目类型只能为 knowledge / experience / expert')
        if not isinstance(e.get('title'), str) or not 1 <= len(e['title']) <= 500:
            raise ValueError('条目标题无效')
        if not isinstance(e.get('content'), str) or len(e['content'].encode('utf-8')) > 128 * 1024:
            raise ValueError('每条正文需为 UTF-8 文本，最大128 KiB')
        if e.get('verification') not in ('unverified', 'case-supported', 'cross-context-supported', 'revised', 'invalid'):
            raise ValueError('verification 验证状态无效')
        if e.get('sharing') not in ('private', 'shareable'):
            raise ValueError('sharing 需为 private 或 shareable')
        if not isinstance(e.get('sources'), list) or any(not isinstance(x, dict) for x in e['sources']):
            raise ValueError('sources 需为来源对象数组')
    if pack.get('sha256') != seal(pack)['sha256']:
        raise ValueError('SHA256 不匹配，资料包可能损坏或被修改')
    return pack

def preview(pack):
    validate(pack)
    text = canonical(pack).decode('utf-8')
    warnings = []
    if any(e['sharing'] == 'private' for e in pack['entries']):
        warnings.append('包含私人条目；导出不自动改变共享授权。')
    if re.search(r'[A-Za-z]:[\\/]|/Users/|/home/|\\\\Users', text):
        warnings.append('发现本机绝对路径；请逐项检查是否适合分享。')
    if re.search(r'(?i)(api[_-]?key|secret|password|token)\s*[=:]\s*[^\s,]{6,}', text):
        warnings.append('发现可能的凭据文字，请人工检查；扫描不保证识别所有秘密。')
    return {'id': pack['id'], 'version': pack['version'], 'title': pack['title'],
            'author': pack['author'], 'license': pack['license'], 'sha256': pack['sha256'],
            'count': len(pack['entries']), 'warnings': warnings,
            'entries': [{k: e.get(k) for k in ('id', 'title', 'kind', 'verification', 'sharing', 'sources')} for e in pack['entries']]}

class Libraries:
    def __init__(self, data_root, mounts=(), documents=()):
        self.root = Path(data_root) / 'libraries'
        self.mounts = [Path(x) for x in mounts]
        self.documents = documents

    def catalog(self):
        result = []
        for root in [self.root, *self.mounts]:
            if not root.exists():
                continue
            for p in sorted(root.glob('*/*/pack.json')):
                try:
                    pack = validate(json.loads(p.read_text('utf-8-sig')))
                    result.append({'key': digest(str(p.resolve()))[:20], 'pack': pack,
                                   'installedLocally': root == self.root})
                except (ValueError, OSError) as e:
                    result.append({'error': str(e), 'name': p.parent.parent.name})
        for mount in self.documents:
            root = Path(mount['path'])
            if not root.is_dir():
                result.append({'error': '原资料目录不可读', 'name': mount.get('title', '外部文档')})
                continue
            # Existing notes stay authoritative in place. This is a derived text view, not a migration.
            entries = []
            for p in sorted(root.iterdir()):
                if not p.is_file() or p.is_symlink() or p.suffix.lower() not in ('.md', '.txt', '.json', '.mjs'):
                    continue
                if p.stat().st_size > 128 * 1024:
                    continue
                try:
                    content = p.read_text('utf-8-sig')
                except (UnicodeError, OSError):
                    continue
                entries.append({'id': 'doc-' + digest(p.name)[:20], 'title': p.name,
                                'kind': 'experience' if '经验' in p.name else 'knowledge', 'content': content,
                                'verification': 'unverified', 'sharing': 'private',
                                'read_scope': '仅为既有记录映射，未重新核验正文结论',
                                'sources': [{'path': str(p.resolve()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}]})
            # Chunk views so each derived pack also respects the portable format limits.
            for i in range(0, len(entries), 40):
                pack = seal({'schema': SCHEMA, 'id': mount['id'] + f'-{i//40+1}', 'version': 'live',
                             'title': mount.get('title', mount['id']), 'author': mount.get('author', 'local-owner'),
                             'license': 'private-use-only', 'entries': entries[i:i+40]})
                validate(pack)
                result.append({'key': digest(str(root.resolve()) + str(i))[:20], 'pack': pack,
                               'installedLocally': False, 'liveDocuments': True})
        return result

    def install(self, pack):
        validate(pack)
        dest = self.root / pack['id'] / pack['version'] / 'pack.json'
        with LOCK:
            if dest.exists():
                old = json.loads(dest.read_text('utf-8'))
                if old.get('sha256') == pack['sha256']:
                    return {'status': 'already-installed', 'id': pack['id'], 'version': pack['version']}
                raise FileExistsError('同 ID 同版本存在不同内容；请使用新版本，不覆盖旧经验')
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix('.tmp')
            try:
                tmp.write_bytes(canonical(pack))
                tmp.replace(dest)
            finally:
                tmp.unlink(missing_ok=True)
        return {'status': 'installed', 'id': pack['id'], 'version': pack['version']}

    def export(self, keys, metadata, allow_private=False):
        if not isinstance(keys, list) or not keys or len(keys) > 100 or len(set(keys)) != len(keys):
            raise ValueError('请选择1–100个不重复条目')
        available = {}
        for c in self.catalog():
            if 'pack' not in c:
                continue
            for e in c['pack']['entries']:
                # Original author, license and parent package identity travel with every export.
                copy = dict(e)
                copy['provenance'] = [*e.get('provenance', []), {k: c['pack'][k] for k in ('id', 'version', 'author', 'license', 'sha256')}]
                available[c['key'] + ':' + e['id']] = copy
        selected = []
        for key in keys:
            if key not in available:
                raise ValueError('条目已变化，请刷新后重选')
            e = available[key]
            if e['sharing'] == 'private' and not allow_private:
                raise ValueError('包含私人条目，请明确确认已检查内容和分享权利')
            e['id'] = 'entry-' + digest(key)[:20]
            selected.append(e)
        pack = seal(dict(schema=SCHEMA, **{k: metadata.get(k, '') for k in ('id', 'version', 'title', 'author', 'license')}, entries=selected))
        validate(pack)
        return pack
