"""Python 3.11+, standard library only."""
import argparse
import json
import shutil
from pathlib import Path
from ac_platform.server import serve

ROOT = Path(__file__).resolve().parent

def main():
    p = argparse.ArgumentParser(description='建筑协作平台：项目只读映射 + 外接资料包管理')
    p.add_argument('--config', type=Path, help='本机绑定配置 JSON')
    p.add_argument('--port', type=int, default=8850)
    p.add_argument('--init-data', type=Path, help='在全新外部目录初始化演示项目，成功后退出')
    args = p.parse_args()
    if args.init_data:
        target = args.init_data.resolve()
        if target.exists():
            p.error('目标已存在；初始化不覆盖现有资料')
        shutil.copytree(ROOT/'examples/demo', target/'project')
        config = {'schemaVersion': 1, 'title': '我的建筑协作项目', 'project_root': 'project', 'data_root': 'storage',
                  'ledger': 'requirements/current.json', 'blackboard': 'blackboard.md', 'checklist': 'checklist.md',
                  'experts': 'experts.json', 'library_mounts': [], 'artifacts': []}
        (target/'local.config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), 'utf-8')
        print(target/'local.config.json')
        return
    serve((args.config or ROOT/'config.example.json').resolve(), args.port)

if __name__ == '__main__':
    main()
