import ast
import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = [
    ROOT / "notebooks" / "00-setup-and-validation.ipynb",
    ROOT / "notebooks" / "demo1-token-limits.ipynb",
    ROOT / "notebooks" / "demo2-token-metrics.ipynb",
    ROOT / "notebooks" / "demo3-content-safety.ipynb",
    ROOT / "notebooks" / "demo4-resilient-pool.ipynb",
]
DISPLAY_HELPERS = {
    "show_table",
    "plot_remaining_tokens",
    "plot_token_series_by_dimension",
}


class NotebookContentTests(unittest.TestCase):
    def test_display_helpers_are_not_bare_final_expressions(self):
        for notebook_path in NOTEBOOKS:
            notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
            for index, cell in enumerate(notebook["cells"]):
                if cell["cell_type"] != "code":
                    continue
                source = "".join(cell.get("source", []))
                body = ast.parse(source).body
                if not body or not isinstance(body[-1], ast.Expr):
                    continue
                call = body[-1].value
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                    continue
                self.assertNotIn(
                    call.func.attr,
                    DISPLAY_HELPERS,
                    f"{notebook_path.name} cell {index} ends with a bare display helper",
                )

    def test_repository_content_has_no_presentation_references(self):
        paths = [ROOT / "README.md"]
        for directory in ("notebooks", "shared", "policies", "tests"):
            paths.extend(
                path
                for path in (ROOT / directory).rglob("*")
                if path.suffix in {".ipynb", ".py", ".xml"}
            )

        pattern = re.compile(r"M8\.|\b" + "sli" + r"de\b|\b" + "de" + r"ck\b", re.IGNORECASE)
        for path in paths:
            content = path.read_text(encoding="utf-8")
            self.assertIsNone(pattern.search(content), str(path.relative_to(ROOT)))

    def test_demo3_documents_not_tripped_outcome(self):
        notebook = json.loads(
            (ROOT / "notebooks" / "demo3-content-safety.ipynb").read_text(encoding="utf-8")
        )
        source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])
        self.assertIn("NOT TRIPPED", source)
        self.assertIn("CONTENT_SAFETY_THRESHOLD_VIOLENCE", source)
        self.assertIn('kind="warning"', source)
        self.assertIn('key == "harm_threshold" and result["status"] == 200', source)
        self.assertIn("results.classify_stream_response(", source)
        self.assertIn('streaming_not_tripped = stream_class == "not_tripped"', source)
        self.assertIn("INCONCLUSIVE", source)

    def test_demo4_notebook_has_observable_four_phase_routing_demo(self):
        notebook = json.loads(
            (ROOT / "notebooks" / "demo4-resilient-pool.ipynb").read_text(encoding="utf-8")
        )
        source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])
        self.assertIn("## Routing mode -- CALL 1", source)
        self.assertIn("## Routing mode -- CALL 2 and observed weighting", source)
        self.assertIn("## Routing mode -- FAULT", source)
        self.assertIn("## Routing mode -- RECOVER", source)
        self.assertIn("x-served-by", source)
        self.assertIn("configure_mode(\"inference\")", source)
        self.assertIn("no client change at all; the backend ID changes in traces", source)
        self.assertIn("subscription_required=True", source)
        self.assertIn("MOCK_BACKEND_CREDENTIALS", source)

    def test_demo4_fault_and_heal_helpers_update_named_values(self):
        notebook = json.loads(
            (ROOT / "notebooks" / "demo4-resilient-pool.ipynb").read_text(encoding="utf-8")
        )
        tree = ast.parse("\n".join(
            "".join(cell.get("source", []))
            for cell in notebook["cells"]
            if cell["cell_type"] == "code"
        ))
        helper_names = {"set_mock_member", "fault_member", "heal_member", "heal_all"}
        helpers = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in helper_names
        ]
        fake_apim = SimpleNamespace(ensure_named_value=Mock())
        namespace = {
            "CIRCUIT_TRIP_SECONDS": 60,
            "MEMBER_BACKEND_IDS": {
                "east": "demo4-ptu-east",
                "central": "demo4-ptu-central",
                "payg": "demo4-payg",
            },
            "cfg": SimpleNamespace(subscription_id="sub", resource_group="rg", apim_name="apim"),
            "apim": fake_apim,
        }
        exec(compile(ast.Module(body=helpers, type_ignores=[]), "<demo4>", "exec"), namespace)

        namespace["fault_member"]("east", retry_after=42)
        fault_calls = fake_apim.ensure_named_value.call_args_list[:2]
        self.assertEqual(fault_calls[0].args[3:6], ("demo4-mock-fault-east",
                                                     "demo4-mock-fault-east", "429"))
        self.assertEqual(fault_calls[1].args[3:6], ("demo4-mock-retry-after-east",
                                                     "demo4-mock-retry-after-east", "42"))
        namespace["heal_member"]("east")
        namespace["heal_all"]()

        calls = fake_apim.ensure_named_value.call_args_list
        values_by_id = {call.args[3]: call.args[5] for call in calls}
        self.assertEqual(values_by_id["demo4-mock-fault-east"], "healthy")
        self.assertEqual(values_by_id["demo4-mock-retry-after-east"], "60")
        self.assertIn("demo4-mock-fault-central", values_by_id)
        self.assertIn("demo4-mock-fault-payg", values_by_id)


def _notebook_code(notebook_path):
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )


def _call_name(node):
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_http_call(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"requests", "httpx", "session"}
        and node.func.attr in {"post", "get", "put", "patch", "delete", "request", "stream"}
    )


class NotebookSafetyTests(unittest.TestCase):
    def test_no_shell_true_in_notebooks(self):
        for notebook_path in NOTEBOOKS:
            self.assertNotIn("shell=True", _notebook_code(notebook_path), notebook_path.name)

    def test_printed_credentials_are_masked(self):
        sensitive = re.compile(r"(SUBSCRIPTION_KEY|REQUEST_HEADERS|CONNECTION_STRING|_KEY$|TOKEN$)")
        for notebook_path in NOTEBOOKS:
            tree = ast.parse(_notebook_code(notebook_path))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and _call_name(node) == "print"):
                    continue
                masked = {
                    id(inner)
                    for call in ast.walk(node)
                    if isinstance(call, ast.Call) and _call_name(call) == "mask_secret"
                    for inner in ast.walk(call)
                }
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Name) and sensitive.search(inner.id):
                        self.assertIn(
                            id(inner), masked,
                            f"{notebook_path.name} prints {inner.id} without mask_secret",
                        )

    def test_policies_get_identity_client_id_injection(self):
        for notebook_path in NOTEBOOKS[1:]:
            self.assertIn(
                "apim.apply_identity_client_id(policy_xml, cfg.apim_identity_client_id)",
                _notebook_code(notebook_path),
                notebook_path.name,
            )

    def test_demo2_uses_explicit_logger_without_message_capture(self):
        source = _notebook_code(ROOT / "notebooks" / "demo2-token-metrics.ipynb")
        self.assertNotIn("get_app_insights_for_apim", source)
        self.assertIn("apim.get_app_insights_logger(", source)
        self.assertIn("apim.assert_no_llm_message_capture(diagnostic_readback)", source)
        self.assertIn("identity_client_id=cfg.apim_identity_client_id", source)
        self.assertIn("allow_local_auth=allow_local_auth_logger", source)

    def test_demo4_mock_templates_match_forwarded_suffix(self):
        source = _notebook_code(ROOT / "notebooks" / "demo4-resilient-pool.ipynb")
        self.assertIn('"POST", f"/{member}/*")', source)
        self.assertIn("backend_credential_header_names", source)
        self.assertIn('RESULTS.exclude("demo4.cleanup", "optional_disabled")', source)


class NotebookResultsTests(unittest.TestCase):
    def test_every_notebook_records_its_required_objectives(self):
        from shared import results

        for notebook_path in NOTEBOOKS:
            name = notebook_path.stem
            tree = ast.parse(_notebook_code(notebook_path))
            recorded = set()
            recorder_names = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                first = node.args[0]
                if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                    continue
                if _call_name(node) == "record":
                    recorded.add(first.value)
                elif _call_name(node) == "NotebookResults":
                    recorder_names.add(first.value)
            with self.subTest(notebook=name):
                self.assertEqual(recorder_names, {name})
                self.assertEqual(recorded, set(results.REQUIRED_OBJECTIVES[name]))


class BudgetEnvelopeTests(unittest.TestCase):
    ENVELOPE = ROOT / "config" / "session-envelope.json"

    def _labels(self, tree):
        return {
            keyword.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == "label"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        }

    def test_every_http_call_is_wrapped_by_guarded_request(self):
        for notebook_path in NOTEBOOKS:
            source = _notebook_code(notebook_path)
            self.assertNotIn("import httpx", source, notebook_path.name)
            tree = ast.parse(source)
            guarded = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _call_name(node) == "guarded_request":
                    send = node.args[3] if len(node.args) > 3 else next(
                        (kw.value for kw in node.keywords if kw.arg == "send"), None
                    )
                    self.assertIsInstance(send, ast.Lambda, notebook_path.name)
                    guarded.update(id(inner) for inner in ast.walk(send))
            for node in ast.walk(tree):
                if _is_http_call(node):
                    self.assertIn(
                        id(node), guarded,
                        f"{notebook_path.name} line {node.lineno}: HTTP call outside guarded_request",
                    )

    def test_shared_modules_do_not_send_inference_requests(self):
        for path in (ROOT / "shared").glob("*.py"):
            if path.name in {"apim.py"}:
                continue
            self.assertNotIn("import requests", path.read_text(encoding="utf-8"), path.name)

    def test_envelope_lists_every_call_site(self):
        envelope = json.loads(self.ENVELOPE.read_text(encoding="utf-8"))
        self.assertEqual(set(envelope["notebooks"]), {path.stem for path in NOTEBOOKS})
        for notebook_path in NOTEBOOKS:
            sites = envelope["notebooks"][notebook_path.stem]["call_sites"]
            enabled = {site["label"] for site in sites if site["enabled"]}
            listed = {site["label"] for site in sites}
            labels = self._labels(ast.parse(_notebook_code(notebook_path)))
            with self.subTest(notebook=notebook_path.stem):
                self.assertTrue(labels.issubset(listed), labels - listed)
                self.assertEqual(enabled, labels)

    def test_envelope_totals_are_consistent(self):
        envelope = json.loads(self.ENVELOPE.read_text(encoding="utf-8"))
        sites = [
            site for notebook in envelope["notebooks"].values() for site in notebook["call_sites"]
        ]
        for site in sites:
            with self.subTest(label=site["label"]):
                self.assertIn(site["kind"], {"model", "safety", "mock"})
                expected = (
                    0 if site["kind"] == "mock"
                    else site["max_attempts"] * (site["estimated_input_tokens"] + site["max_output_tokens"])
                )
                self.assertEqual(site["reserved_tokens"], expected)
                if site["kind"] != "mock" and site["enabled"]:
                    self.assertGreater(site["max_output_tokens"], 0)
        totals = envelope["totals"]
        self.assertEqual(totals["max_attempts"], sum(site["max_attempts"] for site in sites))
        self.assertEqual(totals["max_reserved_tokens"], sum(site["reserved_tokens"] for site in sites))
        self.assertEqual(
            totals["mock_attempts"],
            sum(site["max_attempts"] for site in sites if site["kind"] == "mock"),
        )
        self.assertEqual(
            totals["model_and_safety_attempts"],
            sum(site["max_attempts"] for site in sites if site["kind"] != "mock"),
        )


if __name__ == "__main__":
    unittest.main()
