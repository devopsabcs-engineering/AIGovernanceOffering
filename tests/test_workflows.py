"""Contract tests for the GitHub workflows (Step 5.4): permissions, lock, conditions, timeouts, pins."""

import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs PyYAML from requirements-ci.txt
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
CLOUD_WORKFLOWS = ("lab-session.yml", "teardown.yml")
ALL_WORKFLOWS = ("ci.yml", "pages.yml") + CLOUD_WORKFLOWS
PARAMS = ROOT / "infra" / "main.bicepparam"
HOSTED_JOB_LIMIT = 360
LOCK_GROUP = "aigov-lab-env"
BLANKED = ("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL")

# Step 5.2 matrix, written as literal `if:` expressions. live() == !cancelled(), ok(x) == outcome success.
INIT_OK = "steps.init_session.outcome == 'success'"
NB_OK = "steps.nb_init.outcome == 'success'"
DEPLOY_LOGIN_MODES = "inputs.mode == 'dry-run' || inputs.mode == 'full-session' || inputs.mode == 'deploy-only'"
CREATING = "inputs.mode == 'full-session' || inputs.mode == 'deploy-only'"
RUNTIME = ("(inputs.mode == 'full-session' || inputs.mode == 'deploy-only' || "
           "inputs.mode == 'run-existing' || inputs.mode == 'report-only')")
CLEANUP = f"always() && {INIT_OK} && ({CREATING})"
NOTEBOOKS = {
    "setup": "00-setup-and-validation",
    "demo1": "demo1-token-limits",
    "demo2": "demo2-token-metrics",
    "demo3": "demo3-content-safety",
    "demo4": "demo4-resilient-pool",
}

EXPECTED_CONDITIONS = {
    "init_session": "inputs.mode != 'lock-test'",
    "login_deploy": DEPLOY_LOGIN_MODES,
    "preflight": DEPLOY_LOGIN_MODES,
    "what_if": DEPLOY_LOGIN_MODES,
    "manifest_create": CREATING,
    "upload_manifest": "steps.manifest_create.outcome == 'success'",
    "deploy": "steps.manifest_create.outcome == 'success'",
    "account_clear_runtime": f"!cancelled() && {INIT_OK} && {RUNTIME}",
    "login_runtime": f"!cancelled() && {INIT_OK} && {RUNTIME}",
    "manifest_verify": "inputs.mode == 'run-existing' || inputs.mode == 'report-only'",
    "write_env": "steps.deploy.outcome == 'success' || steps.manifest_verify.outcome == 'success'",
    "readiness": ("steps.write_env.outcome == 'success' && (inputs.mode == 'full-session' || "
                  "inputs.mode == 'deploy-only' || inputs.mode == 'run-existing')"),
    "probe_scopes": "steps.readiness.outcome == 'success' && (inputs.mode == 'full-session' || inputs.mode == 'run-existing')",
    "nb_init": "steps.probe_scopes.outcome == 'success' && (inputs.mode == 'full-session' || inputs.mode == 'run-existing')",
}
for _key in NOTEBOOKS:
    EXPECTED_CONDITIONS[f"login_nb_{_key}"] = f"!cancelled() && {NB_OK}"
    EXPECTED_CONDITIONS[f"nb_{_key}"] = f"!cancelled() && {NB_OK} && steps.login_nb_{_key}.outcome == 'success'"
EXPECTED_CONDITIONS.update({
    "login_traffic": f"!cancelled() && {NB_OK}",
    "traffic": f"!cancelled() && {NB_OK} && steps.login_traffic.outcome == 'success'",
    "showback": (f"!cancelled() && (({NB_OK} && steps.traffic.outcome == 'success') || "
                 "(inputs.mode == 'report-only' && steps.write_env.outcome == 'success'))"),
    "check_notebooks": f"!cancelled() && {NB_OK}",
    "sanitize": f"always() && {INIT_OK} && inputs.mode != 'dry-run'",
    "upload_evidence": f"always() && {INIT_OK} && inputs.mode != 'dry-run' && steps.sanitize.outcome == 'success'",
    "account_clear_cleanup": CLEANUP,
    "login_deploy_cleanup": CLEANUP,
    "cleanup": CLEANUP,
    "post_sanitize": CLEANUP,
    "upload_post": f"{CLEANUP} && steps.post_sanitize.outcome == 'success'",
})
# always() is reserved for evidence and cleanup; everything else is live() or implicit success().
ALWAYS_STEPS = {"sanitize", "upload_evidence", "account_clear_cleanup", "login_deploy_cleanup", "cleanup",
                "post_sanitize", "upload_post"}
CLEANUP_STEPS = {"account_clear_cleanup", "login_deploy_cleanup", "cleanup", "post_sanitize", "upload_post"}
SETUP_STEP_NAMES = ["Record job start", "Check out", "Set up Python", "Install dependencies"]
ALLOWED_UPLOAD_PATHS = {
    "outputs/evidence/${{ env.SESSION_ID }}/evidence.json",
    "outputs/manifest/${{ env.SESSION_ID }}/",
}
PINNED_USES = re.compile(r"^\s*(?:-\s+)?uses:\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)@([0-9a-f]{40})\s+#\s+v\d+(?:\.\d+)*\s*$")


def _load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _text(name):
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _triggers(data):
    # YAML 1.1 reads a bare `on` key as boolean True.
    return data.get("on", data.get(True))


def _cond(value):
    if value is None:
        return None
    text = str(value).strip()
    match = re.fullmatch(r"\$\{\{\s*(.*?)\s*\}\}", text, re.S)
    if match:
        text = match.group(1)
    return re.sub(r"\s+", " ", text).strip()


def _steps_by_id(job):
    return {step["id"]: step for step in job["steps"] if "id" in step}


def _flag(output, flag):
    match = re.search(rf"{re.escape(flag)}\s+(\d+)", output)
    assert match, f"{flag} missing"
    return int(match.group(1))


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-ci.txt)")
class WorkflowShapeTests(unittest.TestCase):
    def test_workflow_files_exist_and_parse(self):
        for name in ALL_WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertIsInstance(_load(name), dict)

    def test_cloud_workflows_have_empty_workflow_permissions(self):
        for name in CLOUD_WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertEqual(_load(name)["permissions"], {})

    def test_ci_is_read_only_and_never_logs_in(self):
        data = _load("ci.yml")
        self.assertEqual(data["permissions"], {"contents": "read"})
        self.assertEqual(set(_triggers(data)), {"push", "pull_request"})
        text = _text("ci.yml")
        self.assertNotIn("azure/login", text)
        self.assertNotIn("id-token", text)
        for job_name, job in data["jobs"].items():
            with self.subTest(job=job_name):
                self.assertNotIn("environment", job)
                self.assertNotIn("permissions", job)

    def test_ci_runs_required_checks(self):
        text = _text("ci.yml")
        for fragment in (
            "python -m unittest discover -s tests -t .",
            "az bicep build --file infra/main.bicep",
            "az bicep lint --file infra/main.bicep",
            "az bicep build-params --file infra/main.bicepparam",
            "actionlint",
            "jekyll build --source docs",
            "Invoke-ScriptAnalyzer",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)

    def test_cloud_workflows_share_one_lock_and_are_manual_only(self):
        for name in CLOUD_WORKFLOWS:
            data = _load(name)
            with self.subTest(workflow=name):
                self.assertEqual(data["concurrency"], {"group": LOCK_GROUP, "cancel-in-progress": False})
                self.assertEqual(list(_triggers(data)), ["workflow_dispatch"])
                for job_name, job in data["jobs"].items():
                    self.assertNotIn("concurrency", job, f"{job_name} must not define job-level concurrency")

    def test_no_reusable_or_scheduled_triggers(self):
        for name in ALL_WORKFLOWS:
            with self.subTest(workflow=name):
                triggers = _triggers(_load(name))
                for forbidden in ("workflow_call", "schedule", "pull_request_target", "workflow_run"):
                    self.assertNotIn(forbidden, triggers)

    def test_pages_publishes_docs_without_azure_access(self):
        data = _load("pages.yml")
        self.assertEqual(data["permissions"], {"contents": "read"})
        self.assertEqual(set(_triggers(data)), {"push", "workflow_dispatch"})
        self.assertNotEqual(data["concurrency"]["group"], LOCK_GROUP)
        text = _text("pages.yml")
        self.assertNotIn("azure/login", text)
        self.assertNotIn("AIGOV_", text)
        self.assertIn("jekyll build --source docs", text)
        deploy = data["jobs"]["deploy"]
        self.assertEqual(deploy["environment"]["name"], "github-pages")
        self.assertEqual(deploy["permissions"], {"pages": "write", "id-token": "write"})
        self.assertNotIn("permissions", data["jobs"]["build"])

    def test_exactly_one_environment_job_per_cloud_workflow(self):
        expected = {"lab-session.yml": "cloud", "teardown.yml": "teardown"}
        for name in CLOUD_WORKFLOWS:
            jobs = _load(name)["jobs"]
            with self.subTest(workflow=name):
                env_jobs = [j for j, job in jobs.items() if "environment" in job]
                self.assertEqual(env_jobs, [expected[name]])
                self.assertEqual(jobs[expected[name]]["environment"], "lab")
                self.assertEqual(jobs[expected[name]]["permissions"], {"id-token": "write", "contents": "read"})
                token_jobs = [j for j, job in jobs.items() if (job.get("permissions") or {}).get("id-token")]
                self.assertEqual(token_jobs, [expected[name]])

    def test_lock_test_jobs_have_no_environment_or_token(self):
        for name, condition in (("lab-session.yml", "inputs.mode == 'lock-test'"), ("teardown.yml", "inputs.lock_test")):
            job = _load(name)["jobs"]["lock-test"]
            with self.subTest(workflow=name):
                self.assertNotIn("environment", job)
                self.assertEqual(job["permissions"], {})
                self.assertEqual(_cond(job["if"]), condition)
                text = str(job)
                self.assertNotIn("azure/login", text)
                self.assertNotIn(" az ", f" {text} ")
                self.assertTrue(any("sleep" in step.get("run", "") for step in job["steps"]))

    def test_protected_jobs_skip_the_lock_rehearsal(self):
        self.assertEqual(_cond(_load("lab-session.yml")["jobs"]["cloud"]["if"]), "inputs.mode != 'lock-test'")
        self.assertEqual(_cond(_load("teardown.yml")["jobs"]["teardown"]["if"]), "!inputs.lock_test")

    def test_lab_session_inputs(self):
        inputs = _triggers(_load("lab-session.yml"))["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["mode"]["options"],
                         ["full-session", "deploy-only", "run-existing", "report-only", "dry-run", "lock-test"])
        self.assertIs(inputs["keep_environment"]["default"], False)
        for key in ("generation", "confirm_resource_group", "report_window_start", "report_window_end"):
            self.assertIn(key, inputs)

    def test_teardown_inputs_default_to_dry_run(self):
        inputs = _triggers(_load("teardown.yml"))["workflow_dispatch"]["inputs"]
        self.assertIs(inputs["execute"]["default"], False)
        self.assertIs(inputs["lock_test"]["default"], False)
        for key in ("confirm_resource_group", "generation"):
            self.assertIn(key, inputs)


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-ci.txt)")
class TimeoutTests(unittest.TestCase):
    def test_every_step_capped_and_job_timeout_covers_sum(self):
        for name in CLOUD_WORKFLOWS:
            for job_name, job in _load(name)["jobs"].items():
                with self.subTest(workflow=name, job=job_name):
                    caps = []
                    for step in job["steps"]:
                        cap = step.get("timeout-minutes")
                        self.assertIsInstance(cap, int, f"step {step.get('name')} lacks timeout-minutes")
                        self.assertGreater(cap, 0)
                        caps.append(cap)
                    self.assertIsInstance(job.get("timeout-minutes"), int)
                    self.assertGreaterEqual(job["timeout-minutes"], sum(caps))
                    self.assertLessEqual(job["timeout-minutes"], HOSTED_JOB_LIMIT)

    def test_session_deadline_arguments_match_step_caps(self):
        job = _load("lab-session.yml")["jobs"]["cloud"]
        steps = _steps_by_id(job)
        run = steps["init_session"]["run"]
        self.assertEqual(_flag(run, "--job-timeout-minutes"), job["timeout-minutes"])
        self.assertEqual(_flag(run, "--cleanup-login-minutes"),
                         steps["account_clear_cleanup"]["timeout-minutes"] + steps["login_deploy_cleanup"]["timeout-minutes"])
        self.assertEqual(_flag(run, "--cleanup-minutes"), steps["cleanup"]["timeout-minutes"])
        self.assertEqual(_flag(run, "--post-sanitize-minutes"), steps["post_sanitize"]["timeout-minutes"])
        self.assertEqual(_flag(run, "--upload-minutes"), steps["upload_post"]["timeout-minutes"])
        after_traffic = sum(steps[s]["timeout-minutes"] for s in ("showback", "check_notebooks", "sanitize", "upload_evidence"))
        self.assertGreaterEqual(_flag(run, "--margin-minutes"), after_traffic)

    def test_script_timeouts_end_before_step_caps(self):
        for step in _load("lab-session.yml")["jobs"]["cloud"]["steps"] + _load("teardown.yml")["jobs"]["teardown"]["steps"]:
            match = re.search(r"--timeout-seconds (\d+)", step.get("run", ""))
            if match:
                with self.subTest(step=step["name"]):
                    self.assertLess(int(match.group(1)), step["timeout-minutes"] * 60)


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-ci.txt)")
class StepMatrixTests(unittest.TestCase):
    def setUp(self):
        self.job = _load("lab-session.yml")["jobs"]["cloud"]
        self.steps = _steps_by_id(self.job)

    def test_step_ids_follow_the_matrix_order(self):
        ids = [step["id"] for step in self.job["steps"] if "id" in step]
        self.assertEqual(ids, list(EXPECTED_CONDITIONS))
        setup = [step for step in self.job["steps"] if "id" not in step]
        self.assertEqual([step["name"] for step in setup], SETUP_STEP_NAMES)
        for step in setup:
            self.assertNotIn("if", step)

    def test_each_condition_matches_the_matrix(self):
        for step_id, expected in EXPECTED_CONDITIONS.items():
            with self.subTest(step=step_id):
                self.assertEqual(_cond(self.steps[step_id].get("if")), expected)

    def test_always_reserved_for_evidence_and_cleanup(self):
        for step in self.job["steps"]:
            condition = _cond(step.get("if")) or ""
            with self.subTest(step=step.get("id", step["name"])):
                if step.get("id") in ALWAYS_STEPS:
                    self.assertTrue(condition.startswith("always() && "))
                else:
                    self.assertNotIn("always()", condition)
                    self.assertNotIn("success()", condition)

    def test_paid_steps_use_live(self):
        paid = [s for s in EXPECTED_CONDITIONS if s.startswith(("nb_", "login_nb_")) and s != "nb_init"]
        paid += ["login_traffic", "traffic", "showback", "check_notebooks", "account_clear_runtime", "login_runtime"]
        for step_id in paid:
            with self.subTest(step=step_id):
                self.assertTrue(_cond(self.steps[step_id]["if"]).startswith("!cancelled() && "))

    def test_logins_use_the_intended_identity(self):
        deploy = {"login_deploy", "login_deploy_cleanup"}
        for step in self.job["steps"]:
            if "azure/login@" not in step.get("uses", ""):
                continue
            with self.subTest(step=step["id"]):
                expected = "AIGOV_DEPLOY_CLIENT_ID" if step["id"] in deploy else "AIGOV_RUNTIME_CLIENT_ID"
                self.assertEqual(step["with"]["client-id"], f"${{{{ vars.{expected} }}}}")

    def test_identity_switches_clear_the_az_profile(self):
        ids = [step["id"] for step in self.job["steps"] if "id" in step]
        for clear, login in (("account_clear_runtime", "login_runtime"), ("account_clear_cleanup", "login_deploy_cleanup")):
            with self.subTest(login=login):
                self.assertEqual(ids.index(clear) + 1, ids.index(login))
                self.assertEqual(self.steps[clear]["run"].strip(), "az account clear")

    def test_each_notebook_runs_once_after_its_own_login(self):
        ids = [step["id"] for step in self.job["steps"] if "id" in step]
        for key, notebook in NOTEBOOKS.items():
            with self.subTest(notebook=notebook):
                self.assertEqual(ids.index(f"login_nb_{key}") + 1, ids.index(f"nb_{key}"))
                self.assertIn(f"run-notebooks --only {notebook} ", self.steps[f"nb_{key}"]["run"] + " ")
        self.assertIn("run-notebooks --init", self.steps["nb_init"]["run"])

    def test_steps_call_the_expected_commands(self):
        commands = {
            "init_session": "scripts/lab_session.py init-session",
            "preflight": "scripts/lab_session.py preflight --params infra/main.bicepparam",
            "what_if": "scripts/lab_session.py what-if",
            "manifest_create": 'scripts/lab_session.py manifest create --mode "$AIGOV_LAB_MODE"',
            "deploy": "scripts/lab_session.py deploy",
            "manifest_verify": 'scripts/lab_session.py manifest verify --mode "$AIGOV_LAB_MODE"',
            "write_env": "scripts/lab_session.py write-env",
            "readiness": "scripts/lab_session.py readiness",
            "probe_scopes": "scripts/lab_session.py probe-scopes",
            "traffic": "scripts/generate_traffic.py",
            "showback": "scripts/showback_report.py",
            "check_notebooks": "scripts/check_notebook_outputs.py",
            "sanitize": "scripts/render_evidence.py sanitize --phase pre-cleanup",
            "cleanup": 'scripts/lab_session.py cleanup --auto --mode "$AIGOV_LAB_MODE"',
            "post_sanitize": "scripts/render_evidence.py sanitize --phase post-cleanup",
        }
        for step_id, command in commands.items():
            with self.subTest(step=step_id):
                self.assertIn(command, self.steps[step_id]["run"])

    def test_cleanup_reads_step_outcomes_not_job_outputs(self):
        env = self.steps["cleanup"]["env"]
        self.assertEqual(env["DEPLOY_OUTCOME"], "${{ steps.deploy.outcome }}")
        self.assertEqual(env["READINESS_OUTCOME"], "${{ steps.readiness.outcome }}")
        self.assertEqual(env["KEEP_ENVIRONMENT"], "${{ inputs.keep_environment }}")
        for step_id in CLEANUP_STEPS:
            with self.subTest(step=step_id):
                text = str(self.steps[step_id])
                self.assertNotIn("needs.", text)
                self.assertNotIn(".outputs.", text)

    def test_untrusted_code_steps_cannot_mint_tokens(self):
        for step in self.job["steps"]:
            run = step.get("run", "")
            if not any(marker in run for marker in ("run-notebooks --only", "generate_traffic.py", "showback_report.py",
                                                    "check_notebook_outputs.py", "render_evidence.py")):
                continue
            with self.subTest(step=step["id"]):
                env = step.get("env") or {}
                for name in BLANKED:
                    self.assertEqual(env.get(name), "")

    def test_only_the_first_sanitize_sets_evidence_ready(self):
        self.assertIn("evidence_ready=true", self.steps["sanitize"]["run"])
        for step in self.job["steps"]:
            if step.get("id") != "sanitize":
                self.assertNotIn("evidence_ready", step.get("run", ""))
        outputs = self.job["outputs"]
        self.assertIn("steps.sanitize.outputs.evidence_ready == 'true'", outputs["evidence_ready"])

    def test_mode_input_reaches_scripts_through_env(self):
        self.assertEqual(self.job["env"]["AIGOV_LAB_MODE"], "${{ inputs.mode }}")
        for step in self.job["steps"]:
            with self.subTest(step=step.get("id", step["name"])):
                self.assertNotIn("${{", step.get("run", ""))

    def test_bicep_parameters_are_supplied(self):
        text = PARAMS.read_text(encoding="utf-8")
        env = self.job["env"]
        ci_env = _load("ci.yml")["jobs"]["bicep"]["env"]
        for match in re.finditer(r"readEnvironmentVariable\('([A-Z0-9_]+)'(?:\s*,\s*'([^']*)')?\)", text):
            name, default = match.group(1), match.group(2)
            with self.subTest(variable=name):
                self.assertIn(name, env)
                self.assertIn(name, ci_env)
                if default is not None:
                    self.assertTrue(str(env[name]).endswith(f"|| '{default}' }}}}"),
                                    f"{name} needs the bicepparam default as its fallback")


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-ci.txt)")
class RenderAndArtifactTests(unittest.TestCase):
    def test_renderer_is_credential_free_and_offline(self):
        job = _load("lab-session.yml")["jobs"]["render"]
        self.assertNotIn("environment", job)
        self.assertEqual(job["permissions"], {"contents": "read"})
        self.assertEqual(job["needs"], "cloud")
        self.assertEqual(_cond(job["if"]), "always() && needs.cloud.outputs.evidence_ready == 'true'")
        self.assertNotIn("azure/login", str(job))
        render_steps = [s for s in job["steps"] if "render_evidence.py render" in s.get("run", "")]
        self.assertEqual(len(render_steps), 1)
        self.assertIn("unshare --net", render_steps[0]["run"])
        self.assertIn("connect_ex", render_steps[0]["run"])

    def test_uploads_overwrite_and_carry_only_evidence_and_manifest(self):
        names = {}
        for name in CLOUD_WORKFLOWS:
            for job_name, job in _load(name)["jobs"].items():
                for step in job["steps"]:
                    if "actions/upload-artifact@" not in step.get("uses", ""):
                        continue
                    with self.subTest(workflow=name, step=step["name"]):
                        options = step["with"]
                        self.assertIs(options.get("overwrite"), True)
                        names.setdefault(options["name"], 0)
                        names[options["name"]] += 1
                        if job_name == "cloud":
                            paths = {p.strip() for p in str(options["path"]).splitlines() if p.strip()}
                            self.assertTrue(paths)
                            self.assertLessEqual(paths, ALLOWED_UPLOAD_PATHS)
        self.assertEqual(names.get("aigov-evidence-${{ env.SESSION_ID }}"), 2)

    def test_no_secret_or_raw_output_paths_in_uploads(self):
        for name in CLOUD_WORKFLOWS:
            text = _text(name)
            for forbidden in ("outputs/session", "outputs/executed", ".env\n", "/logs"):
                with self.subTest(workflow=name, path=forbidden):
                    self.assertNotIn(forbidden, text)


class StaticTextTests(unittest.TestCase):
    """Raw-text checks that need no YAML parser."""

    def test_all_actions_pinned_to_full_sha_with_version_comment(self):
        for name in ALL_WORKFLOWS:
            for number, line in enumerate(_text(name).splitlines(), 1):
                if re.match(r"^\s*(?:-\s+)?uses:", line):
                    with self.subTest(workflow=name, line=number):
                        self.assertRegex(line, PINNED_USES)

    def test_papermill_never_logs_output_and_nothing_purges(self):
        for name in ALL_WORKFLOWS:
            text = _text(name)
            with self.subTest(workflow=name):
                self.assertNotIn("--log-output", text)
                self.assertIsNone(re.search(r"lab_session\.py\s+purge|\bpurge\s+--execute", text))

    def test_lab_session_subcommands_are_allowlisted(self):
        allowed = {"init-session", "preflight", "what-if", "manifest", "deploy", "write-env", "readiness",
                   "probe-scopes", "run-notebooks", "cleanup"}
        for name in CLOUD_WORKFLOWS:
            for sub in re.findall(r"scripts/lab_session\.py\s+([a-z-]+)", _text(name)):
                with self.subTest(workflow=name, subcommand=sub):
                    self.assertIn(sub, allowed)

    def test_checkout_never_persists_credentials(self):
        for name in ALL_WORKFLOWS:
            text = _text(name)
            with self.subTest(workflow=name):
                self.assertEqual(text.count("actions/checkout@"), text.count("persist-credentials: false"))

    def test_bicep_cli_is_pinned_identically(self):
        versions = {}
        for name in ("ci.yml", "lab-session.yml"):
            text = _text(name)
            with self.subTest(workflow=name):
                self.assertIn("bicep.use_binary_from_path=false", text)
                found = re.findall(r"az bicep install --version (v\d+\.\d+\.\d+)", text)
                self.assertEqual(len(found), 1)
                versions[name] = found[0]
        self.assertEqual(len(set(versions.values())), 1, versions)


if __name__ == "__main__":
    unittest.main()
