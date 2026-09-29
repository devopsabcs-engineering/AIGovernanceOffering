"""Tests for the Demo 3 approved-fixture override."""

import json
import tempfile
import unittest
from pathlib import Path

from shared import fixtures


def _approved(**overrides):
    data = {
        "version": "rai-2026-10-v1",
        "fixtures": {
            key: {
                "case": key,
                "input_label": f"Approved {key}",
                "prompt": f"approved prompt for {key}",
                "expected_status": 200 if key == "safe_business_prompt" else 403,
                "expected_evidence": "evidence",
            }
            for key in fixtures.FIXTURE_KEYS
        },
    }
    data.update(overrides)
    return data


class ApprovedFixtureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "approved.json"
        self._saved = (fixtures.FIXTURE_SET_VERSION, fixtures.DEMO3_FIXTURES)

    def tearDown(self):
        fixtures.FIXTURE_SET_VERSION, fixtures.DEMO3_FIXTURES = self._saved
        self._tmp.cleanup()

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def test_placeholders_cover_every_key_and_field(self):
        self.assertEqual(set(fixtures.DEMO3_FIXTURES), set(fixtures.FIXTURE_KEYS))
        for key, entry in fixtures.DEMO3_FIXTURES.items():
            with self.subTest(fixture=key):
                for field in fixtures.FIXTURE_FIELDS:
                    self.assertIn(field, entry)

    def test_approved_file_replaces_placeholders(self):
        self.write(_approved())
        fixtures._apply_override({fixtures.FIXTURES_FILE_ENV: str(self.path)})
        self.assertEqual(fixtures.FIXTURE_SET_VERSION, "rai-2026-10-v1")
        self.assertEqual(fixtures.DEMO3_FIXTURES["prompt_injection"]["prompt"], "approved prompt for prompt_injection")

    def test_no_env_keeps_placeholders(self):
        fixtures._apply_override({})
        self.assertEqual(fixtures.FIXTURE_SET_VERSION, self._saved[0])

    def test_incomplete_or_malformed_files_are_refused(self):
        partial = _approved()
        del partial["fixtures"]["streaming_completion"]
        missing_field = _approved()
        del missing_field["fixtures"]["harm_threshold"]["expected_status"]
        empty_prompt = _approved()
        empty_prompt["fixtures"]["prompt_injection"]["prompt"] = "  "
        for name, data in (("partial", partial), ("missing_field", missing_field),
                           ("empty_prompt", empty_prompt), ("no_version", _approved(version=""))):
            with self.subTest(case=name):
                self.write(data)
                with self.assertRaises(fixtures.FixtureError):
                    fixtures.load_approved_fixtures(self.path)
        with self.assertRaises(fixtures.FixtureError):
            fixtures.load_approved_fixtures(Path(self._tmp.name) / "missing.json")

    def test_error_messages_never_echo_prompt_text(self):
        data = _approved()
        data["fixtures"]["prompt_injection"]["prompt"] = ""
        self.write(data)
        with self.assertRaises(fixtures.FixtureError) as ctx:
            fixtures.load_approved_fixtures(self.path)
        self.assertNotIn("approved prompt", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
