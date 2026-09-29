import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from shared import budget

FUTURE = (datetime.now(timezone.utc) + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
BODY = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 20}


def _env(**overrides):
    env = {
        "SESSION_ID": "run-1",
        "SESSION_MAX_ATTEMPTS": "10",
        "SESSION_MAX_RESERVED_TOKENS": "1000",
        "SESSION_MAX_ESTIMATED_USD": "1.0",
        "SESSION_DEADLINE_UTC": FUTURE,
    }
    env.update(overrides)
    return env


def _ok():
    return SimpleNamespace(status_code=200)


class GuardedRequestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        headless = patch.dict(os.environ, {"AIGOV_HEADLESS": ""})
        headless.start()
        self.addCleanup(headless.stop)

    def _call(self, env, kind="model", input_tokens=30, max_tokens=20, send=_ok, body="default"):
        body = dict(BODY) if body == "default" else body
        return budget.guarded_request(
            kind, input_tokens, max_tokens, send, body=body, label="test.call",
            env=env, root=self.root,
        )

    def _state(self, session_id="run-1"):
        return json.loads(budget.budget_path(session_id, self.root).read_text(encoding="utf-8"))

    def _init(self, env, price=None):
        limits = budget.load_limits(env)
        budget.init_session(env["SESSION_ID"], limits, price=price, root=self.root)

    def test_zero_budget_blocks_before_dispatch(self):
        env = _env(SESSION_MAX_ATTEMPTS="0")
        sent = []
        with self.assertRaises(budget.BudgetExceeded):
            self._call(env, send=lambda: sent.append(1))
        self.assertEqual(sent, [])

    def test_insufficient_token_reservation_blocks(self):
        env = _env(SESSION_MAX_RESERVED_TOKENS="60")
        self._call(env)
        sent = []
        with self.assertRaisesRegex(budget.BudgetExceeded, "token"):
            self._call(env, send=lambda: sent.append(1))
        self.assertEqual(sent, [])
        self.assertEqual(self._state()["totals"]["attempts"], 1)

    def test_timeout_is_counted_as_consumed(self):
        env = _env()

        def timeout():
            raise TimeoutError("read timed out")

        with self.assertRaises(TimeoutError):
            self._call(env, send=timeout)
        state = self._state()
        self.assertEqual(state["totals"]["attempts"], 1)
        self.assertEqual(state["totals"]["reserved_tokens"], 50)
        self.assertEqual(state["totals"]["errors"], 1)
        self.assertEqual(state["entries"][0]["outcome"], "error:TimeoutError")

    def test_burst_and_retry_share_counters(self):
        env = _env(SESSION_MAX_ATTEMPTS="3")
        self._call(env)
        self._call(env, send=lambda: SimpleNamespace(status_code=429))
        self._call(env)
        with self.assertRaisesRegex(budget.BudgetExceeded, "attempt"):
            self._call(env)
        state = self._state()
        self.assertEqual(state["totals"]["attempts"], 3)
        self.assertEqual([entry["outcome"] for entry in state["entries"]],
                         ["http_200", "http_429", "http_200"])

    def test_missing_state_fails_in_headless_mode(self):
        with patch.dict(os.environ, {"AIGOV_HEADLESS": "1"}):
            with self.assertRaisesRegex(budget.BudgetStateError, "missing"):
                self._call(_env())

    def test_headless_without_session_keys_fails_closed(self):
        with patch.dict(os.environ, {"AIGOV_HEADLESS": "1"}):
            with self.assertRaises(budget.BudgetStateError):
                self._call({})

    def test_headless_model_call_requires_price_snapshot(self):
        env = _env()
        self._init(env)
        with patch.dict(os.environ, {"AIGOV_HEADLESS": "1"}):
            with self.assertRaisesRegex(budget.BudgetStateError, "price"):
                self._call(env)
            self._call(env, kind="mock", max_tokens=0, body=None)

    def test_usd_reservation_is_enforced(self):
        env = _env(SESSION_MAX_ESTIMATED_USD="0.00005")
        self._init(env, price={"input_usd_per_million": 1.0, "output_usd_per_million": 1.0,
                               "snapshot_id": "test-snapshot"})
        with patch.dict(os.environ, {"AIGOV_HEADLESS": "1"}):
            self._call(env)
            with self.assertRaisesRegex(budget.BudgetExceeded, "USD"):
                self._call(env)
        self.assertAlmostEqual(self._state()["totals"]["reserved_usd"], 0.00005)

    def test_ambiguous_price_is_rejected(self):
        with self.assertRaises(budget.BudgetStateError):
            budget.validate_price({"input_usd_per_million": None, "output_usd_per_million": 1.0,
                                   "snapshot_id": "x"})
        with self.assertRaises(budget.BudgetStateError):
            budget.validate_price({"input_usd_per_million": 1.0, "output_usd_per_million": 1.0})

    def test_mock_calls_count_without_token_reservation(self):
        env = _env()
        self._call(env, kind="mock", input_tokens=0, max_tokens=0, body=None)
        totals = self._state()["totals"]
        self.assertEqual(totals["attempts"], 1)
        self.assertEqual(totals["reserved_tokens"], 0)
        self.assertEqual(totals["by_kind"]["mock"], 1)

    def test_model_calls_require_matching_max_tokens(self):
        env = _env()
        for body, max_tokens in ((None, 20), ({"max_tokens": 50}, 20), (BODY, 0)):
            with self.subTest(body=body, max_tokens=max_tokens):
                with self.assertRaises(ValueError):
                    self._call(env, max_tokens=max_tokens, body=body)
        self.assertFalse(budget.budget_path("run-1", self.root).exists())

    def test_deadline_blocks_dispatch(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.assertRaisesRegex(budget.BudgetExceeded, "deadline"):
            self._call(_env(SESSION_DEADLINE_UTC=past))

    def test_existing_state_is_never_reset(self):
        env = _env()
        self._init(env)
        with self.assertRaises(budget.BudgetStateError):
            self._init(env)

    def test_partial_session_keys_are_an_error(self):
        with self.assertRaisesRegex(budget.BudgetStateError, "SESSION_MAX_ATTEMPTS"):
            budget.load_limits({"SESSION_ID": "run-1"})

    def test_record_only_mode_never_blocks_interactively(self):
        before = budget.record_only_totals()["attempts"]
        response = self._call({})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(budget.record_only_totals()["attempts"], before + 1)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_estimate_is_conservative(self):
        self.assertGreaterEqual(budget.estimate_prompt_tokens("x" * 300), 100)
        self.assertEqual(
            budget.estimate_prompt_tokens("hi"),
            budget.estimate_prompt_tokens([{"role": "user", "content": "hi"}]),
        )


if __name__ == "__main__":
    unittest.main()
