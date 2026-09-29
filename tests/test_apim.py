import json
import os
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from shared import apim, config

POLICIES = Path(__file__).resolve().parents[1] / "policies"
CLIENT_ID = "11111111-2222-3333-4444-555555555555"


class ApimErrorRedactionTests(unittest.TestCase):
    def test_exception_redacts_known_secret_fields_and_truncates(self):
        body = (
            '{"primaryKey": "pk-fake-0123456789", "secondaryKey": "sk-fake", '
            '"connectionString": "InstrumentationKey=abc;IngestionEndpoint=x", '
            '"headers": {"Authorization": "Bearer fake.jwt.token", '
            '"Ocp-Apim-Subscription-Key": "subkey-fake"}, "api-key": "aoai-fake", '
            '"padding": "' + "x" * 800 + '"}'
        )
        response = SimpleNamespace(status_code=400, text=body)
        error = apim.ApimError("POST", "https://example.test/listSecrets?subscription-key=qs-fake", response)

        message = str(error)
        for secret in ("pk-fake", "sk-fake", "InstrumentationKey=abc", "fake.jwt.token",
                       "subkey-fake", "aoai-fake", "qs-fake"):
            self.assertNotIn(secret, message)
        self.assertIn("***REDACTED***", message)
        self.assertIn("truncated", error.body)
        self.assertLessEqual(len(error.body), 600)

    def test_plain_header_text_is_redacted(self):
        text = apim.redact_secrets("Authorization: Bearer abc.def api-key=xyz")
        self.assertNotIn("abc.def", text)
        self.assertNotIn("xyz", text)


class ApimPolicyTests(unittest.TestCase):
    def test_default_request_uses_llm_capable_api_version(self):
        response = SimpleNamespace(status_code=200)
        with (
            patch.object(apim, "_headers", return_value={}),
            patch.object(apim.requests, "request", return_value=response) as request,
        ):
            apim._request("GET", "https://example.test")

        self.assertEqual(
            request.call_args.kwargs["params"]["api-version"],
            "2024-06-01-preview",
        )

    def test_demo2_token_metric_is_inbound(self):
        policy_path = (
            Path(__file__).resolve().parents[1]
            / "policies"
            / "demo2-emit-token-metric.xml"
        )
        policy = ET.parse(policy_path).getroot()

        metric = policy.find("./inbound/llm-emit-token-metric")
        self.assertIsNotNone(metric)
        self.assertEqual(metric.attrib["namespace"], "module8")
        self.assertEqual(
            [dimension.attrib["name"] for dimension in metric.findall("dimension")],
            ["API ID", "Subscription ID", "ClientApp"],
        )
        self.assertIsNone(policy.find("./outbound/llm-emit-token-metric"))
        self.assertEqual(
            [child.tag for child in policy.find("outbound")],
            ["base"],
        )

    def test_demo3_content_safety_is_configured_in_both_directions(self):
        policy_path = (
            Path(__file__).resolve().parents[1]
            / "policies"
            / "demo3-content-safety.xml"
        )
        policy = ET.parse(policy_path).getroot()

        inbound = policy.find("./inbound/llm-content-safety")
        self.assertIsNotNone(inbound)
        self.assertEqual(inbound.attrib["backend-id"], "demo3-content-safety-backend")
        self.assertEqual(inbound.attrib["shield-prompt"], "true")
        self.assertEqual(inbound.attrib["enforce-on-completions"], "true")

        inbound_categories = inbound.find("categories")
        self.assertIsNotNone(inbound_categories)
        self.assertEqual(inbound_categories.attrib["output-type"], "EightSeverityLevels")
        self.assertEqual(
            {c.attrib["name"] for c in inbound_categories.findall("category")},
            {"Hate", "SelfHarm", "Sexual", "Violence"},
        )
        for category in inbound_categories.findall("category"):
            self.assertEqual(
                category.attrib["threshold"],
                f"{{{{demo3-content-safety-threshold-{category.attrib['name'].lower()}}}}}",
            )

        outbound = policy.find("./outbound/llm-content-safety")
        self.assertIsNotNone(outbound)
        self.assertEqual(outbound.attrib["backend-id"], "demo3-content-safety-backend")
        self.assertIn("window-size", outbound.attrib)
        self.assertIn("window-overlap-size", outbound.attrib)
        # enforce-on-completions only affects inbound and is ignored outbound,
        # so it should not be present here.
        self.assertNotIn("enforce-on-completions", outbound.attrib)

        on_error_choose = policy.find("./on-error/choose")
        self.assertIsNotNone(on_error_choose)
        self.assertIn(
            "llm-content-safety",
            on_error_choose.find("when").attrib["condition"],
        )

    def test_demo4_routes_to_the_pool(self):
        policy_path = (
            Path(__file__).resolve().parents[1]
            / "policies"
            / "demo4-resilient-pool.xml"
        )
        policy = ET.parse(policy_path).getroot()
        backend = policy.find("./inbound/set-backend-service")
        self.assertIsNotNone(backend)
        self.assertEqual(backend.attrib["backend-id"], "demo4-aoai-pool")
        self.assertIsNotNone(policy.find("./inbound/authentication-managed-identity"))
        self.assertEqual(
            policy.find("./outbound/set-header").attrib["name"], "x-demo4-routing"
        )

    def test_demo4_mock_origin_policy_exposes_member_and_throttle(self):
        policy_path = (
            Path(__file__).resolve().parents[1]
            / "policies"
            / "demo4-mock-origin.xml"
        )
        policy = ET.parse(policy_path).getroot()

        responses = policy.findall(".//return-response")
        self.assertGreaterEqual(len(responses), 6)
        served_by_values = [
            header.findtext("value")
            for response in responses
            for header in response.findall("set-header")
            if header.attrib.get("name") == "x-served-by"
        ]
        self.assertEqual(
            set(served_by_values),
            {"demo4-ptu-east", "demo4-ptu-central", "demo4-payg"},
        )
        throttles = [
            response for response in responses
            if response.find("set-status") is not None
            and response.find("set-status").attrib.get("code") == "429"
        ]
        self.assertEqual(len(throttles), 3)
        for response in throttles:
            retry_after = next(
                header for header in response.findall("set-header")
                if header.attrib.get("name") == "Retry-After"
            )
            self.assertIn("demo4-mock-retry-after-", retry_after.findtext("value"))
        self.assertEqual(
            policy.find("./inbound/choose/otherwise/return-response/set-status").attrib["code"],
            "404",
        )

    def test_client_policies_strip_client_subscription_credentials(self):
        for name in ("demo1-token-limit.xml", "demo2-emit-token-metric.xml", "demo3-content-safety.xml",
                     "demo4-resilient-pool.xml"):
            with self.subTest(policy=name):
                inbound = ET.parse(POLICIES / name).getroot().find("inbound")
                children = list(inbound)
                tags = [child.tag for child in children]
                header = next(
                    child for child in children
                    if child.tag == "set-header"
                    and child.attrib.get("name") == "Ocp-Apim-Subscription-Key"
                )
                query = next(
                    child for child in children
                    if child.tag == "set-query-parameter"
                    and child.attrib.get("name") == "subscription-key"
                )
                self.assertEqual(header.attrib["exists-action"], "delete")
                self.assertEqual(query.attrib["exists-action"], "delete")
                self.assertLess(children.index(header), tags.index("set-backend-service"))
                self.assertLess(children.index(query), tags.index("set-backend-service"))

    def test_policy_files_have_no_hardcoded_client_id(self):
        for path in POLICIES.glob("demo*.xml"):
            with self.subTest(policy=path.name):
                self.assertNotIn("client-id", path.read_text(encoding="utf-8"))


class ApplyIdentityClientIdTests(unittest.TestCase):
    SELF_CLOSING = '<inbound><authentication-managed-identity resource="https://cognitiveservices.azure.com" /></inbound>'
    MULTI_LINE = (
        '<inbound>\n    <authentication-managed-identity resource="https://cognitiveservices.azure.com"\n'
        '        output-token-variable-name="aoai-token" ignore-error="false" />\n</inbound>'
    )

    def test_unset_client_id_leaves_policy_unchanged(self):
        for client_id in (None, "", "   "):
            self.assertEqual(apim.apply_identity_client_id(self.MULTI_LINE, client_id), self.MULTI_LINE)

    def test_injects_into_self_closing_element(self):
        updated = apim.apply_identity_client_id(self.SELF_CLOSING, CLIENT_ID)
        element = ET.fromstring(updated).find("authentication-managed-identity")
        self.assertEqual(element.attrib["client-id"], CLIENT_ID)
        self.assertEqual(element.attrib["resource"], "https://cognitiveservices.azure.com")

    def test_injects_into_multi_line_element_and_is_idempotent(self):
        once = apim.apply_identity_client_id(self.MULTI_LINE, CLIENT_ID)
        twice = apim.apply_identity_client_id(once, CLIENT_ID)
        self.assertEqual(once, twice)
        self.assertEqual(once.count("client-id="), 1)
        element = ET.fromstring(once).find("authentication-managed-identity")
        self.assertEqual(element.attrib["output-token-variable-name"], "aoai-token")

    def test_replaces_a_different_existing_client_id(self):
        other = "99999999-2222-3333-4444-555555555555"
        updated = apim.apply_identity_client_id(
            apim.apply_identity_client_id(self.SELF_CLOSING, other), CLIENT_ID
        )
        self.assertIn(CLIENT_ID, updated)
        self.assertNotIn(other, updated)

    def test_every_real_policy_element_is_updated(self):
        for name in ("demo1-token-limit.xml", "demo4-resilient-pool.xml"):
            with self.subTest(policy=name):
                xml = (POLICIES / name).read_text(encoding="utf-8")
                root = ET.fromstring(apim.apply_identity_client_id(xml, CLIENT_ID))
                elements = root.iter("authentication-managed-identity")
                self.assertTrue(all(e.attrib["client-id"] == CLIENT_ID for e in elements))

    def test_rejects_non_guid_client_id(self):
        with self.assertRaisesRegex(ValueError, "GUID"):
            apim.apply_identity_client_id(self.SELF_CLOSING, '" injected="1')


class EnsureBackendTests(unittest.TestCase):
    def test_put_body_omits_credentials_when_not_supplied(self):
        response = SimpleNamespace(status_code=200, content=b"{}", text="{}")

        with patch.object(apim, "_request", return_value=response) as request:
            apim.ensure_backend(
                "sub",
                "rg",
                "apim",
                "demo3-openai-backend",
                "https://example.openai.azure.com",
            )

        properties = request.call_args.kwargs["json_body"]["properties"]
        self.assertNotIn("credentials", properties)

    def test_put_body_includes_managed_identity_credentials(self):
        response = SimpleNamespace(status_code=200, content=b"{}", text="{}")

        with patch.object(apim, "_request", return_value=response) as request:
            apim.ensure_backend(
                "sub",
                "rg",
                "apim",
                "demo3-content-safety-backend",
                "https://example.cognitiveservices.azure.com",
                credentials={
                    "managedIdentity": {
                        "resource": "https://cognitiveservices.azure.com"
                    }
                },
            )

        self.assertEqual(request.call_args.args[0], "PUT")
        self.assertTrue(
            request.call_args.args[1].endswith(
                "/backends/demo3-content-safety-backend"
            )
        )
        properties = request.call_args.kwargs["json_body"]["properties"]
        self.assertEqual(
            properties["credentials"]["managedIdentity"]["resource"],
            "https://cognitiveservices.azure.com",
        )

    def test_managed_identity_credentials_add_client_id_only_when_configured(self):
        self.assertEqual(
            apim.managed_identity_backend_credentials(None),
            {"managedIdentity": {"resource": "https://cognitiveservices.azure.com"}},
        )
        self.assertEqual(
            apim.managed_identity_backend_credentials(CLIENT_ID),
            {"managedIdentity": {"resource": "https://cognitiveservices.azure.com",
                                 "clientId": CLIENT_ID}},
        )

    def test_backend_credential_header_names_never_return_values(self):
        backend = {"properties": {"credentials": {"header": {"Ocp-Apim-Subscription-Key": ["secret"]}}}}
        self.assertEqual(apim.backend_credential_header_names(backend), ["Ocp-Apim-Subscription-Key"])
        self.assertEqual(apim.backend_credential_header_names({"properties": {}}), [])
        self.assertEqual(apim.backend_credential_header_names(None), [])

    def test_put_body_includes_circuit_breaker(self):
        response = SimpleNamespace(status_code=200, content=b"{}", text="{}")
        breaker = {"rules": [{"name": "demo4-throttle-and-server-errors"}]}
        with patch.object(apim, "_request", return_value=response) as request:
            apim.ensure_backend("sub", "rg", "apim", "demo4-ptu-east", "https://example.test", circuit_breaker=breaker)
        self.assertEqual(request.call_args.kwargs["json_body"]["properties"]["circuitBreaker"], breaker)

    BACKENDS_ARM_PATH = (
        "/subscriptions/sub/resourceGroups/rg"
        "/providers/Microsoft.ApiManagement/service/apim/backends"
    )

    def _pool_services(self, members):
        response = SimpleNamespace(status_code=200, content=b"{}", text="{}")
        with patch.object(apim, "_request", return_value=response) as request:
            apim.ensure_backend_pool("sub", "rg", "apim", "demo4-aoai-pool", members)
        self.assertEqual(request.call_args.args[0], "PUT")
        self.assertEqual(
            request.call_args.args[1],
            f"{apim.ARM_BASE}{self.BACKENDS_ARM_PATH}/demo4-aoai-pool",
        )
        properties = request.call_args.kwargs["json_body"]["properties"]
        self.assertEqual(properties["type"], "Pool")
        self.assertNotIn("url", properties)
        self.assertNotIn("protocol", properties)
        return properties["pool"]["services"]

    def test_pool_backend_uses_arm_ids_for_short_member_names(self):
        services = self._pool_services([
            {"id": "demo4-ptu-east", "priority": 1, "weight": 2},
            {"id": "demo4-ptu-central", "priority": 1, "weight": 1},
            {"id": "demo4-payg", "priority": 2, "weight": 1},
        ])
        self.assertEqual(
            [service["id"] for service in services],
            [
                f"{self.BACKENDS_ARM_PATH}/demo4-ptu-east",
                f"{self.BACKENDS_ARM_PATH}/demo4-ptu-central",
                f"{self.BACKENDS_ARM_PATH}/demo4-payg",
            ],
        )

    def test_pool_backend_does_not_double_prefix_qualified_ids(self):
        arm_id = f"{self.BACKENDS_ARM_PATH}/demo4-ptu-east"
        services = self._pool_services([
            {"id": arm_id, "priority": 1, "weight": 2},
            {"id": f"{apim.ARM_BASE}{arm_id}", "priority": 1, "weight": 1},
        ])
        self.assertEqual([service["id"] for service in services], [arm_id, arm_id])

    def test_pool_backend_preserves_priority_weight_without_extra_keys(self):
        members = [
            {"id": "demo4-ptu-east", "priority": 1, "weight": 2, "endpoint": "x"},
            {"id": "demo4-payg", "priority": 2, "weight": 1},
        ]
        services = self._pool_services(members)
        self.assertEqual(
            services,
            [
                {"id": f"{self.BACKENDS_ARM_PATH}/demo4-ptu-east", "priority": 1, "weight": 2},
                {"id": f"{self.BACKENDS_ARM_PATH}/demo4-payg", "priority": 2, "weight": 1},
            ],
        )
        self.assertEqual(members[0]["id"], "demo4-ptu-east")
        self.assertIn("endpoint", members[0])

    def test_pool_backend_requires_positive_priority_and_weight(self):
        with self.assertRaisesRegex(ValueError, "priority"):
            apim.ensure_backend_pool(
                "sub", "rg", "apim", "pool", [{"id": "member", "priority": 0, "weight": 1}]
            )

    def test_pool_backend_validation_errors(self):
        invalid_members = [
            [],
            [{"priority": 1, "weight": 1}],
            [{"id": "", "priority": 1, "weight": 1}],
            [{"id": "member", "priority": 1, "weight": 0}],
            [{"id": "member", "priority": -1, "weight": 1}],
            [{"id": "member", "priority": 1.5, "weight": 1}],
            [{"id": "member", "priority": 1, "weight": "2"}],
            [{"id": "member", "priority": True, "weight": 1}],
            [{"id": "member", "priority": 1}],
        ]
        for members in invalid_members:
            with self.subTest(members=members):
                with (
                    patch.object(apim, "_request") as request,
                    self.assertRaises(ValueError),
                ):
                    apim.ensure_backend_pool("sub", "rg", "apim", "pool", members)
                request.assert_not_called()


class DeleteApimResourceTests(unittest.TestCase):
    def test_missing_resource_does_not_wait_for_completion(self):
        response = SimpleNamespace(status_code=404)
        with (
            patch.object(apim, "_request", return_value=response) as request,
            patch.object(apim, "_wait_for_completion") as wait,
        ):
            deleted = apim.delete_apim_resource_if_exists(
                "sub", "rg", "apim", "backends/demo4-ptu-east"
            )

        self.assertFalse(deleted)
        self.assertEqual(request.call_args.args[0], "DELETE")
        wait.assert_not_called()


class EnsureLoggerTests(unittest.TestCase):
    def test_requires_connection_string_even_with_resource_id(self):
        for connection_string in (None, "   "):
            with self.subTest(connection_string=connection_string):
                with patch.object(apim, "_request") as request:
                    with self.assertRaisesRegex(
                        ValueError,
                        "APIM requires credentials.*APP_INSIGHTS_CONNECTION_STRING",
                    ):
                        apim.ensure_logger(
                            "sub",
                            "rg",
                            "apim",
                            "logger",
                            app_insights_resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Insights/components/appi",
                            app_insights_connection_string=connection_string,
                        )

                request.assert_not_called()

    def test_put_body_includes_resource_id_and_connection_string(self):
        response = SimpleNamespace(status_code=200, content=b"{}", text="{}")
        resource_id = (
            "/subscriptions/sub/resourceGroups/rg/"
            "providers/Microsoft.Insights/components/appi"
        )

        with patch.object(apim, "_request", return_value=response) as request:
            apim.ensure_logger(
                "sub",
                "rg",
                "apim",
                "logger",
                app_insights_resource_id=resource_id,
                app_insights_connection_string="InstrumentationKey=key",
                description="Demo logger",
            )

        self.assertEqual(request.call_args.args[0], "PUT")
        self.assertTrue(request.call_args.args[1].endswith("/loggers/logger"))
        properties = request.call_args.kwargs["json_body"]["properties"]
        self.assertEqual(properties["resourceId"], resource_id)
        self.assertEqual(
            properties["credentials"],
            {"connectionString": "InstrumentationKey=key", "identityClientId": "SystemAssigned"},
        )

    def _logger_credentials(self, **kwargs):
        response = SimpleNamespace(status_code=200, content=b"{}", text="{}")
        with patch.object(apim, "_request", return_value=response) as request:
            apim.ensure_logger(
                "sub", "rg", "apim", "demo2-application-insights",
                app_insights_connection_string="InstrumentationKey=key", **kwargs,
            )
        return request.call_args.kwargs["json_body"]["properties"]["credentials"]

    def test_user_assigned_identity_client_id_is_written(self):
        credentials = self._logger_credentials(identity_client_id=CLIENT_ID)
        self.assertEqual(credentials["identityClientId"], CLIENT_ID)

    def test_blank_identity_defaults_to_system_assigned(self):
        for client_id in (None, "", "  "):
            with self.subTest(client_id=client_id):
                credentials = self._logger_credentials(identity_client_id=client_id)
                self.assertEqual(credentials["identityClientId"], "SystemAssigned")

    def test_connection_string_only_requires_explicit_flag(self):
        with patch.dict(os.environ, {"AIGOV_HEADLESS": ""}):
            credentials = self._logger_credentials(allow_local_auth=True)
        self.assertEqual(credentials, {"connectionString": "InstrumentationKey=key"})

    def test_headless_rejects_local_auth_logger(self):
        with patch.dict(os.environ, {"AIGOV_HEADLESS": "1"}):
            with patch.object(apim, "_request") as request:
                with self.assertRaisesRegex(config.ConfigError, "headless"):
                    apim.ensure_logger(
                        "sub", "rg", "apim", "demo2-application-insights",
                        app_insights_connection_string="InstrumentationKey=key",
                        allow_local_auth=True,
                    )
            request.assert_not_called()

    def test_local_auth_flag_is_rejected_in_headless_mode(self):
        with patch.dict(os.environ, {"AIGOV_HEADLESS": "1", "DEMO2_ALLOW_LOCAL_AUTH_LOGGER": "true"}):
            with self.assertRaises(config.ConfigError):
                config.local_auth_logger_allowed()
        with patch.dict(os.environ, {"AIGOV_HEADLESS": "", "DEMO2_ALLOW_LOCAL_AUTH_LOGGER": "true"}):
            self.assertTrue(config.local_auth_logger_allowed())
        with patch.dict(os.environ, {"AIGOV_HEADLESS": "1", "DEMO2_ALLOW_LOCAL_AUTH_LOGGER": ""}):
            self.assertFalse(config.local_auth_logger_allowed())

    def test_platform_logger_is_never_written(self):
        for logger_id in ("apimlogger", "APIMLogger"):
            with self.subTest(logger_id=logger_id):
                with patch.object(apim, "_request") as request:
                    with self.assertRaisesRegex(ValueError, "platform-owned"):
                        apim.ensure_logger(
                            "sub", "rg", "apim", logger_id,
                            app_insights_connection_string="InstrumentationKey=key",
                        )
                request.assert_not_called()


class GetAppInsightsLoggerTests(unittest.TestCase):
    APPI = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Insights/components/appi"

    def _logger(self, resource_id, identity="SystemAssigned", logger_type="applicationInsights"):
        return {
            "id": "/subscriptions/sub/.../loggers/demo2-application-insights",
            "properties": {
                "loggerType": logger_type,
                "resourceId": resource_id,
                "credentials": {"connectionString": "{{Logger-Credentials--x}}", "identityClientId": identity},
            },
        }

    def test_absent_logger_returns_none(self):
        with patch.object(apim, "get_logger", return_value=None) as get_logger:
            self.assertIsNone(apim.get_app_insights_logger("sub", "rg", "apim", "demo2-application-insights", self.APPI))
        get_logger.assert_called_once_with("sub", "rg", "apim", "demo2-application-insights")

    def test_matching_logger_returns_identity(self):
        with patch.object(apim, "get_logger", return_value=self._logger(self.APPI.upper() + "/")):
            info = apim.get_app_insights_logger("sub", "rg", "apim", "demo2-application-insights", self.APPI)
        self.assertEqual(info["identity_client_id"], "SystemAssigned")
        self.assertEqual(info["logger_id"], "demo2-application-insights")

    def test_different_destination_raises(self):
        other = self.APPI.replace("appi", "other")
        with patch.object(apim, "get_logger", return_value=self._logger(other)):
            with self.assertRaisesRegex(ValueError, "different Application Insights"):
                apim.get_app_insights_logger("sub", "rg", "apim", "demo2-application-insights", self.APPI)

    def test_wrong_logger_type_raises(self):
        with patch.object(apim, "get_logger", return_value=self._logger(self.APPI, logger_type="azureEventHub")):
            with self.assertRaisesRegex(ValueError, "not an Application Insights"):
                apim.get_app_insights_logger("sub", "rg", "apim", "demo2-application-insights")

    def test_first_logger_discovery_is_removed(self):
        self.assertFalse(hasattr(apim, "get_app_insights_for_apim"))
        with patch.object(apim, "list_loggers", side_effect=AssertionError("no discovery")), \
                patch.object(apim, "get_logger", return_value=None):
            apim.get_app_insights_logger("sub", "rg", "apim", "demo2-application-insights")

    def _response(self, status, body):
        response = unittest.mock.Mock(status_code=status)
        response.text = json.dumps(body)
        response.content = response.text.encode("utf-8")
        return response

    def _named_values(self, secret, value=None):
        props = {"displayName": "Logger-Credentials--2", "secret": secret}
        if value is not None:
            props["value"] = value
        return {"value": [{"name": "nv2", "properties": props}]}

    def test_secret_reference_resolved_with_list_value(self):
        responses = [self._response(200, self._named_values(True)), self._response(200, {"value": "client-1"})]
        with patch.object(apim, "get_logger", return_value=self._logger(self.APPI, "{{Logger-Credentials--2}}")), \
                patch.object(apim, "_request", side_effect=responses) as request:
            info = apim.get_app_insights_logger("sub", "rg", "apim", "demo2-application-insights", self.APPI)
        self.assertEqual(info["identity_client_id"], "client-1")
        self.assertTrue(request.call_args_list[1].args[1].endswith("/namedValues/nv2/listValue"))

    def test_unlistable_secret_reference_is_not_returned(self):
        responses = [self._response(200, self._named_values(True)), self._response(403, {})]
        with patch.object(apim, "get_logger", return_value=self._logger(self.APPI, "{{Logger-Credentials--2}}")), \
                patch.object(apim, "_request", side_effect=responses):
            info = apim.get_app_insights_logger("sub", "rg", "apim", "demo2-application-insights", self.APPI)
        self.assertIsNone(info["identity_client_id"])

    def test_plain_reference_resolved_without_list_value(self):
        responses = [self._response(200, self._named_values(False, "client-2"))]
        with patch.object(apim, "get_logger", return_value=self._logger(self.APPI, "{{Logger-Credentials--2}}")), \
                patch.object(apim, "_request", side_effect=responses) as request:
            info = apim.get_app_insights_logger("sub", "rg", "apim", "demo2-application-insights", self.APPI)
        self.assertEqual(info["identity_client_id"], "client-2")
        self.assertEqual(request.call_count, 1)


class EnsureApiDiagnosticTests(unittest.TestCase):
    def _put_properties(self, logger_id="logger"):
        response = SimpleNamespace(status_code=200, content=b"{}", text="{}")
        with patch.object(apim, "_request", return_value=response) as request:
            apim.ensure_api_diagnostic("sub", "rg", "apim", "api", logger_id)
        self.assertEqual(request.call_count, 1)
        return request.call_args.kwargs["json_body"]["properties"]

    def test_put_body_has_no_llm_message_capture(self):
        properties = self._put_properties()
        self.assertNotIn("largeLanguageModel", properties)
        self.assertNotIn("messages", repr(properties))
        self.assertEqual(properties["alwaysLog"], "allErrors")
        self.assertIs(properties["metrics"], True)
        self.assertTrue(properties["loggerId"].endswith("/loggers/logger"))
        self.assertIn("sampling", properties)

    def test_put_body_logs_no_http_bodies_or_headers(self):
        properties = self._put_properties()
        for pipeline in ("frontend", "backend"):
            for direction in ("request", "response"):
                settings = properties[pipeline][direction]
                self.assertEqual(settings["body"]["bytes"], 0)
                self.assertEqual(settings["headers"], [])

    def test_put_body_passes_privacy_readback_check(self):
        evidence = apim.assert_no_llm_message_capture({"properties": self._put_properties()})
        self.assertEqual(evidence["max_body_bytes"], 0)
        self.assertFalse(evidence["llm_block_present"])

    def test_platform_logger_is_rejected(self):
        with patch.object(apim, "_request") as request:
            with self.assertRaisesRegex(ValueError, "platform-owned"):
                apim.ensure_api_diagnostic("sub", "rg", "apim", "api", "apimlogger")
        request.assert_not_called()

    def test_errors_are_not_retried_with_other_settings(self):
        failed_response = SimpleNamespace(status_code=400, text="Invalid field 'loggerId'")
        error = apim.ApimError("PUT", "https://example.test", failed_response)
        with patch.object(apim, "_request", side_effect=error) as request:
            with self.assertRaisesRegex(apim.ApimError, "loggerId"):
                apim.ensure_api_diagnostic("sub", "rg", "apim", "api", "logger")
        self.assertEqual(request.call_count, 1)


class AssertNoLlmMessageCaptureTests(unittest.TestCase):
    def test_rejects_message_capture_and_body_bytes(self):
        failing = [
            None,
            {"properties": {"largeLanguageModel": {"requests": {"messages": "all"}}}},
            {"properties": {"largeLanguageModel": {"logs": "enabled"}}},
            {"properties": {"frontend": {"request": {"body": {"bytes": 8192}}}}},
            {"properties": {"backend": {"response": {"body": {"bytes": 1}}}}},
        ]
        for diagnostic in failing:
            with self.subTest(diagnostic=diagnostic):
                with self.assertRaises(apim.PrivacyConfigurationError):
                    apim.assert_no_llm_message_capture(diagnostic)

    def test_accepts_disabled_llm_logs(self):
        evidence = apim.assert_no_llm_message_capture({"properties": {
            "metrics": True,
            "largeLanguageModel": {"logs": "disabled", "requests": {"messages": "all"}},
        }})
        self.assertEqual(evidence["llm_logs"], "disabled")
        self.assertTrue(evidence["metrics"])


class GetApiPolicyTests(unittest.TestCase):
    POLICY_XML = '<policies><inbound><llm-emit-token-metric namespace="module8" /></inbound></policies>'

    def test_raw_xml_response_returns_policy_document(self):
        response = SimpleNamespace(
            status_code=200,
            content=self.POLICY_XML.encode("utf-8"),
            text=self.POLICY_XML,
        )
        with patch.object(apim, "_request", return_value=response) as request:
            policy = apim.get_api_policy("sub", "rg", "apim", "api")

        self.assertEqual(request.call_args.kwargs["params"]["format"], "rawxml")
        self.assertEqual(policy["properties"]["value"], self.POLICY_XML)
        self.assertEqual(policy["properties"]["format"], "rawxml")

    def test_json_response_is_parsed(self):
        body = '{"properties": {"format": "xaml", "value": "<policies />"}}'
        response = SimpleNamespace(status_code=200, content=body.encode("utf-8"), text=body)
        with patch.object(apim, "_request", return_value=response):
            policy = apim.get_api_policy(
                "sub", "rg", "apim", "api", policy_format="xaml"
            )

        self.assertEqual(policy["properties"]["value"], "<policies />")


class TokenMetricsTests(unittest.TestCase):
    RESOURCE_ID = (
        "/subscriptions/sub/resourceGroups/rg"
        "/providers/Microsoft.ApiManagement/service/apim"
    )

    APP_INSIGHTS_ID = (
        "/subscriptions/sub/resourceGroups/rg"
        "/providers/Microsoft.Insights/components/appi"
    )

    def _fake_logs_client(self, tables, calls):
        def fake_client(credential):
            def query_resource(resource_id, query, timespan=None, **kwargs):
                calls.append({"resource_id": resource_id, "query": query})
                return SimpleNamespace(tables=tables)

            return SimpleNamespace(query_resource=query_resource)

        return SimpleNamespace(LogsQueryClient=fake_client)

    def _query_app_insights_token_metrics(self, columns, calls=None, **kwargs):
        timestamp = object()
        table = SimpleNamespace(
            columns=columns,
            rows=[[timestamp, "prompt_tokens", "claims-portal", 12.0]],
        )
        monitor_query = self._fake_logs_client([table], calls if calls is not None else [])
        with (
            patch.dict("sys.modules", {"azure.monitor.query": monitor_query}),
            patch("shared.auth.get_credential", return_value=object()),
        ):
            return timestamp, apim.query_app_insights_token_metrics(
                app_insights_resource_id=self.APP_INSIGHTS_ID,
                metric_names=["prompt_tokens"],
                **kwargs,
            )

    def test_query_token_metrics_reads_application_insights(self):
        timestamp = object()
        table = SimpleNamespace(
            columns=["timestamp", "metric_name", "dimension_value", "total"],
            rows=[[timestamp, "prompt_tokens", "claims-portal", 12.0]],
        )
        calls = []
        monitor_query = self._fake_logs_client([table], calls)
        with (
            patch.dict("sys.modules", {"azure.monitor.query": monitor_query}),
            patch("shared.auth.get_credential", return_value=object()),
            patch.object(
                apim,
                "get_app_insights_logger",
                return_value={"app_insights_resource_id": self.APP_INSIGHTS_ID},
            ) as resolve,
        ):
            rows = apim.query_token_metrics(
                resource_id=self.RESOURCE_ID,
                metric_names=["prompt_tokens"],
                subscription_filter="demo-sub",
                logger_id="demo2-application-insights",
            )

        resolve.assert_called_once_with("sub", "rg", "apim", "demo2-application-insights")
        self.assertEqual(calls[0]["resource_id"], self.APP_INSIGHTS_ID)
        self.assertIn("customMetrics", calls[0]["query"])
        self.assertIn("'demo-sub'", calls[0]["query"])
        self.assertNotIn("Microsoft.ResourceId", calls[0]["query"])
        self.assertEqual(
            rows,
            [
                {
                    "timestamp": timestamp,
                    "metric_name": "prompt_tokens",
                    "dimension_name": "ClientApp",
                    "dimension_value": "claims-portal",
                    "total": 12.0,
                }
            ],
        )

    def test_query_token_metrics_uses_explicit_app_insights_resource_id(self):
        calls = []
        monitor_query = self._fake_logs_client([], calls)
        with (
            patch.dict("sys.modules", {"azure.monitor.query": monitor_query}),
            patch("shared.auth.get_credential", return_value=object()),
            patch.object(
                apim, "get_app_insights_logger", side_effect=AssertionError("no ARM call")
            ),
        ):
            rows = apim.query_token_metrics(
                resource_id=self.RESOURCE_ID,
                metric_names=["prompt_tokens"],
                app_insights_resource_id=self.APP_INSIGHTS_ID,
                logger_id="demo2-application-insights",
            )

        self.assertEqual(rows, [])
        self.assertEqual(calls[0]["resource_id"], self.APP_INSIGHTS_ID)

    def test_query_token_metrics_raises_without_explicit_target(self):
        with patch.object(
            apim, "get_app_insights_logger", side_effect=AssertionError("no discovery")
        ):
            with self.assertRaisesRegex(RuntimeError, "Application Insights"):
                apim.query_token_metrics(
                    resource_id=self.RESOURCE_ID, metric_names=["prompt_tokens"]
                )

    def test_query_token_metrics_raises_when_named_logger_is_absent(self):
        with patch.object(apim, "get_app_insights_logger", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Application Insights"):
                apim.query_token_metrics(
                    resource_id=self.RESOURCE_ID, metric_names=["prompt_tokens"],
                    logger_id="demo2-application-insights",
                )

    def test_app_insights_resolution_ignores_malformed_resource_ids(self):
        with patch.object(
            apim, "get_app_insights_logger", side_effect=AssertionError("no ARM call")
        ):
            for malformed in (
                "",
                "/subscriptions/sub/resourceGroups/service",
                "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Insights/components/appi",
            ):
                self.assertIsNone(
                    apim._app_insights_for_apim_resource_id(malformed, "logger"), malformed
                )

    def test_query_app_insights_token_metrics_returns_empty_list_without_rows(self):
        empty_table = SimpleNamespace(
            columns=["timestamp", "metric_name", "dimension_value", "total"], rows=[]
        )
        monitor_query = self._fake_logs_client([empty_table], [])
        with (
            patch.dict("sys.modules", {"azure.monitor.query": monitor_query}),
            patch("shared.auth.get_credential", return_value=object()),
        ):
            self.assertEqual(
                apim.query_app_insights_token_metrics(
                    app_insights_resource_id=self.APP_INSIGHTS_ID,
                    metric_names=["prompt_tokens"],
                ),
                [],
            )

    def test_query_app_insights_token_metrics_accepts_string_columns(self):
        timestamp, rows = self._query_app_insights_token_metrics(
            ["timestamp", "metric_name", "dimension_value", "total"]
        )

        self.assertEqual(
            rows,
            [
                {
                    "timestamp": timestamp,
                    "metric_name": "prompt_tokens",
                    "dimension_name": "ClientApp",
                    "dimension_value": "claims-portal",
                    "total": 12.0,
                }
            ],
        )

    def test_query_app_insights_token_metrics_accepts_named_columns(self):
        timestamp, rows = self._query_app_insights_token_metrics(
            [
                SimpleNamespace(name="timestamp"),
                SimpleNamespace(name="metric_name"),
                SimpleNamespace(name="dimension_value"),
                SimpleNamespace(name="total"),
            ]
        )

        self.assertEqual(
            rows,
            [
                {
                    "timestamp": timestamp,
                    "metric_name": "prompt_tokens",
                    "dimension_name": "ClientApp",
                    "dimension_value": "claims-portal",
                    "total": 12.0,
                }
            ],
        )
