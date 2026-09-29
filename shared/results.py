"""Structured objective results and semantic classifiers for the notebooks.

Each notebook records stable objective IDs with ``passed``, ``failed``, or
``inconclusive`` status and allowlisted scalar evidence. Files are written
atomically to ``outputs/results/<session_id>/<notebook>.json`` under the
repository root. Evidence never contains free text from model responses.

The classifiers are pure functions so they can be unit tested with synthetic
fixtures and reused by automation.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from .config import REPO_ROOT, ConfigError, is_headless

RESULTS_ROOT = REPO_ROOT / "outputs" / "results"
SCHEMA_VERSION = 1
STATUSES = ("passed", "failed", "inconclusive")

REQUIRED_OBJECTIVES: Dict[str, Tuple[str, ...]] = {
    "00-setup-and-validation": ("setup.identity", "setup.endpoints", "setup.apim_sku"),
    "demo1-token-limits": (
        "demo1.baseline",
        "demo1.rate_limit_429",
        "demo1.quota_exhausted",
        "demo1.reset_recovery",
    ),
    "demo2-token-metrics": (
        "demo2.logger_configured",
        "demo2.no_message_capture",
        "demo2.metrics_reconciled",
        "demo2.dimensions_observed",
    ),
    "demo3-content-safety": (
        "demo3.safe_prompt",
        "demo3.prompt_shield_block",
        "demo3.stream_intervention",
    ),
    "demo4-resilient-pool": (
        "demo4.routing_paths",
        "demo4.mock_auth_enforced",
        "demo4.fault_observed",
        "demo4.alternate_routing",
        "demo4.recovery",
    ),
}
# Optional cells that are intentionally not part of the acceptance set.
EXCLUDABLE_ITEMS: Dict[str, Tuple[str, ...]] = {
    "demo4-resilient-pool": ("demo4.cleanup",),
}

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,99}$")
_EVIDENCE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_NESTED_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
_SAFE_STRING_RE = re.compile(r"^[A-Za-z0-9 _.,:;/+=()\[\]\-]{0,128}$")
_TOKEN_LIKE_RE = re.compile(r"^[A-Za-z0-9+/=_\-]{32,}$")
_FORBIDDEN_KEY_PARTS = (
    "secret", "password", "connection_string", "subscription_key", "api_key",
    "authorization", "bearer", "credential",
)
_MAX_EVIDENCE_KEYS = 32
_MAX_LIST_ITEMS = 64


class ResultsError(ValueError):
    """Raised for invalid objective IDs, statuses, evidence, or session IDs."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    """Write JSON to ``path`` via a temp file and ``os.replace``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        # Windows: a scanner or reader can hold the destination briefly, making os.replace fail transiently.
        for attempt in range(20):
            try:
                os.replace(tmp_name, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.01 * (attempt + 1))
    except BaseException:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
        raise ResultsError("Session ID must be 1-100 characters of letters, digits, '_', '.', '-'.")
    return session_id


def resolve_session_id(env: Optional[Mapping[str, str]] = None) -> str:
    """Return ``SESSION_ID``; interactively fall back to ``DEMO_RUN``.

    Headless runs require ``SESSION_ID`` because Demo 1 rotates ``DEMO_RUN``.
    """
    env = os.environ if env is None else env
    session_id = (env.get("SESSION_ID") or "").strip()
    if not session_id:
        if is_headless():
            raise ConfigError("SESSION_ID is required in headless mode.")
        session_id = (env.get("DEMO_RUN") or "").strip()
    if not session_id:
        raise ConfigError("Neither SESSION_ID nor DEMO_RUN is set; run load_config() first.")
    return validate_session_id(session_id)


def _validate_scalar(name: str, value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ResultsError(f"Evidence '{name}' must be a finite number.")
        return value
    if isinstance(value, str):
        if not _SAFE_STRING_RE.match(value) or _TOKEN_LIKE_RE.match(value):
            raise ResultsError(
                f"Evidence '{name}' must be a short allowlisted scalar string, not free text or a token."
            )
        return value
    raise ResultsError(f"Evidence '{name}' has unsupported type {type(value).__name__}.")


def validate_evidence(evidence: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a copy of ``evidence`` after enforcing the scalar allowlist."""
    if evidence is None:
        return {}
    if not isinstance(evidence, Mapping):
        raise ResultsError("Evidence must be a mapping.")
    if len(evidence) > _MAX_EVIDENCE_KEYS:
        raise ResultsError(f"Evidence may contain at most {_MAX_EVIDENCE_KEYS} keys.")
    clean: Dict[str, Any] = {}
    for key, value in evidence.items():
        if not isinstance(key, str) or not _EVIDENCE_KEY_RE.match(key):
            raise ResultsError(f"Evidence key {key!r} must be lowercase snake_case.")
        if any(part in key for part in _FORBIDDEN_KEY_PARTS):
            raise ResultsError(f"Evidence key {key!r} names a credential.")
        if isinstance(value, (list, tuple)):
            if len(value) > _MAX_LIST_ITEMS:
                raise ResultsError(f"Evidence '{key}' has too many items.")
            clean[key] = [_validate_scalar(key, item) for item in value]
        elif isinstance(value, Mapping):
            if len(value) > _MAX_LIST_ITEMS:
                raise ResultsError(f"Evidence '{key}' has too many entries.")
            nested: Dict[str, Any] = {}
            for nested_key, nested_value in value.items():
                if not isinstance(nested_key, str) or not _NESTED_KEY_RE.match(nested_key):
                    raise ResultsError(f"Evidence '{key}' has an invalid nested key.")
                nested[nested_key] = _validate_scalar(f"{key}.{nested_key}", nested_value)
            clean[key] = nested
        else:
            clean[key] = _validate_scalar(key, value)
    return clean


def results_path(notebook: str, session_id: str, root: Optional[Path] = None) -> Path:
    if notebook not in REQUIRED_OBJECTIVES:
        raise ResultsError(f"Unknown notebook {notebook!r}.")
    return Path(root or RESULTS_ROOT) / validate_session_id(session_id) / f"{notebook}.json"


def load_results(notebook: str, session_id: str, root: Optional[Path] = None) -> Dict[str, Any]:
    """Load a notebook result file, or an empty document when it does not exist."""
    path = results_path(notebook, session_id, root)
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "notebook": notebook,
            "session_id": session_id,
            "objectives": {},
            "excluded": {},
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("notebook") != notebook or data.get("session_id") != session_id:
        raise ResultsError(f"{path.name} does not belong to this notebook/session.")
    data.setdefault("objectives", {})
    data.setdefault("excluded", {})
    return data


def record_objective(
    notebook: str,
    objective_id: str,
    status: str,
    evidence: Optional[Mapping[str, Any]] = None,
    *,
    session_id: Optional[str] = None,
    root: Optional[Path] = None,
) -> Path:
    """Record one objective outcome and return the result file path."""
    if notebook not in REQUIRED_OBJECTIVES:
        raise ResultsError(f"Unknown notebook {notebook!r}.")
    if objective_id not in REQUIRED_OBJECTIVES[notebook]:
        raise ResultsError(f"Objective {objective_id!r} is not defined for {notebook}.")
    if status not in STATUSES:
        raise ResultsError(f"Status must be one of {', '.join(STATUSES)}.")
    clean_evidence = validate_evidence(evidence)
    session_id = validate_session_id(session_id or resolve_session_id())
    data = load_results(notebook, session_id, root)
    data["objectives"][objective_id] = {
        "status": status,
        "evidence": clean_evidence,
        "recorded_at": _utc_now(),
    }
    path = results_path(notebook, session_id, root)
    atomic_write_json(path, data)
    return path


def record_exclusion(
    notebook: str,
    item_id: str,
    reason: str,
    *,
    session_id: Optional[str] = None,
    root: Optional[Path] = None,
) -> Path:
    """Record that an optional cell was intentionally not executed."""
    if item_id not in EXCLUDABLE_ITEMS.get(notebook, ()):
        raise ResultsError(f"{item_id!r} is not an excludable item for {notebook!r}.")
    _validate_scalar("reason", reason)
    session_id = validate_session_id(session_id or resolve_session_id())
    data = load_results(notebook, session_id, root)
    data["excluded"][item_id] = {"reason": reason, "recorded_at": _utc_now()}
    path = results_path(notebook, session_id, root)
    atomic_write_json(path, data)
    return path


class NotebookResults:
    """Recorder bound to one notebook and one session ID resolved at creation.

    Binding the session ID up front keeps results in one file even when a
    notebook rotates ``DEMO_RUN`` mid-run.
    """

    def __init__(
        self,
        notebook: str,
        *,
        session_id: Optional[str] = None,
        root: Optional[Path] = None,
    ) -> None:
        if notebook not in REQUIRED_OBJECTIVES:
            raise ResultsError(f"Unknown notebook {notebook!r}.")
        self.notebook = notebook
        self.session_id = validate_session_id(session_id or resolve_session_id())
        self.root = root

    @property
    def path(self) -> Path:
        return results_path(self.notebook, self.session_id, self.root)

    def record(
        self, objective_id: str, status: str, evidence: Optional[Mapping[str, Any]] = None
    ) -> str:
        record_objective(
            self.notebook, objective_id, status, evidence,
            session_id=self.session_id, root=self.root,
        )
        return status

    def exclude(self, item_id: str, reason: str) -> None:
        record_exclusion(
            self.notebook, item_id, reason, session_id=self.session_id, root=self.root
        )


# ---------------------------------------------------------------------------
# Classifiers (pure functions)
# ---------------------------------------------------------------------------

CLASSIFICATIONS = ("transport_error", "policy_block_confirmed", "not_tripped", "inconclusive")
CONTENT_SAFETY_ERROR = "content_safety_violation"


def header_value(headers: Optional[Mapping[str, str]], name: str) -> Optional[str]:
    """Case-insensitive header lookup that works for plain dicts too."""
    if not headers:
        return None
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return value
    return None


def _json_or_none(text: Optional[str]) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _is_content_safety_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    if error == CONTENT_SAFETY_ERROR:
        return True
    return isinstance(error, dict) and error.get("code") == CONTENT_SAFETY_ERROR


def has_content_safety_provenance(
    headers: Optional[Mapping[str, str]], body_text: Optional[str]
) -> bool:
    """True when the header or JSON body identifies the llm-content-safety policy."""
    decision = (header_value(headers, "x-content-safety-decision") or "").strip().lower()
    return decision == "blocked" or _is_content_safety_payload(_json_or_none(body_text))


def classify_block_response(
    status_code: Optional[int], headers: Optional[Mapping[str, str]], body_text: Optional[str]
) -> str:
    """Classify a non-streaming Demo 3 response."""
    if status_code == 200:
        return "not_tripped"
    if status_code == 403 and has_content_safety_provenance(headers, body_text):
        return "policy_block_confirmed"
    return "transport_error"


def parse_sse(body_text: Optional[str]) -> Dict[str, Any]:
    """Parse a server-sent-events body into counts; model text is never returned."""
    parsed = {"events": 0, "saw_done": False, "malformed": 0, "safety_event": False}
    text = (body_text or "").replace("\r\n", "\n").replace("\r", "\n")
    for block in text.split("\n\n"):
        data_lines = []
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            if field == "data":
                data_lines.append(value[1:] if value.startswith(" ") else value)
            elif field not in ("event", "id", "retry"):
                parsed["malformed"] += 1
        if not data_lines:
            continue
        data = "\n".join(data_lines).strip()
        if data == "[DONE]":
            parsed["saw_done"] = True
            continue
        payload = _json_or_none(data)
        if payload is None:
            parsed["malformed"] += 1
            continue
        parsed["events"] += 1
        if _is_content_safety_payload(payload):
            parsed["safety_event"] = True
    return parsed


def classify_stream_response(
    status_code: Optional[int],
    headers: Optional[Mapping[str, str]],
    body_text: Optional[str],
) -> Dict[str, Any]:
    """Classify a Demo 3 streaming response.

    ``policy_block_confirmed`` requires policy-specific evidence (a blocked
    decision header or a content-safety error payload) on a stream that did not
    complete, or a 403 carrying that evidence. A missing ``[DONE]`` alone is
    ``inconclusive``; a complete stream is ``not_tripped``; HTTP, content-type,
    and SSE framing problems are ``transport_error``.
    """
    content_type = (header_value(headers, "content-type") or "").lower()
    is_event_stream = content_type.startswith("text/event-stream")
    result: Dict[str, Any] = {
        "classification": "transport_error",
        "status": status_code,
        "event_stream": is_event_stream,
        "event_count": 0,
        "saw_done": False,
        "malformed_events": 0,
        "safety_provenance": False,
    }
    if not status_code:
        return result
    if status_code != 200:
        if status_code == 403 and has_content_safety_provenance(headers, body_text):
            result["classification"] = "policy_block_confirmed"
            result["safety_provenance"] = True
        return result
    if not is_event_stream:
        return result
    parsed = parse_sse(body_text)
    header_blocked = (
        (header_value(headers, "x-content-safety-decision") or "").strip().lower() == "blocked"
    )
    provenance = header_blocked or parsed["safety_event"]
    result.update(
        event_count=parsed["events"],
        saw_done=parsed["saw_done"],
        malformed_events=parsed["malformed"],
        safety_provenance=provenance,
    )
    if parsed["malformed"]:
        return result
    if parsed["saw_done"]:
        result["classification"] = "inconclusive" if provenance else "not_tripped"
    elif provenance:
        result["classification"] = "policy_block_confirmed"
    else:
        result["classification"] = "inconclusive"
    return result


def objective_status(classification: str, not_tripped_status: str = "inconclusive") -> str:
    """Map a classification to an objective status."""
    if classification not in CLASSIFICATIONS:
        raise ResultsError(f"Unknown classification {classification!r}.")
    if not_tripped_status not in STATUSES:
        raise ResultsError(f"Status must be one of {', '.join(STATUSES)}.")
    return {
        "policy_block_confirmed": "passed",
        "transport_error": "failed",
        "inconclusive": "inconclusive",
        "not_tripped": not_tripped_status,
    }[classification]


TOKEN_LIMIT_OUTCOMES = (
    "ok", "gateway_rate_limit", "gateway_quota", "backend_throttle",
    "content_safety_block", "other",
)


def classify_token_limit_response(
    status_code: Optional[int], headers: Optional[Mapping[str, str]], body_text: Optional[str]
) -> str:
    """Attribute a Demo 1 response to the gateway token policy or the backend.

    Gateway 429s carry the policy's ``remaining-tokens`` header and an APIM
    ``statusCode`` body; backend throttles carry an Azure OpenAI ``error``
    object. Gateway quota 403s carry the quota header or a quota message and
    no content-safety evidence.
    """
    if status_code == 200:
        return "ok"
    payload = _json_or_none(body_text)
    backend_shaped = isinstance(payload, dict) and isinstance(payload.get("error"), dict)
    if status_code == 429:
        if backend_shaped or header_value(headers, "remaining-tokens") is None:
            return "backend_throttle"
        return "gateway_rate_limit"
    if status_code == 403:
        if has_content_safety_provenance(headers, body_text):
            return "content_safety_block"
        message = str(payload.get("message", "")).lower() if isinstance(payload, dict) else ""
        if not backend_shaped and (
            header_value(headers, "remaining-quota-tokens") is not None or "quota" in message
        ):
            return "gateway_quota"
    return "other"


DEMO4_MEMBERS = ("demo4-ptu-east", "demo4-ptu-central", "demo4-payg")


def _served_by(call: Mapping[str, Any]) -> Optional[str]:
    served_by = call.get("served_by")
    return served_by if served_by in DEMO4_MEMBERS else None


def summarize_pool_calls(calls: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Count successful responses by member plus unknown members and statuses."""
    calls = list(calls)
    served = {member: 0 for member in DEMO4_MEMBERS}
    status_counts: Dict[str, int] = {}
    unknown = 0
    for call in calls:
        status_counts[str(call.get("status"))] = status_counts.get(str(call.get("status")), 0) + 1
        member = _served_by(call)
        if member is None:
            unknown += 1
        elif call.get("status") == 200:
            served[member] += 1
    return {"calls": len(calls), "served": served, "status_counts": status_counts,
            "unknown_member": unknown}


def _violations(calls: Sequence[Mapping[str, Any]], allowed_statuses: Iterable[int]) -> int:
    allowed = set(allowed_statuses)
    return sum(
        1 for call in calls if _served_by(call) is None or call.get("status") not in allowed
    )


def _count(calls: Sequence[Mapping[str, Any]], member: str, status: int) -> int:
    return sum(1 for call in calls if _served_by(call) == member and call.get("status") == status)


def evaluate_routing_paths(calls: Sequence[Mapping[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """Healthy phase: every call is a named 200, both priority-1 members serve, PAYG does not."""
    calls = list(calls)
    summary = summarize_pool_calls(calls)
    violations = _violations(calls, {200})
    ok = (
        bool(calls)
        and violations == 0
        and summary["served"]["demo4-ptu-east"] > 0
        and summary["served"]["demo4-ptu-central"] > 0
        and summary["served"]["demo4-payg"] == 0
    )
    return ("passed" if ok else "failed"), {**summary, "violations": violations}


def evaluate_fault_observed(calls: Sequence[Mapping[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    """East fault phase: at least two East 429s and no unknown members or statuses."""
    calls = list(calls)
    violations = _violations(calls, {200, 429})
    east_429 = _count(calls, "demo4-ptu-east", 429)
    ok = bool(calls) and violations == 0 and east_429 >= 2
    return ("passed" if ok else "failed"), {
        **summarize_pool_calls(calls), "east_429": east_429, "violations": violations,
    }


def evaluate_alternate_routing(
    after_east_fault: Sequence[Mapping[str, Any]],
    after_both_faults: Sequence[Mapping[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    """Central serves after the East fault, then PAYG serves after both priority-1 faults."""
    after_east_fault = list(after_east_fault)
    after_both_faults = list(after_both_faults)
    violations = _violations(after_east_fault, {200, 429}) + _violations(after_both_faults, {200, 429})
    central_200 = _count(after_east_fault, "demo4-ptu-central", 200)
    payg_200 = _count(after_both_faults, "demo4-payg", 200)
    ok = (
        bool(after_east_fault) and bool(after_both_faults)
        and violations == 0 and central_200 > 0 and payg_200 > 0
    )
    return ("passed" if ok else "failed"), {
        "central_200_after_east_fault": central_200,
        "payg_200_after_both_faults": payg_200,
        "violations": violations,
    }


def evaluate_recovery(
    calls: Sequence[Mapping[str, Any]], fault_status: Optional[str]
) -> Tuple[str, Dict[str, Any]]:
    """Recovery counts only after a recorded fault: East serves again, every call a named 200."""
    calls = list(calls)
    violations = _violations(calls, {200})
    east_200 = _count(calls, "demo4-ptu-east", 200)
    prior_fault = fault_status == "passed"
    ok = prior_fault and bool(calls) and violations == 0 and east_200 > 0
    return ("passed" if ok else "failed"), {
        **summarize_pool_calls(calls), "east_200": east_200,
        "prior_fault_recorded": prior_fault, "violations": violations,
    }


def evaluate_mock_auth_probe(status_code: Optional[int]) -> Tuple[str, Dict[str, Any]]:
    """A direct mock call without the named-value credential must be rejected with 401."""
    return ("passed" if status_code == 401 else "failed"), {"status": status_code}
