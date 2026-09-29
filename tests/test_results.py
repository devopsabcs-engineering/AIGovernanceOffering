import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared import config, results

EVENT_STREAM = {"Content-Type": "text/event-stream; charset=utf-8"}
CHUNK = 'data: {"choices":[{"delta":{"content":"Hello"}}]}'


def _sse(*events):
    return "\n\n".join(events) + "\n\n"


class StreamClassifierTests(unittest.TestCase):
    FIXTURES = {
        "empty_200": (200, EVENT_STREAM, ""),
        "html_200": (200, {"Content-Type": "text/html"}, "<html><body>Sign in</body></html>"),
        "malformed_sse": (200, EVENT_STREAM, _sse(CHUNK, "data: {not json")),
        "truncated_sse": (200, EVENT_STREAM, _sse(CHUNK, CHUNK)),
        "complete_safe_sse": (200, EVENT_STREAM, _sse(CHUNK, CHUNK, "data: [DONE]")),
        "unrelated_403": (403, {"Content-Type": "application/json"},
                          '{"statusCode": 403, "message": "Forbidden"}'),
        "confirmed_interruption": (
            200, EVENT_STREAM,
            _sse(CHUNK, 'data: {"error": {"code": "content_safety_violation"}}'),
        ),
    }

    def test_only_confirmed_interruption_passes(self):
        for name, (status, headers, body) in self.FIXTURES.items():
            with self.subTest(fixture=name):
                classified = results.classify_stream_response(status, headers, body)
                objective = results.objective_status(classified["classification"])
                self.assertEqual(objective == "passed", name == "confirmed_interruption", classified)

    def test_expected_classifications(self):
        expected = {
            "empty_200": "inconclusive",
            "html_200": "transport_error",
            "malformed_sse": "transport_error",
            "truncated_sse": "inconclusive",
            "complete_safe_sse": "not_tripped",
            "unrelated_403": "transport_error",
            "confirmed_interruption": "policy_block_confirmed",
        }
        for name, (status, headers, body) in self.FIXTURES.items():
            with self.subTest(fixture=name):
                self.assertEqual(
                    results.classify_stream_response(status, headers, body)["classification"],
                    expected[name],
                )

    def test_header_provenance_confirms_truncated_stream(self):
        headers = {**EVENT_STREAM, "x-content-safety-decision": "blocked"}
        classified = results.classify_stream_response(200, headers, _sse(CHUNK))
        self.assertEqual(classified["classification"], "policy_block_confirmed")

    def test_transport_failure_without_status(self):
        classified = results.classify_stream_response(None, {}, "")
        self.assertEqual(results.objective_status(classified["classification"]), "failed")

    def test_classifier_output_is_valid_evidence(self):
        for status, headers, body in self.FIXTURES.values():
            results.validate_evidence(results.classify_stream_response(status, headers, body))


class BlockClassifierTests(unittest.TestCase):
    def test_block_requires_content_safety_provenance(self):
        cases = [
            (200, {}, "{}", "not_tripped"),
            (403, {"x-content-safety-decision": "blocked"}, "{}", "policy_block_confirmed"),
            (403, {}, '{"error": "content_safety_violation"}', "policy_block_confirmed"),
            (403, {}, '{"statusCode": 403, "message": "quota"}', "transport_error"),
            (401, {}, "{}", "transport_error"),
            (500, {}, "", "transport_error"),
        ]
        for status, headers, body, expected in cases:
            with self.subTest(status=status, body=body):
                self.assertEqual(results.classify_block_response(status, headers, body), expected)

    def test_prompt_shield_not_tripped_can_fail(self):
        self.assertEqual(results.objective_status("not_tripped", not_tripped_status="failed"), "failed")
        self.assertEqual(results.objective_status("not_tripped"), "inconclusive")


class TokenLimitClassifierTests(unittest.TestCase):
    def test_gateway_and_backend_attribution(self):
        cases = [
            (200, {}, "{}", "ok"),
            (429, {"remaining-tokens": "0", "Retry-After": "30"},
             '{"statusCode": 429, "message": "Token limit is exceeded."}', "gateway_rate_limit"),
            (429, {"Retry-After": "30", "x-ratelimit-remaining-tokens": "0"},
             '{"error": {"code": "429", "message": "Rate limit"}}', "backend_throttle"),
            (429, {"remaining-tokens": "0"}, '{"error": {"code": "429"}}', "backend_throttle"),
            (403, {"remaining-quota-tokens": "0"},
             '{"statusCode": 403, "message": "Token quota is exceeded."}', "gateway_quota"),
            (403, {}, '{"statusCode": 403, "message": "Out of call volume quota."}', "gateway_quota"),
            (403, {"x-content-safety-decision": "blocked"}, "{}", "content_safety_block"),
            (403, {}, '{"error": {"code": "PermissionDenied"}}', "other"),
        ]
        for status, headers, body, expected in cases:
            with self.subTest(status=status, headers=headers):
                self.assertEqual(
                    results.classify_token_limit_response(status, headers, body), expected
                )


def _calls(*pairs):
    return [{"status": status, "served_by": member} for member, status in pairs]


EAST, CENTRAL, PAYG = results.DEMO4_MEMBERS


class Demo4EvaluatorTests(unittest.TestCase):
    HEALTHY = _calls(*([(EAST, 200)] * 20 + [(CENTRAL, 200)] * 10))

    def test_healthy_routing_passes(self):
        status, evidence = results.evaluate_routing_paths(self.HEALTHY)
        self.assertEqual(status, "passed")
        results.validate_evidence(evidence)

    def test_routing_failures(self):
        failing = {
            "all_404": _calls(*([("not returned", 404)] * 10)),
            "unknown_member": self.HEALTHY + _calls(("demo4-unknown", 200)),
            "missing_member_header": self.HEALTHY + [{"status": 200}],
            "no_central": _calls(*([(EAST, 200)] * 10)),
            "payg_while_healthy": self.HEALTHY + _calls((PAYG, 200)),
            "mock_without_backend_credential_401": _calls(*([("not returned", 401)] * 10)),
            "empty": [],
        }
        for name, calls in failing.items():
            with self.subTest(case=name):
                self.assertEqual(results.evaluate_routing_paths(calls)[0], "failed")

    def test_fault_phase(self):
        observed = _calls((EAST, 429), (EAST, 429), (CENTRAL, 200))
        self.assertEqual(results.evaluate_fault_observed(observed)[0], "passed")
        failing = {
            "no_fault": _calls((EAST, 200), (CENTRAL, 200)),
            "one_fault": _calls((EAST, 429), (CENTRAL, 200)),
            "unknown_member": observed + _calls(("not returned", 429)),
            "unexpected_status": observed + _calls((CENTRAL, 500)),
            "all_404": _calls(*([("not returned", 404)] * 12)),
        }
        for name, calls in failing.items():
            with self.subTest(case=name):
                self.assertEqual(results.evaluate_fault_observed(calls)[0], "failed")

    def test_alternate_routing(self):
        after_east = _calls((CENTRAL, 200), (CENTRAL, 200))
        after_both = _calls((CENTRAL, 429), (PAYG, 200))
        self.assertEqual(results.evaluate_alternate_routing(after_east, after_both)[0], "passed")
        failing = {
            "no_central": (_calls((EAST, 429)), after_both),
            "no_payg": (after_east, _calls((CENTRAL, 429), (EAST, 429))),
            "unknown_member": (after_east + _calls(("x", 200)), after_both),
            "empty_phase": (after_east, []),
        }
        for name, (first, second) in failing.items():
            with self.subTest(case=name):
                self.assertEqual(results.evaluate_alternate_routing(first, second)[0], "failed")

    def test_recovery_requires_prior_fault(self):
        recovered = _calls((EAST, 200), (CENTRAL, 200))
        self.assertEqual(results.evaluate_recovery(recovered, "passed")[0], "passed")
        self.assertEqual(results.evaluate_recovery(recovered, "failed")[0], "failed")
        self.assertEqual(results.evaluate_recovery(recovered, None)[0], "failed")
        self.assertEqual(results.evaluate_recovery(_calls((CENTRAL, 200)), "passed")[0], "failed")
        self.assertEqual(
            results.evaluate_recovery(recovered + _calls(("not returned", 404)), "passed")[0], "failed"
        )

    def test_mock_auth_probe_expects_401(self):
        self.assertEqual(results.evaluate_mock_auth_probe(401)[0], "passed")
        for status in (200, 403, 404, None):
            with self.subTest(status=status):
                self.assertEqual(results.evaluate_mock_auth_probe(status)[0], "failed")


class RecordObjectiveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_records_atomically_and_merges(self):
        path = results.record_objective(
            "demo1-token-limits", "demo1.baseline", "passed", {"status": 200},
            session_id="run-1", root=self.root,
        )
        results.record_objective(
            "demo1-token-limits", "demo1.rate_limit_429", "failed", {"requests_sent": 20},
            session_id="run-1", root=self.root,
        )
        self.assertEqual(path, self.root / "run-1" / "demo1-token-limits.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(data["objectives"]), {"demo1.baseline", "demo1.rate_limit_429"})
        self.assertEqual(data["objectives"]["demo1.baseline"]["evidence"], {"status": 200})
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_rejects_unknown_ids_statuses_and_notebooks(self):
        with self.assertRaises(results.ResultsError):
            results.record_objective("demo1-token-limits", "demo1.unknown", "passed",
                                     session_id="run-1", root=self.root)
        with self.assertRaises(results.ResultsError):
            results.record_objective("demo1-token-limits", "demo1.baseline", "ok",
                                     session_id="run-1", root=self.root)
        with self.assertRaises(results.ResultsError):
            results.record_objective("demo9", "demo1.baseline", "passed",
                                     session_id="run-1", root=self.root)
        with self.assertRaises(results.ResultsError):
            results.record_objective("demo1-token-limits", "demo1.baseline", "passed",
                                     session_id="../escape", root=self.root)

    def test_evidence_rejects_free_text_and_credentials(self):
        rejected = [
            {"reply": "Hello! Here is a long model response with punctuation? yes!"},
            {"subscription_key": "abc"},
            {"value": "0123456789abcdef0123456789abcdef"},
            {"BadKey": 1},
            {"nested": {"k": {"deeper": 1}}},
            {"number": float("nan")},
        ]
        for evidence in rejected:
            with self.subTest(evidence=evidence):
                with self.assertRaises(results.ResultsError):
                    results.validate_evidence(evidence)

    def test_exclusion_is_recorded(self):
        recorder = results.NotebookResults("demo4-resilient-pool", session_id="run-2", root=self.root)
        recorder.exclude("demo4.cleanup", "optional_disabled")
        data = results.load_results("demo4-resilient-pool", "run-2", self.root)
        self.assertEqual(data["excluded"]["demo4.cleanup"]["reason"], "optional_disabled")
        with self.assertRaises(results.ResultsError):
            recorder.exclude("demo4.routing_paths", "optional_disabled")

    def test_recorder_binds_session_id_at_creation(self):
        with patch.dict(os.environ, {"AIGOV_HEADLESS": "", "SESSION_ID": "", "DEMO_RUN": "first"}):
            recorder = results.NotebookResults("demo1-token-limits", root=self.root)
            os.environ["DEMO_RUN"] = "rotated"
            recorder.record("demo1.reset_recovery", "inconclusive", {"status": 200})
        self.assertTrue((self.root / "first" / "demo1-token-limits.json").exists())

    def test_session_id_resolution(self):
        with patch.dict(os.environ, {"AIGOV_HEADLESS": "1"}):
            with self.assertRaises(config.ConfigError):
                results.resolve_session_id({"DEMO_RUN": "abc"})
            self.assertEqual(results.resolve_session_id({"SESSION_ID": "s-1", "DEMO_RUN": "abc"}), "s-1")
        with patch.dict(os.environ, {"AIGOV_HEADLESS": ""}):
            self.assertEqual(results.resolve_session_id({"DEMO_RUN": "abc"}), "abc")

    def test_every_notebook_has_required_objectives(self):
        self.assertEqual(
            set(results.REQUIRED_OBJECTIVES),
            {"00-setup-and-validation", "demo1-token-limits", "demo2-token-metrics",
             "demo3-content-safety", "demo4-resilient-pool"},
        )
        for notebook, objectives in results.REQUIRED_OBJECTIVES.items():
            self.assertEqual(len(objectives), len(set(objectives)), notebook)


if __name__ == "__main__":
    unittest.main()
