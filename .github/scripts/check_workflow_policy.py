"""Portfolio workflow rules that zizmor does not check.

zizmor (.github/workflows/workflow-lint.yml) covers pinning, template
injection, excessive permissions, credential persistence and dangerous
triggers. This script covers the rest of what CI-CD-STANDARD asks of a
workflow file, each rule a defect that has shipped somewhere in the
portfolio before:

1. Every `run:` step runs under an explicit `shell: bash` (Actions then uses
   `bash -eo pipefail`; the implicit default is `bash -e`, which lets a
   failure on the left of a pipe pass) and its script starts with
   `set -euo pipefail`.
2. A workflow triggered by `push` or `pull_request` produces status checks,
   so its concurrency group must be per commit: the key has to reference
   `github.sha` (or `github.run_id`). A ref-only key lets a third push evict
   the pending run and leaves a commit with no verdict (§11c).
3. A job that deploys (declares an `environment`, or holds `pages: write` or
   `id-token: write`) runs under a concurrency group with
   `cancel-in-progress: false` (§8b, CICD-23) and restores no cache (§8c,
   CICD-24): no `actions/cache` step and no `cache`/`enable-cache` input on a
   setup action.
4. No `continue-on-error: true` and no `|| true` anywhere: a gate that
   cannot fail is not a gate.

`--self-test` first runs every rule against small workflows that break it
and asserts each one is caught, so a rule that silently stopped matching
fails CI instead of passing everything.

Usage:
    check_workflow_policy.py [--self-test] <workflow.yml> [...]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

PER_COMMIT_TOKENS = ("github.sha", "github.run_id")
DEPLOY_PERMISSIONS = ("pages", "id-token")


def _triggers(doc: dict[Any, Any]) -> set[str]:
    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1).
    on = doc.get("on", doc.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    if isinstance(on, dict):
        return set(on)
    return set()


def _shell(step: dict[str, Any], job: dict[str, Any], doc: dict[str, Any]) -> str | None:
    for scope in (step, (job.get("defaults") or {}).get("run") or {}, (doc.get("defaults") or {}).get("run") or {}):
        if isinstance(scope, dict) and scope.get("shell"):
            return str(scope["shell"])
    return None


def _first_line(script: str) -> str:
    for line in script.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def _is_deploy_job(job: dict[str, Any]) -> bool:
    perms = job.get("permissions") or {}
    writes = isinstance(perms, dict) and any(perms.get(p) == "write" for p in DEPLOY_PERMISSIONS)
    return bool(job.get("environment")) or writes


def check(doc: dict[str, Any], name: str) -> list[str]:
    """Every rule violation in one parsed workflow, as `name: message`."""
    problems: list[str] = []
    jobs = doc.get("jobs") or {}
    workflow_concurrency = doc.get("concurrency")

    if _triggers(doc) & {"push", "pull_request"}:
        group = str((workflow_concurrency or {}).get("group", "")) if isinstance(workflow_concurrency, dict) else ""
        if not any(token in group for token in PER_COMMIT_TOKENS):
            problems.append(f"{name}: push/pull_request workflow needs a per-commit concurrency group, got {group!r}")

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        if job.get("continue-on-error") is True:
            problems.append(f"{name}: job {job_id} sets continue-on-error: true")
        deploy = _is_deploy_job(job)
        if deploy:
            concurrency = job.get("concurrency") or workflow_concurrency
            if not isinstance(concurrency, dict) or concurrency.get("cancel-in-progress") is not False:
                problems.append(f"{name}: deploy job {job_id} needs concurrency with cancel-in-progress: false")
        for index, step in enumerate(job.get("steps") or []):
            label = f"{name}: job {job_id} step {step.get('name') or step.get('uses') or index}"
            if step.get("continue-on-error") is True:
                problems.append(f"{label} sets continue-on-error: true")
            uses = str(step.get("uses", ""))
            inputs = step.get("with") or {}
            if deploy and (
                uses.startswith("actions/cache")
                or inputs.get("enable-cache") not in (None, False, "false")
                or inputs.get("cache") not in (None, False, "false", "")
            ):
                problems.append(f"{label} restores a cache in a deploy job")
            script = step.get("run")
            if script is None:
                continue
            if _shell(step, job, doc) != "bash":
                problems.append(f"{label} does not run under an explicit `shell: bash`")
            if _first_line(str(script)) != "set -euo pipefail":
                problems.append(f"{label} does not start with `set -euo pipefail`")
            if "|| true" in str(script):
                problems.append(f"{label} mutes a failure with `|| true`")
    return problems


def check_file(path: Path) -> list[str]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        return [f"{path}: not a workflow mapping"]
    return check(doc, str(path))


_GOOD = """
on: {push: {branches: [main]}, pull_request: {}}
concurrency: {group: "${{ github.workflow }}-${{ github.ref }}-${{ github.sha }}", cancel-in-progress: true}
jobs:
  verify:
    defaults: {run: {shell: bash}}
    steps:
      - run: |
          set -euo pipefail
          make verify
"""

_BAD = {
    "ref-only concurrency": _GOOD.replace("-${{ github.sha }}", ""),
    "no explicit bash": _GOOD.replace("    defaults: {run: {shell: bash}}\n", ""),
    "no set -euo pipefail": _GOOD.replace("set -euo pipefail", "set -e"),
    "|| true": _GOOD.replace("make verify", "make verify || true"),
    "continue-on-error": _GOOD.replace("    steps:", "    continue-on-error: true\n    steps:"),
    "deploy may cancel": """
on: {schedule: [{cron: "0 0 * * *"}]}
concurrency: {group: pages, cancel-in-progress: true}
jobs:
  deploy:
    permissions: {pages: write, id-token: write}
    steps: [{uses: actions/deploy-pages@0000000000000000000000000000000000000000}]
""",
    "deploy restores a cache": """
on: {schedule: [{cron: "0 0 * * *"}]}
concurrency: {group: pages, cancel-in-progress: false}
jobs:
  deploy:
    environment: github-pages
    steps: [{uses: astral-sh/setup-uv@0000000000000000000000000000000000000000, with: {enable-cache: true}}]
""",
}


def self_test() -> list[str]:
    """Each _BAD sample must differ from _GOOD (the sabotage landed) and
    must be flagged; _GOOD must pass."""
    failures = []
    if check(yaml.safe_load(_GOOD), "good") != []:
        failures.append("self-test: the known-good workflow was flagged")
    for label, text in _BAD.items():
        if text == _GOOD:
            failures.append(f"self-test: the {label!r} sample is identical to the good one (sabotage did not apply)")
        elif not check(yaml.safe_load(text), label):
            failures.append(f"self-test: rule did not catch {label!r}")
    return failures


def main(argv: list[str]) -> int:
    problems: list[str] = []
    if argv and argv[0] == "--self-test":
        argv = argv[1:]
        problems += self_test()
        if not problems:
            print(f"workflow policy self-test: all {len(_BAD)} planted violations caught")
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    for arg in argv:
        problems += check_file(Path(arg))
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"workflow policy: {len(argv)} workflow(s) conform")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
