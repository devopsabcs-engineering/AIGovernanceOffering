"""Idempotent Azure API Management (APIM) control-plane helpers.

All functions use ARM REST (`https://management.azure.com`) with PUT/upsert
semantics so they are safe to call repeatedly (re-running a notebook must
never fail or duplicate resources). Every function is reusable by any of the
workshop demos, not just Demo 1.
"""

from __future__ import annotations

import json as _json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import requests

from .auth import get_arm_token
from .config import ConfigError, is_headless

ARM_BASE = "https://management.azure.com"
API_VERSION = "2024-06-01-preview"
APIM_PREVIEW_API_VERSION = "2025-09-01-preview"
COGNITIVE_SERVICES_RESOURCE = "https://cognitiveservices.azure.com"

# Bicep-owned platform logger; notebook helpers must never write or bind it.
PLATFORM_LOGGER_ID = "apimlogger"
SYSTEM_ASSIGNED_IDENTITY = "SystemAssigned"

# How long to wait for APIM's async provisioning (e.g. a service that is
# still "Updating") before giving up.
_POLL_TIMEOUT_SECONDS = 300
_POLL_INTERVAL_SECONDS = 5

_ERROR_BODY_LIMIT = 500
_REDACTED = "***REDACTED***"
_SECRET_FIELD_NAMES = (
    "primaryKey", "secondaryKey", "connectionString", "key", "value",
    "Ocp-Apim-Subscription-Key", "api-key", "Authorization", "instrumentationKey",
    "access_token", "accessToken", "token", "password", "secret", "clientSecret",
)
_SECRET_NAMES_PATTERN = "|".join(re.escape(name) for name in _SECRET_FIELD_NAMES)
_JSON_SECRET_RE = re.compile(
    r'("(?:' + _SECRET_NAMES_PATTERN + r')"\s*:\s*)("(?:[^"\\]|\\.)*"|[^,}\]\s]+)',
    re.IGNORECASE,
)
_HEADER_SECRET_RE = re.compile(
    r"((?:Ocp-Apim-Subscription-Key|api-key|Authorization)\s*[:=]\s*)([^\s,;&\"']+(?:\s+[^\s,;&\"']+)?)",
    re.IGNORECASE,
)
_QUERY_SECRET_RE = re.compile(
    r"((?:subscription-key|api-key|sig|code|access_token)=)([^&\s\"']+)", re.IGNORECASE
)
_CONNECTION_STRING_RE = re.compile(
    r"((?:InstrumentationKey|SharedAccessKey|AccountKey)=)([^;\s\"']+)", re.IGNORECASE
)
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9\-_.~+/=]+", re.IGNORECASE)
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def redact_secrets(text: Optional[str]) -> str:
    """Mask values of known secret fields, headers, query keys, and bearer tokens."""
    if not text:
        return ""
    text = _JSON_SECRET_RE.sub(lambda m: f'{m.group(1)}"{_REDACTED}"', text)
    text = _HEADER_SECRET_RE.sub(lambda m: f"{m.group(1)}{_REDACTED}", text)
    text = _QUERY_SECRET_RE.sub(lambda m: f"{m.group(1)}{_REDACTED}", text)
    text = _CONNECTION_STRING_RE.sub(lambda m: f"{m.group(1)}{_REDACTED}", text)
    return _BEARER_RE.sub(lambda m: f"{m.group(1)}{_REDACTED}", text)


def sanitize_error_body(text: Optional[str], limit: int = _ERROR_BODY_LIMIT) -> str:
    """Redact secrets, then truncate, so error text is safe to print or log."""
    cleaned = redact_secrets(text)
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + f"...[truncated {len(cleaned) - limit} chars]"
    return cleaned


class ApimError(RuntimeError):
    """Raised when an ARM call against APIM fails; body is redacted and truncated."""

    def __init__(self, method: str, url: str, response: requests.Response):
        self.method = method
        self.url = redact_secrets(str(url))
        self.status_code = response.status_code
        self.body = sanitize_error_body(getattr(response, "text", ""))
        super().__init__(
            f"{method} {self.url} failed with {response.status_code}: {self.body}"
        )


class PrivacyConfigurationError(RuntimeError):
    """Raised when a diagnostic readback shows LLM message or body capture."""


def _headers() -> Dict[str, str]:
    token = get_arm_token()
    return {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    }


def _service_scope(subscription_id: str, resource_group: str, apim_name: str) -> str:
    return (
        f"{ARM_BASE}/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.ApiManagement/service/{apim_name}"
    )


def _resource_group_scope(subscription_id: str, resource_group: str) -> str:
    return f"{ARM_BASE}/subscriptions/{subscription_id}/resourceGroups/{resource_group}"


def _request(
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    ok_statuses: Optional[List[int]] = None,
) -> requests.Response:
    params = dict(params or {})
    params.setdefault("api-version", API_VERSION)
    response = requests.request(
        method, url, headers=_headers(), params=params, json=json_body, timeout=60
    )
    ok_statuses = ok_statuses or [200, 201, 202, 204]
    if response.status_code == 404 and method == "GET":
        return response
    if response.status_code not in ok_statuses:
        raise ApimError(method, response.url, response)
    return response


def _portal_url(resource_id: str, blade: str = "overview") -> str:
    return f"https://portal.azure.com/#@/resource{resource_id}/{blade}"


def _json_body(response: requests.Response) -> Dict[str, Any]:
    """Parse an ARM response body, tolerating a UTF-8 BOM and empty payloads."""
    if not response.content:
        return {}
    text = response.text.lstrip("\ufeff")
    if not text.strip():
        return {}
    try:
        return _json.loads(text)
    except ValueError:
        return {}


def _wait_for_completion(response: requests.Response) -> None:
    """Poll an ARM async operation (202 Accepted) until it finishes."""
    if response.status_code != 202:
        return
    location = response.headers.get("Location") or response.headers.get("Azure-AsyncOperation")
    if not location:
        return
    deadline = time.time() + _POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        poll = requests.get(location, headers=_headers(), timeout=60)
        if poll.status_code in (200, 201, 204):
            body = _json_body(poll)
            status = (body or {}).get("status")
            if status in (None, "Succeeded"):
                return
            if status in ("Failed", "Canceled"):
                raise ApimError("GET", location, poll)
        time.sleep(_POLL_INTERVAL_SECONDS)


def ensure_api(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    api_id: str,
    display_name: str,
    path: str,
    service_url: Optional[str] = None,
    protocols: Optional[List[str]] = None,
    subscription_required: bool = True,
) -> Dict[str, Any]:
    """Create or update (idempotent) an API on the APIM instance."""
    url = f"{_service_scope(subscription_id, resource_group, apim_name)}/apis/{api_id}"
    body = {
        "properties": {
            "displayName": display_name,
            "path": path,
            "protocols": protocols or ["https"],
            "subscriptionRequired": subscription_required,
        }
    }
    if service_url:
        body["properties"]["serviceUrl"] = service_url
    response = _request("PUT", url, json_body=body)
    _wait_for_completion(response)
    return _json_body(response)


def ensure_operation(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    api_id: str,
    operation_id: str,
    display_name: str,
    method: str,
    url_template: str,
) -> Dict[str, Any]:
    """Create or update (idempotent) an operation on an API."""
    url = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}"
        f"/apis/{api_id}/operations/{operation_id}"
    )
    body = {
        "properties": {
            "displayName": display_name,
            "method": method,
            "urlTemplate": url_template,
        }
    }
    response = _request("PUT", url, json_body=body)
    _wait_for_completion(response)
    return _json_body(response)


def ensure_backend(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    backend_id: str,
    backend_url: str,
    description: str = "",
    protocol: str = "http",
    credentials: Optional[Dict[str, Any]] = None,
    circuit_breaker: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create or update (idempotent) a backend pointing at the AOAI endpoint.

    APIM backend ``protocol`` is the backend style enum (``"http"`` versus
    ``"soap"``), not the transport scheme. Keep HTTPS backends as
    ``protocol="http"``; TLS transport is selected by the ``https://`` scheme
    in ``backend_url``. APIM's REST contract does not accept ``"https"`` here.
    Public Azure endpoints should keep both TLS certificate validation flags
    enabled.

    ``credentials`` is used by backends whose auth is configured on the
    backend entity itself rather than via a policy ``set-header`` (this is
    how the ``llm-content-safety`` policy authenticates to its Content Safety
    ``backend-id``, since it calls the backend directly). Pass e.g.
    :func:`managed_identity_backend_credentials` (system- or user-assigned)
    or ``{"header": {"Ocp-Apim-Subscription-Key": ["<key>"]}}``.
    """
    url = f"{_service_scope(subscription_id, resource_group, apim_name)}/backends/{backend_id}"
    body = {
        "properties": {
            "url": backend_url.rstrip("/"),
            "protocol": protocol,
            "description": description or backend_id,
            "tls": {"validateCertificateChain": True, "validateCertificateName": True},
        }
    }
    if credentials:
        body["properties"]["credentials"] = credentials
    if circuit_breaker:
        body["properties"]["circuitBreaker"] = circuit_breaker
    response = _request("PUT", url, json_body=body)
    _wait_for_completion(response)
    return _json_body(response)


def _validate_identity_client_id(client_id: str) -> str:
    client_id = client_id.strip()
    if not _GUID_RE.match(client_id):
        raise ValueError(
            "APIM_IDENTITY_CLIENT_ID must be the user-assigned identity client ID (a GUID)."
        )
    return client_id


def managed_identity_backend_credentials(
    client_id: Optional[str] = None,
    resource: str = COGNITIVE_SERVICES_RESOURCE,
) -> Dict[str, Any]:
    """Backend ``credentials`` for APIM managed identity (user-assigned when ``client_id`` is set)."""
    managed_identity: Dict[str, Any] = {"resource": resource}
    if client_id and client_id.strip():
        managed_identity["clientId"] = _validate_identity_client_id(client_id)
    return {"managedIdentity": managed_identity}


_MI_ELEMENT_RE = re.compile(r"<authentication-managed-identity\b[^>]*?/?>", re.DOTALL)
_CLIENT_ID_ATTR_RE = re.compile(r"\s+client-id\s*=\s*(\"[^\"]*\"|'[^']*')")


def apply_identity_client_id(policy_xml: str, client_id: Optional[str]) -> str:
    """Set ``client-id`` on every ``authentication-managed-identity`` element.

    Returns the policy unchanged when ``client_id`` is empty so the APIM
    system-assigned identity keeps working. Idempotent: an existing
    ``client-id`` attribute is replaced rather than duplicated.
    """
    if not client_id or not client_id.strip():
        return policy_xml
    client_id = _validate_identity_client_id(client_id)

    def _inject(match: "re.Match[str]") -> str:
        element = _CLIENT_ID_ATTR_RE.sub("", match.group(0))
        name = "<authentication-managed-identity"
        return f'{name} client-id="{client_id}"{element[len(name):]}'

    return _MI_ELEMENT_RE.sub(_inject, policy_xml)


def get_backend(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    backend_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetch a backend, returning None if it does not exist."""
    url = f"{_service_scope(subscription_id, resource_group, apim_name)}/backends/{backend_id}"
    response = _request("GET", url)
    if response.status_code == 404:
        return None
    return _json_body(response)


def backend_credential_header_names(backend: Optional[Dict[str, Any]]) -> List[str]:
    """Return the header names (never values) configured as backend credentials."""
    credentials = ((backend or {}).get("properties") or {}).get("credentials") or {}
    return sorted((credentials.get("header") or {}).keys())


def ensure_backend_pool(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    backend_id: str,
    members: List[Dict[str, Any]],
    description: str = "",
) -> Dict[str, Any]:
    """Create or update a Pool backend from backend id, priority, and weight members.

    Uses the module's APIM API version, which supports both Pool backends and
    the circuit breaker properties used by Demo 4.

    APIM's BackendPoolItem contract defines `pool.services[].id` as "the unique
    ARM id of the backend entity" (format `arm-id`), i.e. the bare path
    `/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.ApiManagement/
    service/{apim}/backends/{name}`. A short backend name is rejected with
    `ValidationError: Invalid field 'pool.services[N].id' specified`, so each
    member id is normalized here. Callers may pass a short backend name, a bare
    ARM id, or an ARM id prefixed with ARM_BASE (the prefix is stripped).
    `url` and `protocol` are only required for `Single` backends, so a Pool
    backend omits them.
    """
    if not members:
        raise ValueError("Pool must contain at least one member.")
    scope = _service_scope(subscription_id, resource_group, apim_name)
    backends_path = f"{scope.removeprefix(ARM_BASE)}/backends"
    services: List[Dict[str, Any]] = []
    for member in members:
        member_id = member.get("id")
        if not member_id or not isinstance(member_id, str):
            raise ValueError("Every pool member must specify a backend 'id'.")
        for field_name in ("priority", "weight"):
            value = member.get(field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(
                    f"Pool member {member_id!r} {field_name} must be a positive integer."
                )
        if member_id.startswith(ARM_BASE):
            arm_id = member_id.removeprefix(ARM_BASE)
        elif member_id.startswith("/"):
            arm_id = member_id
        else:
            arm_id = f"{backends_path}/{member_id}"
        services.append(
            {"id": arm_id, "priority": member["priority"], "weight": member["weight"]}
        )
    url = f"{scope}/backends/{backend_id}"
    body = {
        "properties": {
            "type": "Pool",
            "description": description or backend_id,
            "pool": {"services": services},
        }
    }
    response = _request("PUT", url, json_body=body)
    _wait_for_completion(response)
    return _json_body(response)


def ensure_named_value(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    named_value_id: str,
    display_name: str,
    value: str,
    secret: bool = True,
) -> Dict[str, Any]:
    """Create or update (idempotent) a named value (e.g. the AOAI key).

    Convention: the named value id and display name must be identical and
    lowercase, matching the ``{{token}}`` used in the policy XML. APIM resolves
    policy ``{{...}}`` references against the named value *display name*, and
    the lookup is case-sensitive -- a mismatch surfaces later as an opaque
    policy validation error (HTTP 400, "Cannot find a property '<token>'").
    """
    if display_name != named_value_id:
        raise ValueError(
            f"Named value display_name {display_name!r} must match id "
            f"{named_value_id!r}; policy '{{{{...}}}}' lookups are by display "
            "name and are case-sensitive."
        )
    url = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}"
        f"/namedValues/{named_value_id}"
    )
    body = {
        "properties": {
            "displayName": display_name,
            "value": value,
            "secret": secret,
        }
    }
    response = _request("PUT", url, json_body=body)
    _wait_for_completion(response)
    return _json_body(response)


def ensure_product(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    product_id: str,
    display_name: str,
    description: str = "",
    subscription_required: bool = True,
    state: str = "published",
) -> Dict[str, Any]:
    """Create or update (idempotent) a product used to scope a subscription."""
    url = f"{_service_scope(subscription_id, resource_group, apim_name)}/products/{product_id}"
    body = {
        "properties": {
            "displayName": display_name,
            "description": description or display_name,
            "subscriptionRequired": subscription_required,
            "state": state,
        }
    }
    response = _request("PUT", url, json_body=body)
    _wait_for_completion(response)
    return _json_body(response)


def ensure_product_api_link(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    product_id: str,
    api_id: str,
) -> None:
    """Link an API to a product (idempotent).

    Uses the classic product-API association endpoint
    (`/products/{productId}/apis/{apiId}`), which is supported by the
    `API_VERSION` pinned above. The newer `apiLinks` collection only exists in
    2023-03-01-preview and later; calling it with an older api-version makes
    ARM reject the URL with a generic `ResourceNotFound` / "request did not
    have proper uri path format" error.

    The PUT takes no request body and returns 201 on first link, 200 if the
    API is already associated with the product.
    """
    url = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}"
        f"/products/{product_id}/apis/{api_id}"
    )
    _request("PUT", url, ok_statuses=[200, 201, 204])


def ensure_subscription(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    apim_subscription_id: str,
    display_name: str,
    scope: str,
) -> Dict[str, Any]:
    """Create or update (idempotent) an APIM subscription scoped to a product/API.

    `scope` should look like `/products/{product_id}` or `/apis/{api_id}`.
    """
    url = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}"
        f"/subscriptions/{apim_subscription_id}"
    )
    body = {
        "properties": {
            "displayName": display_name,
            "scope": scope,
            "state": "active",
        }
    }
    response = _request("PUT", url, json_body=body)
    _wait_for_completion(response)
    return _json_body(response)


def list_loggers(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
) -> List[Dict[str, Any]]:
    """List APIM loggers configured on the service."""
    url = f"{_service_scope(subscription_id, resource_group, apim_name)}/loggers"
    response = _request("GET", url)
    return _json_body(response).get("value", [])


def get_logger(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    logger_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetch an APIM logger, returning None if it does not exist."""
    url = f"{_service_scope(subscription_id, resource_group, apim_name)}/loggers/{logger_id}"
    response = _request("GET", url)
    if response.status_code == 404:
        return None
    return _json_body(response)


def _reject_platform_logger(logger_id: str) -> None:
    if (logger_id or "").strip().lower() == PLATFORM_LOGGER_ID:
        raise ValueError(
            f"Logger '{PLATFORM_LOGGER_ID}' is platform-owned (Bicep); notebook helpers "
            "must use their own explicit logger ID."
        )


def _normalize_resource_id(resource_id: Optional[str]) -> str:
    return (resource_id or "").strip().rstrip("/").lower()


def ensure_logger(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    logger_id: str,
    *,
    app_insights_connection_string: str,
    app_insights_resource_id: Optional[str] = None,
    identity_client_id: Optional[str] = None,
    allow_local_auth: bool = False,
    description: str = "",
) -> Dict[str, Any]:
    """Create or update an APIM Application Insights logger using managed-identity ingestion.

    Credentials follow the documented shape
    ``{"connectionString": ..., "identityClientId": ...}``: the user-assigned
    identity client ID when ``identity_client_id`` is set, otherwise
    ``"SystemAssigned"``. The chosen APIM identity needs the Monitoring Metrics
    Publisher role on the Application Insights component. A connection-string-only
    (local authentication) logger is written only when ``allow_local_auth`` is
    explicitly True, which headless mode rejects. The platform logger
    ``apimlogger`` is never written by this helper.
    """
    _reject_platform_logger(logger_id)
    if not (app_insights_connection_string or "").strip():
        raise ValueError(
            "APIM requires credentials on an Application Insights logger. "
            "Set APP_INSIGHTS_CONNECTION_STRING from the Application Insights "
            "resource's Overview blade before calling ensure_logger."
        )
    if allow_local_auth and is_headless():
        raise ConfigError(
            "A connection-string-only (local authentication) logger is not permitted "
            "in headless mode."
        )
    app_insights_resource_id = (app_insights_resource_id or "").strip()

    credentials: Dict[str, Any] = {"connectionString": app_insights_connection_string}
    if not allow_local_auth:
        credentials["identityClientId"] = (
            _validate_identity_client_id(identity_client_id)
            if identity_client_id and identity_client_id.strip()
            else SYSTEM_ASSIGNED_IDENTITY
        )

    url = f"{_service_scope(subscription_id, resource_group, apim_name)}/loggers/{logger_id}"
    properties: Dict[str, Any] = {
        "loggerType": "applicationInsights",
        "description": description or logger_id,
        "isBuffered": True,
        "credentials": credentials,
    }
    if app_insights_resource_id:
        properties["resourceId"] = app_insights_resource_id

    response = _request("PUT", url, json_body={"properties": properties})
    _wait_for_completion(response)
    return _json_body(response)


def get_app_insights_logger(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    logger_id: str,
    expected_app_insights_resource_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Look up one Application Insights logger by explicit ID.

    Returns None only when the named logger does not exist. Raises when it
    exists but is not an Application Insights logger, or when it points to a
    different Application Insights resource than
    ``expected_app_insights_resource_id``. There is no "first logger" fallback.
    """
    logger = get_logger(subscription_id, resource_group, apim_name, logger_id)
    if logger is None:
        return None
    props = logger.get("properties", {}) or {}
    if props.get("loggerType") != "applicationInsights":
        raise ValueError(f"Logger '{logger_id}' is not an Application Insights logger.")
    actual_resource_id = props.get("resourceId")
    if expected_app_insights_resource_id and (
        _normalize_resource_id(actual_resource_id)
        != _normalize_resource_id(expected_app_insights_resource_id)
    ):
        raise ValueError(
            f"Logger '{logger_id}' points to a different Application Insights resource "
            "than APP_INSIGHTS_RESOURCE_ID."
        )
    credentials = props.get("credentials") or {}
    return {
        "logger_id": logger_id,
        "logger_resource_id": logger.get("id"),
        "app_insights_resource_id": actual_resource_id,
        "description": props.get("description", ""),
        "identity_client_id": credentials.get("identityClientId"),
    }


def ensure_api_diagnostic(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    api_id: str,
    logger_id: str,
) -> Dict[str, Any]:
    """Enable API-scope Application Insights diagnostics for custom metrics only.

    The ``largeLanguageModel`` block is omitted so no LLM request or response
    messages are captured; the ``2025-09-01-preview`` schema offers only
    ``messages: "all"``. The published schema also lists
    ``largeLanguageModel.logs`` (``enabled``/``disabled``), but its runtime
    acceptance is not verified here, so it is not sent. HTTP body logging stays
    at 0 bytes and no headers are logged. Verify the result with
    :func:`assert_no_llm_message_capture` on a readback.
    """
    _reject_platform_logger(logger_id)
    diagnostic_id = "applicationinsights"
    logger_resource_id = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}/loggers/{logger_id}"
    )
    url = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}"
        f"/apis/{api_id}/diagnostics/{diagnostic_id}"
    )
    no_capture = {"headers": [], "body": {"bytes": 0}}
    properties = {
        "alwaysLog": "allErrors",
        "loggerId": logger_resource_id,
        # "Support custom metrics" in the portal. Without it emit-metric and
        # llm-emit-token-metric run, the request succeeds, and the metric is
        # silently discarded. ARM PUT is a full replace, so this must be sent on
        # every call or the setting reverts to its default of false.
        "metrics": True,
        "sampling": {"samplingType": "fixed", "percentage": 100},
        "frontend": {"request": dict(no_capture), "response": dict(no_capture)},
        "backend": {"request": dict(no_capture), "response": dict(no_capture)},
    }
    response = _request(
        "PUT",
        url,
        params={"api-version": APIM_PREVIEW_API_VERSION},
        json_body={"properties": properties},
    )
    _wait_for_completion(response)
    return _json_body(response)


def assert_no_llm_message_capture(diagnostic: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Raise :class:`PrivacyConfigurationError` if a diagnostic readback captures content.

    Fails when the diagnostic is missing, when LLM logs are enabled, when LLM
    request/response messages are configured without ``logs: "disabled"``, or
    when any HTTP body byte limit is nonzero. Returns scalar evidence.
    """
    if not diagnostic:
        raise PrivacyConfigurationError("API diagnostic readback is missing.")
    props = diagnostic.get("properties", diagnostic) or {}
    llm = props.get("largeLanguageModel") or {}
    llm_logs = str(llm.get("logs") or "").lower()
    message_settings = [
        (llm.get(direction) or {}).get("messages") for direction in ("requests", "responses")
    ]
    if llm_logs == "enabled" or (llm_logs != "disabled" and any(message_settings)):
        raise PrivacyConfigurationError(
            "API diagnostic captures LLM request/response messages; message capture must stay off."
        )
    max_body_bytes = 0
    for pipeline in ("frontend", "backend"):
        for direction in ("request", "response"):
            settings = ((props.get(pipeline) or {}).get(direction) or {})
            max_body_bytes = max(max_body_bytes, int((settings.get("body") or {}).get("bytes") or 0))
    if max_body_bytes:
        raise PrivacyConfigurationError(
            f"API diagnostic logs up to {max_body_bytes} HTTP body bytes; body capture must stay at 0."
        )
    return {
        "llm_block_present": bool(llm),
        "llm_logs": llm_logs or "absent",
        "max_body_bytes": max_body_bytes,
        "metrics": bool(props.get("metrics")),
    }


def get_api_diagnostic(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    api_id: str,
    diagnostic_id: str = "applicationinsights",
) -> Optional[Dict[str, Any]]:
    """Fetch an API diagnostic, returning None if it does not exist."""
    url = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}"
        f"/apis/{api_id}/diagnostics/{diagnostic_id}"
    )
    response = _request(
        "GET",
        url,
        params={"api-version": APIM_PREVIEW_API_VERSION},
    )
    if response.status_code == 404:
        return None
    return _json_body(response)


def app_insights_resource_id(
    subscription_id: str,
    resource_group: str,
    app_insights_name: str,
) -> str:
    """Build an Application Insights component resource id."""
    return (
        f"{_resource_group_scope(subscription_id, resource_group)}"
        f"/providers/Microsoft.Insights/components/{app_insights_name}"
    )


def check_custom_metric_dimensions_enabled(
    app_insights_resource_id: Optional[str],
) -> Dict[str, Any]:
    """Best-effort check for App Insights custom metric dimensions support.

    ARM does not expose this portal setting consistently across environments.
    When the setting cannot be detected, callers should show the returned
    manual remediation text instead of treating the check as silently passed.
    """
    if not app_insights_resource_id:
        return {
            "status": "MANUAL",
            "detail": "No Application Insights resource id is known.",
            "remediation": (
                "Open the Application Insights resource in the Azure portal, "
                "go to Usage and estimated costs, and enable 'Alerting on "
                "custom metric dimensions'."
            ),
            "portal_url": "https://portal.azure.com/",
        }

    url = f"{ARM_BASE}{app_insights_resource_id}/currentbillingfeatures"
    try:
        response = _request(
            "GET",
            url,
            params={"api-version": "2015-05-01"},
            ok_statuses=[200, 404],
        )
    except Exception as exc:
        return {
            "status": "MANUAL",
            "detail": f"ARM check was not available: {exc}",
            "remediation": (
                "Open the Application Insights resource in the Azure portal, "
                "go to Usage and estimated costs, and enable 'Alerting on "
                "custom metric dimensions'."
            ),
            "portal_url": _portal_url(app_insights_resource_id, "usageAndEstimatedCosts"),
        }

    if response.status_code == 404:
        return {
            "status": "MANUAL",
            "detail": "This App Insights setting was not exposed by ARM.",
            "remediation": (
                "Open the Application Insights resource in the Azure portal, "
                "go to Usage and estimated costs, and enable 'Alerting on "
                "custom metric dimensions'."
            ),
            "portal_url": _portal_url(app_insights_resource_id, "usageAndEstimatedCosts"),
        }

    data = _json_body(response)
    features = data.get("currentBillingFeatures") or data.get("properties", {}).get(
        "currentBillingFeatures", []
    )
    enabled = any(
        str(feature).lower() in {"metricdimensions", "custommetricdimensions"}
        for feature in features
    )
    return {
        "status": "PASS" if enabled else "MANUAL",
        "detail": (
            "ARM reported custom metric dimensions support."
            if enabled
            else "ARM response did not explicitly confirm the portal setting."
        ),
        "remediation": (
            "No action needed."
            if enabled
            else "In the Application Insights portal, go to Usage and estimated "
            "costs and enable 'Alerting on custom metric dimensions'."
        ),
        "portal_url": _portal_url(app_insights_resource_id, "usageAndEstimatedCosts"),
    }


def query_token_metrics(
    resource_id: str,
    metric_names: Iterable[str],
    namespace: str = "module8",
    dimension_name: str = "ClientApp",
    subscription_filter: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    interval_minutes: int = 5,
    region: Optional[str] = None,
    app_insights_resource_id: Optional[str] = None,
    logger_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query APIM token metrics, split by a dimension, from Application Insights.

    ``llm-emit-token-metric`` publishes its custom metrics *through the APIM
    Application Insights logger*; the policy's ``namespace`` attribute is only a
    label on the App Insights custom metric. It does not create an Azure Monitor
    metric namespace on the APIM resource, and custom metric namespaces are not
    served at APIM resource scope at all. The batch/multi-resource metrics API
    (``MetricsClient.query_resources``) additionally always projects
    ``Microsoft.ResourceId`` and therefore requires it in the dimension filter.
    Those two constraints together mean that client can never return token
    metrics here, under any filter string - so this function reads the App
    Insights ``customMetrics`` table instead.

    ``resource_id`` is the APIM service resource id. The Application Insights
    component is ``app_insights_resource_id`` when supplied, otherwise the
    destination of the explicitly named ``logger_id`` on that service; there is
    no "first logger" discovery. ``namespace``, ``interval_minutes`` and
    ``region`` are kept for backwards compatibility with existing callers and
    are unused.
    """
    target = app_insights_resource_id
    if not target and logger_id:
        target = _app_insights_for_apim_resource_id(resource_id, logger_id)
    if not target:
        raise RuntimeError(
            "No Application Insights resource could be resolved for "
            f"{resource_id}. Pass app_insights_resource_id, or the explicit "
            "logger_id of an Application Insights logger on the APIM instance."
        )
    return query_app_insights_token_metrics(
        app_insights_resource_id=target,
        metric_names=metric_names,
        dimension_name=dimension_name,
        subscription_filter=subscription_filter,
        start_time=start_time,
        end_time=end_time,
    )


def _app_insights_for_apim_resource_id(resource_id: str, logger_id: str) -> Optional[str]:
    """Resolve the App Insights component behind one explicit logger on an APIM service."""
    parts = [part for part in resource_id.split("/") if part]
    lowered = [part.lower() for part in parts]
    expected = [
        "subscriptions",
        None,
        "resourcegroups",
        None,
        "providers",
        "microsoft.apimanagement",
        "service",
        None,
    ]
    if len(parts) < len(expected):
        return None
    if any(
        segment is not None and lowered[index] != segment
        for index, segment in enumerate(expected)
    ):
        return None
    subscription_id, resource_group, apim_name = parts[1], parts[3], parts[7]
    logger = get_app_insights_logger(subscription_id, resource_group, apim_name, logger_id)
    return (logger or {}).get("app_insights_resource_id")


def query_app_insights_token_metrics(
    app_insights_resource_id: str,
    metric_names: Iterable[str],
    dimension_name: str = "ClientApp",
    subscription_filter: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Kusto query for token metrics in the Application Insights customMetrics table."""
    from azure.monitor.query import LogsQueryClient

    from .auth import get_credential

    end_time = end_time or datetime.now(timezone.utc)
    start_time = start_time or (end_time - timedelta(minutes=30))
    metric_names_literal = ", ".join(repr(name) for name in metric_names)
    subscription_predicate = ""
    if subscription_filter:
        subscription_predicate = (
            f"| where tostring(customDimensions['Subscription ID']) == '{subscription_filter}'"
        )
    query = f"""
customMetrics
| where timestamp between (datetime({start_time.isoformat()}) .. datetime({end_time.isoformat()}))
| where name in ({metric_names_literal})
{subscription_predicate}
| extend dimension_value = tostring(customDimensions['{dimension_name}'])
| summarize total=sum(value) by bin(timestamp, 5m), metric_name=name, dimension_value
| order by timestamp asc
"""
    response = LogsQueryClient(get_credential()).query_resource(
        app_insights_resource_id,
        query,
        timespan=(start_time, end_time),
    )
    if not response.tables:
        return []
    table = response.tables[0]
    columns = [
        column if isinstance(column, str) else column.name for column in table.columns
    ]
    return [
        {
            "timestamp": row[columns.index("timestamp")],
            "metric_name": row[columns.index("metric_name")],
            "dimension_name": dimension_name,
            "dimension_value": row[columns.index("dimension_value")] or "unknown",
            "total": row[columns.index("total")],
        }
        for row in table.rows
    ]


def set_api_policy(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    api_id: str,
    policy_xml: str,
) -> Dict[str, Any]:
    """Apply (idempotent, PUT) an XML policy document at API scope."""
    url = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}"
        f"/apis/{api_id}/policies/policy"
    )
    body = {"properties": {"format": "xml", "value": policy_xml}}
    response = _request("PUT", url, json_body=body)
    _wait_for_completion(response)
    return _json_body(response)


def get_api_policy(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    api_id: str,
    policy_format: str = "rawxml",
) -> Dict[str, Any]:
    """Fetch the XML policy document applied at API scope.

    APIM defaults to ``format=xaml``, which returns the policy with attribute
    quotes and expressions XML-escaped (e.g. ``backend-id=&quot;...&quot;``).
    Request ``rawxml`` so callers can match directives such as
    ``set-backend-service`` literally instead of against escaped XML.

    ARM returns the raw XML document rather than a JSON envelope for
    ``rawxml``. This helper always returns the JSON envelope shape, so the
    policy document is available at ``["properties"]["value"]`` for both
    formats.
    """
    url = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}"
        f"/apis/{api_id}/policies/policy"
    )
    response = _request("GET", url, params={"format": policy_format})
    if response.status_code == 404:
        raise ApimError("GET", response.url, response)
    body = _json_body(response)
    if body:
        return body
    text = (response.text or "").lstrip("\ufeff")
    if not text.strip():
        return {}
    return {"properties": {"format": policy_format, "value": text}}


def get_gateway_url(subscription_id: str, resource_group: str, apim_name: str) -> str:
    """Look up the APIM instance's public gateway URL."""
    url = _service_scope(subscription_id, resource_group, apim_name)
    response = _request("GET", url)
    data = _json_body(response)
    try:
        return data["properties"]["gatewayUrl"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            f"GET {response.url} returned no APIM gateway URL"
        ) from exc


def get_subscription_key(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    apim_subscription_id: str,
) -> str:
    """Fetch the primary subscription key via ARM `listSecrets` (no user prompt)."""
    url = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}"
        f"/subscriptions/{apim_subscription_id}/listSecrets"
    )
    response = _request("POST", url, ok_statuses=[200])
    data = _json_body(response)
    try:
        return data["primaryKey"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            f"POST {response.url} returned no primary subscription key"
        ) from exc


def delete_api_if_exists(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    api_id: str,
) -> bool:
    """Delete an API if it exists; tolerates 404 so cleanup is idempotent."""
    url = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}/apis/{api_id}"
    )
    response = requests.delete(
        url,
        headers=_headers(),
        params={"api-version": API_VERSION, "deleteRevisions": "true"},
        timeout=60,
    )
    if response.status_code in (200, 202, 204, 404):
        _wait_for_completion(response)
        return response.status_code != 404
    raise ApimError("DELETE", response.url, response)


def delete_subscription_if_exists(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    apim_subscription_id: str,
) -> bool:
    """Delete an APIM subscription if it exists; tolerates 404."""
    url = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}"
        f"/subscriptions/{apim_subscription_id}"
    )
    response = requests.delete(
        url, headers=_headers(), params={"api-version": API_VERSION}, timeout=60
    )
    if response.status_code in (200, 202, 204, 404):
        return response.status_code != 404
    raise ApimError("DELETE", response.url, response)


def delete_named_value_if_exists(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    named_value_id: str,
) -> bool:
    """Delete a named value if it exists; tolerates 404."""
    url = (
        f"{_service_scope(subscription_id, resource_group, apim_name)}"
        f"/namedValues/{named_value_id}"
    )
    response = requests.delete(
        url, headers=_headers(), params={"api-version": API_VERSION}, timeout=60
    )
    if response.status_code in (200, 202, 204, 404):
        return response.status_code != 404
    raise ApimError("DELETE", response.url, response)


def delete_apim_resource_if_exists(
    subscription_id: str,
    resource_group: str,
    apim_name: str,
    resource_path: str,
) -> bool:
    """Delete an APIM child resource by path, tolerating 404 for repeatable cleanup.

    ``resource_path`` is relative to the APIM service, for example
    ``"backends/demo4-aoai-pool"`` or ``"products/demo4-resilient-pool"``.
    """
    url = f"{_service_scope(subscription_id, resource_group, apim_name)}/{resource_path.lstrip('/')}"
    response = _request(
        "DELETE", url, ok_statuses=[200, 202, 204, 404]
    )
    if response.status_code != 404:
        _wait_for_completion(response)
    return response.status_code != 404


def get_service(subscription_id: str, resource_group: str, apim_name: str) -> Dict[str, Any]:
    """Fetch the APIM service resource (used for reachability validation)."""
    url = _service_scope(subscription_id, resource_group, apim_name)
    response = _request("GET", url)
    if response.status_code == 404:
        raise ApimError("GET", response.url, response)
    data = _json_body(response)
    if not data:
        raise RuntimeError(f"GET {response.url} returned an empty or invalid JSON body")
    return data
