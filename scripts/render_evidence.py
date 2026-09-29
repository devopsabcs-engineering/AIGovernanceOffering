#!/usr/bin/env python
"""Sanitized evidence builder and credential-free PNG renderer.

``sanitize`` runs in the job that holds secrets. It builds
``outputs/evidence/<session_id>/evidence.json`` only from allowlisted scalar
fields of the notebook result files, verdict, readiness and probe summaries,
showback report, budget totals, and (post-cleanup) residual report. Inputs that
are absent are recorded as ``not_run``; malformed inputs, credential patterns,
or known secret values fail closed: no evidence.json and no PNG remain, and
only a fixed status code is written.

``render`` reads evidence.json only (never executed notebooks, HTML, or the
network) and writes ``lab00-environment-*.png`` through ``lab07-teardown-*.png``.
Anything not ``passed`` renders as a status card, never as a success image.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, TextIO, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aigov_common as common  # noqa: E402
from shared import results  # noqa: E402
from shared.results import atomic_write_json  # noqa: E402

LABS: Tuple[Tuple[str, str], ...] = (
    ("lab00-environment", "readiness"),
    ("lab01-setup-validation", "00-setup-and-validation"),
    ("lab02-token-limits", "demo1-token-limits"),
    ("lab03-token-metrics", "demo2-token-metrics"),
    ("lab04-content-safety", "demo3-content-safety"),
    ("lab05-resilient-pool", "demo4-resilient-pool"),
    ("lab06-chargeback", "showback"),
    ("lab07-teardown", "residual"),
)
TYPE_LABELS = {
    "microsoft.cognitiveservices/accounts/deployments": "model-deployment",
    "microsoft.apimanagement/service": "apim-service",
    "microsoft.cognitiveservices/accounts": "ai-account",
    "microsoft.alertsmanagement/smartdetectoralertrules": "smart-detector-rule",
    "microsoft.insights/actiongroups": "action-group",
    "microsoft.insights/components": "app-insights",
    "microsoft.operationalinsights/workspaces": "log-analytics",
}
TOMBSTONE_KINDS = ("apim", "cognitive", "workspace")
MAX_EVIDENCE_BYTES = 1_000_000

_CODE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}(:[A-Za-z0-9_.\-]{1,64})?$")
_NAME = re.compile(r"^[A-Za-z0-9 _.\-]{1,80}$")
_TEXT = re.compile(r"^[A-Za-z0-9 _.,;:()/+\-]{0,160}$")
_MONEY = re.compile(r"^\d{1,12}(\.\d{1,20})?$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class SanitizeError(RuntimeError):
    """Malformed input or a secret hit; ``code`` is a fixed nonsecret reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# Field validators
# ---------------------------------------------------------------------------


def _match(value: Any, pattern: re.Pattern, *, optional: bool = False) -> Optional[str]:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not pattern.match(value):
        raise SanitizeError("malformed_input")
    return value


def _int(value: Any, *, optional: bool = False) -> Optional[int]:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SanitizeError("malformed_input")
    return value


def _num(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SanitizeError("malformed_input")
    return float(value)


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise SanitizeError("malformed_input")
    return value


def _load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise SanitizeError("malformed_input")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SanitizeError("malformed_input") from None
    if not isinstance(data, dict):
        raise SanitizeError("malformed_input")
    return data


NOT_RUN = {"status": "not_run"}


# ---------------------------------------------------------------------------
# Extractors (allowlisted fields only)
# ---------------------------------------------------------------------------


def extract_notebook(stem: str, session_id: str, paths: common.Paths) -> Dict[str, Any]:
    path = paths.results_root / session_id / f"{stem}.json"
    if not path.exists():
        return dict(NOT_RUN)
    try:
        data = results.load_results(stem, session_id, root=paths.results_root)
        objectives = {}
        for objective_id in results.REQUIRED_OBJECTIVES[stem]:
            entry = (data.get("objectives") or {}).get(objective_id)
            if entry is None:
                objectives[objective_id] = {"status": "missing", "evidence": {}}
                continue
            if entry.get("status") not in results.STATUSES:
                raise SanitizeError("malformed_input")
            objectives[objective_id] = {
                "status": entry["status"],
                "evidence": results.validate_evidence(entry.get("evidence") or {}),
            }
        excluded = {}
        for item_id, entry in (data.get("excluded") or {}).items():
            if item_id not in results.EXCLUDABLE_ITEMS.get(stem, ()):
                raise SanitizeError("malformed_input")
            excluded[item_id] = results.validate_evidence({"reason": (entry or {}).get("reason")})["reason"]
    except (results.ResultsError, ValueError, TypeError, AttributeError):
        raise SanitizeError("malformed_input") from None
    return {"status": "recorded", "objectives": objectives, "excluded": excluded}


def extract_verdict(data: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if data is None:
        return dict(NOT_RUN)
    try:
        return {
            "status": _match(data["status"], _CODE),
            "notebooks": {
                _match(stem, _CODE): {"execution": _match(entry["execution"], _CODE),
                                      "exit_code": _int(entry.get("exit_code"), optional=True)}
                for stem, entry in data["notebooks"].items()
            },
            "objectives": {_match(oid, _CODE): _match(entry["status"], _CODE)
                           for oid, entry in data["objectives"].items()},
            "problems": [_match(p, _CODE) for p in data.get("problems", [])],
            "counts": {_match(k, _CODE): _int(v) for k, v in data.get("counts", {}).items()},
        }
    except (KeyError, TypeError, AttributeError):
        raise SanitizeError("malformed_input") from None


def extract_readiness(data: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if data is None:
        return dict(NOT_RUN)
    try:
        return {
            "status": _match(data["status"], _CODE),
            "failing_check": _match(data.get("failing_check", ""), re.compile(r"^[a-z_]{0,64}$")),
            "scope": _match(data.get("scope", ""), re.compile(r"^[a-z\-]{0,64}$")),
            "checks": {
                _match(name, _CODE): {"status": _match(c["status"], _CODE), "attempts": _int(c.get("attempts", 0)),
                                      "code": _match(c.get("code", ""), _CODE)}
                for name, c in data["checks"].items()
            },
        }
    except (KeyError, TypeError, AttributeError):
        raise SanitizeError("malformed_input") from None


def extract_probes(data: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if data is None:
        return dict(NOT_RUN)
    try:
        probes = {}
        for name, p in data["probes"].items():
            entry = {"status": _int(p.get("status"), optional=True), "passed": _bool(p["passed"])}
            if "bypass_observed" in p:
                entry["bypass_observed"] = _bool(p["bypass_observed"])
            probes[_match(name, _CODE)] = entry
        return {"status": _match(data["status"], _CODE), "probes": probes}
    except (KeyError, TypeError, AttributeError):
        raise SanitizeError("malformed_input") from None


def extract_showback(data: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if data is None:
        return dict(NOT_RUN)
    try:
        if data["label"] != common.SHOWBACK_LABEL:
            raise SanitizeError("malformed_input")
        teams = {}
        for team, t in data["teams"].items():
            if team not in common.TEAMS:
                raise SanitizeError("malformed_input")
            teams[team] = {
                "prompt_tokens": _int(t["prompt_tokens"]),
                "completion_tokens": _int(t["completion_tokens"]),
                "estimated_usd": _match(t.get("estimated_usd"), _MONEY, optional=True),
            }
        totals = data["totals"]
        return {
            "status": "recorded",
            "label": common.SHOWBACK_LABEL,
            "interval": {"start": _match(data["interval"]["start"], _UTC),
                         "end": _match(data["interval"]["end"], _UTC), "half_open": True},
            "snapshot_id": _match(data.get("snapshot_id") or "none", _NAME),
            "price_coverage": _match(data["price_coverage"], _CODE),
            "reconciliation_status": _match(data["reconciliation_status"], _CODE),
            "coverage": _match(data["coverage"], _CODE),
            "teams": teams,
            "totals": {
                "status": _match(totals["status"], _CODE),
                "suppressed_reason": _match(totals.get("suppressed_reason") or "none", _CODE),
                "prompt_tokens": _int(totals.get("prompt_tokens"), optional=True),
                "completion_tokens": _int(totals.get("completion_tokens"), optional=True),
                "estimated_usd": _match(totals.get("estimated_usd"), _MONEY, optional=True),
                "partial_estimated_usd": _match(totals.get("partial_estimated_usd"), _MONEY, optional=True),
            },
            "counts": {_match(k, _CODE): _int(v) for k, v in data["counts"].items()},
            "exclusions": [_match(e, _TEXT) for e in data.get("exclusions", [])],
        }
    except (KeyError, TypeError, AttributeError):
        raise SanitizeError("malformed_input") from None


def extract_budget(data: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if data is None:
        return dict(NOT_RUN)
    try:
        totals, limits = data["totals"], data["limits"]
        return {
            "status": "recorded",
            "spent": {
                "attempts": _int(totals["attempts"]),
                "reserved_tokens": _int(totals["reserved_tokens"]),
                "reserved_usd": round(_num(totals["reserved_usd"]), 6),
                "errors": _int(totals["errors"]),
                "by_kind": {_match(k, _CODE): _int(v) for k, v in totals["by_kind"].items()},
            },
            "limits": {
                "max_attempts": _int(limits["max_attempts"]),
                "max_reserved_tokens": _int(limits["max_reserved_tokens"]),
                "max_estimated_usd": round(_num(limits["max_estimated_usd"]), 6),
                "deadline_utc": _match(limits["deadline_utc"], _UTC),
            },
            "price_snapshot_id": _match(((data.get("price") or {}).get("snapshot_id")) or "none", _NAME),
        }
    except (KeyError, TypeError, AttributeError):
        raise SanitizeError("malformed_input") from None


def _resource(entry: Mapping[str, Any]) -> Dict[str, str]:
    label = TYPE_LABELS.get(str(entry.get("type", "")).lower())
    if label is None:
        raise SanitizeError("malformed_input")
    return {"type": label, "name": _match(entry.get("name"), _NAME)}


def extract_residual(data: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if data is None:
        return dict(NOT_RUN)
    try:
        return {
            "status": _match(data["status"], _CODE),
            "action": _match(data["action"], _CODE),
            "mode": _match(data.get("mode") or "unknown", _CODE),
            "exposure": _match(data.get("exposure") or "unknown", _CODE),
            "quota_release": _match(data.get("quota_release") or "not_applicable", _CODE),
            "tombstone_discovery": _match(data.get("tombstone_discovery") or "not_run", _CODE),
            "active": [_resource(a) for a in data.get("active", [])],
            "failures": [{**_resource(f), "category": _match(f.get("category") or "unknown", _CODE)}
                         for f in data.get("failures", [])],
            "unexpected_count": len(data.get("unexpected", [])),
            "locks": _int(data.get("locks", 0)),
            "tombstones": [
                {"kind": t["kind"] if t.get("kind") in TOMBSTONE_KINDS else _match(None, _CODE),
                 "name": _match(t.get("name"), _NAME)}
                for t in data.get("tombstones", [])
            ],
            "next_operator": _match(data.get("next_operator") or "unassigned", _TEXT),
        }
    except (KeyError, TypeError, AttributeError):
        raise SanitizeError("malformed_input") from None


# ---------------------------------------------------------------------------
# Lab status mapping
# ---------------------------------------------------------------------------


def notebook_status(entry: Mapping[str, Any]) -> str:
    if entry.get("status") == "not_run":
        return "not_run"
    statuses = [o["status"] for oid, o in entry["objectives"].items()
                if results.blocks_verdict(oid, o["status"])]
    if any(s == "missing" for s in statuses):
        return "incomplete"
    if any(s == "failed" for s in statuses):
        return "failed"
    if any(s == "inconclusive" for s in statuses):
        return "inconclusive"
    return "passed"


def showback_status(entry: Mapping[str, Any]) -> str:
    if entry.get("status") == "not_run":
        return "not_run"
    if entry["totals"]["status"] == "complete" and entry["reconciliation_status"] == "reconciled":
        return "passed"
    if entry["reconciliation_status"] == "unreconciled":
        return "unreconciled"
    if entry["totals"]["status"] == "suppressed":
        return "suppressed"
    return entry["reconciliation_status"]


def residual_status(entry: Mapping[str, Any]) -> str:
    status = entry.get("status")
    if status == "not_run":
        return "not_run"
    if status == "clean":
        return "passed"
    if status in ("kept", "dry_run", "no_op"):
        return status
    return "failed"


def lab_statuses(evidence: Mapping[str, Any]) -> Dict[str, Dict[str, str]]:
    labs: Dict[str, Dict[str, str]] = {}
    for lab, source in LABS:
        if source == "readiness":
            status = evidence["readiness"].get("status", "not_run")
        elif source == "showback":
            status = showback_status(evidence["showback"])
        elif source == "residual":
            status = residual_status(evidence["residual"])
        else:
            status = notebook_status(evidence["notebooks"][source])
        labs[lab] = {"status": status, "source": source}
    return labs


# ---------------------------------------------------------------------------
# sanitize
# ---------------------------------------------------------------------------


def known_secret_hashes(paths: common.Paths, session_id: str, env_file: Optional[Path]) -> List[Dict[str, Any]]:
    known = common.load_known_hashes([paths.secret_hashes(session_id)])
    if env_file and Path(env_file).exists():
        values = common.read_env_file(Path(env_file))
        known.extend(common.hashes_for_values(values.get(k, "") for k in common.SECRET_ENV_KEYS))
    return known


def scan_or_raise(text: str, known: Sequence[Mapping[str, Any]]) -> None:
    if common.scan_patterns(text):
        raise SanitizeError("credential_pattern")
    if common.known_value_hits(text, known):
        raise SanitizeError("known_secret")


def build_evidence(session_id: str, paths: common.Paths, phase: str, source_revision: str) -> Dict[str, Any]:
    evidence: Dict[str, Any] = {
        "schema_version": 1,
        "kind": "aigov-evidence",
        "session_id": session_id,
        "phase": phase,
        "generated_at": common.fmt_utc(common.utc_now()),
        "source_revision": _match(source_revision[:12] or "local", _NAME),
        "notebooks": {stem: extract_notebook(stem, session_id, paths) for stem in common.NOTEBOOK_STEMS},
        "verdict": extract_verdict(_load(paths.results_dir(session_id) / "verdict.json")),
        "readiness": extract_readiness(_load(paths.readiness_dir(session_id) / "summary.json")),
        "probes": extract_probes(_load(paths.readiness_dir(session_id) / "probes.json")),
        "showback": extract_showback(_load(paths.showback_dir(session_id) / "report.json")),
        "budget": extract_budget(_load(paths.budget_root / session_id / "budget.json")),
        "residual": extract_residual(_load(paths.residual_dir(session_id) / "report.json")),
    }
    evidence["labs"] = lab_statuses(evidence)
    return evidence


def _fail_closed(evidence_dir: Path, code: str) -> None:
    evidence_file = evidence_dir / "evidence.json"
    if evidence_file.exists():
        evidence_file.unlink()
    png_dir = evidence_dir / "png"
    if png_dir.exists() and not png_dir.is_symlink():
        shutil.rmtree(png_dir)
    atomic_write_json(evidence_dir / "sanitize-status.json", {"status": "failed", "reason": code})


def cmd_sanitize(args: argparse.Namespace, paths: common.Paths, out: TextIO) -> int:
    session_id = common.resolve_session(args.session_id)
    evidence_dir = paths.evidence_dir(session_id)
    try:
        evidence = build_evidence(session_id, paths, args.phase, os.environ.get("GITHUB_SHA", "local"))
        text = json.dumps(evidence, sort_keys=True)
        scan_or_raise(text, known_secret_hashes(paths, session_id, Path(args.env_file) if args.env_file else None))
    except SanitizeError as exc:
        _fail_closed(evidence_dir, exc.code)
        out.write(f"sanitize: failed closed ({exc.code}); no evidence was written\n")
        return 1
    except Exception:  # noqa: BLE001 - any sanitizer error fails closed without echoing payloads
        _fail_closed(evidence_dir, "sanitizer_error")
        out.write("sanitize: failed closed (sanitizer_error); no evidence was written\n")
        return 1
    atomic_write_json(evidence_dir / "evidence.json", evidence)
    atomic_write_json(evidence_dir / "sanitize-status.json", {"status": "passed", "reason": "ok"})
    summary = ", ".join(f"{lab}={entry['status']}" for lab, entry in evidence["labs"].items())
    out.write(f"sanitize: wrote evidence.json ({args.phase}); {summary}\n")
    return 0


# ---------------------------------------------------------------------------
# render (credential-free; evidence.json only)
# ---------------------------------------------------------------------------


def load_evidence_for_render(path: Path) -> Dict[str, Any]:
    path = Path(path)
    if path.suffix.lower() != ".json" or path.name != "evidence.json":
        raise SanitizeError("render_input_not_evidence")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise SanitizeError("render_input_rejected")
    text = path.read_text(encoding="utf-8")
    if common.scan_patterns(text):
        raise SanitizeError("credential_pattern")
    data = json.loads(text)
    if data.get("kind") != "aigov-evidence" or data.get("schema_version") != 1:
        raise SanitizeError("render_input_rejected")
    if set(data.get("labs", {})) != {lab for lab, _ in LABS}:
        raise SanitizeError("render_input_rejected")
    return data


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _status_card(plt, lab: str, status: str, evidence: Mapping[str, Any], path: Path, note: str = "") -> None:
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.axis("off")
    colors = {"failed": "#b00020", "inconclusive": "#b26a00", "incomplete": "#b26a00", "not_run": "#555555"}
    ax.text(0.02, 0.8, lab, fontsize=16, weight="bold", transform=ax.transAxes)
    ax.text(0.02, 0.5, f"Status: {status.upper()} (not verified)", fontsize=14,
            color=colors.get(status, "#b26a00"), transform=ax.transAxes)
    footer = f"Session {evidence['session_id']} | {evidence['phase']} | {evidence['generated_at']}"
    ax.text(0.02, 0.2, footer, fontsize=9, color="#333333", transform=ax.transAxes)
    if note:
        ax.text(0.02, 0.05, note, fontsize=9, color="#333333", transform=ax.transAxes)
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def _table(plt, title: str, rows: Sequence[Sequence[str]], header: Sequence[str], path: Path, footer: str) -> None:
    fig, ax = plt.subplots(figsize=(9, 0.6 + 0.35 * (len(rows) + 2)))
    ax.axis("off")
    ax.set_title(title, loc="left", fontsize=13, weight="bold")
    table = ax.table(cellText=[list(r) for r in rows] or [["-"] * len(header)], colLabels=list(header),
                     loc="upper left", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.3)
    fig.text(0.01, 0.01, footer, fontsize=8, color="#333333")
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def render(evidence: Mapping[str, Any], out_dir: Path) -> List[Path]:
    plt = _plt()
    out_dir = Path(out_dir)
    if out_dir.is_symlink():
        raise SanitizeError("render_output_rejected")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    footer = f"Session {evidence['session_id']} | {evidence['phase']} | {evidence['generated_at']}"
    for lab, source in LABS:
        status = evidence["labs"][lab]["status"]
        if status != "passed":
            note = common.SHOWBACK_LABEL if lab == "lab06-chargeback" else ""
            path = out_dir / f"{lab}-status.png"
            _status_card(plt, lab, status, evidence, path, note)
            written.append(path)
            continue
        path = out_dir / f"{lab}-summary.png"
        if source == "readiness":
            rows = [(n, c["status"], str(c["attempts"])) for n, c in evidence["readiness"]["checks"].items()]
            _table(plt, f"{lab}: readiness checks", rows, ("check", "status", "attempts"), path, footer)
        elif source == "showback":
            sb = evidence["showback"]
            rows = [(t, str(v["prompt_tokens"]), str(v["completion_tokens"]), v["estimated_usd"] or "n/a")
                    for t, v in sb["teams"].items()]
            rows.append(("total", str(sb["totals"]["prompt_tokens"]), str(sb["totals"]["completion_tokens"]),
                         sb["totals"]["estimated_usd"] or "n/a"))
            note = (f"{sb['label']} | {sb['interval']['start']} to {sb['interval']['end']} (half-open) | "
                    f"price {sb['snapshot_id']} | coverage {sb['coverage']}")
            _table(plt, f"{lab}: {sb['label']}", rows, ("team", "prompt", "completion", "USD"), path, note)
            chart = out_dir / f"{lab}-tokens.png"
            fig, ax = plt.subplots(figsize=(8, 4))
            teams = list(sb["teams"])
            ax.bar(teams, [sb["teams"][t]["prompt_tokens"] for t in teams], label="prompt tokens")
            ax.bar(teams, [sb["teams"][t]["completion_tokens"] for t in teams],
                   bottom=[sb["teams"][t]["prompt_tokens"] for t in teams], label="completion tokens")
            ax.set_title(sb["label"], fontsize=11)
            ax.set_ylabel("tokens")
            ax.legend()
            fig.text(0.01, 0.01, note, fontsize=7, color="#333333")
            fig.savefig(chart, dpi=110, bbox_inches="tight")
            plt.close(fig)
            written.append(chart)
        elif source == "residual":
            residual = evidence["residual"]
            rows = [("status", residual["status"]), ("exposure", residual["exposure"]),
                    ("quota release", residual["quota_release"]),
                    ("tombstones", str(len(residual["tombstones"]))), ("active", str(len(residual["active"])))]
            _table(plt, f"{lab}: teardown", rows, ("item", "value"), path, footer)
        else:
            objectives = evidence["notebooks"][source]["objectives"]
            rows = [(oid, o["status"] if o["status"] == "passed" else f"{o['status']} (not verified)")
                    for oid, o in objectives.items()]
            _table(plt, f"{lab}: objectives", rows, ("objective", "status"), path, footer)
        written.append(path)
    return written


def cmd_render(args: argparse.Namespace, out: TextIO) -> int:
    try:
        evidence = load_evidence_for_render(Path(args.evidence))
        written = render(evidence, Path(args.out_dir))
    except SanitizeError as exc:
        out.write(f"render: refused ({exc.code}); no image was written\n")
        return 1
    except ImportError:
        out.write("render: matplotlib is not installed (pip install -r requirements-ci.txt)\n")
        return 1
    out.write(f"render: wrote {len(written)} PNG file(s)\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="render_evidence.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sanitize", help="Build evidence.json from allowlisted fields; fail closed on any hit.")
    s.add_argument("--session-id", help="Session ID (default SESSION_ID).")
    s.add_argument("--phase", choices=("pre-cleanup", "post-cleanup"), default="pre-cleanup")
    s.add_argument("--env-file", default=str(common.REPO_ROOT / ".env"),
                   help="Private .env whose secret values are scanned for (never copied).")
    s.add_argument("--outputs-root", help="Outputs root (default <repo>/outputs).")
    r = sub.add_parser("render", help="Render lab00..lab07 PNGs from evidence.json only (no network, no notebooks).")
    r.add_argument("--evidence", required=True, help="Path to evidence.json.")
    r.add_argument("--out-dir", required=True, help="Output directory for PNG files.")
    return parser


def main(argv: Optional[Sequence[str]] = None, out: Optional[TextIO] = None) -> int:
    args = build_parser().parse_args(argv)
    out = out or sys.stdout
    if args.command == "sanitize":
        paths = common.Paths.default(Path(args.outputs_root) if args.outputs_root else None)
        try:
            return cmd_sanitize(args, paths, out)
        except common.AutomationError as exc:
            out.write(f"sanitize: {exc}\n")
            return 2
    return cmd_render(args, out)


if __name__ == "__main__":
    sys.exit(main())
