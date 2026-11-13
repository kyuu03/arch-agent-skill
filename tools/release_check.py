"""Check a public-core checkout, never traverse linked private directories."""
import hashlib
import json
import re
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','__pycache__'}
PRIVATE_NAMES={'local.config.json','runtime.json','.env','migration-inventory.json'}

def check():
    errors=[];inventory=[]
    for p in sorted(ROOT.rglob('*')):
        if any(x in SKIP for x in p.relative_to(ROOT).parts):continue
        if p.is_symlink():errors.append(f'禁止发布软链接: {p.relative_to(ROOT)}');continue
        if not p.is_file():continue
        rel=p.relative_to(ROOT).as_posix()
        if p.name in PRIVATE_NAMES or p.suffix in {'.skp','.rvt','.dwg','.pdf','.zip','.log'}:
            errors.append('疑似本地数据或二进制成果: '+rel)
        b=p.read_bytes()
        try:t=b.decode('utf-8-sig')
        except UnicodeError:errors.append('未声明的二进制文件: '+rel);continue
        # No private username is needed to recognize a personal machine path.
        if re.search(r'(?i)[a-z]:[\\/]Users[\\/][a-z0-9_.-]+[\\/]|/(?:Users|home)/[a-z0-9_.-]+/',t):
            errors.append('个人绝对路径: '+rel)
        if re.search(r'\bsk-[A-Za-z0-9_-]{24,}\b|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----',t):
            errors.append('可能的密钥: '+rel)
        if rel!='release-manifest.json':inventory.append({'path':rel,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
    return {'passed':not errors,'errors':errors,'files':inventory,'scope':'core only; heuristic scan, not a proof of all confidentiality or rights'}

if __name__=='__main__':
    report=check()
    if '--manifest' in sys.argv and report['passed']:
        (ROOT/'release-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'fileCount':len(report['files']),'errors':report['errors']},ensure_ascii=False,indent=2))
    sys.exit(0 if report['passed'] else 1)
