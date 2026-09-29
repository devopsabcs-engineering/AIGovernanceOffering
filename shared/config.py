"""Configuration loading for the AI Governance workshop notebooks.

Precedence: environment variables -> `.env` file -> interactive `input()`
prompt. Any value collected interactively is persisted back to `.env` so
subsequent runs are non-interactive. Secrets are never printed.

Headless mode (``AIGOV_HEADLESS=1``) never prompts: a missing value raises
:class:`ConfigError`, and a key whose inherited environment value differs
from `.env` raises instead of silently winning. ``DEMO_RUN`` is `.env`-owned
in headless mode, so any inherited ``DEMO_RUN`` is treated as a conflict.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

from dotenv import dotenv_values, set_key

from .auth import get_current_subscription_id, mask_secret

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"

# Fields that should never be echoed back in plain text.
SECRET_FIELDS = {"aoai_key", "app_insights_connection_string", "content_safety_key"}

# Default severity threshold (0-7, EightSeverityLevels) applied to each of the
# four llm-content-safety categories when not overridden. Choosing this value
# is a Responsible AI business decision, not an engineering default -- see
# Demo 3.
DEFAULT_CONTENT_SAFETY_THRESHOLD = "4"

# Supported Azure OpenAI request surfaces:
#   "v1"      -> Microsoft Foundry / v1 surface: POST /openai/v1/chat/completions
#                with the deployment passed in the body as "model" and no
#                api-version query parameter.
#   "classic" -> Azure OpenAI surface: POST /openai/deployments/{deployment}
#                /chat/completions?api-version=...
API_STYLES = ("v1", "classic")

HEADLESS_ENV_KEY = "AIGOV_HEADLESS"
LOCAL_AUTH_LOGGER_ENV_KEY = "DEMO2_ALLOW_LOCAL_AUTH_LOGGER"
# Keys that only the `.env` file may supply in headless mode.
FILE_OWNED_KEYS = frozenset({"DEMO_RUN"})
_TRUE_VALUES = {"1", "true", "yes"}


class ConfigError(ValueError):
    """Raised when configuration is missing or conflicting (never includes values)."""


def is_headless() -> bool:
    """Return True when running unattended (``AIGOV_HEADLESS=1``)."""
    return os.environ.get(HEADLESS_ENV_KEY, "").strip().lower() in _TRUE_VALUES


def local_auth_logger_allowed() -> bool:
    """Return True only when a connection-string-only logger is explicitly allowed.

    The flag is an interactive escape hatch for Application Insights resources
    that still accept local authentication. Headless runs must use managed
    identity ingestion, so the flag is rejected there.
    """
    allowed = os.environ.get(LOCAL_AUTH_LOGGER_ENV_KEY, "").strip().lower() in _TRUE_VALUES
    if allowed and is_headless():
        raise ConfigError(
            f"{LOCAL_AUTH_LOGGER_ENV_KEY} is not permitted in headless mode; "
            "use managed-identity logger credentials."
        )
    return allowed


@dataclass
class WorkshopConfig:
    subscription_id: Optional[str] = None
    resource_group: str = ""
    apim_name: str = ""
    aoai_endpoint: str = ""
    aoai_deployment: str = ""
    aoai_key: Optional[str] = None
    aoai_api_version: str = "2024-10-21"
    aoai_api_style: str = "v1"
    app_insights_name: Optional[str] = None
    app_insights_resource_id: Optional[str] = None
    app_insights_connection_string: Optional[str] = None
    apim_identity_client_id: Optional[str] = None
    content_safety_endpoint: str = ""
    content_safety_key: Optional[str] = None
    content_safety_blocklist_id: Optional[str] = None
    content_safety_threshold_hate: str = DEFAULT_CONTENT_SAFETY_THRESHOLD
    content_safety_threshold_selfharm: str = DEFAULT_CONTENT_SAFETY_THRESHOLD
    content_safety_threshold_sexual: str = DEFAULT_CONTENT_SAFETY_THRESHOLD
    content_safety_threshold_violence: str = DEFAULT_CONTENT_SAFETY_THRESHOLD
    demo4_ptu_east_endpoint: str = ""
    demo4_ptu_central_endpoint: str = ""
    demo4_payg_endpoint: str = ""
    demo4_ptu_east_deployment: str = ""
    demo4_ptu_central_deployment: str = ""
    demo4_payg_deployment: str = ""
    demo_run: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def as_display_dict(self) -> Dict[str, str]:
        """Return a dict safe for printing (secrets masked)."""
        data = asdict(self)
        for field_name in SECRET_FIELDS:
            if data.get(field_name):
                data[field_name] = mask_secret(data[field_name])
        return data


_ENV_KEYS = {
    "subscription_id": "AZURE_SUBSCRIPTION_ID",
    "resource_group": "APIM_RESOURCE_GROUP",
    "apim_name": "APIM_NAME",
    "aoai_endpoint": "AOAI_ENDPOINT",
    "aoai_deployment": "AOAI_DEPLOYMENT",
    "aoai_key": "AOAI_KEY",
    "aoai_api_version": "AOAI_API_VERSION",
    "aoai_api_style": "AOAI_API_STYLE",
    "app_insights_name": "APP_INSIGHTS_NAME",
    "app_insights_resource_id": "APP_INSIGHTS_RESOURCE_ID",
    "app_insights_connection_string": "APP_INSIGHTS_CONNECTION_STRING",
    "apim_identity_client_id": "APIM_IDENTITY_CLIENT_ID",
    "content_safety_endpoint": "CONTENT_SAFETY_ENDPOINT",
    "content_safety_key": "CONTENT_SAFETY_KEY",
    "content_safety_blocklist_id": "CONTENT_SAFETY_BLOCKLIST_ID",
    "content_safety_threshold_hate": "CONTENT_SAFETY_THRESHOLD_HATE",
    "content_safety_threshold_selfharm": "CONTENT_SAFETY_THRESHOLD_SELFHARM",
    "content_safety_threshold_sexual": "CONTENT_SAFETY_THRESHOLD_SEXUAL",
    "content_safety_threshold_violence": "CONTENT_SAFETY_THRESHOLD_VIOLENCE",
    "demo4_ptu_east_endpoint": "DEMO4_PTU_EAST_ENDPOINT",
    "demo4_ptu_central_endpoint": "DEMO4_PTU_CENTRAL_ENDPOINT",
    "demo4_payg_endpoint": "DEMO4_PAYG_ENDPOINT",
    "demo4_ptu_east_deployment": "DEMO4_PTU_EAST_DEPLOYMENT",
    "demo4_ptu_central_deployment": "DEMO4_PTU_CENTRAL_DEPLOYMENT",
    "demo4_payg_deployment": "DEMO4_PAYG_DEPLOYMENT",
    "demo_run": "DEMO_RUN",
}


# Environment keys this module copied from `.env` (as opposed to inherited ones).
_MANAGED_ENV_KEYS: set = set()


def _ensure_env_file() -> None:
    if not ENV_PATH.exists():
        ENV_PATH.touch()


def _persist(key: str, value: str) -> None:
    _ensure_env_file()
    # Windows: a scanner can hold .env briefly, making set_key's os.replace fail transiently.
    for attempt in range(20):
        try:
            set_key(str(ENV_PATH), _ENV_KEYS[key], value, quote_mode="never")
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.01 * (attempt + 1))


def _check_env_conflicts(file_values: Dict[str, str]) -> None:
    """Raise if inherited environment values disagree with `.env` (names only)."""
    conflicts = []
    for key, file_value in file_values.items():
        if key not in os.environ or key in _MANAGED_ENV_KEYS:
            continue
        if key in FILE_OWNED_KEYS or os.environ[key] != file_value:
            conflicts.append(key)
    for key in FILE_OWNED_KEYS:
        if key in os.environ and key not in _MANAGED_ENV_KEYS and key not in file_values:
            conflicts.append(key)
    if conflicts:
        raise ConfigError(
            "Inherited environment variables conflict with .env in headless mode: "
            f"{', '.join(sorted(set(conflicts)))}. Unset them or make .env the single source."
        )


def load_env_file() -> Dict[str, str]:
    """Copy `.env` values into ``os.environ`` without overriding inherited values.

    Keys this module loaded earlier are refreshed from the file so values
    persisted during the session (for example a reset ``DEMO_RUN``) are seen
    by the next :func:`load_config`.
    """
    if not ENV_PATH.exists():
        if is_headless():
            _check_env_conflicts({})
        return {}
    file_values = {
        key: ("" if value is None else value)
        for key, value in dotenv_values(ENV_PATH).items()
        if key
    }
    if is_headless():
        _check_env_conflicts(file_values)
    for key, value in file_values.items():
        if key not in os.environ or key in _MANAGED_ENV_KEYS:
            os.environ[key] = value
            _MANAGED_ENV_KEYS.add(key)
    return file_values


def _prompt(field_name: str, label: str, default: str = "", secret: bool = False) -> str:
    if is_headless():
        raise ConfigError(
            f"Missing required configuration key {_ENV_KEYS.get(field_name, field_name)} "
            "(headless mode never prompts; write it to .env)."
        )
    prompt_default = f" [{default}]" if default else ""
    if secret:
        import getpass

        value = getpass.getpass(f"{label}{prompt_default} (input hidden): ")
    else:
        value = input(f"{label}{prompt_default}: ")
    value = value.strip() or default
    return value


def load_config(interactive: bool = True) -> WorkshopConfig:
    """Load configuration using env vars -> .env -> interactive prompts.

    Values obtained interactively are persisted to `.env` for future runs.
    """
    headless = is_headless()
    load_env_file()

    cfg = WorkshopConfig()
    cfg.subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID") or (
        None if headless else get_current_subscription_id()
    )
    cfg.resource_group = os.environ.get("APIM_RESOURCE_GROUP", "")
    cfg.apim_name = os.environ.get("APIM_NAME", "")
    cfg.aoai_endpoint = os.environ.get("AOAI_ENDPOINT", "")
    cfg.aoai_deployment = os.environ.get("AOAI_DEPLOYMENT", "")
    cfg.aoai_key = os.environ.get("AOAI_KEY") or None
    cfg.aoai_api_version = os.environ.get("AOAI_API_VERSION", cfg.aoai_api_version)
    cfg.aoai_api_style = (
        os.environ.get("AOAI_API_STYLE", "").strip().lower() or cfg.aoai_api_style
    )
    cfg.app_insights_name = os.environ.get("APP_INSIGHTS_NAME") or None
    cfg.app_insights_resource_id = os.environ.get("APP_INSIGHTS_RESOURCE_ID") or None
    cfg.app_insights_connection_string = (
        os.environ.get("APP_INSIGHTS_CONNECTION_STRING") or None
    )
    cfg.apim_identity_client_id = (
        os.environ.get("APIM_IDENTITY_CLIENT_ID", "").strip() or None
    )
    cfg.content_safety_endpoint = os.environ.get("CONTENT_SAFETY_ENDPOINT", "")
    cfg.content_safety_key = os.environ.get("CONTENT_SAFETY_KEY") or None
    cfg.content_safety_blocklist_id = os.environ.get("CONTENT_SAFETY_BLOCKLIST_ID") or None
    cfg.content_safety_threshold_hate = (
        os.environ.get("CONTENT_SAFETY_THRESHOLD_HATE", "") or cfg.content_safety_threshold_hate
    )
    cfg.content_safety_threshold_selfharm = (
        os.environ.get("CONTENT_SAFETY_THRESHOLD_SELFHARM", "")
        or cfg.content_safety_threshold_selfharm
    )
    cfg.content_safety_threshold_sexual = (
        os.environ.get("CONTENT_SAFETY_THRESHOLD_SEXUAL", "")
        or cfg.content_safety_threshold_sexual
    )
    cfg.content_safety_threshold_violence = (
        os.environ.get("CONTENT_SAFETY_THRESHOLD_VIOLENCE", "")
        or cfg.content_safety_threshold_violence
    )
    cfg.demo4_ptu_east_endpoint = (
        os.environ.get("DEMO4_PTU_EAST_ENDPOINT", "") or cfg.demo4_ptu_east_endpoint
    )
    cfg.demo4_ptu_central_endpoint = (
        os.environ.get("DEMO4_PTU_CENTRAL_ENDPOINT", "") or cfg.demo4_ptu_central_endpoint
    )
    cfg.demo4_payg_endpoint = (
        os.environ.get("DEMO4_PAYG_ENDPOINT", "") or cfg.demo4_payg_endpoint
    )
    cfg.demo4_ptu_east_deployment = (
        os.environ.get("DEMO4_PTU_EAST_DEPLOYMENT", "") or cfg.demo4_ptu_east_deployment
    )
    cfg.demo4_ptu_central_deployment = (
        os.environ.get("DEMO4_PTU_CENTRAL_DEPLOYMENT", "")
        or cfg.demo4_ptu_central_deployment
    )
    cfg.demo4_payg_deployment = (
        os.environ.get("DEMO4_PAYG_DEPLOYMENT", "") or cfg.demo4_payg_deployment
    )
    demo_run_from_env = os.environ.get("DEMO_RUN", "")
    cfg.demo_run = demo_run_from_env or cfg.demo_run

    if not interactive:
        return cfg

    if headless:
        missing = [
            env_key
            for env_key, value in (
                ("AZURE_SUBSCRIPTION_ID", cfg.subscription_id),
                ("DEMO_RUN", demo_run_from_env),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                f"Missing required configuration keys in .env: {', '.join(missing)} "
                "(headless mode never prompts)."
            )

    if not cfg.resource_group:
        cfg.resource_group = _prompt("resource_group", "Resource group containing the APIM instance")
        _persist("resource_group", cfg.resource_group)

    if not cfg.apim_name:
        cfg.apim_name = _prompt("apim_name", "APIM instance name")
        _persist("apim_name", cfg.apim_name)

    if not cfg.aoai_endpoint:
        cfg.aoai_endpoint = _prompt(
            "aoai_endpoint", "Azure OpenAI endpoint (e.g. https://<name>.openai.azure.com/)"
        )
        _persist("aoai_endpoint", cfg.aoai_endpoint)

    if not cfg.aoai_deployment:
        cfg.aoai_deployment = _prompt("aoai_deployment", "Azure OpenAI chat deployment name")
        _persist("aoai_deployment", cfg.aoai_deployment)

    # AOAI key is optional (managed identity preferred); only ask once so
    # reruns don't nag if the user deliberately left it blank for MI.
    if cfg.aoai_key is None and "AOAI_KEY" not in _dotenv_keys():
        answer = _prompt(
            "aoai_key",
            "Azure OpenAI API key (leave blank to use managed identity)",
            secret=True,
        )
        cfg.aoai_key = answer or None
        _persist("aoai_key", cfg.aoai_key or "")

    if "AOAI_API_STYLE" not in _dotenv_keys():
        answer = _prompt(
            "aoai_api_style",
            "Azure OpenAI API style -- 'v1' for Microsoft Foundry "
            "(/openai/v1/chat/completions) or 'classic' for Azure OpenAI "
            "(/openai/deployments/...)",
            default=cfg.aoai_api_style,
        )
        answer = answer.strip().lower()
        cfg.aoai_api_style = answer if answer in API_STYLES else cfg.aoai_api_style
        _persist("aoai_api_style", cfg.aoai_api_style)

    if cfg.subscription_id:
        _persist("subscription_id", cfg.subscription_id)
    persist_demo_run(cfg.demo_run)

    return cfg


def _dotenv_keys() -> set:
    if not ENV_PATH.exists():
        return set()
    keys = set()
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0])
    return keys


def persist_demo_run(demo_run: str) -> None:
    """Persist a (regenerated) DEMO_RUN value, used by the demo reset cell.

    The process environment is updated too, so a later :func:`load_config`
    in the same kernel sees the reset value instead of the stale one.
    """
    _persist("demo_run", demo_run)
    os.environ["DEMO_RUN"] = demo_run
    _MANAGED_ENV_KEYS.add("DEMO_RUN")


def validate_config(cfg: WorkshopConfig) -> None:
    """Raise a clear error if required fields are missing."""
    missing = [
        name
        for name, value in (
            ("resource_group", cfg.resource_group),
            ("apim_name", cfg.apim_name),
            ("aoai_endpoint", cfg.aoai_endpoint),
            ("aoai_deployment", cfg.aoai_deployment),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required configuration values: {', '.join(missing)}")

    if cfg.aoai_api_style not in API_STYLES:
        raise ValueError(
            f"AOAI_API_STYLE must be one of {', '.join(API_STYLES)} "
            f"(got '{cfg.aoai_api_style}')."
        )

    parsed = urlparse(cfg.aoai_endpoint)
    if parsed.path not in ("", "/"):
        raise ValueError(
            "AOAI_ENDPOINT must be the resource root (e.g. "
            "https://<name>.services.ai.azure.com or https://<name>.openai.azure.com) "
            f"without a path -- got '{cfg.aoai_endpoint}'. Remove the "
            f"'{parsed.path}' path segment; the notebooks append the correct "
            "request path themselves."
        )


def ensure_content_safety_config(cfg: WorkshopConfig, interactive: bool = True) -> WorkshopConfig:
    """Prompt for (and persist) the Demo 3 Azure AI Content Safety values.

    Content Safety is only required starting with Demo 3, so -- unlike the
    core AOAI fields in :func:`load_config` -- these values are not prompted
    for on every notebook run. Demo 3 calls this explicitly during its
    config/preflight section; Demos 1 and 2 never call it and are unaffected.
    """
    if not cfg.content_safety_endpoint and interactive:
        cfg.content_safety_endpoint = _prompt(
            "content_safety_endpoint",
            "Azure AI Content Safety endpoint (e.g. https://<name>.cognitiveservices.azure.com)",
        )
        _persist("content_safety_endpoint", cfg.content_safety_endpoint)

    if cfg.content_safety_key is None and interactive and "CONTENT_SAFETY_KEY" not in _dotenv_keys():
        answer = _prompt(
            "content_safety_key",
            "Azure AI Content Safety API key (leave blank to use managed identity)",
            secret=True,
        )
        cfg.content_safety_key = answer or None
        _persist("content_safety_key", cfg.content_safety_key or "")

    return cfg


def validate_content_safety_config(cfg: WorkshopConfig) -> None:
    """Raise a clear error if the Demo 3 Content Safety endpoint is missing/malformed."""
    if not cfg.content_safety_endpoint:
        raise ValueError(
            "Missing required configuration value: content_safety_endpoint. Set "
            "CONTENT_SAFETY_ENDPOINT in .env, or run the Demo 3 config cell "
            "interactively."
        )

    parsed = urlparse(cfg.content_safety_endpoint)
    if parsed.path not in ("", "/"):
        raise ValueError(
            "CONTENT_SAFETY_ENDPOINT must be the resource root (e.g. "
            "https://<name>.cognitiveservices.azure.com) without a path -- got "
            f"'{cfg.content_safety_endpoint}'. Remove the '{parsed.path}' path "
            "segment; the notebook appends the correct request path itself."
        )

    for name, value in (
        ("content_safety_threshold_hate", cfg.content_safety_threshold_hate),
        ("content_safety_threshold_selfharm", cfg.content_safety_threshold_selfharm),
        ("content_safety_threshold_sexual", cfg.content_safety_threshold_sexual),
        ("content_safety_threshold_violence", cfg.content_safety_threshold_violence),
    ):
        try:
            threshold = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be an integer 0-7 (got {value!r}).")
        if not 0 <= threshold <= 7:
            raise ValueError(
                f"{name} must be between 0 (most restrictive) and 7 (least "
                f"restrictive) on the EightSeverityLevels scale (got {threshold})."
            )


def ensure_resilient_pool_config(
    cfg: WorkshopConfig, interactive: bool = True
) -> WorkshopConfig:
    """Collect optional Demo 4 pool origins, defaulting each to the primary AOAI origin.

    The optional values let a presenter demonstrate a real multi-region pool.
    Empty values intentionally fall back to the Demo 1 Azure OpenAI endpoint
    and deployment so attendees with one resource can still run the demo.
    """
    fields = (
        ("demo4_ptu_east_endpoint", "PTU East Azure OpenAI endpoint (blank = AOAI_ENDPOINT)"),
        ("demo4_ptu_central_endpoint", "PTU Central Azure OpenAI endpoint (blank = AOAI_ENDPOINT)"),
        ("demo4_payg_endpoint", "PAYG Azure OpenAI endpoint (blank = AOAI_ENDPOINT)"),
        ("demo4_ptu_east_deployment", "PTU East deployment name (blank = AOAI_DEPLOYMENT)"),
        ("demo4_ptu_central_deployment", "PTU Central deployment name (blank = AOAI_DEPLOYMENT)"),
        ("demo4_payg_deployment", "PAYG deployment name (blank = AOAI_DEPLOYMENT)"),
    )
    dotenv_keys = _dotenv_keys()
    for field_name, label in fields:
        env_key = _ENV_KEYS[field_name]
        if interactive and not getattr(cfg, field_name) and env_key not in dotenv_keys:
            value = _prompt(field_name, label)
            setattr(cfg, field_name, value)
            _persist(field_name, value)

    for field_name in (
        "demo4_ptu_east_endpoint",
        "demo4_ptu_central_endpoint",
        "demo4_payg_endpoint",
    ):
        if not getattr(cfg, field_name):
            setattr(cfg, field_name, cfg.aoai_endpoint)
    for field_name in (
        "demo4_ptu_east_deployment",
        "demo4_ptu_central_deployment",
        "demo4_payg_deployment",
    ):
        if not getattr(cfg, field_name):
            setattr(cfg, field_name, cfg.aoai_deployment)
    return cfg


def validate_resilient_pool_config(cfg: WorkshopConfig) -> None:
    """Validate Demo 4 pool roots and enforce the same-model/version rule."""
    for name in (
        "demo4_ptu_east_endpoint",
        "demo4_ptu_central_endpoint",
        "demo4_payg_endpoint",
    ):
        value = getattr(cfg, name) or cfg.aoai_endpoint
        parsed = urlparse(value)
        if (
            not value
            or parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path not in ("", "/")
        ):
            raise ValueError(
                f"{name} must be a non-empty HTTPS Azure OpenAI resource root, not {value!r}."
            )
    deployments = {
        cfg.demo4_ptu_east_deployment or cfg.aoai_deployment,
        cfg.demo4_ptu_central_deployment or cfg.aoai_deployment,
        cfg.demo4_payg_deployment or cfg.aoai_deployment,
    }
    if len(deployments) != 1:
        raise ValueError(
            "Demo 4 pool deployments must match across PTU East, PTU Central, and "
            f"PAYG (found: {', '.join(sorted(deployments))}). Use the same model and "
            "version to avoid silent model drift."
        )
