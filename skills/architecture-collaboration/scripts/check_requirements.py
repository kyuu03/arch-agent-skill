"""Validate a declared requirements ledger. Does not certify design quality."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def check(path, previous=None):
    path = Path(path).resolve()
    data = read(path)
    errors, warnings = [], []
    def indexed(key):
        rows = data.get(key, [])
        counts = Counter(row.get('id') for row in rows)
        if None in counts or '' in counts or any(n != 1 for n in counts.values()):
            errors.append(f'{key}: missing or duplicate IDs')
        return {row.get('id'): row for row in rows}
    reqs = indexed('requirements')
    sources = indexed('sources')
    artifacts = indexed('artifacts')
    tasks = indexed('tasks')
    reviews = indexed('reviews')
    def target(value):
        p = Path(value)
        return p if p.is_absolute() else path.parent / p
    def references(ids, collection, where):
        for item in ids:
            if item not in collection:
                errors.append(f'{where}: unknown ID {item}')
    if not data.get('version'):
        errors.append('version is required')
    for sid, source in sources.items():
        if not source.get('path') or not target(source['path']).exists():
            errors.append(f'source {sid}: missing path')
    for rid, row in reqs.items():
        if not row.get('statement') or not row.get('acceptance'):
            errors.append(f'{rid}: statement and acceptance criteria are required')
        refs = row.get('sources', [])
        if not refs:
            errors.append(f'{rid}: no requirement source')
        references([s['id'] for s in refs], sources, str(rid))
        references(row.get('related', []), reqs, str(rid))
        if row.get('parent'):
            references([row['parent']], reqs, str(rid))
        lifecycle = row.get('lifecycle')
        if lifecycle not in {'active', 'superseded', 'retired'}:
            errors.append(f'{rid}: invalid lifecycle')
        if lifecycle != 'active' and (not row.get('decisionSource') or not row.get('reason')):
            errors.append(f'{rid}: retirement/replacement needs reason and decisionSource')
        if lifecycle != 'active' and row.get('decisionSource'):
            references([row['decisionSource']], sources, f'{rid} decision')
        if row.get('status') in {'done', 'completed', 'closed'}:
            errors.append(f'{rid}: permanent completion belongs to tasks, not persistent criteria')
        seen, current = set(), rid
        while current in reqs:
            if current in seen:
                errors.append(f'{rid}: parent cycle')
                break
            seen.add(current)
            current = reqs[current].get('parent')
    for aid, artifact in artifacts.items():
        p = target(artifact.get('path', ''))
        if not artifact.get('path') or not p.is_file():
            errors.append(f'artifact {aid}: missing file')
        elif not artifact.get('sha256'):
            errors.append(f'artifact {aid}: no fingerprint')
        elif hashlib.sha256(p.read_bytes()).hexdigest() != artifact['sha256'].lower():
            errors.append(f'artifact {aid}: file changed; review applicability must be reassessed')
    for tid, task in tasks.items():
        references(task.get('requirementIds', []), reqs, f'task {tid}')
        if not task.get('requirementIds'):
            errors.append(f'task {tid}: no linked requirement')
    reviewed, limited, attention, negative, feedback = set(), set(), set(), set(), set()
    kinds = {'assistant-technical', 'assistant-experience', 'independent', 'user-feedback'}
    verdicts = {'passed', 'limited', 'failed', 'needs-recheck', 'not-reviewed', 'recorded'}
    for vid, review in reviews.items():
        ids = review.get('requirementIds', [])
        references(ids, reqs, f'review {vid}')
        references(review.get('artifactIds', []), artifacts, f'review {vid}')
        if not ids or review.get('kind') not in kinds or review.get('verdict') not in verdicts:
            errors.append(f'review {vid}: invalid scope, kind or verdict')
        if review.get('verdict') in {'passed', 'limited'}:
            if not review.get('artifactIds') or not review.get('scope') or not review.get('evidence'):
                errors.append(f'review {vid}: a positive check needs version, scope and evidence')
            for aid in review.get('artifactIds', []):
                if review.get('artifactHashes', {}).get(aid) != artifacts.get(aid, {}).get('sha256'):
                    errors.append(f'review {vid}: missing or changed artifact hash for {aid}')
            if review.get('appliesToVersion') == data.get('version'):
                if review.get('verdict') == 'passed' and review.get('kind') != 'user-feedback':
                    reviewed.update(ids)
                else:
                    limited.update(ids)
        if review.get('kind') == 'user-feedback':
            feedback.update(ids)
        if review.get('verdict') in {'failed', 'needs-recheck'}:
            resolvers = [r for r in reviews.values() if vid in r.get('resolves', [])
                         and r.get('resolutionReason')
                         and ((review.get('kind') == 'user-feedback' and r.get('verdict') in {'passed', 'limited', 'recorded'})
                              or (review.get('kind') != 'user-feedback' and r.get('verdict') == 'passed'
                                  and r.get('evidence') and r.get('artifactIds')))
                         and r.get('appliesToVersion') == data.get('version')
                         and (review.get('kind') != 'user-feedback' or r.get('kind') == 'user-feedback')
                         and set(ids).issubset(r.get('requirementIds', []))]
            if not resolvers:
                negative.update(ids)
        references(review.get('resolves', []), reviews, f'review {vid} resolves')
        for p in review.get('evidence', []):
            if not target(p).is_file():
                errors.append(f'review {vid}: missing evidence {p}')
        if review.get('kind') == 'user-feedback' and not review.get('quote'):
            errors.append(f'review {vid}: user feedback needs original words')
    for impact in data.get('pendingImpacts', []):
        references(impact.get('requirementIds', []), reqs, 'pending impact')
        attention.update(impact.get('requirementIds', []))
    for coverage in data.get('sourceCoverage', []):
        references([coverage.get('sourceId')], sources, 'source coverage')
        references(coverage.get('requirementIds', []), reqs, 'source coverage')
    if previous:
        before = read(previous)
        old = {x['id']: x for x in before.get('requirements', [])}
        if before.get('version') != data.get('version'):
            if data.get('parentVersion') != before.get('version'):
                errors.append('parentVersion does not match previous ledger')
        for item in data.get('changes', []):
            references([item.get('source')], sources, 'change decision source')
        changed = {x.get('id') for x in data.get('changes', []) if x.get('reason') and x.get('source') in sources}
        semantic_change = bool(reqs.keys() - old.keys())
        for rid, row in old.items():
            if rid not in reqs:
                errors.append(f'{rid}: silently lost from previous baseline')
                continue
            fields = ('parent', 'statement', 'acceptance', 'lifecycle', 'related')
            if any(row.get(k) != reqs[rid].get(k) for k in fields) and rid not in changed:
                errors.append(f'{rid}: changed without reason and decision source')
            if any(row.get(k) != reqs[rid].get(k) for k in fields):
                semantic_change = True
        for rid in reqs.keys() - old.keys():
            if rid not in changed:
                errors.append(f'{rid}: added without change record')
        if semantic_change and before.get('version') == data.get('version'):
            errors.append('requirement meaning changed without a new baseline version')
        for old_artifact in before.get('artifacts', []):
            aid = old_artifact['id']
            if aid in artifacts and old_artifact.get('sha256') != artifacts[aid].get('sha256'):
                errors.append(f'artifact {aid}: ID rebound to different content; use a new ID')
        for old_review in before.get('reviews', []):
            vid = old_review['id']
            if vid not in reviews:
                errors.append(f'review {vid}: history silently lost; retain original and add a resolution')
            elif reviews[vid] != old_review:
                errors.append(f'review {vid}: immutable history edited; add a new review instead')
    for item in data.get('changes', []):
        references([item.get('source')], sources, 'change decision source')
    active = {rid for rid, row in reqs.items() if row.get('lifecycle') == 'active'}
    attention.update(negative)
    reviewed.difference_update(attention)
    missing = sorted(active - reviewed)
    if missing:
        warnings.append(f'{len(missing)} persistent criteria have no positive review explicitly applicable to this baseline; this is not a verdict on design quality')
    if data.get('pendingImpacts'):
        warnings.append(f'{len(data["pendingImpacts"])} pending impact records require review')
    return data, {'structuralCheckPassed': not errors, 'designAcceptance': 'not-determined-by-this-tool',
                  'version': data.get('version'), 'requirementCount': len(reqs),
                  'activeCount': len(active), 'unreviewedIds': missing,
                  'someCurrentPositiveEvidenceIds': sorted(reviewed),
                  'limitedEvidenceIds': sorted(limited), 'needsAttentionIds': sorted(attention),
                  'unresolvedNegativeIds': sorted(negative), 'userFeedbackIds': sorted(feedback),
                  'errors': errors, 'warnings': warnings}


def render(data, report):
    lines = [f'# 当前大清单 {data["version"]}', '',
             '这是持续验收范围。局部任务完成不会移除要点；本页由同目录 current.json 生成。', '',
             f'有效要点 {report["activeCount"]} 项。结构检查不代表设计验收。', '',
             '## 当前成果与版本', '']
    for a in data.get('artifacts', []):
        lines.append(f'- {a["id"]}：{a.get("role", "")}；文件 `{a["path"]}`；SHA256 `{a["sha256"]}`')
    lines += ['', '## 当前重点与未复核影响', '']
    for impact in data.get('pendingImpacts', []):
        lines.append(f'- {", ".join(impact["requirementIds"])}：{impact["reason"]}')
    lines += ['', '## 持续验收要点', '']
    for row in data.get('requirements', []):
        lines += [f'### {row["id"]} {row["title"]}', '',
                  f'上级：{row.get("parent") or "总目标"}；有效性：{row["lifecycle"]}', '',
                  row['statement'], '', '验收时检查：', '']
        lines.extend(f'- {item}' for item in row['acceptance'])
        lines += ['', '来源：' + '；'.join(f'{x["id"]} {x.get("locator", "")}' for x in row['sources']), '']
        matching = [x for x in data.get('reviews', []) if row['id'] in x.get('requirementIds', [])]
        for review in matching:
            lines += [f'检查记录 {review["id"]}：{review["kind"]} / {review["verdict"]}；{review.get("scope", "")}；适用版本 {review.get("appliesToVersion", "未确认")}。', '']
    lines += ['## 来源与迁移边界', '']
    for source in data.get('sources', []):
        lines += [f'- {source["id"]}：{source["path"]}；{source.get("scope", "") }']
    lines += ['', data.get('migrationLimitations', ''), '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--previous')
    parser.add_argument('--out')
    parser.add_argument('--render')
    args = parser.parse_args()
    data, result = check(args.ledger, args.previous)
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    if args.render:
        Path(args.render).write_text(render(data, result), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['structuralCheckPassed'] else 1)


if __name__ == '__main__':
    main()
