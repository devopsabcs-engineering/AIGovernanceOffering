"""Tests for scripts/lab_session.py with a stubbed ARM client (no Azure calls)."""

import io
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.automation_fakes import (
    GEN, RG, SUB, FakeArm, FakeResponse, common, inventory, lab_session, make_ctx, run, start_session,
    target,
)
from shared import budget


class _Base(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("AIGOV_HEADLESS", None)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.arm = FakeArm()
        self.ctx = make_ctx(self.tmp, self.arm)

    def tearDown(self):
        self._tmp.cleanup()
        self._env.stop()

    def output(self):
        return self.ctx.out.getvalue()

    def create_and_deploy(self, mode="full-session", run_id="100", deploy_error=None, partial=0):
        session_id = start_session(self.ctx, run_id=run_id)
        self.assertEqual(run(self.ctx, "manifest", "create", "--mode", mode), 0, self.output())
        self.arm.deploy_error = deploy_error
        self.arm.deploy_partial = partial
        code = run(self.ctx, "deploy")
        self.assertEqual(code, 1 if deploy_error else 0, self.output())
        return session_id

    def residual(self, session_id):
        return json.loads((self.ctx.paths.residual_dir(session_id) / "report.json").read_text(encoding="utf-8"))


class InitSessionTests(_Base):
    def test_run_attempt_above_two_is_refused(self):
        self.assertEqual(run(self.ctx, "init-session", "--run-id", "100", "--run-attempt", "3"), 1)
        self.assertIn("at most 2", self.output())
        self.assertFalse((self.ctx.paths.budget_root / "100-3").exists())

    def test_creates_session_file_budget_and_github_env(self):
        github_env = self.tmp / "github_env"
        self.ctx.env["GITHUB_ENV"] = str(github_env)
        session_id = start_session(self.ctx, run_id="555", attempt="2")
        self.assertEqual(session_id, "555-2")
        values = common.read_env_file(self.ctx.paths.session_env(session_id))
        self.assertEqual(values["AIGOV_HEADLESS"], "1")
        self.assertEqual(values["SESSION_ID"], "555-2")
        state = budget.load_state(session_id, root=self.ctx.paths.budget_root)
        self.assertEqual(state["price"]["snapshot_id"], "fixture-test-only")
        self.assertEqual(state["price"]["output_usd_per_million"], 2.0)
        self.assertIn("SESSION_ID=555-2", github_env.read_text(encoding="utf-8"))

    def test_second_init_for_same_session_is_refused(self):
        start_session(self.ctx)
        self.assertEqual(run(self.ctx, "init-session", "--run-id", "100", "--run-attempt", "1"), 1)

    def test_require_price_without_snapshot_is_refused(self):
        self.assertEqual(run(self.ctx, "init-session", "--run-id", "1", "--require-price"), 1)

    def test_deadline_subtracts_every_post_work_cap(self):
        start = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)
        deadline = lab_session.compute_deadline(start, 300, 5, 45, 5, 5, 10)
        self.assertEqual(deadline, start + timedelta(minutes=230))
        with self.assertRaises(common.AutomationError):
            lab_session.compute_deadline(start, 361, 5, 45, 5, 5, 10)
        with self.assertRaises(common.AutomationError):
            lab_session.compute_deadline(start, 60, 5, 45, 5, 5, 0)


class ManifestTests(_Base):
    def test_create_persists_append_only_record_and_backup(self):
        session_id = start_session(self.ctx)
        self.assertEqual(run(self.ctx, "manifest", "create", "--mode", "full-session"), 0, self.output())
        records = self.arm.manifest_records()
        self.assertEqual(len(records), 1)
        self.assertRegex(records[0], rf"^aigov-manifest-{GEN}-{session_id}-[0-9a-f]{{8}}$")
        stored = self.arm.deployments[records[0]]
        self.assertEqual(stored["properties"]["mode"], "Incremental")
        manifest = stored["properties"]["outputs"]["manifest"]["value"]
        self.assertEqual(manifest["created_by_session"], session_id)
        self.assertEqual(manifest["record_kind"], "planned")
        self.assertTrue((self.ctx.paths.manifest_dir(session_id) / f"{records[0]}.json").exists())
        self.assertTrue((self.ctx.paths.manifest_dir(session_id) / "planned.json").exists())

    def test_create_refuses_unexpected_resource(self):
        start_session(self.ctx)
        self.arm.add_resource(f"{common.rg_scope(SUB, RG)}/providers/Microsoft.Storage/storageAccounts/stray", "stray")
        self.assertEqual(run(self.ctx, "manifest", "create", "--mode", "full-session"), 1)
        self.assertIn("outside the approved inventory", self.output())
        self.assertEqual(self.arm.manifest_records(), [])

    def test_create_refuses_locks(self):
        start_session(self.ctx)
        self.arm.locks.append({"name": "lock1"})
        self.assertEqual(run(self.ctx, "manifest", "create", "--mode", "deploy-only"), 1)
        self.assertIn("lock", self.output())
        self.assertEqual(self.arm.manifest_records(), [])

    def test_create_refuses_live_owned_resources(self):
        start_session(self.ctx)
        self.arm.add_planned(1)
        self.assertEqual(run(self.ctx, "manifest", "create", "--mode", "full-session"), 1)
        self.assertIn("run-existing", self.output())

    def test_create_only_in_creating_modes(self):
        start_session(self.ctx)
        for mode in ("run-existing", "report-only", "dry-run", "lock-test"):
            self.assertEqual(run(self.ctx, "manifest", "create", "--mode", mode), 1, mode)
        self.assertEqual(self.arm.manifest_records(), [])

    def test_persistence_failure_stops_before_mutation(self):
        start_session(self.ctx)
        self.arm.fail_record_put = True
        self.assertEqual(run(self.ctx, "manifest", "create", "--mode", "full-session"), 1)
        self.assertEqual(self.arm.manifest_records(), [])

    def test_records_are_never_overwritten(self):
        start_session(self.ctx)
        run(self.ctx, "manifest", "create", "--mode", "full-session")
        name = self.arm.manifest_records()[0]
        with self.assertRaises(common.AutomationError):
            self.arm.put_record_deployment(SUB, RG, name, {"x": 1}, "0" * 64)

    def test_verify_uses_newest_valid_record_and_ignores_tampered(self):
        self.create_and_deploy()
        records = self.arm.manifest_records()
        manifests = [self.arm.deployments[n]["properties"]["outputs"]["manifest"]["value"] for n in records]
        newest = next(m for m in manifests if m["record_kind"] == "deploy-attempt")
        newest["resource_group"] = "other"
        start_session(self.ctx, run_id="200")
        self.assertEqual(run(self.ctx, "manifest", "verify", "--mode", "run-existing"), 0, self.output())
        self.assertIn("ignored 1 record", self.output())
        verified = json.loads((self.ctx.paths.manifest_dir("200-1") / "verified.json").read_text(encoding="utf-8"))
        self.assertEqual(verified["manifest"]["record_kind"], "planned")
        self.assertEqual(len(self.arm.manifest_records()), 2)

    def test_verify_picks_newest_record_and_never_creates_one(self):
        self.create_and_deploy()
        start_session(self.ctx, run_id="200")
        self.assertEqual(run(self.ctx, "manifest", "verify", "--mode", "report-only"), 0, self.output())
        verified = json.loads((self.ctx.paths.manifest_dir("200-1") / "verified.json").read_text(encoding="utf-8"))
        self.assertEqual(verified["manifest"]["record_kind"], "deploy-attempt")
        self.assertEqual(len(self.arm.manifest_records()), 2)

    def test_verify_fails_when_a_resource_is_missing(self):
        self.create_and_deploy()
        apim = next(e for e in inventory()["expected"] if e["type"] == "microsoft.apimanagement/service")
        self.arm.resources.pop(apim["id"].lower())
        start_session(self.ctx, run_id="200")
        self.assertEqual(run(self.ctx, "manifest", "verify", "--mode", "report-only"), 1)
        self.assertIn("missing", self.output())


class DeployTests(_Base):
    def test_failure_after_manifest_appends_attempt_record(self):
        session_id = self.create_and_deploy(deploy_error="other", partial=2)
        records = self.arm.manifest_records()
        self.assertEqual(len(records), 2)
        kinds = {}
        for name in records:
            manifest = self.arm.deployments[name]["properties"]["outputs"]["manifest"]["value"]
            kinds[manifest["record_kind"]] = manifest
        self.assertEqual(kinds["deploy-attempt"]["deploy_outcome"], "failed")
        self.assertEqual(len(kinds["deploy-attempt"]["observed_resources"]), 2)
        self.assertEqual(kinds["deploy-attempt"]["created_by_session"], session_id)

    def test_success_prunes_superseded_records_but_never_manifest_records(self):
        for name in ("aigov-main-g00", "aigov-main-g00-ai", "aigov-manifest-g00-1-1-deadbeef", "unrelated"):
            self.arm.deployments[name] = {"name": name, "properties": {"provisioningState": "Succeeded"}}
        self.create_and_deploy()
        self.assertNotIn("aigov-main-g00", self.arm.deployments)
        self.assertNotIn("aigov-main-g00-ai", self.arm.deployments)
        self.assertIn("aigov-manifest-g00-1-1-deadbeef", self.arm.deployments)
        self.assertIn("unrelated", self.arm.deployments)
        self.assertIn(f"aigov-main-{GEN}", self.arm.deployments)


class WhatIfTests(_Base):
    def test_evaluation_rules(self):
        inv = inventory()
        apim = next(e["id"] for e in inv["expected"] if e["type"] == "microsoft.apimanagement/service")
        allowed = [e["id"] for e in inv["expected"]]
        ok = lab_session.evaluate_what_if(
            [{"change_type": "Create", "resource_id": apim}, {"change_type": "Create", "resource_id": apim + "/apis/x"},
             {"change_type": "NoChange", "resource_id": "/other"}], allowed)
        self.assertEqual(ok["status"], "passed")
        delete = lab_session.evaluate_what_if([{"change_type": "Delete", "resource_id": apim}], allowed)
        self.assertEqual(delete["violations"][0]["reason"], "delete")
        outside = lab_session.evaluate_what_if(
            [{"change_type": "Modify", "resource_id": apim + "-other"}], allowed)
        self.assertEqual(outside["violations"][0]["reason"], "outside_plan")

    def test_cli_fails_on_unexpected_delete(self):
        start_session(self.ctx)
        self.arm.what_if_changes = [{"change_type": "Delete", "resource_id": inventory()["expected"][0]["id"]}]
        self.assertEqual(run(self.ctx, "what-if"), 1)
        self.arm.what_if_changes = [{"change_type": "Create", "resource_id": inventory()["expected"][0]["id"]}]
        self.assertEqual(run(self.ctx, "what-if"), 0)


class PreflightTests(_Base):
    def setUp(self):
        super().setUp()
        self.ctx.env.update({
            "AIGOV_LOCATION": "canadacentral", "AIGOV_CONTENT_SAFETY_LOCATION": "canadaeast",
            "AIGOV_PUBLISHER_EMAIL": "ops@example.invalid", "AIGOV_APIM_IDENTITY_RESOURCE_ID": "/x",
            "AIGOV_APIM_IDENTITY_CLIENT_ID": "client", "AIGOV_CHAT_DEPLOYMENT_CAPACITY": "10",
        })
        base = f"/subscriptions/{SUB}/providers"
        for ns in ("microsoft.cognitiveservices", "microsoft.insights", "microsoft.operationalinsights"):
            self.arm.canned[f"{base}/{ns}"] = {"registrationState": "Registered"}
        self.arm.canned[f"{base}/microsoft.apimanagement"] = {
            "registrationState": "Registered",
            "resourceTypes": [{"resourceType": "service", "locations": ["Canada Central"]}],
        }
        self.arm.canned[f"{base}/microsoft.cognitiveservices/locations/canadaeast/models"] = {"value": [
            {"model": {"name": "test-model", "version": "2026-01-01", "skus": [{"name": "Standard"}]}}]}
        self.arm.canned[f"{base}/microsoft.cognitiveservices/locations/canadaeast/usages"] = {"value": [
            {"name": {"value": "OpenAI.Standard.test-model"}, "limit": 100, "currentValue": 10}]}
        self.arm.canned[f"{base}/microsoft.cognitiveservices/skus"] = {"value": [
            {"kind": "ContentSafety", "locations": ["CanadaEast"]}]}
        start_session(self.ctx)

    def summary(self):
        path = self.ctx.paths.outputs / "preflight" / "100-1" / "summary.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_happy_path_passes(self):
        self.assertEqual(run(self.ctx, "preflight"), 0, self.output())
        self.assertEqual(self.summary()["status"], "passed")

    def test_global_sku_requires_approval(self):
        self.ctx.env["AIGOV_CHAT_DEPLOYMENT_SKU"] = "GlobalStandard"
        self.assertEqual(run(self.ctx, "preflight"), 1)
        self.assertEqual(self.summary()["checks"]["model_tuple"]["status"], "failed")

    def test_tombstone_collision_stops(self):
        self.arm.deleted["apim"].append({"name": lab_session.planned_names(target())["apim"], "location": "canadacentral"})
        self.assertEqual(run(self.ctx, "preflight"), 1)
        self.assertEqual(self.summary()["checks"]["tombstones"]["code"], "tombstone_collision")
        self.assertIn("new generation or operator purge required", self.output())

    def test_insufficient_quota_fails(self):
        self.ctx.env["AIGOV_CHAT_DEPLOYMENT_CAPACITY"] = "95"
        self.assertEqual(run(self.ctx, "preflight"), 1)
        self.assertEqual(self.summary()["checks"]["model_quota"]["code"], "insufficient_quota")

    def test_quota_matches_hyphenless_gpt_usage_name(self):
        base = f"/subscriptions/{SUB}/providers/microsoft.cognitiveservices"
        self.ctx.env["AIGOV_CHAT_MODEL_NAME"] = "gpt-4.1-mini"
        self.arm.canned[f"{base}/locations/canadaeast/models"] = {"value": [
            {"model": {"name": "gpt-4.1-mini", "version": "2026-01-01", "skus": [{"name": "Standard"}]}}]}
        self.arm.canned[f"{base}/locations/canadaeast/usages"] = {"value": [
            {"name": {"value": "OpenAI.Standard.gpt4.1-mini"}, "limit": 100, "currentValue": 10}]}
        run(self.ctx, "preflight")
        self.assertEqual(self.summary()["checks"]["model_quota"]["code"], "ok")


class WriteEnvTests(_Base):
    def test_writes_complete_env_and_masks_connection_string(self):
        session_id = self.create_and_deploy()
        validated = []
        self.ctx.validate_env = validated.append
        self.ctx.env["GITHUB_ACTIONS"] = "true"
        self.ctx.out = io.StringIO()
        self.assertEqual(run(self.ctx, "write-env"), 0, self.output())
        lines = self.output().splitlines()
        self.assertTrue(lines[0].startswith("::add-mask::InstrumentationKey="))
        values = common.read_env_file(self.ctx.env_path)
        self.assertEqual(values["APIM_RESOURCE_GROUP"], RG)
        self.assertNotIn("AZURE_RESOURCE_GROUP", values)
        for key in lab_session.EMPTY_ENV_KEYS:
            self.assertEqual(values[key], "", key)
        self.assertRegex(values["DEMO_RUN"], r"^[0-9a-f]{8}$")
        self.assertEqual(values["SESSION_ID"], session_id)
        self.assertEqual(values["TEAM_SUBSCRIPTION_IDS"], "team-retail-sub,team-finance-sub,team-hr-sub")
        self.assertEqual(values["CONTENT_SAFETY_THRESHOLD_HATE"], "4")
        self.assertEqual(validated, [self.ctx.env_path])
        hashes = self.ctx.paths.secret_hashes(session_id).read_text(encoding="utf-8")
        self.assertNotIn("InstrumentationKey", hashes)

    def test_connection_string_is_not_printed_outside_actions(self):
        self.create_and_deploy()
        self.ctx.out = io.StringIO()
        self.assertEqual(run(self.ctx, "write-env"), 0)
        self.assertNotIn("InstrumentationKey", self.output())

    def test_inherited_conflict_is_refused(self):
        self.create_and_deploy()
        self.ctx.env["DEMO_RUN"] = "stale123"
        self.assertEqual(run(self.ctx, "write-env"), 1)
        self.assertIn("DEMO_RUN", self.output())

    def test_tenant_mismatch_is_refused(self):
        self.create_and_deploy()
        self.arm.deployments[f"aigov-main-{GEN}"]["properties"]["outputs"]["AZURE_TENANT_ID"]["value"] = "other"
        self.assertEqual(run(self.ctx, "write-env"), 1)
        self.assertFalse(self.ctx.env_path.exists())


class ReadinessAndProbeTests(_Base):
    def setUp(self):
        super().setUp()
        self.session_id = self.create_and_deploy()
        self.assertEqual(run(self.ctx, "write-env"), 0, self.output())
        scope = common.apim_scope(SUB, RG, lab_session.planned_names(target())["apim"]).lower()
        appi = next(e["id"] for e in inventory()["expected"] if e["type"] == "microsoft.insights/components")
        self.arm.canned[f"{scope}/loggers/apimlogger"] = {
            "properties": {"loggerType": "applicationInsights", "resourceId": appi}}
        self.arm.canned[f"{scope}/diagnostics/applicationinsights"] = {"properties": {
            "loggerId": f"{scope}/loggers/apimlogger", "metrics": True,
            "frontend": {"request": {"body": {"bytes": 0}}}}}

    def test_readiness_passes_and_inference_uses_the_budget(self):
        self.assertEqual(run(self.ctx, "readiness"), 0, self.output())
        summary = json.loads((self.ctx.paths.readiness_dir(self.session_id) / "summary.json").read_text())
        self.assertEqual(summary["status"], "passed")
        totals = budget.session_totals(self.session_id, root=self.ctx.paths.budget_root)
        self.assertEqual(totals["attempts"], 1)

    def test_readiness_reports_failing_check_and_skips_the_rest(self):
        appi = next(e["id"] for e in inventory()["expected"] if e["type"] == "microsoft.insights/components")
        self.arm.resources[appi.lower()]["properties"]["CustomMetricsOptedInType"] = "NoDimensions"
        self.assertEqual(run(self.ctx, "readiness"), 1)
        summary = json.loads((self.ctx.paths.readiness_dir(self.session_id) / "summary.json").read_text())
        self.assertEqual(summary["failing_check"], "custom_metric_dimensions")
        self.assertEqual(summary["scope"], "app-insights")
        self.assertEqual(summary["checks"]["inference"]["status"], "not_run")
        self.assertEqual(budget.session_totals(self.session_id, root=self.ctx.paths.budget_root)["attempts"], 0)

    def _probe_post(self, url, *, headers, json_body, timeout):
        key = headers.get("Ocp-Apim-Subscription-Key")
        if not key:
            return FakeResponse(401, {"statusCode": 401})
        if "aigov-probe" in key:
            return FakeResponse(200, {"usage": {"prompt_tokens": 3}})
        return FakeResponse(200, {"usage": {"prompt_tokens": 3}}, {"remaining-tokens": "100"})

    def test_probe_scopes_records_access_paths_and_deletes_temporary_subscription(self):
        self.ctx.http_post = self._probe_post
        self.assertEqual(run(self.ctx, "probe-scopes"), 0, self.output())
        probes = json.loads((self.ctx.paths.readiness_dir(self.session_id) / "probes.json").read_text())["probes"]
        self.assertTrue(probes["anonymous"]["passed"])
        self.assertTrue(probes["api_scoped"]["bypass_observed"])
        self.assertTrue(probes["api_scoped"]["temporary_subscription_deleted"])
        self.assertFalse(any("aigov-probe" in r["id"] for r in self.arm.resources.values()))
        self.assertNotIn("key-", self.output())

    def test_temporary_subscription_is_deleted_when_the_probe_call_fails(self):
        def post(url, *, headers, json_body, timeout):
            if "aigov-probe" in headers.get("Ocp-Apim-Subscription-Key", ""):
                raise ConnectionError("boom")
            return self._probe_post(url, headers=headers, json_body=json_body, timeout=timeout)

        self.ctx.http_post = post
        self.assertEqual(run(self.ctx, "probe-scopes"), 1)
        self.assertFalse(any("aigov-probe" in r["id"] for r in self.arm.resources.values()))


class RunNotebookTests(_Base):
    def test_five_only_calls_append_without_clearing(self):
        session_id = start_session(self.ctx)
        self.assertEqual(run(self.ctx, "run-notebooks", "--init"), 0)
        marker = self.ctx.paths.executed_dir(session_id) / "marker.txt"
        marker.write_text("keep", encoding="utf-8")
        calls = []
        self.ctx.papermill = lambda nb, out, cwd, log, timeout: calls.append((nb.name, out.name)) or 0
        for stem in common.NOTEBOOK_STEMS:
            self.assertEqual(run(self.ctx, "run-notebooks", "--only", f"{stem}.ipynb"), 0)
        data = json.loads((self.ctx.paths.executed_dir(session_id) / "execution.json").read_text())
        self.assertEqual([r["notebook"] for r in data["runs"]], list(common.NOTEBOOK_STEMS))
        self.assertTrue(marker.exists())
        self.assertEqual(len(calls), 5)
        for record in data["runs"]:
            self.assertRegex(record["source_sha256"], r"^[0-9a-f]{64}$")

    def test_only_without_init_and_double_init_are_refused(self):
        start_session(self.ctx)
        self.assertEqual(run(self.ctx, "run-notebooks", "--only", "demo1-token-limits"), 1)
        self.assertEqual(run(self.ctx, "run-notebooks", "--init"), 0)
        self.assertEqual(run(self.ctx, "run-notebooks", "--init"), 1)
        self.assertEqual(run(self.ctx, "run-notebooks", "--only", "unknown-notebook"), 1)

    def test_failed_notebook_is_recorded_with_its_exit_code(self):
        session_id = start_session(self.ctx)
        run(self.ctx, "run-notebooks", "--init")
        self.ctx.papermill = lambda *a: 3
        self.assertEqual(run(self.ctx, "run-notebooks", "--only", "demo3-content-safety"), 1)
        data = json.loads((self.ctx.paths.executed_dir(session_id) / "execution.json").read_text())
        self.assertEqual(data["runs"][0]["exit_code"], 3)


class CleanupTests(_Base):
    def auto(self, mode, deploy="success", readiness="success", keep="false"):
        self.ctx.env.update({"DEPLOY_OUTCOME": deploy, "READINESS_OUTCOME": readiness, "KEEP_ENVIRONMENT": keep})
        return run(self.ctx, "cleanup", "--auto", "--mode", mode)

    def test_after_partial_deploy_deletes_present_in_dependency_order(self):
        session_id = self.create_and_deploy(deploy_error="other", partial=5)
        self.assertEqual(self.auto("full-session", deploy="failure", readiness="skipped"), 0, self.output())
        report = self.residual(session_id)
        self.assertEqual(report["status"], "clean")
        order = [common.resource_type_of(i) for i in self.arm.deleted_ids]
        self.assertEqual(order[0], "microsoft.cognitiveservices/accounts/deployments")
        self.assertEqual(order, sorted(order, key=common.DELETE_ORDER.index))
        results = {t["type"]: t["result"] for t in report["targets"] if t["name"].startswith("cs-")}
        self.assertEqual(results, {"microsoft.cognitiveservices/accounts": "absent"})
        self.assertTrue(report["spend_record"].startswith("aigov-manifest-"))

    def test_after_rg_content_deleted_everything_is_absent(self):
        session_id = self.create_and_deploy()
        self.arm.resources.clear()
        self.assertEqual(self.auto("full-session"), 0)
        self.assertEqual(self.residual(session_id)["status"], "clean")
        self.arm.rg_exists = False
        self.assertEqual(self.auto("full-session"), 0)

    def test_forbidden_delete_is_an_error_and_not_success(self):
        session_id = self.create_and_deploy()
        apim = next(e["id"] for e in inventory()["expected"] if e["type"] == "microsoft.apimanagement/service")
        self.arm.forbidden_delete.add(apim.lower())
        self.assertEqual(self.auto("full-session"), 1)
        report = self.residual(session_id)
        self.assertEqual(report["status"], "residual")
        self.assertEqual(report["failures"][0]["category"], "forbidden")
        self.assertGreater(len(self.arm.deleted_ids), 1)

    def test_resource_that_never_disappears_is_residual(self):
        session_id = self.create_and_deploy()
        workspace = next(e["id"] for e in inventory()["expected"]
                         if e["type"] == "microsoft.operationalinsights/workspaces")
        self.arm.sticky.add(workspace.lower())
        self.ctx.now = lambda: datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(run(self.ctx, "cleanup", "--auto", "--mode", "full-session", "--timeout-seconds", "0"), 1)
        self.assertEqual(self.residual(session_id)["status"], "residual")

    def test_unexpected_resource_and_lock_refuse_deletion(self):
        session_id = self.create_and_deploy()
        self.arm.add_resource(f"{common.rg_scope(SUB, RG)}/providers/Microsoft.Storage/storageAccounts/x", "x")
        self.assertEqual(self.auto("full-session"), 1)
        self.assertEqual(self.residual(session_id)["status"], "refused")
        self.assertEqual(self.arm.deleted_ids, [])
        self.arm.resources.pop(f"{common.rg_scope(SUB, RG)}/providers/Microsoft.Storage/storageAccounts/x".lower())
        self.arm.locks.append({"name": "lock"})
        self.assertEqual(self.auto("full-session"), 1)
        self.assertEqual(self.arm.deleted_ids, [])

    def test_tombstones_are_listed_but_do_not_fail(self):
        session_id = self.create_and_deploy()
        self.arm.deleted["apim"].append({"name": lab_session.planned_names(target())["apim"],
                                         "location": "canadacentral"})
        self.assertEqual(self.auto("full-session"), 0)
        report = self.residual(session_id)
        self.assertEqual(report["status"], "clean")
        self.assertEqual(len(report["tombstones"]), 1)

    def test_ownership_tag_mismatch_is_not_deleted(self):
        session_id = self.create_and_deploy()
        apim = next(e["id"] for e in inventory()["expected"] if e["type"] == "microsoft.apimanagement/service")
        self.arm.resources[apim.lower()]["tags"] = {"aigov-owner": "someone-else"}
        self.assertEqual(self.auto("full-session"), 1)
        self.assertNotIn(apim, self.arm.deleted_ids)
        self.assertEqual(self.residual(session_id)["failures"][0]["category"], "ownership_mismatch")

    def test_manual_dry_run_and_execute_confirmation(self):
        self.create_and_deploy()
        self.assertEqual(run(self.ctx, "cleanup", "--dry-run"), 0)
        self.assertEqual(self.arm.deleted_ids, [])
        self.assertEqual(run(self.ctx, "cleanup", "--execute"), 1)
        self.assertIn("--confirm-resource-group", self.output())
        self.assertEqual(run(self.ctx, "cleanup", "--execute", "--confirm-resource-group", "wrong"), 1)
        self.assertEqual(self.arm.deleted_ids, [])
        self.assertEqual(run(self.ctx, "cleanup", "--execute", "--confirm-resource-group", RG), 0)
        self.assertTrue(self.arm.deleted_ids)

    def test_refused_full_session_against_kept_environment_deletes_nothing(self):
        self.create_and_deploy(mode="deploy-only", run_id="100")
        self.assertEqual(self.auto("deploy-only"), 0)
        self.assertEqual(self.arm.deleted_ids, [])
        second = start_session(self.ctx, run_id="200")
        self.assertEqual(run(self.ctx, "manifest", "create", "--mode", "full-session"), 1)
        self.assertEqual(self.auto("full-session", deploy="skipped", readiness="skipped"), 0)
        self.assertEqual(self.arm.deleted_ids, [])
        self.assertEqual(self.residual(second)["reason"], "no_records_created_by_this_session")
        self.assertEqual(len(self.arm.resources), len(inventory()["expected"]))

    def test_decision_treats_unknown_outcomes_as_failure(self):
        self.assertEqual(lab_session.decide_auto_cleanup("deploy-only", "", "", False)[0], "delete")
        self.assertEqual(lab_session.decide_auto_cleanup("deploy-only", "success", "cancelled", False)[0], "delete")
        self.assertEqual(lab_session.decide_auto_cleanup("deploy-only", "success", "success", True)[0], "keep")


# (mode, DEPLOY_OUTCOME, READINESS_OUTCOME, KEEP_ENVIRONMENT, deletes)
MODE_TABLE = (
    ("full-session", "success", "success", "false", True),
    ("full-session", "failure", "skipped", "false", True),
    ("full-session", "success", "success", "true", False),
    ("full-session", "failure", "skipped", "true", False),
    ("deploy-only", "success", "success", "false", False),
    ("deploy-only", "failure", "skipped", "false", True),
    ("deploy-only", "success", "failure", "false", True),
    ("run-existing", "skipped", "success", "false", False),
    ("run-existing", "skipped", "failure", "false", False),
    ("report-only", "skipped", "skipped", "false", False),
    ("report-only", "skipped", "failure", "false", False),
    ("dry-run", "skipped", "skipped", "false", False),
    ("dry-run", "failure", "skipped", "false", False),
    ("lock-test", "skipped", "skipped", "false", False),
    ("lock-test", "failure", "failure", "false", False),
)


class ModeTableTests(_Base):
    pass


def _make_cell_test(mode, deploy, readiness, keep, deletes):
    def test(self):
        create_mode = mode if mode in lab_session.CREATING_MODES else "full-session"
        session_id = self.create_and_deploy(mode=create_mode)
        self.ctx.env.update({"DEPLOY_OUTCOME": deploy, "READINESS_OUTCOME": readiness, "KEEP_ENVIRONMENT": keep})
        code = run(self.ctx, "cleanup", "--auto", "--mode", mode)
        report = self.residual(session_id)
        if deletes:
            self.assertEqual(code, 0, self.output())
            self.assertEqual(report["status"], "clean")
            self.assertEqual(self.arm.resources, {})
        else:
            self.assertEqual(code, 0, self.output())
            self.assertEqual(self.arm.deleted_ids, [])
            self.assertEqual(len(self.arm.resources), len(inventory()["expected"]))
            self.assertIn(report["status"], ("kept", "no_op"))
    return test


for _cell in MODE_TABLE:
    _name = "test_" + "_".join(re.sub(r"[^a-z0-9]", "_", str(part).lower()) for part in _cell)
    setattr(ModeTableTests, _name, _make_cell_test(*_cell))


class PurgeTests(_Base):
    def setUp(self):
        super().setUp()
        self.create_and_deploy()
        names = lab_session.planned_names(target())
        self.arm.deleted["apim"].append({"name": names["apim"], "location": "canadacentral"})
        self.arm.deleted["cognitive"].append({"name": names["model_account"], "location": "canadaeast"})
        self.arm.deleted["cognitive"].append({"name": "not-inventoried", "location": "canadaeast"})
        self.arm.deleted["workspace"].append({"name": names["log_analytics"], "location": "canadacentral"})
        self.names = names

    def test_refuses_in_github_actions(self):
        self.ctx.env["GITHUB_ACTIONS"] = "true"
        self.assertEqual(run(self.ctx, "purge", "--execute", "--confirm-resource-group", RG), 1)
        self.assertIn("refuses to run in GitHub Actions", self.output())
        self.assertEqual(self.arm.purged, [])

    def test_typed_confirmation_and_inventory_scope(self):
        typed = {self.names["apim"]: self.names["apim"], self.names["model_account"]: "wrong"}
        self.ctx.prompt = lambda message: next(v for k, v in typed.items() if k in message)
        self.assertEqual(run(self.ctx, "purge", "--execute", "--confirm-resource-group", RG), 0, self.output())
        self.assertEqual(self.arm.purged, [self.names["apim"]])
        self.assertNotIn("not-inventoried", self.output())
        self.assertIn("never force-deleted", self.output())

    def test_listing_only_without_execute(self):
        self.ctx.prompt = lambda message: self.fail("no prompt expected")
        self.assertEqual(run(self.ctx, "purge"), 0)
        self.assertEqual(self.arm.purged, [])


class SecretRegistryTests(unittest.TestCase):
    def test_mask_is_emitted_first_and_only_hashes_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            hash_file = Path(tmp) / "hashes.jsonl"
            registry = common.SecretRegistry(hash_file, env={"GITHUB_ACTIONS": "true"}, stream=out)
            registry.register("fake-secret-value-123")
            registry.register("fake-secret-value-123")
            self.assertEqual(out.getvalue(), "::add-mask::fake-secret-value-123\n")
            self.assertNotIn("fake-secret-value-123", hash_file.read_text(encoding="utf-8"))
            known = common.load_known_hashes([hash_file])
            self.assertEqual(common.known_value_hits("x fake-secret-value-123 y", known), 1)

    def test_no_mask_outside_actions(self):
        out = io.StringIO()
        common.SecretRegistry(None, env={}, stream=out).register("another-fake-value")
        self.assertEqual(out.getvalue(), "")


class HelpTests(unittest.TestCase):
    def test_every_subcommand_has_help(self):
        commands = [["init-session"], ["preflight"], ["what-if"], ["manifest", "create"], ["manifest", "verify"],
                    ["deploy"], ["write-env"], ["readiness"], ["probe-scopes"], ["run-notebooks"], ["cleanup"],
                    ["purge"]]
        for command in commands:
            with self.subTest(command=command), self.assertRaises(SystemExit) as raised, \
                    patch("sys.stdout", new=io.StringIO()):
                lab_session.build_parser().parse_args(command + ["--help"])
            self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
