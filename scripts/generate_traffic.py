#!/usr/bin/env python
"""Serial, non-streaming team traffic for the showback window.

Three team subscriptions call the platform API. Keys come from ARM
``listSecrets`` and are masked on retrieval, never printed or persisted.
Every call goes through ``shared.budget.guarded_request``; there are no
retries. Defaults: 1 worker, 30 attempts, 128 max output tokens, 10,000
reserved tokens, 5 minute deadline. Writes a response-usage manifest with a
fixed half-open UTC window to ``outputs/showback/<session_id>/manifest.json``.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aigov_common as common  # noqa: E402
from aigov_common import AutomationError, AzError  # noqa: E402
from shared import budget  # noqa: E402
from shared.results import atomic_write_json  # noqa: E402

DEFAULT_WORKERS = 1
DEFAULT_ATTEMPTS = 30
DEFAULT_MAX_TOKENS = 128
DEFAULT_RESERVED_TOKENS = 10_000
DEFAULT_DEADLINE_MINUTES = 5.0
REQUEST_TIMEOUT_SECONDS = 30.0
LABEL = "traffic.call"
PROMPTS = (
    "In one short sentence, what does an API gateway do?",
    "In one short sentence, why do teams track token usage?",
    "In one short sentence, what is a rate limit?",
)


@dataclass
class Deps:
    client_factory: Callable[[], common.ArmClient] = common.AzCliArmClient
    http_post: Callable[..., Any] = common.default_http_post
    now: Callable[[], datetime] = common.utc_now
    out: TextIO = field(default_factory=lambda: sys.stdout)
    env: Mapping[str, str] = field(default_factory=dict)


def floor_minute(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def half_open_window(first_start: datetime, last_end: datetime) -> Dict[str, str]:
    """Whole-minute window [start, end) that contains every call."""
    start = floor_minute(first_start)
    end = floor_minute(last_end) + timedelta(minutes=1)
    return {"start": common.fmt_utc(start), "end": common.fmt_utc(end), "half_open": True}


def _team_for_subscription(sid: str) -> str:
    return sid[:-4] if sid.endswith("-sub") else sid


def run_traffic(args: argparse.Namespace, deps: Deps, paths: common.Paths, env_path: Path) -> int:
    if args.workers != 1:
        raise AutomationError("Traffic is serial; only --workers 1 is supported.")
    for name in ("attempts", "max_tokens", "reserved_tokens"):
        if getattr(args, name) <= 0:
            raise AutomationError(f"--{name.replace('_', '-')} must be positive.")
    session_id = common.resolve_session(args.session_id, deps.env)
    env = common.session_budget_env(paths, session_id, deps.env)
    values = common.read_env_file(env_path)
    required = ("AZURE_SUBSCRIPTION_ID", "APIM_RESOURCE_GROUP", "APIM_NAME", "APIM_GATEWAY_URL",
                "PLATFORM_API_PATH", "PLATFORM_API_ID", "AOAI_DEPLOYMENT", "TEAM_SUBSCRIPTION_IDS")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise AutomationError(f".env lacks {', '.join(missing)}; run write-env first.")
    subscriptions = [s for s in values["TEAM_SUBSCRIPTION_IDS"].split(",") if s]
    teams = {_team_for_subscription(sid): sid for sid in subscriptions}
    unknown = sorted(set(teams) - set(common.TEAMS))
    if unknown or not teams:
        raise AutomationError("TEAM_SUBSCRIPTION_IDS must name only the approved team subscriptions.")

    client = deps.client_factory()
    secrets = common.SecretRegistry(paths.secret_hashes(session_id), env=deps.env, stream=deps.out)
    keys: Dict[str, str] = {}
    for team, sid in teams.items():
        data = client.list_apim_subscription_secrets(
            values["AZURE_SUBSCRIPTION_ID"], values["APIM_RESOURCE_GROUP"], values["APIM_NAME"], sid
        )
        keys[team] = secrets.register(data.get("primaryKey") or "")
        if not keys[team]:
            raise AutomationError(f"No key could be retrieved for {team}.")

    url = (f"{values['APIM_GATEWAY_URL'].rstrip('/')}/{values['PLATFORM_API_PATH'].strip('/')}"
           "/v1/chat/completions")
    started = deps.now()
    deadline = started + timedelta(minutes=args.deadline_minutes)
    team_order = [team for team in common.TEAMS if team in teams]
    calls: List[Dict[str, Any]] = []
    reserved = 0
    stopped_reason = "attempts_cap"
    for seq in range(args.attempts):
        if deps.now() >= deadline:
            stopped_reason = "deadline"
            break
        team = team_order[seq % len(team_order)]
        messages = [{"role": "user", "content": PROMPTS[seq % len(PROMPTS)]}]
        body = {"model": values["AOAI_DEPLOYMENT"], "messages": messages,
                "max_tokens": args.max_tokens, "stream": False}
        estimate = budget.estimate_prompt_tokens(messages)
        if reserved + estimate + args.max_tokens > args.reserved_tokens:
            stopped_reason = "reserved_tokens_cap"
            break
        reserved += estimate + args.max_tokens
        headers = {"Ocp-Apim-Subscription-Key": keys[team], "Content-Type": "application/json",
                   "x-client-app": common.TEAM_CLIENT_APPS[team]}
        call: Dict[str, Any] = {"seq": seq + 1, "team": team, "subscription_id": teams[team],
                                "client_app": common.TEAM_CLIENT_APPS[team], "started_at": common.fmt_utc(deps.now())}
        try:
            response = budget.guarded_request(
                "model", estimate, args.max_tokens,
                lambda: deps.http_post(url, headers=headers, json_body=body, timeout=REQUEST_TIMEOUT_SECONDS),
                body=body, label=LABEL, env=env, root=paths.budget_root,
            )
        except budget.BudgetExceeded:
            stopped_reason = "session_budget"
            break
        except budget.BudgetStateError:
            stopped_reason = "budget_state"
            break
        except Exception as exc:  # noqa: BLE001 - no retries; the attempt is consumed and counted
            call.update(status=None, outcome=f"error_{type(exc).__name__}", ended_at=common.fmt_utc(deps.now()))
            calls.append(call)
            continue
        call["ended_at"] = common.fmt_utc(deps.now())
        call["status"] = getattr(response, "status_code", None)
        call["request_id"] = _header(response, "apim-request-id") or ""
        usage: Mapping[str, Any] = {}
        if call["status"] == 200:
            try:
                usage = (response.json() or {}).get("usage") or {}
            except ValueError:
                usage = {}
        if call["status"] == 200 and isinstance(usage.get("prompt_tokens"), int) \
                and isinstance(usage.get("completion_tokens"), int):
            details = usage.get("prompt_tokens_details") or {}
            call.update(outcome="ok", prompt_tokens=usage["prompt_tokens"],
                        completion_tokens=usage["completion_tokens"],
                        cached_tokens=int(details.get("cached_tokens") or 0))
        elif call["status"] == 200:
            call["outcome"] = "ambiguous_usage"
        else:
            call["outcome"] = "failed"
        calls.append(call)

    summary: Dict[str, Dict[str, Any]] = {}
    for team in team_order:
        team_calls = [c for c in calls if c["team"] == team]
        summary[team] = {
            "subscription_id": teams[team],
            "client_app": common.TEAM_CLIENT_APPS[team],
            "attempts": len(team_calls),
            "ok": sum(1 for c in team_calls if c["outcome"] == "ok"),
            "failed": sum(1 for c in team_calls if c["outcome"] not in ("ok", "ambiguous_usage")),
            "ambiguous": sum(1 for c in team_calls if c["outcome"] == "ambiguous_usage"),
            "prompt_tokens": sum(c.get("prompt_tokens", 0) for c in team_calls),
            "completion_tokens": sum(c.get("completion_tokens", 0) for c in team_calls),
            "cached_tokens": sum(c.get("cached_tokens", 0) for c in team_calls),
        }
    ended = deps.now()
    window = half_open_window(started, ended)
    manifest = {
        "schema_version": 1,
        "session_id": session_id,
        "label": common.SHOWBACK_LABEL,
        "window": window,
        "api_id": values["PLATFORM_API_ID"],
        "deployment": values["AOAI_DEPLOYMENT"],
        "model": {
            "name": deps.env.get("AIGOV_CHAT_MODEL_NAME", ""),
            "version": deps.env.get("AIGOV_CHAT_MODEL_VERSION", ""),
            "sku": deps.env.get("AIGOV_CHAT_DEPLOYMENT_SKU", ""),
            "region": deps.env.get("AIGOV_AI_LOCATION", ""),
        },
        "settings": {"workers": args.workers, "attempts": args.attempts, "max_tokens": args.max_tokens,
                     "reserved_tokens": args.reserved_tokens, "deadline_minutes": args.deadline_minutes,
                     "stream": False, "retries": 0},
        "stopped_reason": stopped_reason,
        "reserved_tokens_used": reserved,
        "teams": summary,
        "calls": calls,
        "source_revision": (deps.env.get("GITHUB_SHA") or "local")[:12],
    }
    atomic_write_json(paths.showback_dir(session_id) / "manifest.json", manifest)
    ok = sum(1 for c in calls if c["outcome"] == "ok")
    deps.out.write(f"traffic: {len(calls)} attempt(s), {ok} ok, stopped={stopped_reason}, "
                   f"window={window['start']}..{window['end']}\n")
    return 0 if calls and ok == len(calls) else 1


def _header(response: Any, name: str) -> Optional[str]:
    for key, value in (getattr(response, "headers", None) or {}).items():
        if str(key).lower() == name:
            return value
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="generate_traffic.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--session-id", help="Session ID (default SESSION_ID).")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--reserved-tokens", type=int, default=DEFAULT_RESERVED_TOKENS)
    parser.add_argument("--deadline-minutes", type=float, default=DEFAULT_DEADLINE_MINUTES)
    parser.add_argument("--env-file", default=str(common.REPO_ROOT / ".env"))
    parser.add_argument("--outputs-root", help="Outputs root (default <repo>/outputs).")
    return parser


def main(argv: Optional[Sequence[str]] = None, deps: Optional[Deps] = None) -> int:
    args = build_parser().parse_args(argv)
    deps = deps or Deps(env=os.environ)
    paths = common.Paths.default(Path(args.outputs_root) if args.outputs_root else None)
    try:
        return run_traffic(args, deps, paths, Path(args.env_file))
    except AzError as exc:
        deps.out.write(f"traffic: Azure call failed ({exc.category})\n")
        return 1
    except AutomationError as exc:
        deps.out.write(f"traffic: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
