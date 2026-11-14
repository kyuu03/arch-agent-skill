"""A fresh copied checkout must work without the author's project or skill install."""
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class PortableTests(unittest.TestCase):
    def test_clean_copy_initialization_and_http_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp=Path(tmp);core=temp/'application'
            shutil.copytree(ROOT,core,ignore=shutil.ignore_patterns('__pycache__','.git','*.log'))
            data=temp/'personal-data'
            subprocess.run([sys.executable,'-B',str(core/'app.py'),'--init-data',str(data)],check=True,stdout=subprocess.DEVNULL)
            process=subprocess.Popen([sys.executable,'-B',str(core/'app.py'),'--config',str(data/'local.config.json'),'--port','0'],stdout=subprocess.DEVNULL)
            try:
                runtime=data/'storage/runtime.json'
                for _ in range(100):
                    if runtime.exists():break
                    if process.poll() is not None:self.fail('clean-copy server exited')
                    time.sleep(.05)
                self.assertTrue(runtime.exists())
                url=json.loads(runtime.read_text('utf-8'))['url']
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                def get(route):
                    return json.load(opener.open(url+route,timeout=5))
                state=get('/api/state')
                self.assertEqual(len(state['ledger']['requirements']),1)
                self.assertEqual(state['libraries'],[])
                token=get('/api/session')['token']
                def post(route,obj,origin=None):
                    req=urllib.request.Request(url+route,json.dumps(obj).encode(),headers={'Content-Type':'application/json','Origin':origin or url,'X-AC-Token':token})
                    return json.load(opener.open(req,timeout=5))
                pack=json.loads((core/'examples/example-methods.acpack.json').read_text('utf-8'))
                self.assertEqual(post('/api/packs/preview',{'pack':pack})['count'],1)
                with self.assertRaises(urllib.error.HTTPError) as error:post('/api/packs/install',{'pack':pack,'confirmedSha256':pack['sha256']},'https://foreign.invalid')
                self.assertEqual(error.exception.code,403)
                post('/api/packs/install',{'pack':pack,'confirmedSha256':pack['sha256']})
                installed=get('/api/state')['libraries'][0]
                exported=post('/api/packs/export',{'keys':[installed['key']+':'+pack['entries'][0]['id']],
                    'metadata':{'id':'portable-export','version':'1','title':'roundtrip','author':'tester','license':'private-use-only'}})['pack']
                self.assertEqual(exported['entries'][0]['verification'],'unverified')
                with self.assertRaises(urllib.error.HTTPError) as error:get('/file?path=app.py')
                self.assertEqual(error.exception.code,403)
            finally:
                process.terminate();process.wait(timeout=5)

if __name__=='__main__':unittest.main()
