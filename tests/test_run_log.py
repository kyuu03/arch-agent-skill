import json,tempfile,unittest
from pathlib import Path
from ac_platform.server import Project

class RunLogTests(unittest.TestCase):
 def test_optional_external_log_refresh_and_path_boundary(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'ledger.json').write_text('{"requirements":[]}',encoding='utf-8')
   cfg={'project_root':'.','data_root':'storage','ledger':'ledger.json'}
   p=Project(cfg,root/'config.json')
   self.assertIsNone(p.state()['runLog'])
   cfg['run_log']='run.json'
   cfg['run_logs']=['run.json']
   record={'schemaVersion':1,'mode':'reconstructed','modules':[],'events':[]}
   (root/'run.json').write_text(json.dumps(record),encoding='utf-8')
   self.assertEqual(p.state()['runLog']['events'],[])
   self.assertEqual(p.state()['runLogs'][0]['mode'],'reconstructed')
   record['events']=[{'id':'E01','time':None}]
   (root/'run.json').write_text(json.dumps(record),encoding='utf-8')
   self.assertIsNone(p.state()['runLog']['events'][0]['time'])
   cfg['run_log']='../outside.json'
   with self.assertRaises(ValueError):p.state()

if __name__=='__main__':unittest.main()
