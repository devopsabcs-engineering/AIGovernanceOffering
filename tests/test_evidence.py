"""Tests for the notebook completion checker and the evidence sanitizer/renderer."""

import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.automation_fakes import common  # noqa: F401  (adds scripts/ to sys.path)
import check_notebook_outputs as checker
import render_evidence
from shared import results

SESSION = "300-1"
HAS_MATPLOTLIB = importlib.util.find_spec("matplotlib") is not None


def _executed_notebook(outputs=None, status="completed", exception=False):
    return {
        "metadata": {"papermill": {"exception": exception}},
        "cells": [
            {"cell_type": "markdown", "source": "# title", "metadata": {}},
            {"cell_type": "code", "source": "x = 1", "metadata": {"papermill": {"status": status}},
             "outputs": outputs if outputs is not None else [
                 {"output_type": "stream", "name": "stdout", "text": "PASS"}]},
        ],
    }


class SessionFixture:
    """A complete synthetic session under a temp outputs root."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.paths = common.Paths(tmp / "outputs")
        self.notebooks = tmp / "notebooks"
        self.notebooks.mkdir()
        self.executed = self.paths.executed_dir(SESSION)
        self.executed.mkdir(parents=True)
        runs = []
        for stem in common.NOTEBOOK_STEMS:
            source = self.notebooks / f"{stem}.ipynb"
            source.write_text(json.dumps({"cells": [], "name": stem}), encoding="utf-8")
            self.write_executed(stem, _executed_notebook())
            runs.append({"notebook": stem, "exit_code": 0, "started_at": "2026-09-29T10:00:00Z",
                         "ended_at": "2026-09-29T10:01:00Z", "source_sha256": common.sha256_file(source)})
        self.write_execution(runs)
        for stem, objectives in results.REQUIRED_OBJECTIVES.items():
            for objective_id in objectives:
                results.record_objective(stem, objective_id, "passed", {"count": 1},
                                         session_id=SESSION, root=self.paths.results_root)
        results.record_exclusion("demo4-resilient-pool", "demo4.cleanup", "optional cell not run",
                                 session_id=SESSION, root=self.paths.results_root)

    def write_executed(self, stem, notebook):
        (self.executed / f"{stem}.ipynb").write_text(json.dumps(notebook), encoding="utf-8")

    def write_execution(self, runs):
        (self.executed / "execution.json").write_text(
            json.dumps({"schema_version": 1, "session_id": SESSION, "runs": runs}), encoding="utf-8")

    def execution(self):
        return json.loads((self.executed / "execution.json").read_text(encoding="utf-8"))

    def check(self):
        out = io.StringIO()
        code = checker.main(["--session-id", SESSION, "--notebooks-dir", str(self.notebooks),
                             "--outputs-root", str(self.paths.outputs)], out=out)
        verdict = json.loads((self.paths.results_dir(SESSION) / "verdict.json").read_text(encoding="utf-8"))
        return code, verdict

    def write_reports(self):
        write = results.atomic_write_json
        write(self.paths.readiness_dir(SESSION) / "summary.json", {
            "schema_version": 1, "session_id": SESSION, "status": "passed", "failing_check": "", "scope": "",
            "checks": {"gateway": {"status": "passed", "attempts": 1, "code": "http_200"}}})
        write(self.paths.readiness_dir(SESSION) / "probes.json", {
            "status": "passed", "probes": {"anonymous": {"status": 401, "passed": True}}})
        write(self.paths.showback_dir(SESSION) / "report.json", {
            "label": common.SHOWBACK_LABEL,
            "interval": {"start": "2026-09-29T10:00:00Z", "end": "2026-09-29T10:06:00Z"},
            "snapshot_id": "fixture-test-only", "price_coverage": "complete",
            "reconciliation_status": "reconciled", "coverage": "complete",
            "teams": {"team-retail": {"prompt_tokens": 100, "completion_tokens": 50, "estimated_usd": "0.00015"}},
            "totals": {"status": "complete", "suppressed_reason": "", "prompt_tokens": 100,
                       "completion_tokens": 50, "estimated_usd": "0.00015", "partial_estimated_usd": None},
            "counts": {"duplicate_rows": 0}, "exclusions": ["Cache discounts are excluded."]})
        write(self.paths.budget_root / SESSION / "budget.json", {
            "schema_version": 1, "session_id": SESSION,
            "limits": {"max_attempts": 10, "max_reserved_tokens": 1000, "max_estimated_usd": 1.0,
                       "deadline_utc": "2026-09-29T14:00:00Z"},
            "price": {"snapshot_id": "fixture-test-only", "input_usd_per_million": 0.5,
                      "output_usd_per_million": 2.0},
            "totals": {"attempts": 3, "reserved_tokens": 300, "reserved_usd": 0.0001, "errors": 0,
                       "by_kind": {"model": 3, "safety": 0, "mock": 0}},
            "entries": [{"label": "x", "reserved_at": "2026-09-29T10:00:00Z"}]})

    def sanitize(self, phase="pre-cleanup", env_file=None):
        out = io.StringIO()
        argv = ["sanitize", "--session-id", SESSION, "--phase", phase, "--outputs-root", str(self.paths.outputs),
                "--env-file", str(env_file or (self.tmp / "missing.env"))]
        return render_evidence.main(argv, out=out), out.getvalue()

    @property
    def evidence_file(self):
        return self.paths.evidence_dir(SESSION) / "evidence.json"


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = SessionFixture(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_complete_session_passes(self):
        code, verdict = self.fx.check()
        self.assertEqual(code, 0, verdict["problems"])
        self.assertEqual(verdict["status"], "passed")
        self.assertEqual(verdict["excluded"], {"demo4.cleanup": "intentionally_excluded"})

    def test_empty_directory_fails(self):
        for path in self.fx.executed.iterdir():
            path.unlink()
        code, verdict = self.fx.check()
        self.assertEqual(code, 1)
        self.assertIn("execution_json_missing", verdict["problems"])

    def test_missing_notebook_fails(self):
        (self.fx.executed / "demo2-token-metrics.ipynb").unlink()
        code, verdict = self.fx.check()
        self.assertEqual(code, 1)
        self.assertEqual(verdict["notebooks"]["demo2-token-metrics"]["execution"], "missing")

    def test_renamed_notebook_fails(self):
        (self.fx.executed / "demo1-token-limits.ipynb").rename(self.fx.executed / "demo1 copy.ipynb")
        code, verdict = self.fx.check()
        self.assertEqual(code, 1)
        self.assertIn("unexpected_notebook:demo1_copy", verdict["problems"])

    def test_stale_output_fails(self):
        (self.fx.notebooks / "demo3-content-safety.ipynb").write_text("{}", encoding="utf-8")
        code, verdict = self.fx.check()
        self.assertEqual(code, 1)
        self.assertEqual(verdict["notebooks"]["demo3-content-safety"]["execution"], "stale")

    def test_killed_kernel_fails(self):
        self.fx.write_executed("demo4-resilient-pool", _executed_notebook(status="pending"))
        code, verdict = self.fx.check()
        self.assertEqual(code, 1)
        self.assertEqual(verdict["notebooks"]["demo4-resilient-pool"]["execution"], "incomplete_cell")
        execution = self.fx.execution()
        execution["runs"][0]["exit_code"] = 137
        self.fx.write_execution(execution["runs"])
        _, verdict = self.fx.check()
        self.assertEqual(verdict["notebooks"]["00-setup-and-validation"]["execution"], "failed")

    def test_traceback_after_pass_fails(self):
        outputs = [{"output_type": "stream", "name": "stdout", "text": "PASS"},
                   {"output_type": "error", "ename": "RuntimeError", "evalue": "x", "traceback": []}]
        self.fx.write_executed("demo1-token-limits", _executed_notebook(outputs=outputs))
        code, verdict = self.fx.check()
        self.assertEqual(code, 1)
        self.assertEqual(verdict["notebooks"]["demo1-token-limits"]["execution"], "error_output")
        stderr = [{"output_type": "stream", "name": "stdout", "text": "PASS"},
                  {"output_type": "stream", "name": "stderr", "text": ["Traceback (most recent call last):\n"]}]
        self.fx.write_executed("demo1-token-limits", _executed_notebook(outputs=stderr))
        _, verdict = self.fx.check()
        self.assertEqual(verdict["notebooks"]["demo1-token-limits"]["execution"], "traceback_output")

    def test_inconclusive_observational_objective_does_not_fail(self):
        results.record_objective("demo3-content-safety", "demo3.stream_intervention", "inconclusive", {},
                                 session_id=SESSION, root=self.fx.paths.results_root)
        code, verdict = self.fx.check()
        self.assertEqual(code, 0, verdict["problems"])
        self.assertEqual(verdict["status"], "passed")
        self.assertEqual(verdict["objectives"]["demo3.stream_intervention"]["status"], "inconclusive")
        self.assertEqual(verdict["counts"]["inconclusive"], 1)

    def test_failed_observational_objective_fails(self):
        results.record_objective("demo3-content-safety", "demo3.stream_intervention", "failed", {},
                                 session_id=SESSION, root=self.fx.paths.results_root)
        code, verdict = self.fx.check()
        self.assertEqual(code, 1)
        self.assertEqual(verdict["status"], "failed")

    def test_inconclusive_required_objective_fails(self):
        results.record_objective("demo3-content-safety", "demo3.prompt_shield_block", "inconclusive", {},
                                 session_id=SESSION, root=self.fx.paths.results_root)
        code, verdict = self.fx.check()
        self.assertEqual(code, 1)
        self.assertEqual(verdict["counts"]["inconclusive"], 1)

    def test_missing_objective_fails(self):
        path = self.fx.paths.results_root / SESSION / "demo2-token-metrics.json"
        path.unlink()
        code, verdict = self.fx.check()
        self.assertEqual(code, 1)
        self.assertEqual(verdict["objectives"]["demo2.metrics_reconciled"]["status"], "missing")


class SanitizerTests(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {}, clear=False)
        self._env.start()
        os.environ.pop("GITHUB_SHA", None)
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = SessionFixture(Path(self._tmp.name))
        self.fx.check()

    def tearDown(self):
        self._tmp.cleanup()
        self._env.stop()

    def assert_failed_closed(self, reason=None):
        code, out = self.fx.sanitize()
        self.assertEqual(code, 1, out)
        self.assertFalse(self.fx.evidence_file.exists())
        self.assertFalse((self.fx.paths.evidence_dir(SESSION) / "png").exists())
        status = json.loads((self.fx.paths.evidence_dir(SESSION) / "sanitize-status.json").read_text())
        self.assertEqual(status["status"], "failed")
        if reason:
            self.assertEqual(status["reason"], reason)
        return out

    def _set_evidence(self, stem, objective_id, evidence):
        path = self.fx.paths.results_root / SESSION / f"{stem}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["objectives"][objective_id]["evidence"] = evidence
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_builds_allowlisted_evidence_with_not_run_inputs(self):
        self.fx.write_reports()
        code, out = self.fx.sanitize()
        self.assertEqual(code, 0, out)
        evidence = json.loads(self.fx.evidence_file.read_text(encoding="utf-8"))
        self.assertEqual(evidence["kind"], "aigov-evidence")
        self.assertEqual(list(evidence["labs"]), [lab for lab, _ in render_evidence.LABS])
        self.assertEqual(evidence["labs"]["lab00-environment"]["status"], "passed")
        self.assertEqual(evidence["labs"]["lab06-chargeback"]["status"], "passed")
        self.assertEqual(evidence["labs"]["lab07-teardown"]["status"], "not_run")
        self.assertEqual(evidence["residual"], {"status": "not_run"})
        self.assertEqual(evidence["budget"]["spent"]["attempts"], 3)
        self.assertNotIn("entries", json.dumps(evidence["budget"]))

    def test_missing_inputs_are_not_errors(self):
        code, out = self.fx.sanitize()
        self.assertEqual(code, 0, out)
        evidence = json.loads(self.fx.evidence_file.read_text(encoding="utf-8"))
        for key in ("readiness", "probes", "showback", "budget", "residual"):
            self.assertEqual(evidence[key], {"status": "not_run"}, key)

    def test_fake_key_in_result_evidence_fails_closed(self):
        self._set_evidence("demo1-token-limits", "demo1.baseline", {"value": "0123456789abcdef0123456789abcdef"})
        self.fx.evidence_file.parent.mkdir(parents=True, exist_ok=True)
        self.fx.evidence_file.write_text("{}", encoding="utf-8")
        self.assert_failed_closed()

    def test_bearer_token_fails_closed(self):
        self._set_evidence("demo3-content-safety", "demo3.safe_prompt", {"note": "Bearer abcdefghijklmnopqrstuv"})
        self.assert_failed_closed("credential_pattern")

    def test_connection_string_fails_closed(self):
        self._set_evidence("demo2-token-metrics", "demo2.logger_configured",
                           {"note": "InstrumentationKey=fake;IngestionEndpoint=https://x"})
        self.assert_failed_closed("credential_pattern")

    def test_fake_key_in_error_string_fails_closed(self):
        verdict_path = self.fx.paths.results_dir(SESSION) / "verdict.json"
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        verdict["problems"] = ["notebook_failed:0123456789abcdef0123456789abcdef"]
        verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
        self.assert_failed_closed("credential_pattern")

    def test_jwt_in_metadata_fails_closed(self):
        self.fx.write_reports()
        results.atomic_write_json(self.fx.paths.residual_dir(SESSION) / "report.json", {
            "status": "residual", "action": "deleted", "active": [
                {"type": "microsoft.apimanagement/service", "name": "eyJhbGciOiJIUzI1.eyJzdWIiOiIx.c2ln"}]})
        self.assert_failed_closed("credential_pattern")

    def test_known_secret_value_fails_closed(self):
        self.fx.write_reports()
        env_file = self.fx.tmp / ".env"
        env_file.write_text("AOAI_KEY=zq9-known-fake-value\n", encoding="utf-8")
        summary = self.fx.paths.readiness_dir(SESSION) / "summary.json"
        data = json.loads(summary.read_text(encoding="utf-8"))
        data["checks"]["gateway"]["code"] = "zq9-known-fake-value"
        summary.write_text(json.dumps(data), encoding="utf-8")
        code, _ = self.fx.sanitize(env_file=env_file)
        self.assertEqual(code, 1)
        self.assertFalse(self.fx.evidence_file.exists())

    def test_malformed_input_fails_closed(self):
        (self.fx.paths.readiness_dir(SESSION)).mkdir(parents=True, exist_ok=True)
        (self.fx.paths.readiness_dir(SESSION) / "summary.json").write_text("not json", encoding="utf-8")
        self.assert_failed_closed("malformed_input")

    def test_non_passed_objectives_map_to_lab_status(self):
        results.record_objective("demo3-content-safety", "demo3.prompt_shield_block", "inconclusive", {},
                                 session_id=SESSION, root=self.fx.paths.results_root)
        results.record_objective("demo1-token-limits", "demo1.baseline", "failed", {},
                                 session_id=SESSION, root=self.fx.paths.results_root)
        self.assertEqual(self.fx.sanitize()[0], 0)
        labs = json.loads(self.fx.evidence_file.read_text(encoding="utf-8"))["labs"]
        self.assertEqual(labs["lab04-content-safety"]["status"], "inconclusive")
        self.assertEqual(labs["lab02-token-limits"]["status"], "failed")
        self.assertEqual(labs["lab01-setup-validation"]["status"], "passed")

    def test_observational_inconclusive_keeps_lab_passed(self):
        results.record_objective("demo3-content-safety", "demo3.stream_intervention", "inconclusive", {},
                                 session_id=SESSION, root=self.fx.paths.results_root)
        self.assertEqual(self.fx.sanitize()[0], 0)
        labs = json.loads(self.fx.evidence_file.read_text(encoding="utf-8"))["labs"]
        self.assertEqual(labs["lab04-content-safety"]["status"], "passed")

    def test_renderer_refuses_notebooks_and_tainted_evidence(self):
        out = io.StringIO()
        notebook = self.fx.executed / "demo1-token-limits.ipynb"
        self.assertEqual(render_evidence.main(["render", "--evidence", str(notebook), "--out-dir",
                                               str(self.fx.tmp / "png")], out=out), 1)
        self.assertFalse((self.fx.tmp / "png").exists())
        self.assertEqual(self.fx.sanitize()[0], 0)
        text = self.fx.evidence_file.read_text(encoding="utf-8")
        self.fx.evidence_file.write_text(text.replace('"local"', '"InstrumentationKey=x"'), encoding="utf-8")
        self.assertEqual(render_evidence.main(["render", "--evidence", str(self.fx.evidence_file), "--out-dir",
                                               str(self.fx.tmp / "png")], out=out), 1)
        self.assertFalse((self.fx.tmp / "png").exists())

    def test_renderer_does_not_open_notebook_files(self):
        source = (Path(render_evidence.__file__)).read_text(encoding="utf-8")
        self.assertNotIn("nbformat", source)
        self.assertNotIn("executed_dir", source)
        self.assertNotIn("requests", source)

    @unittest.skipUnless(HAS_MATPLOTLIB, "matplotlib is not installed")
    def test_render_writes_canonical_names_and_status_cards(self):
        self.fx.write_reports()
        results.record_objective("demo3-content-safety", "demo3.prompt_shield_block", "inconclusive", {},
                                 session_id=SESSION, root=self.fx.paths.results_root)
        self.assertEqual(self.fx.sanitize()[0], 0)
        out_dir = self.fx.tmp / "png"
        self.assertEqual(render_evidence.main(["render", "--evidence", str(self.fx.evidence_file),
                                               "--out-dir", str(out_dir)], out=io.StringIO()), 0)
        names = sorted(p.name for p in out_dir.glob("*.png"))
        self.assertIn("lab04-content-safety-status.png", names)
        self.assertNotIn("lab04-content-safety-summary.png", names)
        self.assertIn("lab07-teardown-status.png", names)
        self.assertIn("lab06-chargeback-tokens.png", names)
        for lab, _ in render_evidence.LABS:
            self.assertTrue(any(name.startswith(lab + "-") for name in names), lab)


if __name__ == "__main__":
    unittest.main()
