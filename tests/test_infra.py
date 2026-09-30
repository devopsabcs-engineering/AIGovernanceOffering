"""Static checks for the platform infrastructure, policies, roles, and bootstrap script."""

import json
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
POLICIES = ROOT / "policies"
ROLES = ROOT / "scripts" / "roles"
GATEWAY_POLICY = POLICIES / "platform-ai-gateway.xml"
PRODUCT_POLICY = POLICIES / "platform-team-product.xml"
BOOTSTRAP = ROOT / "scripts" / "bootstrap-lab.ps1"
DECOMMISSION = ROOT / "scripts" / "decommission-lab.ps1"

GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
LONG_HEX = re.compile(r"\b[0-9a-fA-F]{32,}\b")
CREDENTIAL_MARKERS = re.compile(r"InstrumentationKey=|AccountKey=|SharedAccessKey=|sig=", re.IGNORECASE)
CLIENT_APPS = ("retail-web", "finance-batch", "hr-assistant")

# ARM child-type segments that shared/apim.py addresses under the APIM service.
CHILD_TYPES = {
    "apis": "apis",
    "operations": "apis/operations",
    "policies": "apis/policies",
    "diagnostics": "apis/diagnostics",
    "backends": "backends",
    "namedValues": "namedValues",
    "products": "products",
    "subscriptions": "subscriptions",
    "loggers": "loggers",
}


def _inbound(path: Path) -> ET.Element:
    inbound = ET.parse(path).getroot().find("inbound")
    assert inbound is not None, f"{path.name} has no inbound section"
    return inbound


def _infra_texts():
    paths = sorted(INFRA.rglob("*.bicep")) + sorted(INFRA.rglob("*.bicepparam"))
    paths += sorted(POLICIES.glob("platform-*.xml"))
    return [(path, path.read_text(encoding="utf-8")) for path in paths]


class PlatformPolicyTests(unittest.TestCase):
    def test_every_section_calls_base(self):
        for path in (GATEWAY_POLICY, PRODUCT_POLICY):
            root = ET.parse(path).getroot()
            for section in ("inbound", "backend", "outbound", "on-error"):
                element = root.find(section)
                self.assertIsNotNone(element, f"{path.name} lacks {section}")
                self.assertIsNotNone(element.find("base"), f"{path.name} {section} lacks <base />")

    def test_exactly_one_token_metric_emitter(self):
        root = ET.parse(GATEWAY_POLICY).getroot()
        self.assertEqual(len(root.findall(".//llm-emit-token-metric")), 1)
        product_root = ET.parse(PRODUCT_POLICY).getroot()
        self.assertEqual(len(product_root.findall(".//llm-emit-token-metric")), 0)

    def test_subscription_key_header_and_query_are_stripped(self):
        inbound = _inbound(GATEWAY_POLICY)
        headers = {
            (el.get("name"), el.get("exists-action")) for el in inbound.findall("set-header")
        }
        queries = {
            (el.get("name"), el.get("exists-action"))
            for el in inbound.findall("set-query-parameter")
        }
        self.assertIn(("Ocp-Apim-Subscription-Key", "delete"), headers)
        self.assertIn(("subscription-key", "delete"), queries)
        children = [child.tag for child in inbound]
        self.assertLess(children.index("set-header"), children.index("set-backend-service"))
        self.assertLess(children.index("set-query-parameter"), children.index("set-backend-service"))

    def test_backend_and_identity_come_from_platform_objects(self):
        inbound = _inbound(GATEWAY_POLICY)
        backend = inbound.find("set-backend-service")
        self.assertEqual(backend.get("backend-id"), "ai-gateway-foundry")
        identity = inbound.find("authentication-managed-identity")
        self.assertEqual(identity.get("resource"), "https://cognitiveservices.azure.com")
        self.assertEqual(identity.get("client-id"), "{{ai-gateway-identity-client-id}}")

    def test_metric_dimensions_and_client_app_allowlist(self):
        emitter = _inbound(GATEWAY_POLICY).find("llm-emit-token-metric")
        dimensions = {el.get("name"): el.get("value") for el in emitter.findall("dimension")}
        self.assertEqual(set(dimensions), {"API ID", "Subscription ID", "ClientApp"})
        client_app = dimensions["ClientApp"]
        self.assertIn('"unknown"', client_app)
        for app in CLIENT_APPS:
            self.assertIn(f'"{app}"', client_app)
        main = (INFRA / "main.bicep").read_text(encoding="utf-8")
        self.assertIn(f"var tokenMetricNamespace = '{emitter.get('namespace')}'", main)
        for app in CLIENT_APPS:
            self.assertIn(f"'{app}'", main)

    def test_product_policy_limits_by_subscription(self):
        limit = _inbound(PRODUCT_POLICY).find("llm-token-limit")
        self.assertIsNotNone(limit)
        self.assertEqual(limit.get("counter-key"), "@(context.Subscription.Id)")
        self.assertEqual(limit.get("tokens-per-minute"), "__TOKENS_PER_MINUTE__")
        self.assertEqual(limit.get("token-quota"), "__DAILY_TOKEN_QUOTA__")
        self.assertEqual(limit.get("token-quota-period"), "Daily")


class InfraSourceTests(unittest.TestCase):
    def test_no_hardcoded_identifiers_or_keys(self):
        for path, text in _infra_texts():
            self.assertIsNone(GUID.search(text), f"GUID literal in {path.relative_to(ROOT)}")
            self.assertIsNone(LONG_HEX.search(text), f"hex key literal in {path.relative_to(ROOT)}")
            self.assertIsNone(
                CREDENTIAL_MARKERS.search(text), f"credential marker in {path.relative_to(ROOT)}"
            )

    def test_no_llm_message_logging_or_gateway_llm_logs(self):
        for path, text in _infra_texts():
            for forbidden in ("GatewayLlmLogs", "largeLanguageModel", "diagnosticSettings"):
                self.assertNotIn(forbidden, text, f"{forbidden} in {path.relative_to(ROOT)}")

    def test_local_auth_disabled_and_single_documented_suppression(self):
        bicep = "\n".join(p.read_text(encoding="utf-8") for p in INFRA.rglob("*.bicep"))
        self.assertIn("DisableLocalAuth: true", bicep)
        self.assertEqual(bicep.count("disableLocalAuth: true"), 2)
        self.assertEqual(len(re.findall(r"#disable-next-line", bicep)), 1)
        self.assertRegex(bicep, r"#disable-next-line BCP037\s+CustomMetricsOptedInType: 'WithDimensions'")

    def test_apim_uses_user_assigned_identity_and_identity_logger(self):
        apim = (INFRA / "modules" / "apim.bicep").read_text(encoding="utf-8")
        self.assertIn("type: 'UserAssigned'", apim)
        self.assertNotIn("SystemAssigned", apim)
        self.assertRegex(apim, r"identityClientId: apimIdentityClientId")
        self.assertIn("name: 'apimlogger'", apim)
        self.assertIn("metrics: true", apim)

    def test_outputs_are_not_secrets(self):
        for path in INFRA.rglob("*.bicep"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("output "):
                    lowered = line.lower()
                    for marker in ("connectionstring", "listkeys", "listsecrets", "key"):
                        self.assertNotIn(marker, lowered, f"{path.name}: {line}")

    def test_parameters_do_not_guess_the_model(self):
        params = (INFRA / "main.bicepparam").read_text(encoding="utf-8")
        for name, variable in (
            ("chatModelName", "AIGOV_CHAT_MODEL_NAME"),
            ("chatModelVersion", "AIGOV_CHAT_MODEL_VERSION"),
            ("chatDeploymentSku", "AIGOV_CHAT_DEPLOYMENT_SKU"),
            ("aiLocation", "AIGOV_AI_LOCATION"),
            ("generation", "AIGOV_GENERATION"),
        ):
            self.assertRegex(params, rf"param {name} = readEnvironmentVariable\('{variable}'\)\n")
        self.assertIn("int(readEnvironmentVariable('AIGOV_CHAT_DEPLOYMENT_CAPACITY'))", params)
        self.assertIn("readEnvironmentVariable('AIGOV_ALLOW_GLOBAL_PROCESSING', 'false')", params)
        main = (INFRA / "main.bicep").read_text(encoding="utf-8")
        self.assertIn("param allowGlobalProcessing bool = false", main)
        self.assertIn("fail(", main)
        for name in ("chatModelName", "chatModelVersion", "chatDeploymentSku", "aiLocation", "generation"):
            self.assertRegex(main, rf"param {name} string\n")
        self.assertRegex(main, r"param chatDeploymentCapacity int\n")


class RoleDefinitionTests(unittest.TestCase):
    def _role(self, name):
        return json.loads((ROLES / name).read_text(encoding="utf-8"))

    def test_operator_role_cannot_manage_the_service(self):
        actions = self._role("aigov-apim-lab-operator.json")["Actions"]
        self.assertNotIn("Microsoft.ApiManagement/service/write", actions)
        self.assertNotIn("Microsoft.ApiManagement/service/delete", actions)
        for action in actions:
            self.assertTrue(action.startswith("Microsoft.ApiManagement/service/"), action)
            self.assertNotIn("*", action)

    def test_operator_role_covers_shared_apim_inventory(self):
        actions = set(self._role("aigov-apim-lab-operator.json")["Actions"])
        source = (ROOT / "shared" / "apim.py").read_text(encoding="utf-8")
        self.assertIn("Microsoft.ApiManagement/service/read", actions)
        found = set()
        for match in re.finditer(r"/([A-Za-z]+)/\{[a-z_]+\}(?:/([A-Za-z]+))?", source):
            first, second = match.group(1), match.group(2)
            if first in CHILD_TYPES:
                found.add(CHILD_TYPES[first])
            if first == "apis" and second in CHILD_TYPES:
                found.add(CHILD_TYPES[second])
            if first == "products" and second == "apis":
                found.add("products/apis")
        if "/listSecrets" in source:
            self.assertIn("Microsoft.ApiManagement/service/subscriptions/listSecrets/action", actions)
        self.assertTrue(found, "no APIM child paths discovered in shared/apim.py")
        for child in found:
            for verb in ("read", "write"):
                self.assertIn(f"Microsoft.ApiManagement/service/{child}/{verb}", actions)

    def test_preflight_role_is_read_only(self):
        role = self._role("aigov-preflight-reader.json")
        self.assertEqual(role["AssignableScopes"], ["/subscriptions/{subscriptionId}"])
        self.assertEqual(role["DataActions"], [])
        for action in role["Actions"]:
            self.assertTrue(action.endswith("/read"), action)
            self.assertNotIn("*", action)

    def test_roles_have_placeholder_scopes_only(self):
        for name in ("aigov-apim-lab-operator.json", "aigov-preflight-reader.json"):
            role = self._role(name)
            self.assertTrue(role["IsCustom"])
            for scope in role["AssignableScopes"]:
                self.assertIsNone(GUID.search(scope), name)


class BootstrapScriptTests(unittest.TestCase):
    def setUp(self):
        self.script = BOOTSTRAP.read_text(encoding="utf-8")

    def test_dry_run_by_default(self):
        self.assertIn("[CmdletBinding(SupportsShouldProcess)]", self.script)
        self.assertIn("[switch]$Execute", self.script)
        self.assertIn("if (-not $Execute)", self.script)

    def test_no_secret_creation(self):
        for forbidden in ("credential reset", "client-secret", "gh secret", "--password", "listKeys"):
            self.assertNotIn(forbidden, self.script)

    def test_federated_subject_is_environment_bound(self):
        self.assertIn(":environment:$GitHubEnvironment", self.script)
        self.assertNotIn("ref:refs/heads", self.script)
        self.assertIn("$GitHubEnvironment = 'lab'", self.script)

    def test_federated_subject_honors_immutable_prefix(self):
        self.assertIn("$customization.sub_claim_prefix):environment:$GitHubEnvironment", self.script)


class DecommissionScriptTests(unittest.TestCase):
    def setUp(self):
        self.script = DECOMMISSION.read_text(encoding="utf-8")

    def test_dry_run_by_default_and_admin_only(self):
        self.assertIn("[CmdletBinding(SupportsShouldProcess)]", self.script)
        self.assertIn("[switch]$Execute", self.script)
        self.assertIn("if ($Execute -and $refused.Count -eq 0 -and $PSCmdlet.ShouldProcess(", self.script)
        self.assertIn("$env:GITHUB_ACTIONS -eq 'true'", self.script)

    def test_refuses_unowned_locked_or_nonempty_groups(self):
        self.assertIn("$OwnerValue = 'aigov-lab'", self.script)
        self.assertIn("'lock', 'list'", self.script)
        self.assertIn("unexpected resource(s)", self.script)
        self.assertIn("-AllowedResourceId $IdentityResourceId", self.script)
        self.assertRegex(self.script, r"Test-ResourceGroup -Name \$LabResourceGroup\)")

    def test_exports_manifest_records_and_never_purges(self):
        self.assertIn("manifest-records.json", self.script)
        self.assertLess(self.script.index("manifest-records.json"), self.script.index("'group', 'delete'"))
        self.assertNotIn("'--method', 'delete'", self.script.lower())
        self.assertNotIn("purge --execute", self.script)

    def test_never_touches_identities_roles_or_github(self):
        for forbidden in ("'ad', 'app'", "'role', 'assignment', 'delete'", "'role', 'definition'", "gh "):
            self.assertNotIn(forbidden, self.script)


if __name__ == "__main__":
    unittest.main()
