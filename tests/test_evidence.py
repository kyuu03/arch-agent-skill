import json,tempfile,unittest,hashlib
from pathlib import Path
from ac_platform.server import Project

class EvidenceTests(unittest.TestCase):
 def test_bound_evidence_containment_and_changed_file(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);(root/'note.md').write_text('observed result',encoding='utf-8')
   expected=hashlib.sha256((root/'note.md').read_bytes()).hexdigest()
   log={'id':'run','events':[{'id':'E01','evidence':[{'path':'note.md','sha256':expected},'legacy text',{'path':'../outside.md'}]}]}
   (root/'run.json').write_text(json.dumps(log),encoding='utf-8')
   p=Project({'project_root':'.','data_root':'storage','run_log':'run.json'},root/'config.json')
   e,raw,suffix=p.evidence('run','E01',0)
   self.assertTrue(e['matchesExpected']);self.assertEqual(e['content'],'observed result')
   (root/'note.md').write_text('changed',encoding='utf-8')
   self.assertFalse(p.evidence('run','E01',0)[0]['matchesExpected'])
   for args in [('unknown','E01',0),('run','E99',0),('run','E01',-1),('run','E01',1),('run','E01',2)]:
    with self.assertRaises(ValueError):p.evidence(*args)
 def test_html_is_download_and_image_kind_ignores_claim(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);(root/'source.html').write_text('<script>danger()</script>',encoding='utf-8')
   (root/'run.json').write_text(json.dumps({'id':'r','events':[{'id':'e','evidence':[{'path':'source.html','kind':'image'}]}]}),encoding='utf-8')
   p=Project({'project_root':'.','data_root':'storage','run_logs':['run.json']},root/'config.json')
   e,_,_=p.evidence('r','e',0);self.assertEqual(e['kind'],'download');self.assertNotIn('content',e)

if __name__=='__main__':unittest.main()
