import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from shared import config


class ResilientPoolConfigTests(unittest.TestCase):
    def test_pool_defaults_to_primary_values(self):
        cfg = config.WorkshopConfig(
            aoai_endpoint="https://example.openai.azure.com",
            aoai_deployment="gpt-4o",
        )
        config.ensure_resilient_pool_config(cfg, interactive=False)
        self.assertEqual(cfg.demo4_ptu_east_endpoint, cfg.aoai_endpoint)
        self.assertEqual(cfg.demo4_payg_deployment, cfg.aoai_deployment)

    def test_pool_rejects_mismatched_deployments(self):
        cfg = config.WorkshopConfig(
            aoai_endpoint="https://example.openai.azure.com",
            aoai_deployment="gpt-4o",
            demo4_ptu_east_deployment="gpt-4o",
            demo4_ptu_central_deployment="another-model",
        )
        with self.assertRaisesRegex(ValueError, "must match"):
            config.validate_resilient_pool_config(cfg)

    def test_pool_rejects_missing_or_invalid_endpoint(self):
        cfg = config.WorkshopConfig(aoai_deployment="gpt-4o")
        with self.assertRaisesRegex(ValueError, "non-empty HTTPS"):
            config.validate_resilient_pool_config(cfg)


def _base_cfg(**overrides) -> config.WorkshopConfig:
    cfg = config.WorkshopConfig(
        resource_group="rg",
        apim_name="apim",
        aoai_endpoint="https://example.openai.azure.com",
        aoai_deployment="gpt-4o-mini",
        content_safety_endpoint="https://example.cognitiveservices.azure.com",
    )
    return replace(cfg, **overrides)


class ValidateContentSafetyConfigTests(unittest.TestCase):
    def test_requires_endpoint(self):
        cfg = _base_cfg(content_safety_endpoint="")
        with self.assertRaisesRegex(ValueError, "content_safety_endpoint"):
            config.validate_content_safety_config(cfg)

    def test_rejects_endpoint_with_path(self):
        cfg = _base_cfg(
            content_safety_endpoint="https://example.cognitiveservices.azure.com/some/path"
        )
        with self.assertRaisesRegex(ValueError, "CONTENT_SAFETY_ENDPOINT"):
            config.validate_content_safety_config(cfg)

    def test_accepts_defaults(self):
        cfg = _base_cfg()
        # Should not raise.
        config.validate_content_safety_config(cfg)

    def test_rejects_non_integer_threshold(self):
        cfg = _base_cfg(content_safety_threshold_hate="high")
        with self.assertRaisesRegex(ValueError, "content_safety_threshold_hate"):
            config.validate_content_safety_config(cfg)

    def test_rejects_out_of_range_threshold(self):
        cfg = _base_cfg(content_safety_threshold_violence="8")
        with self.assertRaisesRegex(ValueError, "content_safety_threshold_violence"):
            config.validate_content_safety_config(cfg)


COMPLETE_ENV = """AZURE_SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000000
APIM_RESOURCE_GROUP=rg-lab
APIM_NAME=apim-lab
APIM_IDENTITY_CLIENT_ID=
AOAI_ENDPOINT=https://example.openai.azure.com
AOAI_DEPLOYMENT=gpt-test
AOAI_KEY=
AOAI_API_STYLE=v1
APP_INSIGHTS_CONNECTION_STRING=
CONTENT_SAFETY_ENDPOINT=https://example.cognitiveservices.azure.com
CONTENT_SAFETY_KEY=
DEMO4_PTU_EAST_ENDPOINT=
DEMO4_PTU_CENTRAL_ENDPOINT=
DEMO4_PAYG_ENDPOINT=
DEMO4_PTU_EAST_DEPLOYMENT=
DEMO4_PTU_CENTRAL_DEPLOYMENT=
DEMO4_PAYG_DEPLOYMENT=
DEMO_RUN=abc12345
"""


class HeadlessConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env_path = Path(self._tmp.name) / ".env"
        patches = [
            patch.object(config, "ENV_PATH", self.env_path),
            patch.object(config, "_MANAGED_ENV_KEYS", set()),
            patch.dict(os.environ, {}, clear=True),
            patch.object(config, "get_current_subscription_id",
                         side_effect=AssertionError("no az lookup in tests")),
            patch("builtins.input", side_effect=AssertionError("no prompt")),
            patch("getpass.getpass", side_effect=AssertionError("no prompt")),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self._tmp.cleanup)
        os.environ["AIGOV_HEADLESS"] = "1"

    def _write(self, text):
        self.env_path.write_text(text, encoding="utf-8")

    def test_missing_key_raises_instead_of_prompting(self):
        self._write(COMPLETE_ENV.replace("APIM_NAME=apim-lab\n", ""))
        with self.assertRaises(config.ConfigError) as ctx:
            config.load_config(interactive=True)
        self.assertIn("APIM_NAME", str(ctx.exception))

    def test_missing_optional_physical_key_raises(self):
        self._write(COMPLETE_ENV.replace("AOAI_KEY=\n", ""))
        with self.assertRaisesRegex(config.ConfigError, "AOAI_KEY"):
            config.load_config(interactive=True)

    def test_conflicting_inherited_value_raises_with_names_only(self):
        self._write(COMPLETE_ENV)
        os.environ["APIM_NAME"] = "inherited-secret-looking-value"
        with self.assertRaises(config.ConfigError) as ctx:
            config.load_config(interactive=True)
        self.assertIn("APIM_NAME", str(ctx.exception))
        self.assertNotIn("inherited-secret-looking-value", str(ctx.exception))
        self.assertNotIn("apim-lab", str(ctx.exception))

    def test_inherited_demo_run_is_a_conflict_even_when_equal(self):
        self._write(COMPLETE_ENV)
        os.environ["DEMO_RUN"] = "abc12345"
        with self.assertRaisesRegex(config.ConfigError, "DEMO_RUN"):
            config.load_config(interactive=True)

    def test_equal_inherited_value_is_accepted(self):
        self._write(COMPLETE_ENV)
        os.environ["APIM_NAME"] = "apim-lab"
        self.assertEqual(config.load_config(interactive=True).apim_name, "apim-lab")

    def test_empty_optional_keys_are_accepted(self):
        self._write(COMPLETE_ENV)
        cfg = config.load_config(interactive=True)
        cfg = config.ensure_content_safety_config(cfg, interactive=True)
        cfg = config.ensure_resilient_pool_config(cfg, interactive=True)
        self.assertIsNone(cfg.aoai_key)
        self.assertIsNone(cfg.content_safety_key)
        self.assertIsNone(cfg.apim_identity_client_id)
        self.assertEqual(cfg.demo4_payg_endpoint, cfg.aoai_endpoint)
        self.assertEqual(cfg.demo4_ptu_east_deployment, cfg.aoai_deployment)

    def test_demo_run_reset_persists_across_fresh_load(self):
        self._write(COMPLETE_ENV)
        self.assertEqual(config.load_config(interactive=True).demo_run, "abc12345")
        config.persist_demo_run("fedcba98")
        self.assertEqual(config.load_config(interactive=True).demo_run, "fedcba98")
        self.assertIn("DEMO_RUN=fedcba98", self.env_path.read_text(encoding="utf-8"))

    def test_identity_client_id_is_loaded(self):
        client_id = "11111111-2222-3333-4444-555555555555"
        self._write(COMPLETE_ENV.replace("APIM_IDENTITY_CLIENT_ID=", f"APIM_IDENTITY_CLIENT_ID={client_id}"))
        self.assertEqual(config.load_config(interactive=True).apim_identity_client_id, client_id)

    def test_interactive_mode_keeps_inherited_precedence(self):
        os.environ["AIGOV_HEADLESS"] = ""
        self._write(COMPLETE_ENV)
        os.environ["APIM_NAME"] = "from-environment"
        os.environ["DEMO_RUN"] = "abc12345"
        self.assertEqual(config.load_config(interactive=True).apim_name, "from-environment")


if __name__ == "__main__":
    unittest.main()
