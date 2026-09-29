"""Shared helpers for the lab automation scripts.

Everything that touches Azure goes through :class:`ArmClient`, whose
``rest``/``deploy_bicep``/``what_if``/``account`` methods are the only
transport. :class:`AzCliArmClient` implements them with the ``az`` CLI
(list arguments, no shell); tests subclass :class:`ArmClient` with a stub.
Secrets are registered with :class:`SecretRegistry`, which emits GitHub
``::add-mask::`` commands and keeps only SHA-256 hashes for the sanitizer.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, TextIO

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.results import atomic_write_json, validate_session_id  # noqa: E402

ARM_ENDPOINT = "https://management.azure.com"
TEAMS = ("team-retail", "team-finance", "team-hr")
TEAM_CLIENT_APPS = {"team-retail": "retail-web", "team-finance": "finance-batch", "team-hr": "hr-assistant"}
NOTEBOOK_STEMS = (
    "00-setup-and-validation",
    "demo1-token-limits",
    "demo2-token-metrics",
    "demo3-content-safety",
    "demo4-resilient-pool",
)
SHOWBACK_LABEL = "Estimated model-token showback (USD retail)"
PROMPT_METRIC = "Prompt Tokens"
COMPLETION_METRIC = "Completion Tokens"

API_VERSIONS = {
    "deployments": "2024-03-01",
    "resources": "2021-04-01",
    "locks": "2020-05-01",
    "providers": "2021-04-01",
    "apim": "2024-05-01",
    "cognitive": "2024-10-01",
    "insights": "2020-02-02",
    "workspaces": "2023-09-01",
}
# Resource types owned by one generation, in deletion order (model deployments first).
DELETE_ORDER = (
    "microsoft.cognitiveservices/accounts/deployments",
    "microsoft.apimanagement/service",
    "microsoft.cognitiveservices/accounts",
    "microsoft.alertsmanagement/smartdetectoralertrules",
    "microsoft.insights/actiongroups",
    "microsoft.insights/components",
    "microsoft.operationalinsights/workspaces",
)
TYPE_API_VERSION = {
    "microsoft.cognitiveservices/accounts/deployments": API_VERSIONS["cognitive"],
    "microsoft.apimanagement/service": API_VERSIONS["apim"],
    "microsoft.cognitiveservices/accounts": API_VERSIONS["cognitive"],
    "microsoft.alertsmanagement/smartdetectoralertrules": "2021-04-01",
    "microsoft.insights/actiongroups": "2023-01-01",
    "microsoft.insights/components": API_VERSIONS["insights"],
    "microsoft.operationalinsights/workspaces": API_VERSIONS["workspaces"],
}

SECRET_ENV_KEYS = ("AOAI_KEY", "CONTENT_SAFETY_KEY", "APP_INSIGHTS_CONNECTION_STRING")


class AutomationError(RuntimeError):
    """A refusal or failure that the CLI reports with a nonzero exit code."""


# ---------------------------------------------------------------------------
# Time and hashing
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fmt_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str, name: str = "timestamp") -> datetime:
    """Parse an ISO 8601 timestamp that must carry an explicit UTC offset."""
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise AutomationError(f"{name} must be an ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise AutomationError(f"{name} must be in UTC (suffix 'Z' or '+00:00').")
    return parsed.astimezone(timezone.utc)


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Unsupported JSON type {type(value).__name__}")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes"}


def in_github_actions(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return (env.get("GITHUB_ACTIONS") or "").strip().lower() == "true"


# ---------------------------------------------------------------------------
# Output layout
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Paths:
    outputs: Path

    @classmethod
    def default(cls, outputs: Optional[Path] = None) -> "Paths":
        return cls(Path(outputs) if outputs else REPO_ROOT / "outputs")

    def _sub(self, area: str, session_id: str) -> Path:
        return self.outputs / area / validate_session_id(session_id)

    @property
    def budget_root(self) -> Path:
        return self.outputs / "session"

    @property
    def results_root(self) -> Path:
        return self.outputs / "results"

    def session_dir(self, session_id: str) -> Path:
        return self._sub("session", session_id)

    def session_env(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.env"

    def secret_hashes(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "secret-hashes.jsonl"

    def manifest_dir(self, session_id: str) -> Path:
        return self._sub("manifest", session_id)

    def whatif_dir(self, session_id: str) -> Path:
        return self._sub("whatif", session_id)

    def readiness_dir(self, session_id: str) -> Path:
        return self._sub("readiness", session_id)

    def executed_dir(self, session_id: str) -> Path:
        return self._sub("executed", session_id)

    def results_dir(self, session_id: str) -> Path:
        return self._sub("results", session_id)

    def showback_dir(self, session_id: str) -> Path:
        return self._sub("showback", session_id)

    def residual_dir(self, session_id: str) -> Path:
        return self._sub("residual", session_id)

    def evidence_dir(self, session_id: str) -> Path:
        return self._sub("evidence", session_id)


def resolve_session(arg_value: Optional[str], env: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if env is None else env
    session_id = (arg_value or env.get("SESSION_ID") or "").strip()
    if not session_id:
        raise AutomationError("SESSION_ID is required (pass --session-id or run init-session first).")
    return validate_session_id(session_id)


SESSION_KEYS = (
    "AIGOV_HEADLESS",
    "SESSION_ID",
    "SESSION_MAX_ATTEMPTS",
    "SESSION_MAX_RESERVED_TOKENS",
    "SESSION_MAX_ESTIMATED_USD",
    "SESSION_DEADLINE_UTC",
)


def session_budget_env(
    paths: "Paths", session_id: str, base_env: Optional[Mapping[str, str]] = None
) -> Dict[str, str]:
    """Environment view for ``guarded_request``: process env overlaid with the private session keys."""
    session_file = paths.session_env(session_id)
    if not session_file.exists():
        raise AutomationError("Session file is missing; run init-session first.")
    merged = dict(os.environ if base_env is None else base_env)
    merged.update({k: v for k, v in read_env_file(session_file).items() if k in SESSION_KEYS})
    if truthy(merged.get("AIGOV_HEADLESS")):
        # shared.config.is_headless() reads the process environment.
        os.environ["AIGOV_HEADLESS"] = "1"
    return merged


def read_env_file(path: Path) -> Dict[str, str]:
    """Read KEY=VALUE lines without expanding or printing values."""
    values: Dict[str, str] = {}
    path = Path(path)
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_private_text(path: Path, text: str) -> None:
    """Atomically write a private file (mode 600 where supported)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                # Windows: a scanner can hold the destination briefly.
                if attempt == 19:
                    raise
                time.sleep(0.01 * (attempt + 1))
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


class FileLock:
    """Exclusive O_EXCL lock file used for read-modify-write of small JSON files."""

    def __init__(self, target: Path, timeout: float = 30.0) -> None:
        self.path = Path(target).with_name(Path(target).name + ".lock")
        self.timeout = timeout

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise AutomationError(f"Timed out waiting for lock {self.path.name}.") from None
                time.sleep(0.05)

    def __exit__(self, *exc: Any) -> None:
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Secret masking
# ---------------------------------------------------------------------------


class SecretRegistry:
    """Register secrets as soon as they are retrieved.

    In GitHub Actions the value is announced with ``::add-mask::`` before any
    other output. Only ``{length, sha256}`` pairs are persisted, so the
    sanitizer can find known values without storing them.
    """

    MIN_LENGTH = 8

    def __init__(
        self,
        hash_file: Optional[Path] = None,
        *,
        env: Optional[Mapping[str, str]] = None,
        stream: Optional[TextIO] = None,
    ) -> None:
        self.hash_file = Path(hash_file) if hash_file else None
        self.env = os.environ if env is None else env
        self.stream = stream
        self._seen: set = set()

    def register(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return value
        if value not in self._seen:
            self._seen.add(value)
            if in_github_actions(self.env):
                stream = self.stream or sys.stdout
                for line in str(value).splitlines() or [str(value)]:
                    if line:
                        stream.write(f"::add-mask::{line}\n")
                stream.flush()
            if self.hash_file and len(value) >= self.MIN_LENGTH:
                self.hash_file.parent.mkdir(parents=True, exist_ok=True)
                with self.hash_file.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"length": len(value), "sha256": sha256_text(value)}) + "\n")
        return value


# ---------------------------------------------------------------------------
# Pattern scanning shared by the sanitizer and renderer
# ---------------------------------------------------------------------------

CREDENTIAL_PATTERNS = {
    "guid": re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    "long_hex": re.compile(r"\b[0-9a-fA-F]{32,}\b"),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_\-]{5,}\.eyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]*"),
    "bearer": re.compile(r"\bbearer\s+[A-Za-z0-9._~+/\-]{10,}=*", re.IGNORECASE),
    "instrumentation_key": re.compile(r"InstrumentationKey=", re.IGNORECASE),
    "account_key": re.compile(r"AccountKey=", re.IGNORECASE),
    "shared_access_key": re.compile(r"SharedAccessKey=", re.IGNORECASE),
    "sas_signature": re.compile(r"\bsig=", re.IGNORECASE),
    "long_token": re.compile(r"(?<![A-Za-z0-9+/_\-])[A-Za-z0-9+/_\-]{40,}={0,2}(?![A-Za-z0-9+/_\-])"),
}


def scan_patterns(text: str) -> List[str]:
    """Return the names of credential patterns found in ``text`` (never the match)."""
    return sorted(name for name, pattern in CREDENTIAL_PATTERNS.items() if pattern.search(text))


def load_known_hashes(paths: Iterable[Path]) -> List[Dict[str, Any]]:
    known: List[Dict[str, Any]] = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                known.append({"length": int(entry["length"]), "sha256": str(entry["sha256"])})
    return known


def known_value_hits(text: str, known: Sequence[Mapping[str, Any]]) -> int:
    """Count known secrets present in ``text`` by hashing same-length windows."""
    by_length: Dict[int, set] = {}
    for entry in known:
        by_length.setdefault(int(entry["length"]), set()).add(entry["sha256"])
    hits = 0
    for length, digests in by_length.items():
        if length <= 0 or length > len(text):
            continue
        for start in range(0, len(text) - length + 1):
            if sha256_text(text[start:start + length]) in digests:
                hits += 1
                break
    return hits


def hashes_for_values(values: Iterable[str]) -> List[Dict[str, Any]]:
    return [
        {"length": len(value), "sha256": sha256_text(value)}
        for value in values
        if value and len(value) >= SecretRegistry.MIN_LENGTH
    ]


# ---------------------------------------------------------------------------
# Pricing (shared by init-session and the showback report)
# ---------------------------------------------------------------------------

PRICE_UNITS = {"per_million_tokens": Decimal(1), "per_thousand_tokens": Decimal(1000)}
PRICE_METERS = ("input", "output")


class PriceError(AutomationError):
    def __init__(self, coverage: str, message: str) -> None:
        super().__init__(message)
        self.coverage = coverage


def normalize_region(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def load_price_snapshot(path: Path) -> Dict[str, Any]:
    snapshot = read_json(path)
    for key in ("snapshot_id", "currency", "records"):
        if key not in snapshot:
            raise PriceError("invalid", f"Price snapshot lacks '{key}'.")
    if not isinstance(snapshot["records"], list):
        raise PriceError("invalid", "Price snapshot 'records' must be a list.")
    return snapshot


def select_prices(
    snapshot: Mapping[str, Any],
    *,
    model: str,
    version: str,
    sku: str,
    region: str,
    at: datetime,
    currency: str = "USD",
) -> Dict[str, Any]:
    """Return exactly one per-million USD rate per meter, or raise PriceError.

    ``coverage`` on the error is ``missing`` or ``duplicate`` so callers can
    suppress totals instead of converting unknown prices to zero.
    """
    rates: Dict[str, Decimal] = {}
    for meter in PRICE_METERS:
        matches = []
        for record in snapshot.get("records", []):
            if (
                record.get("meter") == meter
                and record.get("model") == model
                and record.get("version") == version
                and str(record.get("sku", "")).lower() == str(sku).lower()
                and normalize_region(record.get("region", "")) == normalize_region(region)
                and record.get("currency") == currency
                and _effective(record, at)
            ):
                matches.append(record)
        if not matches:
            raise PriceError("missing", f"No {meter} price for {model} {version} {sku} {region}.")
        if len(matches) > 1:
            raise PriceError("duplicate", f"Ambiguous {meter} price: {len(matches)} matching records.")
        record = matches[0]
        unit = record.get("unit")
        if unit not in PRICE_UNITS:
            raise PriceError("invalid", f"Unsupported price unit {unit!r}.")
        price = record.get("unit_price")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0:
            raise PriceError("invalid", f"Invalid {meter} unit_price.")
        rates[meter] = Decimal(str(price)) * PRICE_UNITS[unit]
    return {
        "snapshot_id": str(snapshot["snapshot_id"]),
        "currency": currency,
        "input_usd_per_million": rates["input"],
        "output_usd_per_million": rates["output"],
    }


def _effective(record: Mapping[str, Any], at: datetime) -> bool:
    start = record.get("effective_from")
    end = record.get("effective_to")
    if not start:
        return False
    if at < parse_utc(start, "effective_from"):
        return False
    return end is None or at < parse_utc(end, "effective_to")


def price_usage(prompt_tokens: int, completion_tokens: int, prices: Mapping[str, Any]) -> Decimal:
    """Uncached retail identity: prompt x input rate + completion x output rate.

    Cached prompt tokens are a subset of prompt tokens and are never added on
    top; cache discounts are excluded from this estimate.
    """
    return (
        Decimal(int(prompt_tokens)) * Decimal(prices["input_usd_per_million"])
        + Decimal(int(completion_tokens)) * Decimal(prices["output_usd_per_million"])
    ) / Decimal(1_000_000)


# ---------------------------------------------------------------------------
# Azure Resource Manager client
# ---------------------------------------------------------------------------

_NOT_FOUND = re.compile(r"\b404\b|NotFound|Not Found|ResourceGroupNotFound|DeploymentNotFound", re.IGNORECASE)
_FORBIDDEN = re.compile(r"\b403\b|Forbidden|AuthorizationFailed|LinkedAuthorizationFailed", re.IGNORECASE)
_CONFLICT = re.compile(r"\b409\b|Conflict", re.IGNORECASE)
_THROTTLED = re.compile(r"\b429\b|TooManyRequests|Throttl", re.IGNORECASE)
_ERROR_CODE = re.compile(r"\(([A-Za-z][A-Za-z0-9]{2,60})\)")


class AzError(AutomationError):
    """An Azure call failed; ``category`` is not_found, forbidden, conflict, throttled, timeout, or other."""

    def __init__(self, category: str, code: str = "", message: str = "") -> None:
        super().__init__(message or f"Azure call failed ({category}{': ' + code if code else ''}).")
        self.category = category
        self.code = code

    @classmethod
    def from_output(cls, text: str) -> "AzError":
        text = text or ""
        match = _ERROR_CODE.search(text)
        code = match.group(1) if match else ""
        for category, pattern in (
            ("not_found", _NOT_FOUND),
            ("forbidden", _FORBIDDEN),
            ("conflict", _CONFLICT),
            ("throttled", _THROTTLED),
        ):
            if pattern.search(text):
                return cls(category, code)
        return cls("other", code)


RECORD_TEMPLATE = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    "contentVersion": "1.0.0.0",
    "parameters": {
        "manifest": {"type": "object"},
        "contentSha256": {"type": "string"},
    },
    "resources": [],
    "outputs": {
        "manifest": {"type": "object", "value": "[parameters('manifest')]"},
        "contentSha256": {"type": "string", "value": "[parameters('contentSha256')]"},
    },
}


def rg_scope(subscription_id: str, resource_group: str) -> str:
    return f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"


def apim_scope(subscription_id: str, resource_group: str, apim_name: str) -> str:
    return f"{rg_scope(subscription_id, resource_group)}/providers/Microsoft.ApiManagement/service/{apim_name}"


def resource_type_of(resource_id: str) -> str:
    """Return the lowercase provider type of an ARM resource ID, including child types."""
    parts = [p for p in resource_id.split("/") if p]
    lowered = [p.lower() for p in parts]
    if "providers" not in lowered:
        return ""
    index = len(lowered) - 1 - lowered[::-1].index("providers")
    tail = parts[index + 1:]
    namespace, rest = tail[0], tail[1:]
    types = [rest[i] for i in range(0, len(rest), 2)]
    return "/".join([namespace] + types).lower()


class ArmClient:
    """High-level ARM operations built on four transport primitives."""

    poll_interval_seconds = 5.0

    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self.sleep = sleep

    # -- transport primitives (overridden by the az implementation and test stubs)
    def rest(self, method: str, path: str, body: Optional[Mapping[str, Any]] = None) -> Any:
        raise NotImplementedError

    def account(self) -> Dict[str, str]:
        raise NotImplementedError

    def deploy_bicep(self, resource_group: str, name: str, template: Path, parameters: Path) -> Dict[str, Any]:
        raise NotImplementedError

    def what_if(self, resource_group: str, template: Path, parameters: Path) -> List[Dict[str, Any]]:
        raise NotImplementedError

    # -- helpers
    def get_all(self, path: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        response = self.rest("GET", path) or {}
        items.extend(response.get("value", []))
        next_link = response.get("nextLink")
        guard = 0
        while next_link and guard < 100:
            response = self.rest("GET", next_link) or {}
            items.extend(response.get("value", []))
            next_link = response.get("nextLink")
            guard += 1
        return items

    def list_rg_resources(self, subscription_id: str, resource_group: str) -> List[Dict[str, Any]]:
        path = f"{rg_scope(subscription_id, resource_group)}/resources?api-version={API_VERSIONS['resources']}"
        return self.get_all(path)

    def list_locks(self, subscription_id: str, resource_group: str) -> List[Dict[str, Any]]:
        path = (
            f"{rg_scope(subscription_id, resource_group)}/providers/Microsoft.Authorization/locks"
            f"?api-version={API_VERSIONS['locks']}"
        )
        return self.get_all(path)

    def get_resource(self, resource_id: str, api_version: str) -> Dict[str, Any]:
        return self.rest("GET", f"{resource_id}?api-version={api_version}") or {}

    def delete_resource(self, resource_id: str, api_version: str) -> None:
        self.rest("DELETE", f"{resource_id}?api-version={api_version}")

    def _deployments_path(self, subscription_id: str, resource_group: str, name: str = "") -> str:
        suffix = f"/{name}" if name else ""
        return (
            f"{rg_scope(subscription_id, resource_group)}/providers/Microsoft.Resources/deployments{suffix}"
            f"?api-version={API_VERSIONS['deployments']}"
        )

    def list_deployments(self, subscription_id: str, resource_group: str) -> List[Dict[str, Any]]:
        return self.get_all(self._deployments_path(subscription_id, resource_group))

    def get_deployment(self, subscription_id: str, resource_group: str, name: str) -> Dict[str, Any]:
        return self.rest("GET", self._deployments_path(subscription_id, resource_group, name)) or {}

    def delete_deployment(self, subscription_id: str, resource_group: str, name: str) -> None:
        self.rest("DELETE", self._deployments_path(subscription_id, resource_group, name))

    def put_record_deployment(
        self,
        subscription_id: str,
        resource_group: str,
        name: str,
        manifest: Mapping[str, Any],
        content_sha256: str,
        timeout_seconds: float = 300.0,
    ) -> None:
        """Create an append-only record: empty template, Incremental mode pinned, never overwritten."""
        try:
            self.get_deployment(subscription_id, resource_group, name)
        except AzError as exc:
            if exc.category != "not_found":
                raise
        else:
            raise AutomationError(f"Manifest record {name} already exists; records are never overwritten.")
        body = {
            "properties": {
                "mode": "Incremental",
                "template": RECORD_TEMPLATE,
                "parameters": {
                    "manifest": {"value": manifest},
                    "contentSha256": {"value": content_sha256},
                },
            }
        }
        self.rest("PUT", self._deployments_path(subscription_id, resource_group, name), body)
        deadline = time.monotonic() + timeout_seconds
        while True:
            state = (self.get_deployment(subscription_id, resource_group, name).get("properties") or {}).get(
                "provisioningState"
            )
            if state == "Succeeded":
                return
            if state in ("Failed", "Canceled"):
                raise AutomationError(f"Manifest record {name} ended in state {state}.")
            if time.monotonic() > deadline:
                raise AutomationError(f"Timed out waiting for manifest record {name}.")
            self.sleep(self.poll_interval_seconds)

    def list_apim_subscription_secrets(
        self, subscription_id: str, resource_group: str, apim_name: str, sid: str
    ) -> Dict[str, Any]:
        path = (
            f"{apim_scope(subscription_id, resource_group, apim_name)}/subscriptions/{sid}/listSecrets"
            f"?api-version={API_VERSIONS['apim']}"
        )
        return self.rest("POST", path) or {}


class AzCliArmClient(ArmClient):
    """ARM transport using the Azure CLI through ``subprocess`` with list arguments."""

    def __init__(self, timeout_seconds: float = 600.0, sleep: Callable[[float], None] = time.sleep) -> None:
        super().__init__(sleep=sleep)
        self.timeout_seconds = timeout_seconds
        self._az = shutil.which("az")
        self._az_prefix: List[str] = [self._az] if self._az else []
        if self._az and os.name == "nt":
            # az.cmd routes arguments through cmd.exe, which mangles '&' and '%' in nextLink URLs.
            bundled = Path(self._az).resolve().parent.parent / "python.exe"
            if bundled.is_file():
                self._az_prefix = [str(bundled), "-IBm", "azure.cli"]

    def _run(self, args: Sequence[str], timeout: Optional[float] = None) -> Any:
        if not self._az:
            raise AutomationError("Azure CLI 'az' was not found on PATH.")
        try:
            proc = subprocess.run(
                [*self._az_prefix, *args, "--only-show-errors", "--output", "json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout_seconds,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise AzError("timeout") from None
        if proc.returncode != 0:
            raise AzError.from_output(proc.stderr)
        text = (proc.stdout or "").strip()
        return json.loads(text) if text else None

    def rest(self, method: str, path: str, body: Optional[Mapping[str, Any]] = None) -> Any:
        url = path if path.startswith("https://") else ARM_ENDPOINT + path
        args = ["rest", "--method", method.lower(), "--url", url]
        if body is None:
            return self._run(args)
        fd, body_path = tempfile.mkstemp(prefix="aigov-body-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(body, handle)
            return self._run(args + ["--headers", "Content-Type=application/json", "--body", f"@{body_path}"])
        finally:
            os.remove(body_path)

    def account(self) -> Dict[str, str]:
        data = self._run(["account", "show"]) or {}
        return {"tenant_id": data.get("tenantId", ""), "subscription_id": data.get("id", "")}

    def deploy_bicep(self, resource_group: str, name: str, template: Path, parameters: Path) -> Dict[str, Any]:
        data = self._run(
            [
                "deployment", "group", "create",
                "--resource-group", resource_group,
                "--name", name,
                "--mode", "Incremental",
                "--template-file", str(template),
                "--parameters", str(parameters),
            ],
            timeout=self.timeout_seconds * 6,
        ) or {}
        properties = data.get("properties") or {}
        return {"provisioning_state": properties.get("provisioningState"), "outputs": properties.get("outputs") or {}}

    def what_if(self, resource_group: str, template: Path, parameters: Path) -> List[Dict[str, Any]]:
        data = self._run(
            [
                "deployment", "group", "what-if",
                "--resource-group", resource_group,
                "--mode", "Incremental",
                "--template-file", str(template),
                "--parameters", str(parameters),
                "--no-pretty-print",
                "--result-format", "ResourceIdOnly",
            ],
            timeout=self.timeout_seconds * 2,
        ) or {}
        return [
            {"change_type": change.get("changeType"), "resource_id": change.get("resourceId", "")}
            for change in data.get("changes", [])
        ]


# ---------------------------------------------------------------------------
# HTTP and telemetry transports (injectable)
# ---------------------------------------------------------------------------


def default_http_post(url: str, *, headers: Mapping[str, str], json_body: Any, timeout: float) -> Any:
    import requests

    return requests.post(url, headers=dict(headers), json=json_body, timeout=timeout)


def default_http_get(url: str, *, timeout: float) -> Any:
    import requests

    return requests.get(url, timeout=timeout)


def default_logs_query(resource_id: str, query: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """Run a KQL query against an Application Insights component with the Azure CLI identity."""
    from azure.identity import AzureCliCredential
    from azure.monitor.query import LogsQueryClient

    response = LogsQueryClient(AzureCliCredential()).query_resource(resource_id, query, timespan=(start, end))
    tables = getattr(response, "tables", None) or []
    if not tables:
        return []
    table = tables[0]
    columns = [c if isinstance(c, str) else c.name for c in table.columns]
    return [dict(zip(columns, row)) for row in table.rows]
