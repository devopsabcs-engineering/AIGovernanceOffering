"""Stub ARM client, HTTP responses, and helpers for the automation script tests."""

from __future__ import annotations

import copy
import io
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import aigov_common as common  # noqa: E402
import lab_session  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PRICE_FIXTURE = FIXTURES / "prices" / "fixture-snapshot.json"
SUB = "sub-test"
TENANT = "tenant-test"
RG = "rg-aigov-lab"
GEN = "g01"
SUFFIX = "abcd"
OWNER_TAGS = {"aigov-owner": "aigov-lab", "aigov-generation": GEN}

BASE_ENV = {
    "AIGOV_GENERATION": GEN,
    "AIGOV_LAB_RESOURCE_GROUP": RG,
    "AIGOV_ENVIRONMENT_NAME": "lab",
    "AIGOV_NAME_SUFFIX": SUFFIX,
    "AZURE_SUBSCRIPTION_ID": SUB,
    "AIGOV_CHAT_MODEL_NAME": "test-model",
    "AIGOV_CHAT_MODEL_VERSION": "2026-01-01",
    "AIGOV_CHAT_DEPLOYMENT_SKU": "Standard",
    "AIGOV_AI_LOCATION": "canadaeast",
}


class FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, headers: Optional[Mapping[str, str]] = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = dict(headers or {})
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class Clock:
    """Deterministic clock anchored at real time so budget deadlines stay valid."""

    def __init__(self, step_seconds: float = 1.0) -> None:
        self.current = common.utc_now()
        self.step = timedelta(seconds=step_seconds)

    def __call__(self):
        self.current += self.step
        return self.current


def target() -> "lab_session.Target":
    return lab_session.Target(SUB, RG, GEN, "lab", SUFFIX, TENANT)


def inventory() -> Dict[str, List[Dict[str, str]]]:
    return lab_session.planned_inventory(target())


class FakeArm(common.ArmClient):
    """In-memory ARM: resources, deployments, locks, tombstones, and APIM secrets."""

    def __init__(self) -> None:
        super().__init__(sleep=lambda _s: None)
        self.resources: Dict[str, Dict[str, Any]] = {}
        self.deployments: Dict[str, Dict[str, Any]] = {}
        self.locks: List[Dict[str, Any]] = []
        self.deleted: Dict[str, List[Dict[str, Any]]] = {"apim": [], "cognitive": [], "workspace": []}
        self.forbidden_delete: set = set()
        self.sticky: set = set()
        self.rg_exists = True
        self.fail_record_put = False
        self.deploy_error: Optional[str] = None
        self.deploy_partial = 0
        self.what_if_changes: List[Dict[str, Any]] = []
        self.canned: Dict[str, Any] = {}
        self.secrets: Dict[str, str] = {}
        self.calls: List[tuple] = []
        self.deleted_ids: List[str] = []
        self.purged: List[str] = []

    # -- helpers for tests
    def add_resource(self, resource_id: str, name: str, tags: Optional[Mapping[str, str]] = None,
                     properties: Optional[Mapping[str, Any]] = None) -> None:
        self.resources[resource_id.lower()] = {
            "id": resource_id, "name": name, "type": common.resource_type_of(resource_id),
            "tags": dict(OWNER_TAGS if tags is None else tags), "properties": dict(properties or {}),
        }

    def add_planned(self, count: Optional[int] = None) -> None:
        entries = inventory()["expected"]
        for entry in entries[: count if count is not None else len(entries)]:
            props: Dict[str, Any] = {"provisioningState": "Succeeded"}
            if entry["type"] == "microsoft.insights/components":
                props.update(ConnectionString="InstrumentationKey=fake;IngestionEndpoint=https://example.invalid/",
                             CustomMetricsOptedInType="WithDimensions")
            self.add_resource(entry["id"], entry["name"], properties=props)

    def manifest_records(self) -> List[str]:
        return sorted(n for n in self.deployments if n.startswith(lab_session.MANIFEST_PREFIX))

    # -- transport primitives
    def account(self) -> Dict[str, str]:
        return {"tenant_id": TENANT, "subscription_id": SUB}

    def deploy_bicep(self, resource_group, name, template, parameters):
        self.calls.append(("deploy", name))
        count = self.deploy_partial if self.deploy_error else None
        self.add_planned(count)
        if self.deploy_error:
            raise common.AzError(self.deploy_error)
        self.deployments[name] = {"name": name, "properties": {"provisioningState": "Succeeded",
                                                               "outputs": deployment_outputs()}}
        return {"provisioning_state": "Succeeded", "outputs": deployment_outputs()}

    def what_if(self, resource_group, template, parameters):
        return list(self.what_if_changes)

    def rest(self, method: str, path: str, body: Optional[Mapping[str, Any]] = None) -> Any:
        self.calls.append((method, path))
        base = path.split("?", 1)[0]
        lower = base.lower()
        rg_prefix = common.rg_scope(SUB, RG).lower()
        if lower == rg_prefix + "/resources":
            if not self.rg_exists:
                raise common.AzError("not_found")
            return {"value": [r for r in self.resources.values() if r["type"].count("/") == 1]}
        if lower == rg_prefix + "/providers/microsoft.authorization/locks":
            if not self.rg_exists:
                raise common.AzError("not_found")
            return {"value": list(self.locks)}
        if lower.startswith(rg_prefix + "/providers/microsoft.resources/deployments"):
            name = base[len(rg_prefix + "/providers/Microsoft.Resources/deployments"):].strip("/")
            if not name:
                return {"value": copy.deepcopy(list(self.deployments.values()))}
            if method == "GET":
                if name not in self.deployments:
                    raise common.AzError("not_found")
                return copy.deepcopy(self.deployments[name])
            if method == "PUT":
                if self.fail_record_put:
                    raise common.AzError("forbidden")
                params = json.loads(json.dumps(body["properties"]["parameters"]))
                self.deployments[name] = {"name": name, "properties": {
                    "provisioningState": "Succeeded", "mode": body["properties"]["mode"],
                    "outputs": {"manifest": {"type": "Object", "value": params["manifest"]["value"]},
                                "contentSha256": {"type": "String", "value": params["contentSha256"]["value"]}},
                }}
                return self.deployments[name]
            if method == "DELETE":
                self.deployments.pop(name, None)
                return None
        if lower.endswith("/listsecrets"):
            sid = base.split("/")[-2]
            return {"primaryKey": self.secrets.get(sid, f"key-{sid}-0123456789abcdef")}
        if method == "GET" and lower.endswith("/providers/microsoft.apimanagement/deletedservices"):
            return {"value": self.deleted["apim"]}
        if method == "GET" and lower.endswith("/providers/microsoft.cognitiveservices/deletedaccounts"):
            return {"value": self.deleted["cognitive"]}
        if method == "GET" and lower.endswith("/providers/microsoft.operationalinsights/deletedworkspaces"):
            return {"value": self.deleted["workspace"]}
        if method == "DELETE" and ("/deletedservices/" in lower or "/deletedaccounts/" in lower):
            self.purged.append(base.rsplit("/", 1)[-1])
            return None
        if lower in self.canned:
            return copy.deepcopy(self.canned[lower])
        if method == "PUT":
            self.add_resource(base, base.rsplit("/", 1)[-1], tags={}, properties=dict((body or {}).get("properties", {})))
            return self.resources[lower]
        if lower in self.resources:
            if method == "GET":
                return copy.deepcopy(self.resources[lower])
            if method == "DELETE":
                if lower in self.forbidden_delete:
                    raise common.AzError("forbidden")
                self.deleted_ids.append(base)
                if lower not in self.sticky:
                    self.resources.pop(lower)
                return None
        raise common.AzError("not_found")


def deployment_outputs() -> Dict[str, Dict[str, Any]]:
    inv = {e["type"] + ":" + e["name"]: e["id"] for e in inventory()["expected"]}
    names = lab_session.planned_names(target())

    def rid(kind: str, name: str) -> str:
        return inv[f"{kind}:{name}"]

    values: Dict[str, Any] = {
        "AZURE_TENANT_ID": TENANT,
        "AZURE_SUBSCRIPTION_ID": SUB,
        "AZURE_RESOURCE_GROUP": RG,
        "GENERATION": GEN,
        "APIM_NAME": names["apim"],
        "APIM_RESOURCE_ID": rid("microsoft.apimanagement/service", names["apim"]),
        "APIM_GATEWAY_URL": "https://apim.example.invalid",
        "APIM_IDENTITY_CLIENT_ID": "client-id-test",
        "APIM_IDENTITY_RESOURCE_ID": "/subscriptions/sub-test/resourceGroups/rg-id/providers/x/y/z",
        "AOAI_ACCOUNT_NAME": names["model_account"],
        "AOAI_ACCOUNT_RESOURCE_ID": rid("microsoft.cognitiveservices/accounts", names["model_account"]),
        "AOAI_ENDPOINT": "https://aif.example.invalid",
        "AOAI_DEPLOYMENT": "chat",
        "AOAI_API_STYLE": "v1",
        "CONTENT_SAFETY_NAME": names["content_safety"],
        "CONTENT_SAFETY_RESOURCE_ID": rid("microsoft.cognitiveservices/accounts", names["content_safety"]),
        "CONTENT_SAFETY_ENDPOINT": "https://cs.example.invalid",
        "APP_INSIGHTS_NAME": names["app_insights"],
        "APP_INSIGHTS_RESOURCE_ID": rid("microsoft.insights/components", names["app_insights"]),
        "LOG_ANALYTICS_WORKSPACE_NAME": names["log_analytics"],
        "LOG_ANALYTICS_WORKSPACE_RESOURCE_ID": rid("microsoft.operationalinsights/workspaces", names["log_analytics"]),
        "LOG_ANALYTICS_WORKSPACE_CUSTOMER_ID": "workspace-customer-id",
        "PLATFORM_LOGGER_ID": "apimlogger",
        "PLATFORM_API_ID": "ai-gateway-api",
        "PLATFORM_API_PATH": "ai-gateway",
        "PLATFORM_BACKEND_ID": "ai-gateway-foundry",
        "TOKEN_METRIC_NAMESPACE": "aigov",
        "CLIENT_APP_ALLOWLIST": ["retail-web", "finance-batch", "hr-assistant"],
        "TEAM_PRODUCT_IDS": ["team-retail", "team-finance", "team-hr"],
        "TEAM_SUBSCRIPTION_IDS": ["team-retail-sub", "team-finance-sub", "team-hr-sub"],
    }
    return {k: {"type": "Array" if isinstance(v, list) else "String", "value": v} for k, v in values.items()}


def make_ctx(tmp: Path, arm: FakeArm, env: Optional[Dict[str, str]] = None, **overrides: Any) -> "lab_session.Context":
    ctx = lab_session.Context(
        client_factory=lambda: arm,
        paths=common.Paths(Path(tmp) / "outputs"),
        env=dict(BASE_ENV) if env is None else env,
        out=io.StringIO(),
        sleep=lambda _s: None,
        now=Clock(),
        http_post=lambda *a, **k: FakeResponse(200, {"usage": {"prompt_tokens": 5, "completion_tokens": 2}}),
        http_get=lambda *a, **k: FakeResponse(200, {}),
        logs_query=lambda *a, **k: [{"rows": 3}],
        validate_env=lambda _p: None,
        papermill=lambda *a: 0,
        env_path=Path(tmp) / ".env",
    )
    for key, value in overrides.items():
        setattr(ctx, key, value)
    return ctx


def run(ctx: "lab_session.Context", *argv: str) -> int:
    return lab_session.main(list(argv), ctx)


def start_session(ctx: "lab_session.Context", run_id: str = "100", attempt: str = "1", price: bool = True) -> str:
    argv = ["init-session", "--run-id", run_id, "--run-attempt", attempt]
    if price:
        argv += ["--price-snapshot", str(PRICE_FIXTURE)]
    assert run(ctx, *argv) == 0, ctx.out.getvalue()
    session_id = f"{run_id}-{attempt}"
    ctx.env["SESSION_ID"] = session_id
    return session_id
