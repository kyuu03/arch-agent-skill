"""Export a read-only trace matrix from the authoritative JSON ledger."""
import argparse
import html
import json
from pathlib import Path
from check_requirements import check


def build(ledger, previous, profile=None):
    data, result = check(ledger, previous)
    if not result['structuralCheckPassed']:
        raise ValueError('Ledger validation failed: ' + '; '.join(result['errors']))
    reqs = {r['id']: r for r in data['requirements']}
    profile = profile or {'requirements': []}
    if profile.get('requirements') and profile.get('ledgerVersion') != data['version']:
        raise ValueError('Verification profiles belong to another requirements baseline')
    configured = {}
    for row in profile.get('requirements', []):
        rid = row['id']
        if rid not in reqs or rid in configured:
            raise ValueError('Unknown or duplicate verification profile ID: ' + rid)
        configured[rid] = row
    rows = []
    for row in data['requirements']:
        rid = row['id']
        reviews = [v for v in data.get('reviews', []) if rid in v.get('requirementIds', [])]
        rows.append({
            'id': rid, 'title': row['title'], 'category': rid.split('-')[0] if '-' in rid else rid[0],
            'parent': row.get('parent'), 'related': row.get('related', []),
            'children': [q['id'] for q in data['requirements'] if q.get('parent') == rid],
            'lifecycle': row['lifecycle'], 'acceptance': row['acceptance'],
            'sources': row['sources'],
            'taskIds': [t['id'] for t in data.get('tasks', []) if rid in t.get('requirementIds', [])],
            'verificationProfile': configured.get(rid),
            'reviews': [{'id': v['id'], 'kind': v['kind'], 'verdict': v['verdict'],
                         'scope': v.get('scope', ''), 'appliesToVersion': v.get('appliesToVersion'),
                         'artifactIds': v.get('artifactIds', []), 'evidence': v.get('evidence', [])}
                        for v in reviews],
            'needsAttention': rid in result['needsAttentionIds'],
            'acceptanceVerdict': 'not-determined-by-this-export',
        })
    return {'version': data['version'], 'authority': str(Path(ledger).resolve()),
            'recordCount': len(rows), 'designCompletionPercentage': None,
            'note': 'Record inventory and declared trace links only; no automated gate aggregation or design acceptance.',
            'rows': rows}


def render(matrix):
    esc = html.escape
    def show(value):
        return esc(json.dumps(value, ensure_ascii=False))
    body = []
    for row in matrix['rows']:
        profile = row['verificationProfile']
        methods = ', '.join(profile.get('methods', [])) if profile else '尚未配置方法映射'
        scope = profile.get('status', '') if profile else ''
        reviews = '<br>'.join(esc(f'{v["id"]}: {v["kind"]} / {v["verdict"]} / {v["appliesToVersion"] or "旧版或适用性未确认"}') for v in row['reviews']) or '无登记检查'
        body.append(f'<tr data-search="{esc(row["id"] + " " + row["title"], quote=True)}">'
                    f'<td id="{esc(row["id"])}"><strong>{esc(row["id"])}</strong><br>{esc(row["title"])}</td>'
                    f'<td>{esc(row["parent"] or "总目标")}<br><small>子项 {esc(", ".join(row["children"]))}<br>关联 {esc(", ".join(row["related"]))}</small></td>'
                    f'<td>{show(row["sources"])}<br><small>任务 {esc(", ".join(row["taskIds"]))}</small></td>'
                    f'<td>{esc(methods)}<br><small>{esc(scope)}</small><details><summary>验收要点</summary><ul>'
                    + ''.join(f'<li>{esc(v)}</li>' for v in row['acceptance']) + '</ul></details></td>'
                    f'<td>{reviews}</td><td>{"有待复核或未解决记录" if row["needsAttention"] else "未由本表判定"}<br><small>用户评价与助手检查分开</small></td></tr>')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>需求与证据追踪矩阵</title><style>
body{font:15px/1.65 "Microsoft YaHei",sans-serif;margin:28px;color:#24343b;background:#f6f7f8}h1{font-size:28px}p{max-width:1100px}input{font:inherit;padding:10px;width:340px;max-width:90%}table{width:100%;border-collapse:collapse;background:white;margin-top:20px}th,td{padding:13px;vertical-align:top;border:1px solid #d8dfe4;overflow-wrap:anywhere}th{background:#e5edf1;text-align:left;position:sticky;top:0}td:first-child{min-width:155px}small{color:#63737b}tr[hidden]{display:none}@media(max-width:850px){.scroll{overflow:auto}table{min-width:1150px}}
</style><h1>需求与证据追踪矩阵</h1><p>版本 ''' + esc(matrix['version']) + '''。本页由权威JSON单向生成，展示''' + str(matrix['recordCount']) + '''条记录中的父子关系、来源、任务和检查声明。条目有重叠，未计算完成率；存在检查记录也不代表验收通过。</p><p>方法样例与正式验收配置分开。其余项保留“尚未配置”；当前没有自动闸门、常驻监控或完整逐项验收。限定范围证据、旧版证据和用户反馈均保留原身份。</p><input type="search" id="search" placeholder="搜索编号或标题" aria-label="搜索需求"><div class="scroll"><table><thead><tr><th>要点</th><th>关系</th><th>来源和任务</th><th>验收方法</th><th>已登记检查</th><th>当前需注意</th></tr></thead><tbody>''' + ''.join(body) + '''</tbody></table></div><script>document.querySelector('#search').addEventListener('input',e=>{const q=e.target.value.toLowerCase().trim();document.querySelectorAll('tbody tr').forEach(r=>r.hidden=!r.dataset.search.toLowerCase().includes(q))});</script></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--previous', required=True)
    parser.add_argument('--profiles')
    parser.add_argument('--out', required=True)
    parser.add_argument('--html', required=True)
    args = parser.parse_args()
    profile = json.loads(Path(args.profiles).read_text('utf8')) if args.profiles else None
    matrix = build(args.ledger, args.previous, profile)
    Path(args.out).write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding='utf8')
    Path(args.html).write_text(render(matrix), encoding='utf8')
    print(f'Exported {matrix["recordCount"]} records; design acceptance not computed.')


if __name__ == '__main__':
    main()
