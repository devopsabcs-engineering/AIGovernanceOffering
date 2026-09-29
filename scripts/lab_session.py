#!/usr/bin/env python
"""Lab session orchestrator: one CLI with subcommands for the lab-session workflow.

Every subcommand prints only nonsecret status. Secrets are announced with
``::add-mask::`` (GitHub Actions) immediately after retrieval. Azure is
reached only through an injectable :class:`aigov_common.ArmClient`, so tests
use stubs and no subcommand runs a shell.

Cleanup authority comes only from the mode-by-outcome table implemented in
:func:`decide_auto_cleanup` and only for manifest records created by the
current ``SESSION_ID``. Purge is human-only and refuses to run in GitHub
Actions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, TextIO, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aigov_common as common  # noqa: E402
from aigov_common import AutomationError, AzError  # noqa: E402
from shared import budget  # noqa: E402
from shared.config import DEFAULT_CONTENT_SAFETY_THRESHOLD  # noqa: E402
from shared.results import atomic_write_json  # noqa: E402

MODES = ("full-session", "deploy-only", "run-existing", "report-only", "dry-run", "lock-test")
CREATING_MODES = ("full-session", "deploy-only")
VERIFY_MODES = ("run-existing", "report-only")
MAX_RUN_ATTEMPT = 2
INSTANCE = "001"
MANIFEST_PREFIX = "aigov-manifest-"
MAIN_PREFIX = "aigov-main-"
MODULES = ("monitoring", "ai", "apim", "platform-api")
TEMPLATE = common.REPO_ROOT / "infra" / "main.bicep"
PARAMS = common.REPO_ROOT / "infra" / "main.bicepparam"
ENVELOPE = common.REPO_ROOT / "config" / "session-envelope.json"
ENV_PATH = common.REPO_ROOT / ".env"

# Automation calls beyond the notebook envelope, reserved in the default session caps.
TRAFFIC_ATTEMPTS = 30
TRAFFIC_RESERVED_TOKENS = 10_000
READINESS_ATTEMPTS = 3
PROBE_ATTEMPTS = 3
PROBE_MAX_TOKENS = 16
DEFAULT_MAX_ESTIMATED_USD = 2.0

SESSION_KEYS = common.SESSION_KEYS
EMPTY_ENV_KEYS = (
    "AOAI_KEY",
    "CONTENT_SAFETY_KEY",
    "CONTENT_SAFETY_BLOCKLIST_ID",
    "DEMO4_PTU_EAST_ENDPOINT",
    "DEMO4_PTU_CENTRAL_ENDPOINT",
    "DEMO4_PAYG_ENDPOINT",
    "DEMO4_PTU_EAST_DEPLOYMENT",
    "DEMO4_PTU_CENTRAL_DEPLOYMENT",
    "DEMO4_PAYG_DEPLOYMENT",
)
THRESHOLD_KEYS = (
    "CONTENT_SAFETY_THRESHOLD_HATE",
    "CONTENT_SAFETY_THRESHOLD_SELFHARM",
    "CONTENT_SAFETY_THRESHOLD_SEXUAL",
    "CONTENT_SAFETY_THRESHOLD_VIOLENCE",
)
# Deployment output -> .env key (AZURE_RESOURCE_GROUP maps to APIM_RESOURCE_GROUP).
OUTPUT_ENV_MAP = (
    ("AZURE_TENANT_ID", "AZURE_TENANT_ID"),
    ("AZURE_SUBSCRIPTION_ID", "AZURE_SUBSCRIPTION_ID"),
    ("AZURE_RESOURCE_GROUP", "APIM_RESOURCE_GROUP"),
    ("APIM_NAME", "APIM_NAME"),
    ("APIM_RESOURCE_ID", "APIM_RESOURCE_ID"),
    ("APIM_GATEWAY_URL", "APIM_GATEWAY_URL"),
    ("APIM_IDENTITY_CLIENT_ID", "APIM_IDENTITY_CLIENT_ID"),
    ("AOAI_ACCOUNT_RESOURCE_ID", "AOAI_ACCOUNT_RESOURCE_ID"),
    ("AOAI_ENDPOINT", "AOAI_ENDPOINT"),
    ("AOAI_DEPLOYMENT", "AOAI_DEPLOYMENT"),
    ("AOAI_API_STYLE", "AOAI_API_STYLE"),
    ("APP_INSIGHTS_NAME", "APP_INSIGHTS_NAME"),
    ("APP_INSIGHTS_RESOURCE_ID", "APP_INSIGHTS_RESOURCE_ID"),
    ("CONTENT_SAFETY_RESOURCE_ID", "CONTENT_SAFETY_RESOURCE_ID"),
    ("CONTENT_SAFETY_ENDPOINT", "CONTENT_SAFETY_ENDPOINT"),
    ("LOG_ANALYTICS_WORKSPACE_CUSTOMER_ID", "LOG_ANALYTICS_WORKSPACE_CUSTOMER_ID"),
    ("PLATFORM_LOGGER_ID", "PLATFORM_LOGGER_ID"),
    ("PLATFORM_API_ID", "PLATFORM_API_ID"),
    ("PLATFORM_API_PATH", "PLATFORM_API_PATH"),
    ("TOKEN_METRIC_NAMESPACE", "TOKEN_METRIC_NAMESPACE"),
    ("CLIENT_APP_ALLOWLIST", "CLIENT_APP_ALLOWLIST"),
    ("TEAM_PRODUCT_IDS", "TEAM_PRODUCT_IDS"),
    ("TEAM_SUBSCRIPTION_IDS", "TEAM_SUBSCRIPTION_IDS"),
    ("GENERATION", "AIGOV_GENERATION"),
)
# Bicep tags these types; tags corroborate ownership in addition to exact IDs.
TAGGED_TYPES = (
    "microsoft.apimanagement/service",
    "microsoft.cognitiveservices/accounts",
    "microsoft.insights/components",
    "microsoft.operationalinsights/workspaces",
)
MANIFEST_ID_OUTPUTS = (
    "APIM_RESOURCE_ID",
    "AOAI_ACCOUNT_RESOURCE_ID",
    "CONTENT_SAFETY_RESOURCE_ID",
    "APP_INSIGHTS_RESOURCE_ID",
    "LOG_ANALYTICS_WORKSPACE_RESOURCE_ID",
)


# ---------------------------------------------------------------------------
# Runtime context (everything external is injectable)
# ---------------------------------------------------------------------------


def _default_validate_env(env_path: Path) -> None:
    """Validate the written .env with load_config() in a fresh headless interpreter."""
    if Path(env_path).resolve() != ENV_PATH.resolve():
        raise AutomationError("Headless validation only supports the repository-root .env.")
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from shared.config import load_config, validate_config;"
        "validate_config(load_config())"
    )
    env = dict(os.environ)
    env["AIGOV_HEADLESS"] = "1"
    proc = subprocess.run(
        [sys.executable, "-c", code, str(common.REPO_ROOT)],
        cwd=str(common.REPO_ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        lines = [line for line in (proc.stderr or "").splitlines() if line.strip()]
        detail = lines[-1][:300] if lines else "unknown error"
        # ConfigError/ValueError messages name keys only, never values.
        raise AutomationError(f"Headless load_config() validation failed: {detail}")


def _default_papermill(notebook: Path, output: Path, cwd: Path, log_path: Path, timeout: float) -> int:
    """Run papermill without --log-output; cell output stays in a runner-local log file."""
    command = [sys.executable, "-m", "papermill", str(notebook), str(output), "--cwd", str(cwd)]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        try:
            proc = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            return 124
    return proc.returncode


@dataclass
class Context:
    client_factory: Callable[[], common.ArmClient] = common.AzCliArmClient
    paths: common.Paths = field(default_factory=common.Paths.default)
    env: Mapping[str, str] = field(default_factory=lambda: os.environ)
    out: TextIO = field(default_factory=lambda: sys.stdout)
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = common.utc_now
    http_post: Callable[..., Any] = common.default_http_post
    http_get: Callable[..., Any] = common.default_http_get
    logs_query: Callable[..., List[Dict[str, Any]]] = common.default_logs_query
    prompt: Optional[Callable[[str], str]] = None
    validate_env: Callable[[Path], None] = _default_validate_env
    papermill: Callable[[Path, Path, Path, Path, float], int] = _default_papermill
    env_path: Path = ENV_PATH
    _client: Optional[common.ArmClient] = None

    @property
    def client(self) -> common.ArmClient:
        if self._client is None:
            self._client = self.client_factory()
        return self._client

    def say(self, message: str) -> None:
        self.out.write(message + "\n")
        self.out.flush()

    def secrets(self, session_id: Optional[str]) -> common.SecretRegistry:
        hash_file = self.paths.secret_hashes(session_id) if session_id else None
        return common.SecretRegistry(hash_file, env=self.env, stream=self.out)


# ---------------------------------------------------------------------------
# Target and inventory
# ---------------------------------------------------------------------------


@dataclass
class Target:
    subscription_id: str
    resource_group: str
    generation: str
    environment_name: str
    name_suffix: str
    tenant_id: str = ""


def _env_first(ctx: Context, *keys: str) -> str:
    for key in keys:
        value = (ctx.env.get(key) or "").strip()
        if value:
            return value
    return ""


def resolve_target(ctx: Context, args: argparse.Namespace, *, need_suffix: bool = True) -> Target:
    generation = (getattr(args, "generation", None) or _env_first(ctx, "AIGOV_GENERATION")).strip()
    resource_group = (getattr(args, "resource_group", None) or _env_first(ctx, "AIGOV_LAB_RESOURCE_GROUP")).strip()
    environment_name = _env_first(ctx, "AIGOV_ENVIRONMENT_NAME") or "lab"
    suffix = _env_first(ctx, "AIGOV_NAME_SUFFIX")
    missing = [
        name for name, value in (
            ("--generation/AIGOV_GENERATION", generation),
            ("--resource-group/AIGOV_LAB_RESOURCE_GROUP", resource_group),
            ("AIGOV_NAME_SUFFIX", suffix if need_suffix else "ok"),
        ) if not value
    ]
    if missing:
        raise AutomationError(f"Missing target settings: {', '.join(missing)}.")
    if not re.fullmatch(r"[a-z0-9]{2,4}", generation):
        raise AutomationError("Generation must be 2-4 lowercase letters or digits.")
    if not re.fullmatch(r"[a-z0-9]{2,8}", environment_name):
        raise AutomationError("AIGOV_ENVIRONMENT_NAME must be 2-8 lowercase letters or digits.")
    if need_suffix and not re.fullmatch(r"[a-z0-9]{4,6}", suffix):
        raise AutomationError("AIGOV_NAME_SUFFIX must be 4-6 lowercase letters or digits.")
    account = ctx.client.account()
    subscription_id = (getattr(args, "subscription_id", None) or _env_first(ctx, "AZURE_SUBSCRIPTION_ID")
                       or account.get("subscription_id", ""))
    if account.get("subscription_id") and account["subscription_id"] != subscription_id:
        raise AutomationError("Signed-in subscription does not match the approved subscription.")
    expected_tenant = _env_first(ctx, "AZURE_TENANT_ID")
    if expected_tenant and account.get("tenant_id") and account["tenant_id"] != expected_tenant:
        raise AutomationError("Signed-in tenant does not match the approved tenant.")
    confirm = getattr(args, "confirm_resource_group", None)
    if confirm and confirm != resource_group:
        raise AutomationError("--confirm-resource-group does not match the target resource group.")
    return Target(subscription_id, resource_group, generation, environment_name, suffix,
                  account.get("tenant_id", ""))


def planned_names(target: Target) -> Dict[str, str]:
    token = f"aigov-{target.environment_name}-{target.generation}-{INSTANCE}"
    return {
        "log_analytics": f"log-{token}",
        "app_insights": f"appi-{token}",
        "apim": f"apim-{token}-{target.name_suffix}",
        "model_account": f"aif-{token}-{target.name_suffix}",
        "content_safety": f"cs-{token}-{target.name_suffix}",
        "chat_deployment": "chat",
    }


def planned_inventory(target: Target) -> Dict[str, List[Dict[str, str]]]:
    names = planned_names(target)
    providers = f"{common.rg_scope(target.subscription_id, target.resource_group)}/providers"
    model_account = f"{providers}/Microsoft.CognitiveServices/accounts/{names['model_account']}"
    expected = [
        (f"{providers}/Microsoft.OperationalInsights/workspaces/{names['log_analytics']}", names["log_analytics"]),
        (f"{providers}/Microsoft.Insights/components/{names['app_insights']}", names["app_insights"]),
        (f"{providers}/Microsoft.ApiManagement/service/{names['apim']}", names["apim"]),
        (model_account, names["model_account"]),
        (f"{model_account}/deployments/{names['chat_deployment']}", names["chat_deployment"]),
        (f"{providers}/Microsoft.CognitiveServices/accounts/{names['content_safety']}", names["content_safety"]),
    ]
    # Created implicitly by Application Insights in some tenants; owned and removed with the component.
    optional = [
        (f"{providers}/microsoft.alertsmanagement/smartDetectorAlertRules/Failure Anomalies - {names['app_insights']}",
         f"Failure Anomalies - {names['app_insights']}"),
        (f"{providers}/microsoft.insights/actiongroups/Application Insights Smart Detection",
         "Application Insights Smart Detection"),
    ]

    def entry(resource_id: str, name: str) -> Dict[str, str]:
        return {"id": resource_id, "type": common.resource_type_of(resource_id), "name": name}

    return {
        "expected": [entry(i, n) for i, n in expected],
        "optional": [entry(i, n) for i, n in optional],
    }


# ---------------------------------------------------------------------------
# Manifest records (DD-03, DD-07)
# ---------------------------------------------------------------------------


def _arm_safe(value: Any) -> Any:
    """Records round-trip through ARM outputs, so only strings, ints, bools, lists, and dicts are allowed."""
    if isinstance(value, dict):
        return {str(k): _arm_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_arm_safe(v) for v in value]
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, (str, int, bool)):
        return value
    raise AutomationError(f"Unsupported manifest value type {type(value).__name__}.")


def source_revision(ctx: Context) -> str:
    return _env_first(ctx, "GITHUB_SHA") or "local"


def build_manifest(
    ctx: Context,
    target: Target,
    *,
    record_kind: str,
    session_id: str,
    mode: str,
    inventory: Mapping[str, Any],
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    manifest = {
        "schema_version": 1,
        "kind": "aigov-manifest",
        "record_kind": record_kind,
        "created_by_session": session_id,
        "mode": mode,
        "created_at": common.fmt_utc(ctx.now()),
        "tenant_id": target.tenant_id,
        "subscription_id": target.subscription_id,
        "resource_group": target.resource_group,
        "resource_group_id": common.rg_scope(target.subscription_id, target.resource_group),
        "generation": target.generation,
        "environment_name": target.environment_name,
        "name_suffix": target.name_suffix,
        "deployment_name": f"{MAIN_PREFIX}{target.generation}",
        "module_deployment_names": [f"{MAIN_PREFIX}{target.generation}-{m}" for m in MODULES],
        "expected_resources": list(inventory["expected"]),
        "optional_resources": list(inventory["optional"]),
        "source_revision": source_revision(ctx),
        "run_id": _env_first(ctx, "GITHUB_RUN_ID"),
        "run_attempt": _env_first(ctx, "GITHUB_RUN_ATTEMPT"),
    }
    manifest.update(extra or {})
    return _arm_safe(manifest)


def record_name(generation: str, session_id: str, content_sha256: str) -> str:
    name = f"{MANIFEST_PREFIX}{generation}-{session_id}-{content_sha256[:8]}"
    if len(name) > 64 or not re.fullmatch(r"[A-Za-z0-9_.()\-]+", name):
        raise AutomationError("Manifest record name exceeds ARM deployment name rules.")
    return name


def persist_record(ctx: Context, manifest: Mapping[str, Any]) -> str:
    """Write the artifact backup, then the append-only ARM record; both must succeed."""
    content_sha256 = common.sha256_text(common.canonical_json(manifest))
    session_id = manifest["created_by_session"]
    name = record_name(manifest["generation"], session_id, content_sha256)
    backup = ctx.paths.manifest_dir(session_id) / f"{name}.json"
    if backup.exists():
        raise AutomationError(f"Manifest backup {backup.name} already exists; records are never overwritten.")
    atomic_write_json(backup, {"name": name, "content_sha256": content_sha256, "manifest": manifest})
    ctx.client.put_record_deployment(
        manifest["subscription_id"], manifest["resource_group"], name, manifest, content_sha256
    )
    return name


def _record_from_deployment(deployment: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    outputs = (deployment.get("properties") or {}).get("outputs") or {}
    manifest = (outputs.get("manifest") or {}).get("value")
    content_sha256 = (outputs.get("contentSha256") or {}).get("value")
    if not isinstance(manifest, dict) or not isinstance(content_sha256, str):
        return None
    return {"name": deployment.get("name", ""), "manifest": manifest, "content_sha256": content_sha256}


def validate_record(record: Mapping[str, Any], target: Target) -> bool:
    manifest = record.get("manifest") or {}
    digest = common.sha256_text(common.canonical_json(manifest))
    return (
        digest == record.get("content_sha256")
        and str(record.get("name", "")).endswith(digest[:8])
        and manifest.get("kind") == "aigov-manifest"
        and manifest.get("generation") == target.generation
        and str(manifest.get("resource_group", "")).lower() == target.resource_group.lower()
        and manifest.get("subscription_id") == target.subscription_id
    )


def load_records(
    ctx: Context, target: Target, *, session_id: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], int]:
    """Return valid records for the generation (oldest first) and the count of invalid ones."""
    prefix = f"{MANIFEST_PREFIX}{target.generation}-"
    valid: List[Dict[str, Any]] = []
    invalid = 0
    for deployment in ctx.client.list_deployments(target.subscription_id, target.resource_group):
        name = deployment.get("name", "")
        if not name.startswith(prefix):
            continue
        record = _record_from_deployment(deployment)
        if record is None:
            record = _record_from_deployment(
                ctx.client.get_deployment(target.subscription_id, target.resource_group, name)
            )
        if record is None or not validate_record(record, target):
            invalid += 1
            continue
        if session_id and record["manifest"].get("created_by_session") != session_id:
            continue
        valid.append(record)
    valid.sort(key=lambda r: (r["manifest"].get("created_at", ""), r["name"]))
    return valid, invalid


def load_record_file(path: Path, target: Target) -> Dict[str, Any]:
    record = common.read_json(path)
    if not validate_record(record, target):
        raise AutomationError("Manifest backup failed hash or target validation.")
    return record


def record_targets(records: Sequence[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """Union of expected, optional, and observed resources across records (deduplicated by ID)."""
    seen: Dict[str, Dict[str, str]] = {}
    for record in records:
        manifest = record["manifest"]
        for key in ("expected_resources", "optional_resources", "observed_resources"):
            for item in manifest.get(key) or []:
                resource_id = str(item.get("id", ""))
                if resource_id:
                    seen.setdefault(resource_id.lower(), {
                        "id": resource_id,
                        "type": common.resource_type_of(resource_id),
                        "name": str(item.get("name", "")),
                    })
    return list(seen.values())


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def load_session_env(ctx: Context, session_id: str, *, required: bool = True) -> Dict[str, str]:
    path = ctx.paths.session_env(session_id)
    if not path.exists():
        if required:
            raise AutomationError("Session file is missing; run init-session first.")
        return {}
    return common.read_env_file(path)


def budget_env(ctx: Context, session_id: str) -> Dict[str, str]:
    return common.session_budget_env(ctx.paths, session_id, ctx.env)


def default_limits() -> Tuple[int, int]:
    envelope = common.read_json(ENVELOPE)
    totals = envelope.get("totals", {})
    probe_tokens = (READINESS_ATTEMPTS + PROBE_ATTEMPTS) * (budget.estimate_prompt_tokens("x" * 64) + PROBE_MAX_TOKENS)
    attempts = int(totals.get("max_attempts", 0)) + TRAFFIC_ATTEMPTS + READINESS_ATTEMPTS + PROBE_ATTEMPTS
    tokens = int(totals.get("max_reserved_tokens", 0)) + TRAFFIC_RESERVED_TOKENS + probe_tokens
    return attempts, tokens


def compute_deadline(
    job_start: datetime,
    job_timeout_minutes: int,
    cleanup_login_minutes: int,
    cleanup_minutes: int,
    post_sanitize_minutes: int,
    upload_minutes: int,
    margin_minutes: int,
) -> datetime:
    """Deadline = job start + job timeout - (cleanup login + cleanup + post sanitize + upload + margin)."""
    reserved = cleanup_login_minutes + cleanup_minutes + post_sanitize_minutes + upload_minutes + margin_minutes
    for value in (job_timeout_minutes, cleanup_login_minutes, cleanup_minutes, post_sanitize_minutes,
                  upload_minutes, margin_minutes):
        if value < 0:
            raise AutomationError("Timeout components must be non-negative minutes.")
    if job_timeout_minutes > 360:
        raise AutomationError("Job timeout exceeds the 360-minute hosted-runner limit.")
    if reserved >= job_timeout_minutes:
        raise AutomationError("Post-work caps leave no time for budgeted work.")
    return job_start + timedelta(minutes=job_timeout_minutes - reserved)


# ---------------------------------------------------------------------------
# init-session
# ---------------------------------------------------------------------------


def cmd_init_session(ctx: Context, args: argparse.Namespace) -> int:
    attempt_text = str(args.run_attempt or _env_first(ctx, "GITHUB_RUN_ATTEMPT") or "1")
    try:
        attempt = int(attempt_text)
    except ValueError:
        raise AutomationError("Run attempt must be an integer.") from None
    if attempt < 1 or attempt > MAX_RUN_ATTEMPT:
        raise AutomationError(
            f"Run attempt {attempt} refused: each session allows at most {MAX_RUN_ATTEMPT} approved attempts."
        )
    now = ctx.now()
    run_id = str(args.run_id or _env_first(ctx, "GITHUB_RUN_ID") or f"local{now.strftime('%Y%m%d%H%M%S')}")
    if not re.fullmatch(r"[A-Za-z0-9]{1,40}", run_id):
        raise AutomationError("Run ID must be 1-40 letters or digits.")
    session_id = f"{run_id}-{attempt}"

    job_start = common.parse_utc(args.job_start_utc, "--job-start-utc") if args.job_start_utc else now
    deadline = compute_deadline(
        job_start, args.job_timeout_minutes, args.cleanup_login_minutes, args.cleanup_minutes,
        args.post_sanitize_minutes, args.upload_minutes, args.margin_minutes,
    )
    if deadline <= now:
        raise AutomationError("The computed session deadline is already in the past.")

    default_attempts, default_tokens = default_limits()
    limits = budget.SessionLimits(
        max_attempts=args.max_attempts if args.max_attempts is not None else default_attempts,
        max_reserved_tokens=args.max_reserved_tokens if args.max_reserved_tokens is not None else default_tokens,
        max_estimated_usd=args.max_estimated_usd,
        deadline_utc=common.fmt_utc(deadline),
    )

    price = None
    if args.price_snapshot:
        snapshot = common.load_price_snapshot(Path(args.price_snapshot))
        selected = common.select_prices(
            snapshot,
            model=_env_first(ctx, "AIGOV_CHAT_MODEL_NAME"),
            version=_env_first(ctx, "AIGOV_CHAT_MODEL_VERSION"),
            sku=_env_first(ctx, "AIGOV_CHAT_DEPLOYMENT_SKU"),
            region=_env_first(ctx, "AIGOV_AI_LOCATION"),
            at=now,
        )
        price = {
            "input_usd_per_million": float(selected["input_usd_per_million"]),
            "output_usd_per_million": float(selected["output_usd_per_million"]),
            "snapshot_id": selected["snapshot_id"],
        }
    elif args.require_price:
        raise AutomationError("An approved price snapshot is required for this mode (--price-snapshot).")

    try:
        budget.init_session(session_id, limits, price=price, root=ctx.paths.budget_root)
    except budget.BudgetStateError as exc:
        raise AutomationError(str(exc)) from None

    values = {
        "AIGOV_HEADLESS": "1",
        "SESSION_ID": session_id,
        "SESSION_MAX_ATTEMPTS": str(limits.max_attempts),
        "SESSION_MAX_RESERVED_TOKENS": str(limits.max_reserved_tokens),
        "SESSION_MAX_ESTIMATED_USD": f"{limits.max_estimated_usd:g}",
        "SESSION_DEADLINE_UTC": limits.deadline_utc,
    }
    body = "# Private session file written by lab_session.py init-session. Never upload.\n"
    body += "".join(f"{key}={value}\n" for key, value in values.items())
    common.write_private_text(ctx.paths.session_env(session_id), body)
    atomic_write_json(ctx.paths.session_dir(session_id) / "session.json", {
        "schema_version": 1,
        "session_id": session_id,
        "run_id": run_id,
        "run_attempt": attempt,
        "created_at": common.fmt_utc(now),
        "job_start_utc": common.fmt_utc(job_start),
        "deadline_utc": limits.deadline_utc,
        "price_snapshot_id": price["snapshot_id"] if price else "",
    })
    github_env = ctx.env.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as handle:
            handle.write("".join(f"{key}={value}\n" for key, value in values.items()))
    ctx.say(f"init-session: SESSION_ID={session_id} deadline={limits.deadline_utc} "
            f"max_attempts={limits.max_attempts} max_reserved_tokens={limits.max_reserved_tokens} "
            f"price_snapshot={'set' if price else 'none'}")
    return 0


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------


def _params_env_names(params_path: Path) -> Tuple[List[str], List[str]]:
    text = Path(params_path).read_text(encoding="utf-8")
    required, optional = [], []
    for match in re.finditer(r"readEnvironmentVariable\('([A-Z0-9_]+)'(\s*,)?", text):
        (optional if match.group(2) else required).append(match.group(1))
    return sorted(set(required)), sorted(set(optional))


def check_model_tuple(env: Mapping[str, str]) -> Dict[str, Any]:
    tuple_keys = ("AIGOV_CHAT_MODEL_NAME", "AIGOV_CHAT_MODEL_VERSION", "AIGOV_CHAT_DEPLOYMENT_SKU",
                  "AIGOV_AI_LOCATION", "AIGOV_CHAT_DEPLOYMENT_CAPACITY")
    missing = [k for k in tuple_keys if not (env.get(k) or "").strip()]
    if missing:
        raise AutomationError(f"Approved model tuple incomplete: {', '.join(missing)}.")
    try:
        capacity = int(env["AIGOV_CHAT_DEPLOYMENT_CAPACITY"])
    except ValueError:
        raise AutomationError("AIGOV_CHAT_DEPLOYMENT_CAPACITY must be an integer.") from None
    if capacity < 1:
        raise AutomationError("AIGOV_CHAT_DEPLOYMENT_CAPACITY must be at least 1.")
    sku = env["AIGOV_CHAT_DEPLOYMENT_SKU"].strip()
    if sku.lower().startswith(("global", "datazone")) and not common.truthy(env.get("AIGOV_ALLOW_GLOBAL_PROCESSING")):
        raise AutomationError(
            f"Deployment SKU {sku} may process data outside the model region; "
            "set AIGOV_ALLOW_GLOBAL_PROCESSING=true only after approval."
        )
    return {
        "model": env["AIGOV_CHAT_MODEL_NAME"].strip(),
        "version": env["AIGOV_CHAT_MODEL_VERSION"].strip(),
        "sku": sku,
        "region": env["AIGOV_AI_LOCATION"].strip(),
        "capacity": capacity,
    }


def _tombstone_names(ctx: Context, subscription_id: str) -> Dict[str, List[Dict[str, str]]]:
    lists = {
        "apim": f"/subscriptions/{subscription_id}/providers/Microsoft.ApiManagement/deletedservices"
                f"?api-version={common.API_VERSIONS['apim']}",
        "cognitive": f"/subscriptions/{subscription_id}/providers/Microsoft.CognitiveServices/deletedAccounts"
                     f"?api-version={common.API_VERSIONS['cognitive']}",
        "workspace": f"/subscriptions/{subscription_id}/providers/Microsoft.OperationalInsights/deletedWorkspaces"
                     f"?api-version={common.API_VERSIONS['workspaces']}",
    }
    found: Dict[str, List[Dict[str, str]]] = {}
    for kind, path in lists.items():
        found[kind] = [
            {
                "name": str(item.get("name", "")),
                "location": str(item.get("location") or (item.get("properties") or {}).get("location", "")),
                "scheduled_purge": str((item.get("properties") or {}).get("scheduledPurgeDate", "")),
            }
            for item in ctx.client.get_all(path)
        ]
    return found


def cmd_preflight(ctx: Context, args: argparse.Namespace) -> int:
    session_id = common.resolve_session(args.session_id, ctx.env)
    required, _ = _params_env_names(Path(args.params))
    missing = [name for name in required if not _env_first(ctx, name)]
    checks: Dict[str, Dict[str, Any]] = {}

    def record(name: str, ok: bool, code: str) -> None:
        checks[name] = {"status": "passed" if ok else "failed", "code": code}

    record("parameters_present", not missing, "ok" if not missing else "missing:" + ",".join(missing))
    if missing:
        return _finish_preflight(ctx, session_id, checks)
    try:
        model = check_model_tuple(ctx.env)
        record("model_tuple", True, "ok")
    except AutomationError as exc:
        record("model_tuple", False, "rejected")
        ctx.say(f"preflight: {exc}")
        return _finish_preflight(ctx, session_id, checks)

    target = resolve_target(ctx, args)
    sub = target.subscription_id
    location = common.normalize_region(_env_first(ctx, "AIGOV_LOCATION"))
    cs_location = common.normalize_region(_env_first(ctx, "AIGOV_CONTENT_SAFETY_LOCATION"))
    ai_location = common.normalize_region(model["region"])

    def guarded(name: str, fn: Callable[[], Tuple[bool, str]]) -> None:
        try:
            ok, code = fn()
        except AzError as exc:
            ok, code = False, f"azure_{exc.category}"
        record(name, ok, code)

    def providers() -> Tuple[bool, str]:
        for namespace in ("Microsoft.ApiManagement", "Microsoft.CognitiveServices", "Microsoft.Insights",
                          "Microsoft.OperationalInsights"):
            data = ctx.client.rest("GET", f"/subscriptions/{sub}/providers/{namespace}"
                                          f"?api-version={common.API_VERSIONS['providers']}") or {}
            if data.get("registrationState") != "Registered":
                return False, f"not_registered:{namespace}"
            if namespace == "Microsoft.ApiManagement":
                service = [t for t in data.get("resourceTypes", []) if str(t.get("resourceType")).lower() == "service"]
                locations = {common.normalize_region(loc) for t in service for loc in t.get("locations", [])}
                if location not in locations:
                    return False, "apim_region_unavailable"
        return True, "ok"

    def model_available() -> Tuple[bool, str]:
        items = ctx.client.get_all(f"/subscriptions/{sub}/providers/Microsoft.CognitiveServices/locations/"
                                   f"{ai_location}/models?api-version={common.API_VERSIONS['cognitive']}")
        for item in items:
            info = item.get("model") or {}
            if info.get("name") == model["model"] and info.get("version") == model["version"]:
                if any(str(s.get("name", "")).lower() == model["sku"].lower() for s in info.get("skus", [])):
                    return True, "ok"
                return False, "sku_unavailable"
        return False, "model_unavailable"

    def quota() -> Tuple[bool, str]:
        items = ctx.client.get_all(f"/subscriptions/{sub}/providers/Microsoft.CognitiveServices/locations/"
                                   f"{ai_location}/usages?api-version={common.API_VERSIONS['cognitive']}")
        usage_name = f"OpenAI.{model['sku']}.{model['model']}".lower()
        for item in items:
            if str((item.get("name") or {}).get("value", "")).lower() == usage_name:
                headroom = float(item.get("limit", 0)) - float(item.get("currentValue", 0))
                return (headroom >= model["capacity"]), ("ok" if headroom >= model["capacity"] else "insufficient_quota")
        return False, "quota_unknown"

    def content_safety() -> Tuple[bool, str]:
        items = ctx.client.get_all(f"/subscriptions/{sub}/providers/Microsoft.CognitiveServices/skus"
                                   f"?api-version={common.API_VERSIONS['cognitive']}")
        for item in items:
            if item.get("kind") == "ContentSafety" and cs_location in {
                common.normalize_region(loc) for loc in item.get("locations", [])
            }:
                return True, "ok"
        return False, "content_safety_unavailable"

    def tombstones() -> Tuple[bool, str]:
        names = planned_names(target)
        found = _tombstone_names(ctx, sub)
        collisions = [e["name"] for e in found["apim"] if e["name"] == names["apim"]]
        collisions += [e["name"] for e in found["cognitive"]
                       if e["name"] in (names["model_account"], names["content_safety"])]
        collisions += [e["name"] for e in found["workspace"] if e["name"] == names["log_analytics"]]
        if collisions:
            ctx.say("preflight: soft-deleted resources hold planned names "
                    f"({', '.join(sorted(collisions))}); new generation or operator purge required.")
            return False, "tombstone_collision"
        return True, "ok"

    guarded("providers_and_region", providers)
    guarded("model_available", model_available)
    guarded("model_quota", quota)
    guarded("content_safety_available", content_safety)
    guarded("tombstones", tombstones)
    return _finish_preflight(ctx, session_id, checks)


def _finish_preflight(ctx: Context, session_id: str, checks: Mapping[str, Any]) -> int:
    failed = [name for name, check in checks.items() if check["status"] != "passed"]
    atomic_write_json(ctx.paths.outputs / "preflight" / session_id / "summary.json", {
        "schema_version": 1,
        "session_id": session_id,
        "status": "failed" if failed else "passed",
        "checks": dict(checks),
    })
    for name, check in checks.items():
        ctx.say(f"preflight: {name}: {check['status']} ({check['code']})")
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# what-if
# ---------------------------------------------------------------------------


def evaluate_what_if(changes: Sequence[Mapping[str, Any]], allowed_ids: Sequence[str]) -> Dict[str, Any]:
    allowed = [a.lower() for a in allowed_ids]
    counts: Dict[str, int] = {}
    violations: List[Dict[str, str]] = []
    for change in changes:
        change_type = str(change.get("change_type") or "")
        resource_id = str(change.get("resource_id") or "")
        counts[change_type] = counts.get(change_type, 0) + 1
        lowered = resource_id.lower()
        inside = any(lowered == a or lowered.startswith(a + "/") for a in allowed)
        if change_type == "Delete":
            violations.append({"change_type": change_type, "type": common.resource_type_of(resource_id),
                               "name": resource_id.rsplit("/", 1)[-1], "reason": "delete"})
        elif change_type in ("Create", "Modify", "Deploy"):
            if not inside:
                violations.append({"change_type": change_type, "type": common.resource_type_of(resource_id),
                                   "name": resource_id.rsplit("/", 1)[-1], "reason": "outside_plan"})
        elif change_type not in ("NoChange", "Ignore", "Unsupported"):
            violations.append({"change_type": change_type, "type": common.resource_type_of(resource_id),
                               "name": resource_id.rsplit("/", 1)[-1], "reason": "unknown_change_type"})
    return {"status": "failed" if violations else "passed", "counts": counts, "violations": violations}


def cmd_what_if(ctx: Context, args: argparse.Namespace) -> int:
    session_id = common.resolve_session(args.session_id, ctx.env)
    target = resolve_target(ctx, args)
    inventory = planned_inventory(target)
    allowed = [e["id"] for e in inventory["expected"] + inventory["optional"]]
    changes = ctx.client.what_if(target.resource_group, Path(args.template), Path(args.params))
    summary = evaluate_what_if(changes, allowed)
    atomic_write_json(ctx.paths.whatif_dir(session_id) / "summary.json",
                      {"schema_version": 1, "session_id": session_id, **summary})
    counts = ", ".join(f"{k}={v}" for k, v in sorted(summary["counts"].items()))
    ctx.say(f"what-if: {counts or 'no changes'}")
    for violation in summary["violations"]:
        ctx.say(f"what-if: refused {violation['change_type']} {violation['type']} {violation['name']} "
                f"({violation['reason']})")
    return 0 if summary["status"] == "passed" else 1


# ---------------------------------------------------------------------------
# manifest create / verify
# ---------------------------------------------------------------------------


def _live_state(ctx: Context, target: Target) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    resources = ctx.client.list_rg_resources(target.subscription_id, target.resource_group)
    locks = ctx.client.list_locks(target.subscription_id, target.resource_group)
    return resources, locks


def cmd_manifest_create(ctx: Context, args: argparse.Namespace) -> int:
    session_id = common.resolve_session(args.session_id, ctx.env)
    if args.mode not in CREATING_MODES:
        raise AutomationError(f"manifest create is only allowed in {', '.join(CREATING_MODES)}.")
    load_session_env(ctx, session_id)
    target = resolve_target(ctx, args)
    inventory = planned_inventory(target)
    try:
        live, locks = _live_state(ctx, target)
    except AzError as exc:
        if exc.category == "not_found":
            raise AutomationError("The lab resource group does not exist; run the bootstrap first.") from None
        raise
    if locks:
        raise AutomationError(f"Refused: the resource group has {len(locks)} lock(s); locks are never removed automatically.")
    owned = {e["id"].lower() for e in inventory["expected"] + inventory["optional"]}
    live_owned = [r for r in live if str(r.get("id", "")).lower() in owned]
    unexpected = [r for r in live if str(r.get("id", "")).lower() not in owned]
    if unexpected:
        raise AutomationError(
            "Refused: the resource group contains resources outside the approved inventory: "
            + ", ".join(sorted(f"{common.resource_type_of(r['id'])}/{r.get('name', '')}" for r in unexpected))
        )
    if live_owned:
        raise AutomationError(
            f"Refused: {len(live_owned)} live owned resource(s) already exist for generation "
            f"{target.generation}; use run-existing or teardown instead."
        )
    manifest = build_manifest(ctx, target, record_kind="planned", session_id=session_id, mode=args.mode,
                              inventory=inventory, extra={"baseline_resource_count": len(live)})
    name = persist_record(ctx, manifest)
    atomic_write_json(ctx.paths.manifest_dir(session_id) / "planned.json", {
        "name": name, "content_sha256": common.sha256_text(common.canonical_json(manifest)), "manifest": manifest,
    })
    ctx.say(f"manifest create: recorded {name} (mode {args.mode}, {len(inventory['expected'])} planned resources)")
    return 0


def cmd_manifest_verify(ctx: Context, args: argparse.Namespace) -> int:
    session_id = common.resolve_session(args.session_id, ctx.env)
    target = resolve_target(ctx, args, need_suffix=False)
    records, invalid = load_records(ctx, target)
    if invalid:
        ctx.say(f"manifest verify: ignored {invalid} record(s) that failed hash or target validation")
    if not records:
        raise AutomationError(f"No valid manifest record exists for generation {target.generation}.")
    newest = records[-1]
    manifest = newest["manifest"]
    if target.tenant_id and manifest.get("tenant_id") and manifest["tenant_id"] != target.tenant_id:
        raise AutomationError("Manifest tenant does not match the signed-in tenant.")
    live, locks = _live_state(ctx, target)
    live_ids = {str(r.get("id", "")).lower() for r in live}
    targets = record_targets([newest])
    optional = {str(e.get("id", "")).lower() for e in manifest.get("optional_resources", [])}
    top_level = [t for t in targets if t["type"] != "microsoft.cognitiveservices/accounts/deployments"
                 and t["id"].lower() not in optional]
    missing = [t for t in top_level if t["id"].lower() not in live_ids]
    allowed = {t["id"].lower() for t in targets}
    unexpected = [r for r in live if str(r.get("id", "")).lower() not in allowed]
    problems = []
    if missing:
        problems.append(f"{len(missing)} expected resource(s) missing")
    if unexpected:
        problems.append(f"{len(unexpected)} unexpected resource(s)")
    if locks and args.mode == "run-existing":
        problems.append(f"{len(locks)} lock(s)")
    if problems:
        raise AutomationError("manifest verify failed: " + "; ".join(problems) + ".")
    atomic_write_json(ctx.paths.manifest_dir(session_id) / "verified.json", {
        "name": newest["name"], "content_sha256": newest["content_sha256"], "manifest": manifest,
        "verified_at": common.fmt_utc(ctx.now()), "locks": len(locks),
    })
    ctx.say(f"manifest verify: {newest['name']} matches {len(top_level)} live resource(s)")
    return 0


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------


def _planned_record(ctx: Context, session_id: str, target: Target) -> Dict[str, Any]:
    path = ctx.paths.manifest_dir(session_id) / "planned.json"
    if not path.exists():
        raise AutomationError("No planned manifest for this session; run manifest create first.")
    record = load_record_file(path, target)
    if record["manifest"].get("created_by_session") != session_id:
        raise AutomationError("The planned manifest belongs to another session.")
    return record


def _observed(ctx: Context, target: Target, inventory: Mapping[str, Any]) -> List[Dict[str, str]]:
    owned = {e["id"].lower(): e for e in inventory["expected"] + inventory["optional"]}
    observed = []
    try:
        for resource in ctx.client.list_rg_resources(target.subscription_id, target.resource_group):
            entry = owned.get(str(resource.get("id", "")).lower())
            if entry:
                observed.append(dict(entry))
    except AzError:
        return observed
    for entry in inventory["expected"]:
        if entry["type"] == "microsoft.cognitiveservices/accounts/deployments":
            try:
                ctx.client.get_resource(entry["id"], common.TYPE_API_VERSION[entry["type"]])
                observed.append(dict(entry))
            except AzError:
                pass
    return observed


def cmd_deploy(ctx: Context, args: argparse.Namespace) -> int:
    session_id = common.resolve_session(args.session_id, ctx.env)
    target = resolve_target(ctx, args)
    planned = _planned_record(ctx, session_id, target)
    manifest = planned["manifest"]
    deployment_name = manifest["deployment_name"]
    outcome, error_category = "failed", ""
    try:
        result = ctx.client.deploy_bicep(target.resource_group, deployment_name, Path(args.template), Path(args.params))
        outcome = "succeeded" if result.get("provisioning_state") == "Succeeded" else "failed"
    except AzError as exc:
        error_category = exc.category
    inventory = {"expected": manifest["expected_resources"], "optional": manifest["optional_resources"]}
    observed = _observed(ctx, target, inventory)
    attempt = build_manifest(
        ctx, target, record_kind="deploy-attempt", session_id=session_id, mode=manifest["mode"],
        inventory=inventory,
        extra={"deploy_outcome": outcome, "deploy_error_category": error_category, "observed_resources": observed},
    )
    name = persist_record(ctx, attempt)
    ctx.say(f"deploy: {deployment_name} {outcome}; recorded {name} ({len(observed)} observed resource(s))")
    if outcome == "succeeded":
        prune_history(ctx, target, keep=[deployment_name, *manifest["module_deployment_names"]])
        return 0
    return 1


def prune_history(ctx: Context, target: Target, keep: Sequence[str]) -> int:
    """Delete superseded aigov-main-* records (and nested module records); never manifest records."""
    keep_lower = {k.lower() for k in keep}
    deleted = 0
    try:
        deployments = ctx.client.list_deployments(target.subscription_id, target.resource_group)
    except AzError as exc:
        ctx.say(f"deploy: history pruning skipped ({exc.category})")
        return 0
    for deployment in deployments:
        name = str(deployment.get("name", ""))
        if name.startswith(MANIFEST_PREFIX) or not name.startswith(MAIN_PREFIX) or name.lower() in keep_lower:
            continue
        try:
            ctx.client.delete_deployment(target.subscription_id, target.resource_group, name)
            deleted += 1
        except AzError as exc:
            ctx.say(f"deploy: could not prune a superseded deployment record ({exc.category})")
    if deleted:
        ctx.say(f"deploy: pruned {deleted} superseded deployment record(s)")
    return deleted


# ---------------------------------------------------------------------------
# write-env
# ---------------------------------------------------------------------------


def _manifest_for_session(ctx: Context, session_id: str) -> Dict[str, Any]:
    for name in ("planned.json", "verified.json"):
        path = ctx.paths.manifest_dir(session_id) / name
        if path.exists():
            return common.read_json(path)["manifest"]
    raise AutomationError("No planned or verified manifest for this session.")


def _output_value(outputs: Mapping[str, Any], key: str) -> Any:
    entry = outputs.get(key)
    if entry is None:
        # ARM may normalize output-name casing.
        entry = next((v for k, v in outputs.items() if k.lower() == key.lower()), None)
    if entry is None:
        raise AutomationError(f"Deployment output {key} is missing.")
    return entry.get("value") if isinstance(entry, dict) else entry


def cmd_write_env(ctx: Context, args: argparse.Namespace) -> int:
    session_id = common.resolve_session(args.session_id, ctx.env)
    session_values = load_session_env(ctx, session_id)
    manifest = _manifest_for_session(ctx, session_id)
    sub, rg = manifest["subscription_id"], manifest["resource_group"]
    deployment = ctx.client.get_deployment(sub, rg, manifest["deployment_name"])
    properties = deployment.get("properties") or {}
    if properties.get("provisioningState") != "Succeeded":
        raise AutomationError("The platform deployment is not in the Succeeded state.")
    outputs = properties.get("outputs") or {}

    if _output_value(outputs, "AZURE_TENANT_ID") != manifest.get("tenant_id") and manifest.get("tenant_id"):
        raise AutomationError("Deployment tenant does not match the manifest.")
    if _output_value(outputs, "AZURE_SUBSCRIPTION_ID") != sub:
        raise AutomationError("Deployment subscription does not match the manifest.")
    if str(_output_value(outputs, "AZURE_RESOURCE_GROUP")).lower() != rg.lower():
        raise AutomationError("Deployment resource group does not match the manifest.")
    if _output_value(outputs, "GENERATION") != manifest.get("generation"):
        raise AutomationError("Deployment generation does not match the manifest.")
    expected_ids = {str(e.get("id", "")).lower() for e in manifest.get("expected_resources", [])}
    for key in MANIFEST_ID_OUTPUTS:
        if str(_output_value(outputs, key)).lower() not in expected_ids:
            raise AutomationError(f"Deployment output {key} is not a manifest resource.")

    secrets = ctx.secrets(session_id)
    component = ctx.client.get_resource(_output_value(outputs, "APP_INSIGHTS_RESOURCE_ID"), common.API_VERSIONS["insights"])
    connection_string = secrets.register((component.get("properties") or {}).get("ConnectionString") or "")
    if not connection_string:
        raise AutomationError("Application Insights connection string could not be read.")

    values: Dict[str, str] = {}
    for key in SESSION_KEYS:
        if key not in session_values:
            raise AutomationError(f"Session file lacks {key}.")
        values[key] = session_values[key]
    for output_key, env_key in OUTPUT_ENV_MAP:
        value = _output_value(outputs, output_key)
        values[env_key] = ",".join(str(v) for v in value) if isinstance(value, list) else str(value)
    values["APP_INSIGHTS_CONNECTION_STRING"] = connection_string
    for key in EMPTY_ENV_KEYS:
        values[key] = ""
    for key in THRESHOLD_KEYS:
        values[key] = _env_first(ctx, f"AIGOV_{key}") or DEFAULT_CONTENT_SAFETY_THRESHOLD
    values["DEMO_RUN"] = uuid.uuid4().hex[:8]

    conflicts = sorted(k for k, v in values.items() if k in ctx.env and ctx.env[k] != v)
    if conflicts:
        raise AutomationError(
            "Inherited environment variables would conflict with .env in headless mode: " + ", ".join(conflicts)
        )
    body = f"# Private file written by lab_session.py write-env for session {session_id}. Never commit or upload.\n"
    body += "".join(f"{key}={value}\n" for key, value in values.items())
    common.write_private_text(ctx.env_path, body)
    ctx.validate_env(ctx.env_path)
    ctx.say(f"write-env: wrote {len(values)} keys to .env (secret values masked) and validated headless load_config()")
    return 0


# ---------------------------------------------------------------------------
# readiness and probe-scopes
# ---------------------------------------------------------------------------


def _lab_env(ctx: Context) -> Dict[str, str]:
    values = common.read_env_file(ctx.env_path)
    required = ("AZURE_SUBSCRIPTION_ID", "APIM_RESOURCE_GROUP", "APIM_NAME", "APIM_GATEWAY_URL",
                "PLATFORM_API_PATH", "PLATFORM_API_ID", "AOAI_DEPLOYMENT", "APP_INSIGHTS_RESOURCE_ID",
                "TEAM_SUBSCRIPTION_IDS")
    missing = [k for k in required if not values.get(k)]
    if missing:
        raise AutomationError(f".env lacks {', '.join(missing)}; run write-env first.")
    return values


def _inference_url(values: Mapping[str, str]) -> str:
    return f"{values['APIM_GATEWAY_URL'].rstrip('/')}/{values['PLATFORM_API_PATH'].strip('/')}/v1/chat/completions"


def _probe_body(values: Mapping[str, str], text: str) -> Dict[str, Any]:
    return {
        "model": values["AOAI_DEPLOYMENT"],
        "messages": [{"role": "user", "content": text}],
        "max_tokens": PROBE_MAX_TOKENS,
        "stream": False,
    }


def _team_key(ctx: Context, values: Mapping[str, str], secrets: common.SecretRegistry, sid: str) -> str:
    data = ctx.client.list_apim_subscription_secrets(
        values["AZURE_SUBSCRIPTION_ID"], values["APIM_RESOURCE_GROUP"], values["APIM_NAME"], sid
    )
    key = secrets.register(data.get("primaryKey") or "")
    if not key:
        raise AutomationError("A subscription key could not be retrieved.")
    return key


def _guarded_post(
    ctx: Context, session_id: str, env: Mapping[str, str], label: str, url: str,
    headers: Mapping[str, str], body: Mapping[str, Any], timeout: float = 30.0,
) -> Any:
    estimate = budget.estimate_prompt_tokens(body["messages"])
    return budget.guarded_request(
        "model", estimate, body["max_tokens"],
        lambda: ctx.http_post(url, headers=headers, json_body=body, timeout=timeout),
        body=body, label=label, env=env, root=ctx.paths.budget_root,
    )


def _header(response: Any, name: str) -> Optional[str]:
    headers = getattr(response, "headers", None) or {}
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return value
    return None


def cmd_readiness(ctx: Context, args: argparse.Namespace) -> int:
    session_id = common.resolve_session(args.session_id, ctx.env)
    env = budget_env(ctx, session_id)
    values = _lab_env(ctx)
    sub, rg, apim = values["AZURE_SUBSCRIPTION_ID"], values["APIM_RESOURCE_GROUP"], values["APIM_NAME"]
    scope = common.apim_scope(sub, rg, apim)
    secrets = ctx.secrets(session_id)
    started = ctx.now()
    checks: Dict[str, Dict[str, Any]] = {}
    state: Dict[str, Any] = {}

    def gateway() -> Tuple[bool, str]:
        response = ctx.http_get(f"{values['APIM_GATEWAY_URL'].rstrip('/')}/status-0123456789abcdef", timeout=15)
        return getattr(response, "status_code", 0) == 200, f"http_{getattr(response, 'status_code', 0)}"

    def logger() -> Tuple[bool, str]:
        logger_id = values.get("PLATFORM_LOGGER_ID") or "apimlogger"
        data = ctx.client.get_resource(f"{scope}/loggers/{logger_id}", common.API_VERSIONS["apim"])
        props = data.get("properties") or {}
        if props.get("loggerType") != "applicationInsights":
            return False, "logger_type"
        if str(props.get("resourceId", "")).lower() != values["APP_INSIGHTS_RESOURCE_ID"].lower():
            return False, "logger_destination"
        return True, "ok"

    def diagnostic() -> Tuple[bool, str]:
        data = ctx.client.get_resource(f"{scope}/diagnostics/applicationinsights", common.API_VERSIONS["apim"])
        props = data.get("properties") or {}
        logger_id = values.get("PLATFORM_LOGGER_ID") or "apimlogger"
        if not str(props.get("loggerId", "")).lower().endswith(f"/loggers/{logger_id}".lower()):
            return False, "diagnostic_logger"
        if props.get("metrics") is not True:
            return False, "metrics_disabled"
        for side in ("frontend", "backend"):
            for direction in ("request", "response"):
                body = ((props.get(side) or {}).get(direction) or {}).get("body") or {}
                if int(body.get("bytes") or 0) != 0:
                    return False, "body_capture"
        return True, "ok"

    def dimensions() -> Tuple[bool, str]:
        data = ctx.client.get_resource(values["APP_INSIGHTS_RESOURCE_ID"], common.API_VERSIONS["insights"])
        opted = (data.get("properties") or {}).get("CustomMetricsOptedInType")
        return opted == "WithDimensions", "ok" if opted == "WithDimensions" else "dimensions_not_opted_in"

    def content_safety() -> Tuple[bool, str]:
        resource_id = values.get("CONTENT_SAFETY_RESOURCE_ID")
        if not resource_id:
            return False, "content_safety_unknown"
        data = ctx.client.get_resource(resource_id, common.API_VERSIONS["cognitive"])
        ok = (data.get("properties") or {}).get("provisioningState") == "Succeeded"
        return ok, "ok" if ok else "content_safety_not_ready"

    def inference() -> Tuple[bool, str]:
        if "key" not in state:
            team_subs = [s for s in values["TEAM_SUBSCRIPTION_IDS"].split(",") if s]
            state["key"] = _team_key(ctx, values, secrets, team_subs[0])
        body = _probe_body(values, "Reply with the single word: ready")
        headers = {"Ocp-Apim-Subscription-Key": state["key"], "Content-Type": "application/json",
                   "x-client-app": common.TEAM_CLIENT_APPS["team-retail"]}
        response = _guarded_post(ctx, session_id, env, "readiness.inference", _inference_url(values), headers, body)
        status = getattr(response, "status_code", 0)
        if status != 200:
            return False, f"http_{status}"
        try:
            usage = response.json().get("usage") or {}
        except ValueError:
            return False, "invalid_json"
        return (bool(usage.get("prompt_tokens")), "ok" if usage.get("prompt_tokens") else "usage_missing")

    def ingestion() -> Tuple[bool, str]:
        api_id = values["PLATFORM_API_ID"].replace("'", "")
        query = (
            "customMetrics"
            f" | where timestamp >= datetime({common.fmt_utc(started - timedelta(minutes=5))})"
            f" | where name in ('{common.PROMPT_METRIC}', '{common.COMPLETION_METRIC}')"
            f" | where tostring(customDimensions['API ID']) == '{api_id}'"
            " | summarize rows = count()"
        )
        rows = ctx.logs_query(values["APP_INSIGHTS_RESOURCE_ID"], query, started - timedelta(minutes=5), ctx.now())
        count = int((rows[0] if rows else {}).get("rows") or 0)
        return count > 0, "ok" if count > 0 else "no_metrics_yet"

    plan: List[Tuple[str, str, Callable[[], Tuple[bool, str]], float, int]] = [
        ("gateway", "apim-gateway", gateway, args.check_timeout_seconds, 0),
        ("logger", "apim-logger", logger, args.check_timeout_seconds, 0),
        ("diagnostic", "apim-diagnostic", diagnostic, args.check_timeout_seconds, 0),
        ("custom_metric_dimensions", "app-insights", dimensions, args.check_timeout_seconds, 0),
        ("content_safety_account", "content-safety", content_safety, args.check_timeout_seconds, 0),
        ("inference", "platform-api", inference, args.check_timeout_seconds, args.inference_attempts),
        ("metric_ingestion", "telemetry", ingestion, args.ingestion_timeout_seconds, 0),
    ]
    failing: Optional[Tuple[str, str]] = None
    for name, scope_label, check, timeout, max_attempts in plan:
        if failing:
            checks[name] = {"status": "not_run", "attempts": 0, "code": "skipped"}
            continue
        deadline = ctx.now() + timedelta(seconds=timeout)
        attempts, ok, code = 0, False, "not_attempted"
        while True:
            attempts += 1
            try:
                ok, code = check()
            except (budget.BudgetExceeded, budget.BudgetStateError):
                ok, code = False, "budget_refused"
                break
            except AzError as exc:
                ok, code = False, f"azure_{exc.category}"
                if exc.category == "forbidden":
                    break
            except AutomationError:
                ok, code = False, "configuration"
                break
            except Exception as exc:  # transport errors are reported by type only
                ok, code = False, f"error_{type(exc).__name__}"
            if ok or (max_attempts and attempts >= max_attempts) or ctx.now() >= deadline:
                break
            ctx.sleep(args.poll_seconds)
        checks[name] = {"status": "passed" if ok else "failed", "attempts": attempts, "code": code}
        ctx.say(f"readiness: {name}: {'passed' if ok else 'failed'} ({code}, {attempts} attempt(s))")
        if not ok:
            failing = (name, scope_label)
    summary = {
        "schema_version": 1,
        "session_id": session_id,
        "status": "failed" if failing else "passed",
        "started_at": common.fmt_utc(started),
        "completed_at": common.fmt_utc(ctx.now()),
        "checks": checks,
        "failing_check": failing[0] if failing else "",
        "scope": failing[1] if failing else "",
    }
    atomic_write_json(ctx.paths.readiness_dir(session_id) / "summary.json", summary)
    if failing:
        ctx.say(f"readiness: failed at {failing[0]} (scope {failing[1]}); permissions were not changed")
        return 1
    return 0


def cmd_probe_scopes(ctx: Context, args: argparse.Namespace) -> int:
    session_id = common.resolve_session(args.session_id, ctx.env)
    env = budget_env(ctx, session_id)
    values = _lab_env(ctx)
    sub, rg, apim = values["AZURE_SUBSCRIPTION_ID"], values["APIM_RESOURCE_GROUP"], values["APIM_NAME"]
    secrets = ctx.secrets(session_id)
    url = _inference_url(values)
    body = _probe_body(values, "Reply with the single word: probe")
    probes: Dict[str, Dict[str, Any]] = {}

    def call(label: str, key: Optional[str]) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json", "x-client-app": common.TEAM_CLIENT_APPS["team-retail"]}
        if key:
            headers["Ocp-Apim-Subscription-Key"] = key
        try:
            response = _guarded_post(ctx, session_id, env, label, url, headers, body)
        except (budget.BudgetExceeded, budget.BudgetStateError):
            return {"status": None, "outcome": "budget_refused", "product_policy_headers": False}
        except Exception as exc:  # noqa: BLE001 - reported by type only
            return {"status": None, "outcome": f"error_{type(exc).__name__}", "product_policy_headers": False}
        return {
            "status": getattr(response, "status_code", None),
            "outcome": "response",
            "product_policy_headers": _header(response, "remaining-tokens") is not None,
        }

    team_subs = [s for s in values["TEAM_SUBSCRIPTION_IDS"].split(",") if s]
    product = call("probe.product_scoped", _team_key(ctx, values, secrets, team_subs[0]))
    product["expected"] = "200 with product token-limit headers"
    product["passed"] = product["status"] == 200 and product["product_policy_headers"]
    probes["product_scoped"] = product

    probe_sid = f"aigov-probe-{session_id}"
    sub_path = (f"{common.apim_scope(sub, rg, apim)}/subscriptions/{probe_sid}"
                f"?api-version={common.API_VERSIONS['apim']}")
    api_scope = f"{common.apim_scope(sub, rg, apim)}/apis/{values['PLATFORM_API_ID']}"
    api_probe: Dict[str, Any] = {"status": None, "outcome": "not_run", "product_policy_headers": False}
    deleted = False
    try:
        ctx.client.rest("PUT", sub_path, {"properties": {
            "scope": api_scope, "displayName": "AIGov temporary API-scoped probe", "state": "active",
            "allowTracing": False,
        }})
        api_probe = call("probe.api_scoped", _team_key(ctx, values, secrets, probe_sid))
    except AzError as exc:
        api_probe["outcome"] = f"azure_{exc.category}"
    finally:
        try:
            ctx.client.rest("DELETE", sub_path)
            deleted = True
        except AzError as exc:
            deleted = exc.category == "not_found"
    api_probe["expected"] = "recorded; API-scoped keys bypass product policies"
    api_probe["bypass_observed"] = api_probe["status"] == 200 and not api_probe["product_policy_headers"]
    api_probe["temporary_subscription_deleted"] = deleted
    api_probe["passed"] = deleted and api_probe["outcome"] == "response"
    probes["api_scoped"] = api_probe

    anonymous = call("probe.anonymous", None)
    anonymous["expected"] = "401"
    anonymous["passed"] = anonymous["status"] == 401
    probes["anonymous"] = anonymous
    probes["all_access"] = {"status": None, "outcome": "not_run", "passed": True,
                            "expected": "not used; bypass documented from Microsoft guidance"}

    failed = [name for name, probe in probes.items() if not probe["passed"]]
    atomic_write_json(ctx.paths.readiness_dir(session_id) / "probes.json", {
        "schema_version": 1, "session_id": session_id, "status": "failed" if failed else "passed",
        "excluded_subscription_ids": [probe_sid], "probes": probes,
    })
    for name, probe in probes.items():
        ctx.say(f"probe-scopes: {name}: status={probe['status']} passed={probe['passed']}")
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# run-notebooks
# ---------------------------------------------------------------------------


def _normalize_notebook(name: str) -> str:
    stem = name[:-6] if name.endswith(".ipynb") else name
    stem = Path(stem).name
    if stem not in common.NOTEBOOK_STEMS:
        raise AutomationError(f"Unknown notebook {name!r}; expected one of {', '.join(common.NOTEBOOK_STEMS)}.")
    return stem


def cmd_run_notebooks(ctx: Context, args: argparse.Namespace) -> int:
    session_id = common.resolve_session(args.session_id, ctx.env)
    executed = ctx.paths.executed_dir(session_id)
    execution_file = executed / "execution.json"
    if args.init:
        if executed.exists():
            raise AutomationError("The executed-notebook directory already exists for this session; --init runs once.")
        executed.mkdir(parents=True)
        atomic_write_json(execution_file, {"schema_version": 1, "session_id": session_id,
                                           "created_at": common.fmt_utc(ctx.now()), "runs": []})
        ctx.say(f"run-notebooks: initialized {executed.relative_to(ctx.paths.outputs).as_posix()}")
        return 0
    stem = _normalize_notebook(args.only)
    if not execution_file.exists():
        raise AutomationError("execution.json is missing; run 'run-notebooks --init' first.")
    notebooks_dir = Path(args.notebooks_dir)
    source = notebooks_dir / f"{stem}.ipynb"
    source_hash = common.sha256_file(source)
    started = ctx.now()
    exit_code = ctx.papermill(source, executed / f"{stem}.ipynb", notebooks_dir,
                              ctx.paths.session_dir(session_id) / "logs" / f"{stem}.log", args.timeout_seconds)
    ended = ctx.now()
    with common.FileLock(execution_file):
        data = common.read_json(execution_file)
        if data.get("session_id") != session_id:
            raise AutomationError("execution.json belongs to another session.")
        data["runs"].append({
            "notebook": stem,
            "exit_code": int(exit_code),
            "started_at": common.fmt_utc(started),
            "ended_at": common.fmt_utc(ended),
            "source_sha256": source_hash,
        })
        atomic_write_json(execution_file, data)
    ctx.say(f"run-notebooks: {stem} exit_code={exit_code}")
    return 0 if exit_code == 0 else 1


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


def decide_auto_cleanup(mode: str, deploy_outcome: str, readiness_outcome: str, keep_environment: bool) -> Tuple[str, str]:
    """Mode-by-outcome table: return ('delete'|'keep'|'none', reason). Unknown outcomes count as failure."""
    if mode not in MODES:
        raise AutomationError(f"Unknown mode {mode!r}.")
    if mode == "full-session":
        return ("keep", "keep_environment") if keep_environment else ("delete", "full_session")
    if mode == "deploy-only":
        if deploy_outcome == "success" and readiness_outcome == "success":
            return "keep", "deploy_only_success_retained"
        return "delete", "deploy_only_failure"
    return "none", f"{mode}_never_cleans"


def _order_key(target: Mapping[str, str]) -> int:
    try:
        return common.DELETE_ORDER.index(target["type"])
    except ValueError:
        return len(common.DELETE_ORDER)


def _validate_targets(targets: Sequence[Mapping[str, str]], sub: str, rg: str) -> None:
    prefix = (common.rg_scope(sub, rg) + "/providers/").lower()
    for t in targets:
        if not t["id"].lower().startswith(prefix) or t["type"] not in common.DELETE_ORDER:
            raise AutomationError("A manifest target lies outside the lab resource group or owned types; refused.")


def _tombstones_for(ctx: Context, sub: str, targets: Sequence[Mapping[str, str]]) -> Tuple[List[Dict[str, str]], str]:
    names = {
        "apim": {t["name"] for t in targets if t["type"] == "microsoft.apimanagement/service"},
        "cognitive": {t["name"] for t in targets if t["type"] == "microsoft.cognitiveservices/accounts"},
        "workspace": {t["name"] for t in targets if t["type"] == "microsoft.operationalinsights/workspaces"},
    }
    try:
        found = _tombstone_names(ctx, sub)
    except AzError:
        return [], "failed"
    tombstones = []
    for kind, entries in found.items():
        for entry in entries:
            if entry["name"] in names[kind]:
                tombstones.append({"kind": kind, **entry})
    return tombstones, "ok"


def _delete_one(ctx: Context, target: Mapping[str, str], generation: str, retries: int, poll_seconds: float,
                timeout_seconds: float) -> Tuple[str, str]:
    api = common.TYPE_API_VERSION[target["type"]]
    try:
        current = ctx.client.get_resource(target["id"], api)
    except AzError as exc:
        return ("absent", "") if exc.category == "not_found" else ("error", exc.category)
    tags = current.get("tags") or {}
    if target["type"] in TAGGED_TYPES and (
        tags.get("aigov-owner") != "aigov-lab" or tags.get("aigov-generation") != generation
    ):
        return "error", "ownership_mismatch"
    for attempt in range(1, retries + 1):
        try:
            ctx.client.delete_resource(target["id"], api)
            break
        except AzError as exc:
            if exc.category == "not_found":
                return "absent", ""
            if exc.category in ("forbidden", "timeout") or attempt == retries:
                return "error", exc.category
            ctx.sleep(poll_seconds)
    deadline = ctx.now() + timedelta(seconds=timeout_seconds)
    while True:
        try:
            ctx.client.get_resource(target["id"], api)
        except AzError as exc:
            if exc.category == "not_found":
                return "deleted", ""
            return "error", exc.category
        if ctx.now() >= deadline:
            return "still_active", "timeout"
        ctx.sleep(poll_seconds)


def run_cleanup(
    ctx: Context,
    target: Target,
    records: Sequence[Mapping[str, Any]],
    *,
    execute: bool,
    retries: int = 3,
    poll_seconds: float = 15.0,
    timeout_seconds: float = 1800.0,
) -> Dict[str, Any]:
    """Delete (or list) owned targets from manifest records and build the residual report."""
    for record in records:
        manifest = record["manifest"]
        if manifest.get("subscription_id") != target.subscription_id or \
                str(manifest.get("resource_group", "")).lower() != target.resource_group.lower():
            raise AutomationError("Manifest subscription or resource group does not match the target.")
        if target.tenant_id and manifest.get("tenant_id") and manifest["tenant_id"] != target.tenant_id:
            raise AutomationError("Manifest tenant does not match the signed-in tenant.")
    targets = sorted(record_targets(records), key=_order_key)
    _validate_targets(targets, target.subscription_id, target.resource_group)
    report: Dict[str, Any] = {
        "schema_version": 1, "resource_group": target.resource_group, "generation": target.generation,
        "targets": [], "active": [], "failures": [], "unexpected": [], "locks": 0,
        "tombstones": [], "tombstone_discovery": "not_run",
        "next_operator": _env_first(ctx, "AIGOV_RECOVERY_OWNER") or "repository administrator",
    }
    try:
        live = ctx.client.list_rg_resources(target.subscription_id, target.resource_group)
        locks = ctx.client.list_locks(target.subscription_id, target.resource_group)
    except AzError as exc:
        if exc.category != "not_found":
            report.update(status="refused", action="refused", exposure="unknown",
                          failures=[{"type": "resourcegroup", "name": target.resource_group, "category": exc.category}])
            return report
        live, locks = [], []
    report["locks"] = len(locks)
    allowed = {t["id"].lower() for t in targets}
    unexpected = [r for r in live if str(r.get("id", "")).lower() not in allowed]
    report["unexpected"] = [{"type": common.resource_type_of(r["id"]), "name": r.get("name", "")} for r in unexpected]
    if locks or unexpected:
        report.update(status="refused", action="refused", exposure="unknown")
        return report

    for t in targets:
        entry = {"id": t["id"], "type": t["type"], "name": t["name"], "result": "", "error_category": ""}
        if not execute:
            try:
                ctx.client.get_resource(t["id"], common.TYPE_API_VERSION[t["type"]])
                entry["result"] = "would_delete"
            except AzError as exc:
                entry["result"], entry["error_category"] = (
                    ("absent", "") if exc.category == "not_found" else ("error", exc.category)
                )
        else:
            entry["result"], entry["error_category"] = _delete_one(
                ctx, t, target.generation, retries, poll_seconds, timeout_seconds
            )
        report["targets"].append(entry)
        if entry["result"] in ("error", "still_active", "would_delete"):
            report["active"].append({"type": t["type"], "name": t["name"]})
        if entry["result"] in ("error", "still_active"):
            report["failures"].append({"type": t["type"], "name": t["name"], "category": entry["error_category"]})

    report["tombstones"], report["tombstone_discovery"] = _tombstones_for(ctx, target.subscription_id, targets)
    if not execute:
        report.update(status="dry_run", action="dry_run",
                      exposure="continuing" if report["active"] else "none_known")
    elif report["failures"] or report["active"]:
        report.update(status="residual", action="deleted",
                      exposure="unknown" if any(f["category"] != "timeout" for f in report["failures"]) else "continuing")
    else:
        report.update(status="clean", action="deleted", exposure="none_known")
    model_targets = [e for e in report["targets"] if e["type"] == "microsoft.cognitiveservices/accounts/deployments"]
    report["quota_release"] = (
        "released" if model_targets and all(e["result"] in ("deleted", "absent") for e in model_targets)
        else ("not_applicable" if not model_targets else "unknown")
    )
    return report


def _kept_report(ctx: Context, target: Target, records: Sequence[Mapping[str, Any]], reason: str) -> Dict[str, Any]:
    active = []
    unknown = False
    for t in sorted(record_targets(records), key=_order_key):
        try:
            ctx.client.get_resource(t["id"], common.TYPE_API_VERSION.get(t["type"], common.API_VERSIONS["resources"]))
            active.append({"type": t["type"], "name": t["name"]})
        except AzError as exc:
            unknown = unknown or exc.category != "not_found"
    return {
        "schema_version": 1, "resource_group": target.resource_group, "generation": target.generation,
        "status": "kept", "action": "kept", "reason": reason, "targets": [], "active": active,
        "failures": [], "unexpected": [], "locks": 0, "tombstones": [], "tombstone_discovery": "not_run",
        "exposure": "unknown" if unknown else ("continuing" if active else "none_known"),
        "quota_release": "not_applicable",
        "next_operator": _env_first(ctx, "AIGOV_RECOVERY_OWNER") or "repository administrator",
    }


def _write_residual(ctx: Context, session_id: str, report: Dict[str, Any]) -> None:
    report = dict(report)
    report["session_id"] = session_id
    report["generated_at"] = common.fmt_utc(ctx.now())
    atomic_write_json(ctx.paths.residual_dir(session_id) / "report.json", report)
    ctx.say(f"cleanup: status={report['status']} action={report['action']} active={len(report.get('active', []))} "
            f"failures={len(report.get('failures', []))} tombstones={len(report.get('tombstones', []))} "
            f"exposure={report.get('exposure', 'unknown')}")


def _append_spend_record(ctx: Context, target: Target, session_id: str, records: Sequence[Mapping[str, Any]],
                         mode: str) -> str:
    try:
        totals = budget.session_totals(session_id, root=ctx.paths.budget_root)
    except budget.BudgetStateError:
        totals = {"status": "missing"}
    base = records[-1]["manifest"]
    manifest = build_manifest(
        ctx, target, record_kind="spend", session_id=session_id, mode=mode,
        inventory={"expected": base.get("expected_resources", []), "optional": base.get("optional_resources", [])},
        extra={"observed_resources": record_targets(records), "spent_totals": totals},
    )
    try:
        return persist_record(ctx, manifest)
    except (AzError, AutomationError) as exc:
        ctx.say(f"cleanup: spend record could not be written ({type(exc).__name__})")
        return ""


def cmd_cleanup(ctx: Context, args: argparse.Namespace) -> int:
    if args.auto:
        return _cleanup_auto(ctx, args)
    if args.execute and not args.confirm_resource_group:
        raise AutomationError("cleanup --execute requires --confirm-resource-group.")
    target = resolve_target(ctx, args, need_suffix=False)
    session_id = common.resolve_session(args.session_id or _env_first(ctx, "SESSION_ID")
                                        or f"teardown{ctx.now().strftime('%Y%m%d%H%M%S')}", ctx.env)
    if args.manifest_file:
        records = [load_record_file(Path(args.manifest_file), target)]
    else:
        records, invalid = load_records(ctx, target)
        if invalid:
            ctx.say(f"cleanup: ignored {invalid} record(s) that failed hash or target validation")
    if not records:
        raise AutomationError(f"No valid manifest record for generation {target.generation}; nothing is inventoried.")
    report = run_cleanup(ctx, target, records, execute=args.execute, retries=args.retries,
                         poll_seconds=args.poll_seconds, timeout_seconds=args.timeout_seconds)
    report["mode"] = "teardown"
    _write_residual(ctx, session_id, report)
    return 0 if report["status"] in ("clean", "dry_run") else 1


def _cleanup_auto(ctx: Context, args: argparse.Namespace) -> int:
    mode = args.mode
    action, reason = decide_auto_cleanup(
        mode,
        (ctx.env.get("DEPLOY_OUTCOME") or "").strip().lower(),
        (ctx.env.get("READINESS_OUTCOME") or "").strip().lower(),
        common.truthy(ctx.env.get("KEEP_ENVIRONMENT")),
    )
    session_id = (args.session_id or ctx.env.get("SESSION_ID") or "").strip()
    if action == "none":
        ctx.say(f"cleanup: mode {mode} never deletes ({reason}); no action")
        if session_id:
            _write_residual(ctx, common.resolve_session(session_id, ctx.env), {
                "schema_version": 1, "mode": mode, "status": "no_op", "action": "none", "reason": reason,
                "active": [], "failures": [], "tombstones": [], "exposure": "not_assessed",
            })
        return 0
    session_id = common.resolve_session(session_id, ctx.env)
    target = resolve_target(ctx, args, need_suffix=False)
    records, _ = load_records(ctx, target, session_id=session_id)
    if not records:
        _write_residual(ctx, session_id, {
            "schema_version": 1, "mode": mode, "status": "no_op", "action": "none",
            "reason": "no_records_created_by_this_session", "active": [], "failures": [], "tombstones": [],
            "exposure": "not_assessed", "resource_group": target.resource_group, "generation": target.generation,
        })
        return 0
    if action == "keep":
        report = _kept_report(ctx, target, records, reason)
    else:
        report = run_cleanup(ctx, target, records, execute=True, retries=args.retries,
                             poll_seconds=args.poll_seconds, timeout_seconds=args.timeout_seconds)
        report["reason"] = reason
    report["mode"] = mode
    report["spend_record"] = _append_spend_record(ctx, target, session_id, records, mode) or "failed"
    _write_residual(ctx, session_id, report)
    return 0 if report["status"] in ("clean", "kept") else 1


# ---------------------------------------------------------------------------
# purge (human operator only, DD-02)
# ---------------------------------------------------------------------------


def cmd_purge(ctx: Context, args: argparse.Namespace) -> int:
    if common.in_github_actions(ctx.env):
        raise AutomationError("purge is human-operator only and refuses to run in GitHub Actions.")
    target = resolve_target(ctx, args, need_suffix=False)
    if args.execute and args.confirm_resource_group != target.resource_group:
        raise AutomationError("purge --execute requires --confirm-resource-group matching the target.")
    records, _ = load_records(ctx, target)
    if not records:
        raise AutomationError("No valid manifest record inventories tombstones for this generation.")
    targets = record_targets(records)
    tombstones, discovery = _tombstones_for(ctx, target.subscription_id, targets)
    if discovery != "ok":
        raise AutomationError("Tombstones could not be listed.")
    prompt = ctx.prompt
    if prompt is None:
        if not sys.stdin.isatty():
            raise AutomationError("purge requires an interactive terminal for typed confirmation.")
        prompt = input
    purged, skipped = 0, 0
    for tomb in tombstones:
        ctx.say(f"purge: tombstone {tomb['kind']} {tomb['name']} ({tomb['location']}) "
                f"scheduled purge {tomb['scheduled_purge'] or 'unknown'}")
        if tomb["kind"] == "workspace":
            ctx.say("purge: Log Analytics workspaces are never force-deleted here; they expire after 14 days.")
            skipped += 1
            continue
        if not args.execute:
            continue
        typed = prompt(f"Type the exact name to permanently purge {tomb['name']}: ")
        if typed != tomb["name"]:
            ctx.say(f"purge: confirmation mismatch; {tomb['name']} skipped")
            skipped += 1
            continue
        location = common.normalize_region(tomb["location"])
        if tomb["kind"] == "apim":
            path = (f"/subscriptions/{target.subscription_id}/providers/Microsoft.ApiManagement/locations/"
                    f"{location}/deletedservices/{tomb['name']}?api-version={common.API_VERSIONS['apim']}")
        else:
            path = (f"/subscriptions/{target.subscription_id}/providers/Microsoft.CognitiveServices/locations/"
                    f"{location}/resourceGroups/{target.resource_group}/deletedAccounts/{tomb['name']}"
                    f"?api-version={common.API_VERSIONS['cognitive']}")
        ctx.client.rest("DELETE", path)
        purged += 1
        ctx.say(f"purge: requested permanent purge of {tomb['name']}")
    if not args.execute:
        ctx.say("purge: listing only; rerun with --execute --confirm-resource-group <rg> to purge.")
    ctx.say(f"purge: {purged} purged, {skipped} skipped, {len(tombstones)} inventoried tombstone(s)")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _add_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--resource-group", help="Lab resource group (default AIGOV_LAB_RESOURCE_GROUP).")
    parser.add_argument("--generation", help="Ownership generation (default AIGOV_GENERATION).")
    parser.add_argument("--subscription-id", help="Approved subscription (default AZURE_SUBSCRIPTION_ID or az account).")


def _add_session_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session-id", help="Session ID (default SESSION_ID from the environment).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lab_session.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--outputs-root", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-session", help="Create SESSION_ID, deadline, budget state, and the private session file.")
    p.add_argument("--run-id", help="Workflow run ID (default GITHUB_RUN_ID).")
    p.add_argument("--run-attempt", help="Workflow run attempt (default GITHUB_RUN_ATTEMPT); attempts > 2 are refused.")
    p.add_argument("--job-start-utc", help="Job start in UTC (default now).")
    p.add_argument("--job-timeout-minutes", type=int, default=300)
    p.add_argument("--cleanup-login-minutes", type=int, default=5)
    p.add_argument("--cleanup-minutes", type=int, default=45)
    p.add_argument("--post-sanitize-minutes", type=int, default=5)
    p.add_argument("--upload-minutes", type=int, default=5)
    p.add_argument("--margin-minutes", type=int, default=10)
    p.add_argument("--max-attempts", type=int, help="Session attempt cap (default: envelope + automation allowance).")
    p.add_argument("--max-reserved-tokens", type=int, help="Session token cap (default: envelope + automation allowance).")
    p.add_argument("--max-estimated-usd", type=float, default=DEFAULT_MAX_ESTIMATED_USD)
    p.add_argument("--price-snapshot", help="Approved price snapshot JSON (scripts/prices/<snapshot>.json).")
    p.add_argument("--require-price", action="store_true", help="Refuse to start without a matching price.")
    p.set_defaults(func=cmd_init_session)

    p = sub.add_parser("preflight", help="Read-only checks: model tuple, providers, quota, Content Safety, tombstones.")
    p.add_argument("--params", default=str(PARAMS))
    _add_target_args(p)
    _add_session_arg(p)
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("what-if", help="Run RG what-if and refuse deletes or changes outside planned resources.")
    p.add_argument("--template", default=str(TEMPLATE))
    p.add_argument("--params", default=str(PARAMS))
    _add_target_args(p)
    _add_session_arg(p)
    p.set_defaults(func=cmd_what_if)

    p = sub.add_parser("manifest", help="Create or verify append-only manifest records.")
    msub = p.add_subparsers(dest="manifest_command", required=True)
    m = msub.add_parser("create", help="Persist the expected-target manifest before mutation (full-session, deploy-only).")
    m.add_argument("--mode", required=True, choices=MODES)
    _add_target_args(m)
    _add_session_arg(m)
    m.set_defaults(func=cmd_manifest_create)
    m = msub.add_parser("verify", help="Hash-check the newest record and confirm live resources (run-existing, report-only).")
    m.add_argument("--mode", required=True, choices=MODES)
    _add_target_args(m)
    _add_session_arg(m)
    m.set_defaults(func=cmd_manifest_verify)

    p = sub.add_parser("deploy", help="Incremental deployment of infra/main.bicep; records every attempt.")
    p.add_argument("--template", default=str(TEMPLATE))
    p.add_argument("--params", default=str(PARAMS))
    _add_target_args(p)
    _add_session_arg(p)
    p.set_defaults(func=cmd_deploy)

    p = sub.add_parser("write-env", help="Write the private root .env from deployment outputs and validate it headless.")
    _add_session_arg(p)
    p.set_defaults(func=cmd_write_env)

    p = sub.add_parser("readiness", help="Bounded readiness polls; inference goes through guarded_request.")
    p.add_argument("--check-timeout-seconds", type=float, default=300.0)
    p.add_argument("--ingestion-timeout-seconds", type=float, default=600.0)
    p.add_argument("--poll-seconds", type=float, default=15.0)
    p.add_argument("--inference-attempts", type=int, default=READINESS_ATTEMPTS)
    _add_session_arg(p)
    p.set_defaults(func=cmd_readiness)

    p = sub.add_parser("probe-scopes", help="Record product, temporary API-scoped, and anonymous access behavior.")
    _add_session_arg(p)
    p.set_defaults(func=cmd_probe_scopes)

    p = sub.add_parser("run-notebooks", help="--init once, then --only <notebook> per step (papermill, no --log-output).")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", action="store_true")
    group.add_argument("--only", metavar="NOTEBOOK")
    p.add_argument("--notebooks-dir", default=str(common.REPO_ROOT / "notebooks"))
    p.add_argument("--timeout-seconds", type=float, default=2400.0)
    _add_session_arg(p)
    p.set_defaults(func=cmd_run_notebooks)

    p = sub.add_parser("cleanup", help="Manifest-scoped deletion: --dry-run/--execute, or --auto --mode <mode>.")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--execute", action="store_true")
    group.add_argument("--auto", action="store_true",
                       help="Workflow entry: reads DEPLOY_OUTCOME, READINESS_OUTCOME, KEEP_ENVIRONMENT, SESSION_ID.")
    p.add_argument("--mode", choices=MODES, help="Required with --auto.")
    p.add_argument("--confirm-resource-group")
    p.add_argument("--manifest-file", help="Recovery: use a workflow-artifact manifest backup instead of ARM records.")
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--poll-seconds", type=float, default=15.0)
    p.add_argument("--timeout-seconds", type=float, default=1800.0)
    _add_target_args(p)
    _add_session_arg(p)
    p.set_defaults(func=cmd_cleanup)

    p = sub.add_parser(
        "purge", help="Human-operator only: typed-confirmation purge of inventoried tombstones.",
        description="Human-operator only; refuses to run in GitHub Actions. Lists the soft-deleted APIM and "
                    "Cognitive Services tombstones recorded in this generation's manifest records. With --execute, "
                    "purges each one only after its exact name is typed; anything not inventoried is never "
                    "touched, and Log Analytics workspaces are left to expire after 14 days.",
    )
    p.add_argument("--execute", action="store_true", help="Purge after typed confirmation (default: list only).")
    p.add_argument("--confirm-resource-group", help="Required with --execute; must equal the lab resource group.")
    _add_target_args(p)
    p.set_defaults(func=cmd_purge)
    return parser


def main(argv: Optional[Sequence[str]] = None, ctx: Optional[Context] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ctx = ctx or Context()
    if args.outputs_root:
        ctx.paths = common.Paths.default(Path(args.outputs_root))
    if args.command == "cleanup" and args.auto and not args.mode:
        parser.error("cleanup --auto requires --mode")
    try:
        return args.func(ctx, args)
    except AzError as exc:
        ctx.say(f"{args.command}: Azure call failed ({exc.category}{': ' + exc.code if exc.code else ''})")
        return 1
    except AutomationError as exc:
        ctx.say(f"{args.command}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
