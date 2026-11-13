"""Check a local collaboration run. Does not call agents or judge domain truth."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve(record, target):
    path = Path(target)
    return path if path.is_absolute() else record.parent / path


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        if read_json(path) != data:
            raise OSError("Saved record did not read back identically")
    finally:
        if temp.exists():
            temp.unlink()


def check(registry_path, run_path):
    registry, run = read_json(registry_path), read_json(run_path)
    errors, warnings, ready, waiting, decisions = [], [], [], [], []
    sources = {item["id"]: item for item in registry.get("sources", [])}
    experts = {item["id"]: item for item in registry.get("experts", [])}
    tasks = {item["id"]: item for item in run.get("tasks", [])}
    assessments = {item["id"]: item for item in run.get("assessments", [])}
    if len(tasks) != len(run.get("tasks", [])):
        errors.append("Duplicate task IDs")
    if len(experts) != len(registry.get("experts", [])):
        errors.append("Duplicate expert IDs")
    if not run.get("scope") or not run.get("stopCondition"):
        errors.append("Run needs a scope and stopCondition")
    if run.get("roundsUsed", 0) > run.get("maxRounds", 0):
        errors.append("Run exceeded cumulative round limit; reframe before more work")

    for item in run.get("inputs", []):
        path = resolve(run_path, item["path"])
        if not path.is_file():
            errors.append("Missing run input: " + item["path"])
        elif item.get("sha256") and fingerprint(path) != item["sha256"]:
            errors.append("Changed run input: " + item["path"])

    for item in run.get("assessments", []):
        dimensions = ("relevance", "evidenceCapability", "interfaceImpact", "reviewNeed")
        for dimension in dimensions:
            value = item.get(dimension, {})
            if not value.get("grade") or not value.get("reason"):
                errors.append(item["id"] + ": missing grade/reason for " + dimension)
        if item.get("expert") not in experts or not item.get("decisionReason"):
            errors.append(item["id"] + ": unknown expert or missing decision reason")
        decisions.append({"assessment": item["id"], "expert": item.get("expert"),
                          "decision": item.get("decision"), "reason": item.get("decisionReason")})

    completed = {"done", "needs-evidence"}
    allowed = {"planned", "running", "delivered", "done", "needs-evidence", "blocked", "failed"}
    for task_id, task in tasks.items():
        expert = experts.get(task.get("expert"))
        assessment = assessments.get(task.get("assessment"))
        if not expert or not assessment or assessment.get("expert") != task.get("expert"):
            errors.append(task_id + ": missing/mismatched expert assessment")
            continue
        if assessment.get("decision") not in {"now", "after-dependency"}:
            errors.append(task_id + ": task assigned despite non-execution decision")
        capability = next((c for c in expert.get("capabilities", [])
                           if c["id"] == task.get("capability")), None)
        if not capability:
            errors.append(task_id + ": undeclared capability")
        else:
            evidence = capability.get("evidence", [])
            if capability.get("status") not in {"researching", "limited", "supported"}:
                errors.append(task_id + ": unknown capability evidence status")
            if task.get("purpose") != "learning" and (not evidence or capability.get("status") == "researching"):
                errors.append(task_id + ": research-only capability cannot take this responsibility")
            for source_id in evidence:
                source = sources.get(source_id)
                if not source or not resolve(registry_path, source["path"]).is_file():
                    errors.append(task_id + ": missing capability evidence " + source_id)
            if capability.get("status") == "limited":
                warnings.append(task_id + ": limited capability; enforce recorded scope and limitations")
        if not task.get("deliverable") or not task.get("stopCondition") or not task.get("writeScope"):
            errors.append(task_id + ": incomplete delivery/stop/write contract")
        if task.get("purpose") not in {"delivery", "learning", "review", "system"}:
            errors.append(task_id + ": unknown task purpose")
        if assessment.get("relevance", {}).get("grade") == "none":
            errors.append(task_id + ": irrelevant role selected")
        if task.get("status") not in allowed:
            errors.append(task_id + ": unknown task state")
        if task.get("reviewOf"):
            original = tasks.get(task["reviewOf"])
            if not original or original.get("expert") == task.get("expert"):
                errors.append(task_id + ": review must have a different responsible expert")
            if not task.get("independenceMethod"):
                errors.append(task_id + ": missing independence method")
        deps = task.get("dependsOn", [])
        if any(dep not in tasks for dep in deps):
            errors.append(task_id + ": unknown dependency")
        accepted_gaps = task.get("acceptEvidenceGapFrom", [])
        if any(dep not in deps for dep in accepted_gaps):
            errors.append(task_id + ": evidence-gap acceptance names a non-dependency")
        pending = [dep for dep in deps if dep in tasks and (
            tasks[dep].get("status") not in completed or
            (tasks[dep].get("status") == "needs-evidence" and dep not in accepted_gaps))]
        if pending:
            waiting.append({"task": task_id, "dependencies": pending})
            if task.get("status") not in {"planned", "blocked"}:
                errors.append(task_id + ": started before dependencies completed")
        elif task.get("status") == "planned":
            ready.append(task_id)
        artifacts = task.get("artifacts", [])
        if task.get("status") in {"delivered", "done", "needs-evidence"}:
            if not artifacts or not task.get("outcome"):
                errors.append(task_id + ": completed state lacks saved outcome/artifact")
        for artifact in artifacts:
            path = resolve(run_path, artifact["path"])
            if not path.is_file():
                errors.append(task_id + ": missing artifact " + artifact["path"])
            elif artifact.get("sha256") and fingerprint(path) != artifact["sha256"]:
                errors.append(task_id + ": changed artifact " + artifact["path"])
        if task.get("status") == "needs-evidence" and not task.get("evidenceGap"):
            errors.append(task_id + ": evidence-gap exit needs a specific missing input")
        if task.get("requiresIndependentReview"):
            reviewers = [other for other in tasks.values() if other.get("reviewOf") == task_id]
            if not reviewers:
                errors.append(task_id + ": required independent review has no assigned task")

    # Detect dependency cycles even when no task has started.
    visiting, visited = set(), set()
    def visit(task_id):
        if task_id in visiting:
            errors.append("Dependency cycle at " + task_id)
            return
        if task_id in visited:
            return
        visiting.add(task_id)
        for dep in tasks[task_id].get("dependsOn", []):
            if dep in tasks:
                visit(dep)
        visiting.remove(task_id)
        visited.add(task_id)
    for task_id in tasks:
        visit(task_id)

    if run.get("status") == "complete" and any(t.get("status") not in completed for t in tasks.values()):
        errors.append("Run marked complete with unfinished assigned tasks")
    if run.get("designIssueStatus") == "closed":
        if not run.get("uniqueObjectLocated") or not run.get("technicalAndExperienceVerified"):
            errors.append("Design issue closed without located object and affected checks")
        for task in tasks.values():
            if task.get("reviewOf") and task.get("reviewVerdict") != "accepted":
                errors.append(task["id"] + ": design issue closed without accepted independent review")
    for task in tasks.values():
        tokens = task.get("usage", {}).get("tokens")
        if tokens is not None and (not isinstance(tokens, (int, float)) or tokens < 0):
            errors.append(task["id"] + ": tokens must be a nonnegative measurement or null")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "readyTasks": ready, "waitingTasks": waiting, "decisions": decisions,
            "checksProve": "record contracts, file identity, declared dependencies and state consistency",
            "checksDoNotProve": "source credibility, domain competence, design quality, compliance or real token savings"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        result = check(args.registry.resolve(), args.run.resolve())
        if args.out:
            save_json(args.out.resolve(), result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"ok": False, "fatal": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
