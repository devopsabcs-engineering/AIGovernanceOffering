#!/usr/bin/env python
"""Notebook completion checker: executed notebooks, execution.json, and objective results.

Requires exactly the five executed notebooks in ``outputs/executed/<session_id>/``
with a matching ``execution.json`` (latest run per notebook exit code 0, source
hash equal to the committed notebook), no error outputs or incomplete cells, and
every required objective ``passed``. Writes an allowlisted
``outputs/results/<session_id>/verdict.json`` before exiting; exits nonzero
unless every required objective passed. Never prints notebook content.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aigov_common as common  # noqa: E402
from shared import results  # noqa: E402

TRACEBACK_MARKER = "Traceback (most recent call last)"


def inspect_executed_notebook(path: Path) -> str:
    """Return ``ok`` or a failure code for an executed notebook (content is never returned)."""
    try:
        notebook = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable"
    papermill = (notebook.get("metadata") or {}).get("papermill") or {}
    if papermill.get("exception"):
        return "papermill_exception"
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        source = "".join(source) if isinstance(source, list) else str(source)
        status = ((cell.get("metadata") or {}).get("papermill") or {}).get("status")
        if source.strip() and status is not None and status != "completed":
            return "incomplete_cell"
        for output in cell.get("outputs", []):
            if output.get("output_type") == "error":
                return "error_output"
            if output.get("output_type") == "stream" and output.get("name") == "stderr":
                text = output.get("text", "")
                text = "".join(text) if isinstance(text, list) else str(text)
                if TRACEBACK_MARKER in text:
                    return "traceback_output"
    return "ok"


def check_session(
    session_id: str,
    *,
    paths: common.Paths,
    notebooks_dir: Path,
) -> Dict[str, Any]:
    executed = paths.executed_dir(session_id)
    problems: List[str] = []
    notebooks: Dict[str, Dict[str, Any]] = {stem: {"execution": "missing", "exit_code": None}
                                            for stem in common.NOTEBOOK_STEMS}
    runs: Dict[str, Mapping[str, Any]] = {}
    if not executed.is_dir():
        problems.append("executed_directory_missing")
    else:
        execution_file = executed / "execution.json"
        try:
            execution = common.read_json(execution_file)
            if execution.get("session_id") != session_id or not isinstance(execution.get("runs"), list):
                problems.append("execution_json_mismatch")
            else:
                for run in execution["runs"]:
                    runs[str(run.get("notebook"))] = run
        except (OSError, ValueError):
            problems.append("execution_json_missing")
        present = {p.name for p in executed.glob("*.ipynb")}
        expected = {f"{stem}.ipynb" for stem in common.NOTEBOOK_STEMS}
        for extra in sorted(present - expected):
            safe = re.sub(r"[^A-Za-z0-9_.\-]", "_", Path(extra).stem)[:40] or "unnamed"
            problems.append(f"unexpected_notebook:{safe}")
        for stem in common.NOTEBOOK_STEMS:
            state = notebooks[stem]
            if f"{stem}.ipynb" not in present:
                state["execution"] = "missing"
                continue
            run = runs.get(stem)
            if run is None:
                state["execution"] = "not_recorded"
                continue
            state["exit_code"] = run.get("exit_code")
            if run.get("exit_code") != 0:
                state["execution"] = "failed"
                continue
            source = notebooks_dir / f"{stem}.ipynb"
            if not source.exists() or common.sha256_file(source) != run.get("source_sha256"):
                state["execution"] = "stale"
                continue
            state["execution"] = inspect_executed_notebook(executed / f"{stem}.ipynb")
        for stem, state in notebooks.items():
            if state["execution"] != "ok":
                problems.append(f"notebook_{state['execution']}:{stem}")

    objectives: Dict[str, Dict[str, str]] = {}
    excluded: Dict[str, str] = {}
    for stem, required in results.REQUIRED_OBJECTIVES.items():
        try:
            data = results.load_results(stem, session_id, root=paths.results_root)
        except (results.ResultsError, ValueError, OSError):
            problems.append(f"results_invalid:{stem}")
            data = {"objectives": {}, "excluded": {}}
        recorded = data.get("objectives") or {}
        for objective_id in required:
            status = (recorded.get(objective_id) or {}).get("status", "missing")
            if status not in results.STATUSES:
                status = "missing"
            objectives[objective_id] = {"notebook": stem, "status": status}
        for item_id in (data.get("excluded") or {}):
            if item_id in results.EXCLUDABLE_ITEMS.get(stem, ()):
                excluded[item_id] = "intentionally_excluded"
    not_passed = [oid for oid, o in objectives.items() if o["status"] != "passed"]
    status = "passed" if not problems and not not_passed else "failed"
    return {
        "schema_version": 1,
        "session_id": session_id,
        "status": status,
        "generated_at": common.fmt_utc(common.utc_now()),
        "notebooks": notebooks,
        "objectives": objectives,
        "excluded": excluded,
        "problems": problems,
        "counts": {
            "passed": sum(1 for o in objectives.values() if o["status"] == "passed"),
            "failed": sum(1 for o in objectives.values() if o["status"] == "failed"),
            "inconclusive": sum(1 for o in objectives.values() if o["status"] == "inconclusive"),
            "missing": sum(1 for o in objectives.values() if o["status"] == "missing"),
        },
    }


def print_table(verdict: Mapping[str, Any], out: TextIO) -> None:
    out.write(f"{'objective':<28} {'notebook':<26} status\n")
    for objective_id, entry in verdict["objectives"].items():
        out.write(f"{objective_id:<28} {entry['notebook']:<26} {entry['status']}\n")
    for problem in verdict["problems"]:
        out.write(f"problem: {problem}\n")
    out.write(f"verdict: {verdict['status']}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="check_notebook_outputs.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--session-id", help="Session ID (default SESSION_ID).")
    parser.add_argument("--notebooks-dir", default=str(common.REPO_ROOT / "notebooks"))
    parser.add_argument("--outputs-root", help="Outputs root (default <repo>/outputs).")
    return parser


def main(argv: Optional[Sequence[str]] = None, out: Optional[TextIO] = None) -> int:
    args = build_parser().parse_args(argv)
    out = out or sys.stdout
    try:
        session_id = common.resolve_session(args.session_id)
    except common.AutomationError as exc:
        out.write(f"check_notebook_outputs: {exc}\n")
        return 2
    paths = common.Paths.default(Path(args.outputs_root) if args.outputs_root else None)
    verdict = check_session(session_id, paths=paths, notebooks_dir=Path(args.notebooks_dir))
    results.atomic_write_json(paths.results_dir(session_id) / "verdict.json", verdict)
    print_table(verdict, out)
    return 0 if verdict["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
