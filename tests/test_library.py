import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from ac_platform.library import Libraries, seal, validate

SAMPLE=Path(__file__).resolve().parents[1]/'examples/example-methods.acpack.json'

class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.lib=Libraries(self.root)
        self.pack=json.loads(SAMPLE.read_text('utf-8'))
    def tearDown(self):
        self.tmp.cleanup()
    def test_import_roundtrip_preserves_evidence_and_status(self):
        self.lib.install(self.pack)
        c=self.lib.catalog()[0]
        p=self.lib.export([c['key']+':'+self.pack['entries'][0]['id']],
                          {'id':'selected','version':'1.0','title':'选定','author':'tester','license':'private-use-only'})
        self.assertEqual(p['entries'][0]['sources'],self.pack['entries'][0]['sources'])
        self.assertEqual(p['entries'][0]['verification'],'unverified')
        self.assertEqual(p['entries'][0]['provenance'][0]['sha256'],self.pack['sha256'])
        second=Libraries(self.root/'other')
        second.install(p)
        self.assertEqual(second.catalog()[0]['pack']['sha256'],p['sha256'])
    def test_corruption_and_path_traversal_rejected(self):
        self.pack['entries'][0]['content']+='tampered'
        with self.assertRaises(ValueError):self.lib.install(self.pack)
        self.pack['id']='../escape'
        with self.assertRaises(ValueError):self.lib.install(seal(self.pack))
        self.assertFalse((self.root/'escape').exists())
    def test_no_overwrite_and_idempotence_under_concurrency(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.lib.install(self.pack),range(8)))
        self.assertEqual(sum(r['status']=='installed' for r in results),1)
        modified=dict(self.pack,title='different')
        with self.assertRaises(FileExistsError):self.lib.install(seal(modified))
    def test_private_export_needs_explicit_confirmation(self):
        self.pack['entries'][0]['sharing']='private'
        self.lib.install(seal(self.pack))
        c=self.lib.catalog()[0];keys=[c['key']+':'+c['pack']['entries'][0]['id']]
        meta={'id':'p','version':'1','title':'private','author':'a','license':'private-use-only'}
        with self.assertRaises(ValueError):self.lib.export(keys,meta)
        self.assertEqual(self.lib.export(keys,meta,True)['entries'][0]['sharing'],'private')
    def test_live_directory_is_read_only_and_refreshes(self):
        docs=self.root/'notes';docs.mkdir();p=docs/'note.md';p.write_text('first',encoding='utf-8')
        lib=Libraries(self.root/'data',documents=[{'id':'notes','path':str(docs),'title':'notes'}])
        a=lib.catalog()[0]['pack'];p.write_text('second',encoding='utf-8');b=lib.catalog()[0]['pack']
        self.assertNotEqual(a['sha256'],b['sha256'])
        self.assertEqual(b['entries'][0]['content'],'second')
        self.assertEqual(b['entries'][0]['verification'],'unverified')

if __name__=='__main__':unittest.main()
