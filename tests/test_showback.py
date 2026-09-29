"""Tests for pricing, the showback report, and the traffic generator (stubbed telemetry and HTTP)."""

import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from tests.automation_fakes import (
    PRICE_FIXTURE, Clock, FakeArm, FakeResponse, common, make_ctx, start_session,
)
import generate_traffic
import showback_report
from shared import budget

AT = datetime(2026, 9, 29, tzinfo=timezone.utc)
MODEL = {"name": "test-model", "version": "2026-01-01", "sku": "Standard", "region": "canadaeast"}


class PricingTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = common.load_price_snapshot(PRICE_FIXTURE)

    def select(self, region):
        return common.select_prices(self.snapshot, model="test-model", version="2026-01-01", sku="Standard",
                                    region=region, at=AT)

    def test_per_thousand_and_per_million_units(self):
        prices = self.select("Canada East")
        self.assertEqual(prices["input_usd_per_million"], Decimal("0.5"))
        self.assertEqual(prices["output_usd_per_million"], Decimal("2.000"))

    def test_missing_price_is_reported_not_zero(self):
        with self.assertRaises(common.PriceError) as raised:
            self.select("westus")
        self.assertEqual(raised.exception.coverage, "missing")

    def test_duplicate_price_is_ambiguous(self):
        with self.assertRaises(common.PriceError) as raised:
            self.select("eastus")
        self.assertEqual(raised.exception.coverage, "duplicate")

    def test_effective_period_is_enforced(self):
        with self.assertRaises(common.PriceError):
            common.select_prices(self.snapshot, model="test-model", version="2026-01-01", sku="Standard",
                                 region="canadaeast", at=datetime(2025, 1, 1, tzinfo=timezone.utc))

    def test_cached_tokens_are_not_added_on_top(self):
        prices = self.select("canadaeast")
        cost = common.price_usage(1000, 500, prices)
        self.assertEqual(cost, (Decimal(1000) * Decimal("0.5") + Decimal(500) * Decimal("2")) / Decimal(1_000_000))
        self.assertEqual(cost, Decimal("0.0015"))

    def test_schema_matches_fixture_fields(self):
        schema = json.loads((common.REPO_ROOT / "scripts" / "prices" / "schema.json").read_text(encoding="utf-8"))
        required = set(schema["properties"]["records"]["items"]["required"])
        for record in self.snapshot["records"]:
            self.assertEqual(set(record), required)
        self.assertTrue(set(schema["required"]).issubset(self.snapshot))


class ShowbackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.paths = common.Paths(self.tmp / "outputs")
        self.env_file = self.tmp / ".env"
        self.env_file.write_text(
            "APP_INSIGHTS_RESOURCE_ID=/subscriptions/s/resourceGroups/r/providers/Microsoft.Insights/components/a\n"
            "PLATFORM_API_ID=ai-gateway-api\nTEAM_SUBSCRIPTION_IDS=team-retail-sub,team-finance-sub,team-hr-sub\n",
            encoding="utf-8")
        self.now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self._tmp.cleanup()

    def write_manifest(self, teams=None):
        teams = teams or {
            "team-retail": {"subscription_id": "team-retail-sub", "prompt_tokens": 100, "completion_tokens": 40,
                            "cached_tokens": 30, "failed": 0, "ambiguous": 0},
            "team-finance": {"subscription_id": "team-finance-sub", "prompt_tokens": 80, "completion_tokens": 20,
                             "cached_tokens": 0, "failed": 1, "ambiguous": 0},
        }
        results_dir = self.paths.showback_dir("400-1")
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / "manifest.json").write_text(json.dumps({
            "session_id": "400-1", "window": {"start": "2026-09-29T11:00:00Z", "end": "2026-09-29T11:06:00Z"},
            "model": MODEL, "teams": teams}), encoding="utf-8")

    def rows(self, retail=(100, 40), finance=(80, 20), extra=()):
        rows = [
            {"name": "Prompt Tokens", "api": "ai-gateway-api", "sub": "team-retail-sub", "app": "retail-web",
             "value_sum": retail[0]},
            {"name": "Completion Tokens", "api": "ai-gateway-api", "sub": "team-retail-sub", "app": "retail-web",
             "value_sum": retail[1]},
            {"name": "Prompt Tokens", "api": "ai-gateway-api", "sub": "team-finance-sub", "app": "finance-batch",
             "value_sum": finance[0]},
            {"name": "Completion Tokens", "api": "ai-gateway-api", "sub": "team-finance-sub", "app": "finance-batch",
             "value_sum": finance[1]},
        ]
        return rows + list(extra)

    def run_report(self, rows_fn, *extra_args, price=True):
        queries = []

        def logs_query(resource_id, query, start, end):
            queries.append(query)
            return rows_fn()

        clock = Clock(step_seconds=30)
        clock.current = self.now
        out = io.StringIO()
        deps = showback_report.Deps(logs_query=logs_query, now=clock, sleep=lambda _s: None, out=out,
                                    env={"AIGOV_CHAT_MODEL_NAME": "test-model",
                                         "AIGOV_CHAT_MODEL_VERSION": "2026-01-01",
                                         "AIGOV_CHAT_DEPLOYMENT_SKU": "Standard",
                                         "AIGOV_AI_LOCATION": "canadaeast"})
        argv = ["--session-id", "400-1", "--env-file", str(self.env_file), "--outputs-root", str(self.paths.outputs),
                "--poll-timeout-seconds", "120", *extra_args]
        if price:
            argv += ["--price-snapshot", str(PRICE_FIXTURE)]
        code = showback_report.main(argv, deps)
        report_path = self.paths.showback_dir("400-1") / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
        return code, report, queries, out.getvalue()

    def test_reconciled_report_uses_exact_pricing_identity(self):
        self.write_manifest()
        code, report, queries, out = self.run_report(self.rows)
        self.assertEqual(code, 0, report)
        self.assertEqual(report["label"], "Estimated model-token showback (USD retail)")
        self.assertIn("Estimated model-token showback (USD retail)", out)
        self.assertEqual(report["reconciliation_status"], "reconciled")
        self.assertEqual(report["totals"]["status"], "complete")
        retail = Decimal(report["teams"]["team-retail"]["estimated_usd"])
        finance = Decimal(report["teams"]["team-finance"]["estimated_usd"])
        self.assertEqual(retail, (Decimal(100) * Decimal("0.5") + Decimal(40) * Decimal(2)) / Decimal(1_000_000))
        self.assertEqual(retail + finance, Decimal(report["totals"]["estimated_usd"]))
        self.assertEqual(report["counts"]["failed_calls"], 1)
        self.assertEqual(len(queries), 1)
        self.assertIn("sum(valueSum)", queries[0])
        self.assertNotIn("Total Tokens", queries[0])

    def test_total_metric_rows_are_never_added(self):
        self.write_manifest()
        total_row = {"name": "Total Tokens", "api": "ai-gateway-api", "sub": "team-retail-sub", "app": "retail-web",
                     "value_sum": 140}
        code, report, _, _ = self.run_report(lambda: self.rows(extra=[total_row]))
        self.assertEqual(code, 0)
        self.assertEqual(report["teams"]["team-retail"]["prompt_tokens"], 100)
        self.assertEqual(report["totals"]["prompt_tokens"] + report["totals"]["completion_tokens"], 240)
        self.assertEqual(report["counts"]["ignored_metric_rows"], 1)

    def test_duplicate_aggregate_rows_suppress_totals(self):
        self.write_manifest()
        rows = self.rows()
        code, report, _, _ = self.run_report(lambda: rows + [dict(rows[0])])
        self.assertEqual(code, 1)
        self.assertEqual(report["reconciliation_status"], "ambiguous")
        self.assertIsNone(report["totals"]["estimated_usd"])
        self.assertIsNone(report["teams"]["team-retail"]["estimated_usd"])

    def test_contaminated_window_is_rejected(self):
        self.write_manifest()
        stray = {"name": "Prompt Tokens", "api": "ai-gateway-api", "sub": "someone-else", "app": "unknown",
                 "value_sum": 9}
        code, report, _, _ = self.run_report(lambda: self.rows(extra=[stray]))
        self.assertEqual(code, 1)
        self.assertEqual(report["reconciliation_status"], "contaminated")
        self.assertEqual(report["totals"]["status"], "suppressed")
        self.assertEqual(report["unattributed"]["prompt_tokens"], 9)

    def test_missing_telemetry_is_incomplete_not_zero(self):
        self.write_manifest()
        code, report, queries, _ = self.run_report(lambda: [])
        self.assertEqual(code, 1)
        self.assertEqual(report["reconciliation_status"], "incomplete")
        self.assertNotEqual(report["totals"]["status"], "complete")
        self.assertIsNone(report["totals"]["estimated_usd"])
        self.assertGreater(len(queries), 1)
        self.assertLess(len(queries), 10)

    def test_missing_price_suppresses_cost_totals(self):
        self.write_manifest()
        code, report, _, _ = self.run_report(self.rows, price=False)
        self.assertEqual(code, 1)
        self.assertEqual(report["totals"]["status"], "suppressed")
        self.assertEqual(report["totals"]["suppressed_reason"], "price_not_provided")
        self.assertEqual(report["counts"]["unpriced_tokens"], 240)

    def test_report_only_window_validation(self):
        cases = {
            "reversed": ("2026-09-29T11:00:00Z", "2026-09-29T10:00:00Z"),
            "future": ("2026-09-29T11:00:00Z", "2026-09-29T13:00:00Z"),
            "too_long": ("2026-09-28T10:00:00Z", "2026-09-29T11:00:00Z"),
            "not_utc": ("2026-09-29T10:00:00+02:00", "2026-09-29T11:00:00Z"),
            "naive": ("2026-09-29T10:00:00", "2026-09-29T11:00:00Z"),
        }
        for name, (start, end) in cases.items():
            with self.subTest(case=name):
                code, report, queries, out = self.run_report(self.rows, "--window-start", start,
                                                             "--window-end", end)
                self.assertEqual(code, 2, out)
                self.assertIsNone(report)
                self.assertEqual(queries, [])

    def test_report_only_is_unreconciled_and_never_complete(self):
        code, report, _, _ = self.run_report(self.rows, "--window-start", "2026-09-29T10:00:00Z",
                                             "--window-end", "2026-09-29T11:00:00Z")
        self.assertEqual(code, 0)
        self.assertEqual(report["reconciliation_status"], "unreconciled")
        self.assertEqual(report["totals"]["status"], "partial")
        self.assertIsNone(report["totals"]["estimated_usd"])
        self.assertIsNotNone(report["totals"]["partial_estimated_usd"])
        self.assertEqual(report["label"], common.SHOWBACK_LABEL)
        self.assertEqual(report["interval"], {"start": "2026-09-29T10:00:00Z", "end": "2026-09-29T11:00:00Z",
                                              "half_open": True})


class TrafficTests(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.arm = FakeArm()
        self.ctx = make_ctx(self.tmp, self.arm)
        self.session_id = start_session(self.ctx, run_id="500")
        self.env_file = self.tmp / ".env"
        self.env_file.write_text(
            "AZURE_SUBSCRIPTION_ID=sub-test\nAPIM_RESOURCE_GROUP=rg-aigov-lab\nAPIM_NAME=apim-x\n"
            "APIM_GATEWAY_URL=https://apim.example.invalid\nPLATFORM_API_PATH=ai-gateway\n"
            "PLATFORM_API_ID=ai-gateway-api\nAOAI_DEPLOYMENT=chat\n"
            "TEAM_SUBSCRIPTION_IDS=team-retail-sub,team-finance-sub,team-hr-sub\n", encoding="utf-8")
        self.posts = []

    def tearDown(self):
        self._tmp.cleanup()
        self._env.stop()

    def post(self, url, *, headers, json_body, timeout):
        self.posts.append((headers.get("x-client-app"), json_body))
        return FakeResponse(200, {"usage": {"prompt_tokens": 12, "completion_tokens": 5,
                                            "prompt_tokens_details": {"cached_tokens": 2}}},
                            {"apim-request-id": "req"})

    def run_traffic(self, *argv, post=None, env=None):
        out = io.StringIO()
        deps = generate_traffic.Deps(client_factory=lambda: self.arm, http_post=post or self.post, now=Clock(),
                                     out=out, env=dict(env or self.ctx.env))
        code = generate_traffic.main(["--session-id", self.session_id, "--env-file", str(self.env_file),
                                      "--outputs-root", str(self.ctx.paths.outputs), *argv], deps)
        path = self.ctx.paths.showback_dir(self.session_id) / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        return code, manifest, out.getvalue()

    def test_defaults(self):
        args = generate_traffic.build_parser().parse_args([])
        self.assertEqual((args.workers, args.attempts, args.max_tokens, args.reserved_tokens, args.deadline_minutes),
                         (1, 30, 128, 10_000, 5.0))

    def test_serial_run_uses_the_guard_and_records_a_half_open_window(self):
        code, manifest, out = self.run_traffic()
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.posts), 30)
        self.assertTrue(all(body["max_tokens"] == 128 and body["stream"] is False for _, body in self.posts))
        self.assertEqual({app for app, _ in self.posts}, {"retail-web", "finance-batch", "hr-assistant"})
        totals = budget.session_totals(self.session_id, root=self.ctx.paths.budget_root)
        self.assertEqual(totals["attempts"], 30)
        window = manifest["window"]
        start = common.parse_utc(window["start"])
        end = common.parse_utc(window["end"])
        self.assertEqual((start.second, end.second), (0, 0))
        self.assertLess(start, end)
        self.assertTrue(window["half_open"])
        self.assertEqual(manifest["teams"]["team-retail"]["prompt_tokens"], 10 * 12)
        self.assertEqual(manifest["teams"]["team-retail"]["cached_tokens"], 10 * 2)
        self.assertEqual(manifest["settings"]["retries"], 0)

    def test_reserved_token_cap_stops_before_dispatch(self):
        code, manifest, _ = self.run_traffic("--reserved-tokens", "500")
        self.assertEqual(manifest["stopped_reason"], "reserved_tokens_cap")
        self.assertEqual(len(self.posts), 3)
        self.assertLessEqual(manifest["reserved_tokens_used"], 500)

    def test_failures_are_not_retried(self):
        def flaky(url, *, headers, json_body, timeout):
            self.posts.append((headers.get("x-client-app"), json_body))
            if len(self.posts) == 2:
                raise ConnectionError("reset")
            return FakeResponse(500, {"error": {"code": "x"}}) if len(self.posts) == 3 else \
                FakeResponse(200, {"usage": {"prompt_tokens": 1, "completion_tokens": 1}})

        code, manifest, _ = self.run_traffic("--attempts", "4", post=flaky)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.posts), 4)
        self.assertEqual([c["outcome"] for c in manifest["calls"]], ["ok", "error_ConnectionError", "failed", "ok"])
        self.assertEqual(budget.session_totals(self.session_id, root=self.ctx.paths.budget_root)["attempts"], 4)

    def test_keys_are_masked_and_never_persisted(self):
        env = dict(self.ctx.env, GITHUB_ACTIONS="true")
        code, manifest, out = self.run_traffic("--attempts", "3", env=env)
        self.assertEqual(code, 0, out)
        key = "key-team-retail-sub-0123456789abcdef"
        self.assertIn(f"::add-mask::{key}", out)
        self.assertNotIn(key, json.dumps(manifest))
        self.assertLess(out.index("::add-mask::"), out.index("traffic:"))

    def test_more_than_one_worker_is_refused(self):
        code, manifest, out = self.run_traffic("--workers", "2")
        self.assertEqual(code, 1)
        self.assertIsNone(manifest)
        self.assertEqual(self.posts, [])


if __name__ == "__main__":
    unittest.main()
