#!/usr/bin/env python
"""Estimated model-token showback (USD retail) from one telemetry representation.

Queries Application Insights ``customMetrics`` summed by ``valueSum`` (the only
representation used; totals are never added to prompt plus completion) for the
platform API and approved team subscriptions inside a fixed half-open UTC
window. With a traffic manifest the sums are reconciled against response usage
with an explicit tolerance and bounded polling; missing telemetry is reported
``incomplete``, never zero. Without a manifest (report-only) the window is
validated and the result is ``unreconciled``. Prices come from exactly one
snapshot record per meter; missing or duplicate prices suppress cost totals.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, TextIO, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aigov_common as common  # noqa: E402
from aigov_common import AutomationError  # noqa: E402
from shared.results import atomic_write_json  # noqa: E402

REPRESENTATION = "customMetrics sum(valueSum)"
MAX_WINDOW = timedelta(hours=24)
EXCLUSIONS = (
    "Shared APIM, logging, Content Safety, networking, taxes, and contract adjustments are excluded.",
    "Uncached retail rates; cache discounts are excluded, and cached tokens are not added on top.",
    "Provisioned throughput is not priced by this pay-as-you-go estimate.",
    "Temporary probe subscriptions and non-team subscriptions are not attributed to teams.",
)
_SAFE_IDENT = re.compile(r"^[A-Za-z0-9 _.\-]{1,80}$")


class WindowError(AutomationError):
    """Invalid report window."""


@dataclass
class Deps:
    logs_query: Callable[..., List[Dict[str, Any]]] = common.default_logs_query
    now: Callable[[], datetime] = common.utc_now
    sleep: Callable[[float], None] = time.sleep
    out: TextIO = field(default_factory=lambda: sys.stdout)
    env: Mapping[str, str] = field(default_factory=dict)


def validate_window(start_text: str, end_text: str, now: datetime) -> Tuple[datetime, datetime]:
    """UTC timestamps, start before end, end not in the future, length at most 24 hours."""
    try:
        start = common.parse_utc(start_text, "--window-start")
        end = common.parse_utc(end_text, "--window-end")
    except AutomationError as exc:
        raise WindowError(str(exc)) from None
    if start >= end:
        raise WindowError("The window start must be before the window end.")
    if end > now:
        raise WindowError("The window end must not be in the future.")
    if end - start > MAX_WINDOW:
        raise WindowError("The window must be at most 24 hours long.")
    return start, end


def _ident(value: str, name: str) -> str:
    if not _SAFE_IDENT.match(value or ""):
        raise AutomationError(f"{name} contains unsupported characters.")
    return value


def build_query(start: datetime, end: datetime, api_id: str, prompt_metric: str, completion_metric: str) -> str:
    """One representation: customMetrics valueSum, prompt and completion names only."""
    api_id = _ident(api_id, "API ID")
    prompt_metric = _ident(prompt_metric, "prompt metric")
    completion_metric = _ident(completion_metric, "completion metric")
    return (
        "customMetrics"
        f" | where timestamp >= datetime({common.fmt_utc(start)}) and timestamp < datetime({common.fmt_utc(end)})"
        f" | where name in ('{prompt_metric}', '{completion_metric}')"
        " | extend api = tostring(customDimensions['API ID']),"
        " sub = tostring(customDimensions['Subscription ID']),"
        " app = tostring(customDimensions['ClientApp'])"
        f" | where api == '{api_id}'"
        " | summarize value_sum = sum(valueSum) by name, api, sub, app"
    )


def aggregate(
    rows: Sequence[Mapping[str, Any]],
    team_subscriptions: Mapping[str, str],
    prompt_metric: str,
    completion_metric: str,
) -> Dict[str, Any]:
    """Sum prompt and completion valueSum per team; flag duplicate keys and unattributed usage."""
    teams = {team: {"prompt_tokens": 0, "completion_tokens": 0} for team in team_subscriptions}
    by_sub = {sid: team for team, sid in team_subscriptions.items()}
    unattributed = {"prompt_tokens": 0, "completion_tokens": 0, "rows": 0}
    seen = set()
    duplicates = 0
    ignored_metrics = 0
    for row in rows:
        name = str(row.get("name", ""))
        if name == prompt_metric:
            field_name = "prompt_tokens"
        elif name == completion_metric:
            field_name = "completion_tokens"
        else:
            ignored_metrics += 1
            continue
        key = (name, str(row.get("api", "")), str(row.get("sub", "")), str(row.get("app", "")))
        if key in seen:
            duplicates += 1
        seen.add(key)
        value = int(round(float(row.get("value_sum") or 0)))
        team = by_sub.get(str(row.get("sub", "")))
        if team is None:
            unattributed[field_name] += value
            unattributed["rows"] += 1
        else:
            teams[team][field_name] += value
    return {"teams": teams, "unattributed": unattributed, "duplicate_rows": duplicates,
            "ignored_metric_rows": ignored_metrics, "row_count": len(rows)}


def reconcile(
    observed: Mapping[str, Mapping[str, int]],
    expected: Mapping[str, Mapping[str, int]],
    tolerance_ratio: float,
    tolerance_tokens: int,
) -> str:
    """``reconciled`` within tolerance, ``incomplete`` when short, ``mismatch`` when over."""
    status = "reconciled"
    for team, exp in expected.items():
        for metric in ("prompt_tokens", "completion_tokens"):
            want = int(exp.get(metric, 0))
            got = int((observed.get(team) or {}).get(metric, 0))
            tolerance = max(tolerance_tokens, int(want * tolerance_ratio))
            if got > want + tolerance:
                return "mismatch"
            if got < want - tolerance:
                status = "incomplete"
    return status


def _money(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


def build_report(
    *,
    session_id: str,
    start: datetime,
    end: datetime,
    aggregated: Mapping[str, Any],
    reconciliation: str,
    prices: Optional[Mapping[str, Any]],
    price_coverage: str,
    snapshot_id: str,
    expected: Optional[Mapping[str, Mapping[str, Any]]],
    manifest_counts: Mapping[str, int],
) -> Dict[str, Any]:
    if aggregated["duplicate_rows"] > 0:
        reconciliation = "ambiguous"
    elif expected is not None and aggregated["unattributed"]["rows"] > 0:
        reconciliation = "contaminated"
    if prices is None:
        totals_status, reason = "suppressed", f"price_{price_coverage}"
    elif reconciliation == "reconciled":
        totals_status, reason = "complete", ""
    elif reconciliation in ("unreconciled", "incomplete"):
        totals_status, reason = "partial", reconciliation
    else:
        totals_status, reason = "suppressed", reconciliation
    priced = prices is not None and totals_status != "suppressed"

    teams_out: Dict[str, Dict[str, Any]] = {}
    total_prompt = total_completion = 0
    total_cost = Decimal(0)
    for team, usage in aggregated["teams"].items():
        entry: Dict[str, Any] = {
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "estimated_usd": None,
        }
        if expected is not None:
            entry["expected_prompt_tokens"] = int((expected.get(team) or {}).get("prompt_tokens", 0))
            entry["expected_completion_tokens"] = int((expected.get(team) or {}).get("completion_tokens", 0))
        if priced:
            cost = common.price_usage(usage["prompt_tokens"], usage["completion_tokens"], prices)
            entry["estimated_usd"] = _money(cost)
            total_cost += cost
        total_prompt += usage["prompt_tokens"]
        total_completion += usage["completion_tokens"]
        teams_out[team] = entry

    totals = {
        "status": totals_status,
        "suppressed_reason": reason,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "estimated_usd": _money(total_cost) if totals_status == "complete" else None,
        "partial_estimated_usd": _money(total_cost) if totals_status == "partial" else None,
    }
    coverage = {"complete": "complete", "partial": "partial"}.get(totals_status, "incomplete")
    return {
        "schema_version": 1,
        "label": common.SHOWBACK_LABEL,
        "session_id": session_id,
        "interval": {"start": common.fmt_utc(start), "end": common.fmt_utc(end), "half_open": True},
        "representation": REPRESENTATION,
        "snapshot_id": snapshot_id,
        "price_coverage": price_coverage,
        "reconciliation_status": reconciliation,
        "coverage": coverage,
        "teams": teams_out,
        "totals": totals,
        "unattributed": dict(aggregated["unattributed"]),
        "counts": {
            "duplicate_rows": aggregated["duplicate_rows"],
            "ignored_metric_rows": aggregated["ignored_metric_rows"],
            "unattributed_rows": aggregated["unattributed"]["rows"],
            "unpriced_tokens": 0 if priced else total_prompt + total_completion,
            "failed_calls": int(manifest_counts.get("failed", 0)),
            "ambiguous_calls": int(manifest_counts.get("ambiguous", 0)),
        },
        "exclusions": list(EXCLUSIONS),
    }


def resolve_prices(
    snapshot_path: Optional[str], model: Mapping[str, str], at: datetime
) -> Tuple[Optional[Dict[str, Any]], str, str]:
    if not snapshot_path:
        return None, "not_provided", ""
    snapshot = common.load_price_snapshot(Path(snapshot_path))
    try:
        prices = common.select_prices(snapshot, model=model.get("name", ""), version=model.get("version", ""),
                                      sku=model.get("sku", ""), region=model.get("region", ""), at=at)
    except common.PriceError as exc:
        return None, exc.coverage, str(snapshot.get("snapshot_id", ""))
    return prices, "complete", prices["snapshot_id"]


def run(args: argparse.Namespace, deps: Deps, paths: common.Paths) -> int:
    session_id = common.resolve_session(args.session_id, deps.env)
    values = common.read_env_file(Path(args.env_file))
    resource_id = args.app_insights_resource_id or values.get("APP_INSIGHTS_RESOURCE_ID", "")
    api_id = args.api_id or values.get("PLATFORM_API_ID", "") or "ai-gateway-api"
    if not resource_id:
        raise AutomationError("The Application Insights resource ID is required.")
    manifest_path = Path(args.manifest) if args.manifest else paths.showback_dir(session_id) / "manifest.json"
    now = deps.now()
    expected: Optional[Dict[str, Dict[str, Any]]] = None
    manifest_counts: Dict[str, int] = {}
    if args.window_start or args.window_end:
        if not (args.window_start and args.window_end):
            raise WindowError("Report-only mode needs both --window-start and --window-end.")
        start, end = validate_window(args.window_start, args.window_end, now)
        subs = [s for s in (args.team_subscriptions or values.get("TEAM_SUBSCRIPTION_IDS", "")).split(",") if s]
        team_subscriptions = {s[:-4] if s.endswith("-sub") else s: s for s in subs}
        model = {"name": deps.env.get("AIGOV_CHAT_MODEL_NAME", ""), "version": deps.env.get("AIGOV_CHAT_MODEL_VERSION", ""),
                 "sku": deps.env.get("AIGOV_CHAT_DEPLOYMENT_SKU", ""), "region": deps.env.get("AIGOV_AI_LOCATION", "")}
    else:
        if not manifest_path.exists():
            raise AutomationError("No traffic manifest; pass --window-start/--window-end for report-only.")
        manifest = common.read_json(manifest_path)
        if manifest.get("session_id") != session_id:
            raise AutomationError("The traffic manifest belongs to another session.")
        start, end = validate_window(manifest["window"]["start"], manifest["window"]["end"], now + MAX_WINDOW)
        team_subscriptions = {team: data["subscription_id"] for team, data in manifest["teams"].items()}
        expected = {team: {"prompt_tokens": data["prompt_tokens"], "completion_tokens": data["completion_tokens"]}
                    for team, data in manifest["teams"].items()}
        manifest_counts = {
            "failed": sum(int(d.get("failed", 0)) for d in manifest["teams"].values()),
            "ambiguous": sum(int(d.get("ambiguous", 0)) for d in manifest["teams"].values()),
        }
        model = manifest.get("model") or {}
    if not team_subscriptions:
        raise AutomationError("No team subscriptions to attribute.")

    prices, price_coverage, snapshot_id = resolve_prices(args.price_snapshot, model, start)
    query = build_query(start, end, api_id, args.prompt_metric, args.completion_metric)
    deadline = deps.now() + timedelta(seconds=args.poll_timeout_seconds)
    while True:
        rows = deps.logs_query(resource_id, query, start, end)
        aggregated = aggregate(rows, team_subscriptions, args.prompt_metric, args.completion_metric)
        if expected is None:
            reconciliation = "unreconciled"
            break
        reconciliation = reconcile(aggregated["teams"], expected, args.tolerance_ratio, args.tolerance_tokens)
        if reconciliation != "incomplete" or aggregated["duplicate_rows"] or deps.now() >= deadline:
            break
        deps.sleep(args.poll_seconds)

    report = build_report(
        session_id=session_id, start=start, end=end, aggregated=aggregated, reconciliation=reconciliation,
        prices=prices, price_coverage=price_coverage, snapshot_id=snapshot_id, expected=expected,
        manifest_counts=manifest_counts,
    )
    atomic_write_json(paths.showback_dir(session_id) / "report.json", report)
    totals = report["totals"]
    deps.out.write(
        f"{common.SHOWBACK_LABEL}: interval={report['interval']['start']}..{report['interval']['end']} "
        f"snapshot={snapshot_id or 'none'} reconciliation={report['reconciliation_status']} "
        f"totals={totals['status']} estimated_usd={totals['estimated_usd'] or 'suppressed'}\n"
    )
    if expected is None:
        return 0
    return 0 if totals["status"] == "complete" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="showback_report.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--session-id", help="Session ID (default SESSION_ID).")
    parser.add_argument("--manifest", help="Traffic manifest (default outputs/showback/<session>/manifest.json).")
    parser.add_argument("--window-start", help="Report-only: UTC window start (inclusive).")
    parser.add_argument("--window-end", help="Report-only: UTC window end (exclusive).")
    parser.add_argument("--team-subscriptions", help="Report-only: comma-separated team subscription IDs.")
    parser.add_argument("--price-snapshot", help="Price snapshot JSON (scripts/prices/<snapshot>.json).")
    parser.add_argument("--app-insights-resource-id")
    parser.add_argument("--api-id")
    parser.add_argument("--prompt-metric", default=common.PROMPT_METRIC)
    parser.add_argument("--completion-metric", default=common.COMPLETION_METRIC)
    parser.add_argument("--tolerance-ratio", type=float, default=0.02)
    parser.add_argument("--tolerance-tokens", type=int, default=5)
    parser.add_argument("--poll-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--env-file", default=str(common.REPO_ROOT / ".env"))
    parser.add_argument("--outputs-root", help="Outputs root (default <repo>/outputs).")
    return parser


def main(argv: Optional[Sequence[str]] = None, deps: Optional[Deps] = None) -> int:
    args = build_parser().parse_args(argv)
    deps = deps or Deps(env=os.environ)
    paths = common.Paths.default(Path(args.outputs_root) if args.outputs_root else None)
    try:
        return run(args, deps, paths)
    except WindowError as exc:
        deps.out.write(f"showback: invalid window: {exc}\n")
        return 2
    except AutomationError as exc:
        deps.out.write(f"showback: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
