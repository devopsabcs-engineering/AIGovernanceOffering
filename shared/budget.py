"""Session-wide dispatch guard for inference, safety, and mock requests.

Every notebook inference or safety call goes through :func:`guarded_request`,
which reserves one attempt, conservative input-plus-maximum-output tokens, and
estimated USD spend BEFORE sending. Reservations are never refunded: timeouts
and ambiguous failures count as consumed. Counters persist atomically to
``outputs/session/<SESSION_ID>/budget.json`` under the repository root so
every kernel in a session shares one envelope.

Modes:

* Enforced: ``SESSION_ID`` plus ``SESSION_MAX_ATTEMPTS``,
  ``SESSION_MAX_RESERVED_TOKENS``, ``SESSION_MAX_ESTIMATED_USD``, and
  ``SESSION_DEADLINE_UTC`` are set. Headless runs require the state file to
  exist already (created once by the session initializer) and require an
  approved price snapshot for model and safety calls.
* Record-only: interactive use without those keys counts calls in memory and
  never blocks, preserving the existing workshop behavior.

Management-plane (ARM) calls are intentionally not budgeted so cleanup is
never starved.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, TypeVar, Union

from .config import REPO_ROOT, is_headless
from .results import atomic_write_json, validate_session_id

SESSION_ROOT = REPO_ROOT / "outputs" / "session"
SCHEMA_VERSION = 1
KINDS = ("model", "safety", "mock")
TOKEN_KINDS = ("model", "safety")
SESSION_ID_ENV_KEY = "SESSION_ID"
LIMIT_ENV_KEYS = (
    "SESSION_MAX_ATTEMPTS",
    "SESSION_MAX_RESERVED_TOKENS",
    "SESSION_MAX_ESTIMATED_USD",
    "SESSION_DEADLINE_UTC",
)
PRICE_KEYS = ("input_usd_per_million", "output_usd_per_million")

_LOCK_TIMEOUT_SECONDS = 30
_LOCK_STALE_SECONDS = 120

T = TypeVar("T")


class BudgetExceeded(RuntimeError):
    """Raised before dispatch when a reservation does not fit the session envelope."""


class BudgetStateError(RuntimeError):
    """Raised when budget configuration or persisted state is missing or invalid."""


@dataclass(frozen=True)
class SessionLimits:
    max_attempts: int
    max_reserved_tokens: int
    max_estimated_usd: float
    deadline_utc: str


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise BudgetStateError("SESSION_DEADLINE_UTC must be an ISO 8601 UTC timestamp.") from exc
    if parsed.tzinfo is None:
        raise BudgetStateError("SESSION_DEADLINE_UTC must include a UTC offset (for example 'Z').")
    return parsed.astimezone(timezone.utc)


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_limits(limits: SessionLimits) -> SessionLimits:
    if not isinstance(limits.max_attempts, int) or limits.max_attempts < 0:
        raise BudgetStateError("SESSION_MAX_ATTEMPTS must be a non-negative integer.")
    if not isinstance(limits.max_reserved_tokens, int) or limits.max_reserved_tokens < 0:
        raise BudgetStateError("SESSION_MAX_RESERVED_TOKENS must be a non-negative integer.")
    usd = limits.max_estimated_usd
    if not isinstance(usd, (int, float)) or not math.isfinite(usd) or usd < 0:
        raise BudgetStateError("SESSION_MAX_ESTIMATED_USD must be a non-negative number.")
    _parse_utc(limits.deadline_utc)
    return limits


def load_limits(env: Optional[Mapping[str, str]] = None) -> Optional[SessionLimits]:
    """Return session limits from the environment, or None when no session keys are set.

    A partial set of keys is an error rather than a silent fallback.
    """
    env = os.environ if env is None else env
    keys = (SESSION_ID_ENV_KEY,) + LIMIT_ENV_KEYS
    present = [key for key in keys if (env.get(key) or "").strip()]
    if not present:
        return None
    missing = [key for key in keys if key not in present]
    if missing:
        raise BudgetStateError(f"Incomplete session budget configuration; missing: {', '.join(missing)}.")
    try:
        limits = SessionLimits(
            max_attempts=int(env["SESSION_MAX_ATTEMPTS"]),
            max_reserved_tokens=int(env["SESSION_MAX_RESERVED_TOKENS"]),
            max_estimated_usd=float(env["SESSION_MAX_ESTIMATED_USD"]),
            deadline_utc=env["SESSION_DEADLINE_UTC"].strip(),
        )
    except ValueError as exc:
        raise BudgetStateError("Session budget limits must be numeric.") from exc
    return validate_limits(limits)


def validate_price(price: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Validate an approved price snapshot (USD per million tokens)."""
    if price is None:
        return None
    clean: Dict[str, Any] = {}
    for key in PRICE_KEYS:
        value = price.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise BudgetStateError(f"Price snapshot '{key}' must be one non-negative number.")
        clean[key] = float(value)
    snapshot_id = price.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise BudgetStateError("Price snapshot requires a non-empty 'snapshot_id'.")
    clean["snapshot_id"] = snapshot_id.strip()
    return clean


def estimate_prompt_tokens(messages: Union[str, Sequence[Mapping[str, Any]]]) -> int:
    """Conservative prompt token estimate: about one token per three characters plus overhead."""
    if isinstance(messages, str):
        messages = [{"content": messages}]
    total = 8
    for message in messages:
        total += 8 + math.ceil(len(str(message.get("content", ""))) / 3)
    return total


def budget_path(session_id: str, root: Optional[Path] = None) -> Path:
    return Path(root or SESSION_ROOT) / validate_session_id(session_id) / "budget.json"


def _new_totals() -> Dict[str, Any]:
    return {
        "attempts": 0,
        "reserved_tokens": 0,
        "reserved_usd": 0.0,
        "errors": 0,
        "by_kind": {kind: 0 for kind in KINDS},
    }


def init_session(
    session_id: str,
    limits: SessionLimits,
    *,
    price: Optional[Mapping[str, Any]] = None,
    root: Optional[Path] = None,
) -> Path:
    """Create the session budget state once; an existing state is never reset."""
    path = budget_path(session_id, root)
    if path.exists():
        raise BudgetStateError(f"Budget state already exists for session {session_id}.")
    state = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "created_at": _utc_now_text(),
        "limits": asdict(validate_limits(limits)),
        "price": validate_price(price),
        "totals": _new_totals(),
        "entries": [],
    }
    atomic_write_json(path, state)
    return path


def load_state(session_id: str, root: Optional[Path] = None) -> Dict[str, Any]:
    path = budget_path(session_id, root)
    if not path.exists():
        raise BudgetStateError(f"Budget state file is missing for session {session_id}.")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != SCHEMA_VERSION or state.get("session_id") != session_id:
        raise BudgetStateError("Budget state does not match this session or schema version.")
    return state


def session_totals(session_id: str, root: Optional[Path] = None) -> Dict[str, Any]:
    """Return persisted totals for evidence reporting."""
    return dict(load_state(session_id, root)["totals"])


class _FileLock:
    """Cross-process exclusive lock using an O_EXCL lock file next to the state."""

    def __init__(self, target: Path) -> None:
        self.path = target.parent / (target.name + ".lock")

    def __enter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > _LOCK_STALE_SECONDS:
                        os.remove(self.path)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > deadline:
                    raise BudgetStateError("Timed out waiting for the budget state lock.") from None
                time.sleep(0.05)

    def __exit__(self, *exc_info: Any) -> None:
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass


_RECORD_ONLY_TOTALS: Dict[str, Any] = _new_totals()


def record_only_totals() -> Dict[str, Any]:
    """Return in-memory counters kept when no session budget is configured."""
    return {**_RECORD_ONLY_TOTALS, "by_kind": dict(_RECORD_ONLY_TOTALS["by_kind"])}


def _validate_request(
    kind: str,
    estimated_input_tokens: int,
    max_output_tokens: int,
    body: Optional[Mapping[str, Any]],
) -> int:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}.")
    for name, value in (
        ("estimated_input_tokens", estimated_input_tokens),
        ("max_output_tokens", max_output_tokens),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer.")
    if kind == "mock":
        return 0
    if max_output_tokens <= 0:
        raise ValueError("Model and safety calls require a nonzero max_output_tokens.")
    if body is None or body.get("max_tokens") != max_output_tokens:
        raise ValueError("The request body must set max_tokens equal to max_output_tokens.")
    return estimated_input_tokens + max_output_tokens


def _finalize(path: Path, seq: int, outcome: str, error: bool) -> None:
    with _FileLock(path):
        state = json.loads(path.read_text(encoding="utf-8"))
        for entry in reversed(state["entries"]):
            if entry["seq"] == seq:
                entry["outcome"] = outcome
                break
        if error:
            state["totals"]["errors"] += 1
        atomic_write_json(path, state)


def _dispatch_record_only(kind: str, tokens: int, send: Callable[[], T]) -> T:
    _RECORD_ONLY_TOTALS["attempts"] += 1
    _RECORD_ONLY_TOTALS["reserved_tokens"] += tokens
    _RECORD_ONLY_TOTALS["by_kind"][kind] += 1
    try:
        return send()
    except BaseException:
        _RECORD_ONLY_TOTALS["errors"] += 1
        raise


def guarded_request(
    kind: str,
    estimated_input_tokens: int,
    max_output_tokens: int,
    send: Callable[[], T],
    *,
    body: Optional[Mapping[str, Any]] = None,
    label: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> T:
    """Reserve budget, then call ``send()`` and return its response.

    ``kind`` is ``model``, ``safety``, or ``mock``. Model and safety calls must
    pass the request ``body`` with ``max_tokens == max_output_tokens``. Mock
    calls count as attempts with zero token reservation. Raises
    :class:`BudgetExceeded` or :class:`BudgetStateError` before dispatch when the
    reservation cannot be made; exceptions from ``send`` are re-raised after
    the attempt is recorded as consumed.
    """
    tokens = _validate_request(kind, estimated_input_tokens, max_output_tokens, body)
    env = os.environ if env is None else env
    headless = is_headless()
    limits = load_limits(env)
    if limits is None:
        if headless:
            raise BudgetStateError(
                "Headless runs require SESSION_ID and SESSION_MAX_* budget keys before any request."
            )
        return _dispatch_record_only(kind, tokens, send)

    session_id = validate_session_id(env[SESSION_ID_ENV_KEY].strip())
    path = budget_path(session_id, root)
    with _FileLock(path):
        if not path.exists():
            if headless:
                raise BudgetStateError(
                    f"Budget state file is missing for session {session_id}; initialize the session first."
                )
            init_session(session_id, limits, root=root)
        state = load_state(session_id, root)
        state_limits = validate_limits(SessionLimits(**state["limits"]))
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if current >= _parse_utc(state_limits.deadline_utc):
            raise BudgetExceeded("The session deadline has passed; no further requests are allowed.")

        reserved_usd = 0.0
        if kind in TOKEN_KINDS:
            try:
                price = validate_price(state.get("price"))
            except BudgetStateError:
                raise BudgetStateError("The session price snapshot is ambiguous or invalid.") from None
            if price is None:
                if headless:
                    raise BudgetStateError(
                        "No approved price snapshot is recorded for this session; model calls are blocked."
                    )
            else:
                reserved_usd = (
                    estimated_input_tokens * price["input_usd_per_million"]
                    + max_output_tokens * price["output_usd_per_million"]
                ) / 1_000_000

        totals = state["totals"]
        if totals["attempts"] + 1 > state_limits.max_attempts:
            raise BudgetExceeded("Session attempt budget exhausted.")
        if totals["reserved_tokens"] + tokens > state_limits.max_reserved_tokens:
            raise BudgetExceeded("Session token reservation does not fit the remaining budget.")
        if totals["reserved_usd"] + reserved_usd > state_limits.max_estimated_usd:
            raise BudgetExceeded("Session estimated USD reservation does not fit the remaining budget.")

        totals["attempts"] += 1
        totals["reserved_tokens"] += tokens
        totals["reserved_usd"] = round(totals["reserved_usd"] + reserved_usd, 8)
        totals["by_kind"][kind] = totals["by_kind"].get(kind, 0) + 1
        seq = totals["attempts"]
        state["entries"].append({
            "seq": seq,
            "kind": kind,
            "label": label,
            "estimated_input_tokens": estimated_input_tokens,
            "max_output_tokens": max_output_tokens if kind in TOKEN_KINDS else 0,
            "reserved_tokens": tokens,
            "reserved_usd": round(reserved_usd, 8),
            "reserved_at": _utc_now_text(),
            "outcome": "pending",
        })
        atomic_write_json(path, state)

    try:
        response = send()
    except BaseException as exc:
        _finalize(path, seq, f"error:{type(exc).__name__}", error=True)
        raise
    _finalize(path, seq, f"http_{getattr(response, 'status_code', 'unknown')}", error=False)
    return response
