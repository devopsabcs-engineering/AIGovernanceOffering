<!-- markdownlint-disable-file -->
# Implementation Details: APIM Basic v2 IaC, Automated Labs, Showback, Teardown, and Bilingual Site

## Context Reference

Sources:

* .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (authoritative; gates G1-G9, dispositions P01-P08, A01-A11, F1-F10)
* .copilot-tracking/research/subagents/2026-09-28/adversarial-platform-review.md, adversarial-automation-review.md, adversarial-telemetry-review.md (defect evidence)
* .copilot-tracking/research/subagents/2026-09-28/current-repo-research.md, sibling-fsi-lab-pattern-research.md, apim-lza-apiops-research.md (inventory only; superseded where they conflict)
* .copilot-tracking/plans/logs/2026-09-28/apim-basicv2-iac-labs-log.md (DD-01 user-assigned identity, DD-02 human purge, DD-03 manifest store)

Global rules for every phase:

* Local unit test command: `python -m unittest discover -s tests -t .`
* Never print, log, persist in artifacts, or commit secrets. Keep `.env` out of logs and artifacts.
* tests/test_notebooks.py forbids the regex `M8\.|\bslide\b|\bdeck\b` in README.md and in notebooks, shared, policies, and tests. New text on those surfaces must comply.
* Edit notebooks with the notebook editing tool, not raw JSON rewrites. Cell numbers below are 1-based visible cells from the research; re-anchor before editing.
* Before generating Bicep or running any Azure command, load Azure best-practice guidance (Azure MCP `get_azure_bestpractices`, Bicep best practices, and resource type schemas via the Bicep MCP tools).
* Phases 1-5 are local and credential-free. Phase 6 and later require explicit user approval before any Azure or GitHub-settings mutation.

## Implementation Phase 1: Local safety, privacy, and headless compatibility

<!-- parallelizable: true -->

Files owned by this phase: shared/*.py, notebooks/*.ipynb, policies/demo*.xml, .env.example, tests/test_apim.py, tests/test_config.py, tests/test_notebooks.py, new shared/results.py, new shared/budget.py, new tests/test_results.py, new tests/test_budget.py, new config/session-envelope.json.

All `outputs/` paths are anchored to the repository root via `shared.config.REPO_ROOT` (notebooks run with `notebooks/` as cwd); `.gitignore` already ignores `outputs/`.

### Step 1.1: Prevent secret output at source

Remove clear-text credential output and sanitize exception text.

* notebooks/demo4-resilient-pool.ipynb cell 10 source lines 1-8: stop printing REQUEST_HEADERS with the raw subscription key; print headers through `auth.mask_secret` or print only header names.
* shared/apim.py lines 30-40: exception messages include full response bodies. Truncate bodies (for example 500 characters) and redact values matching known secret keys (`primaryKey`, `secondaryKey`, `connectionString`, `key`, `Ocp-Apim-Subscription-Key`, `api-key`, `Authorization`) before building the message.
* Search notebooks and shared for other `print(` of headers, keys, connection strings, or tokens and apply the same masking.

Discrepancy references: addresses A01 and R10 source-prevention requirement.

Success criteria:

* No code path prints a subscription key, connection string, bearer token, or API key value.
* New test in tests/test_apim.py asserts the exception builder redacts a fake `primaryKey` and `Authorization` value.

Context references:

* .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 31-66) - local evidence table
* .copilot-tracking/research/subagents/2026-09-28/adversarial-automation-review.md (section HIGH A01) - raw evidence disclosure

Dependencies:

* None

### Step 1.2: Explicit logger ownership and managed-identity ingestion

Make every Application Insights logger use managed-identity ingestion with explicit owner IDs.

* shared/apim.py `ensure_logger` (around line 426): accept `identity_client_id` and write credentials `{"connectionString": ..., "identityClientId": <client id or "SystemAssigned">}`. Verify the exact credential shape against the current APIM "Integrate Application Insights" documentation before coding. When `APIM_IDENTITY_CLIENT_ID` is unset (interactive users), use `SystemAssigned` and document that the APIM system identity needs Monitoring Metrics Publisher on the component. A connection-string-only logger is created only when `DEMO2_ALLOW_LOCAL_AUTH_LOGGER=true` is explicitly set; headless mode rejects that flag.
* shared/apim.py first-logger discovery (around line 470): replace with lookup by explicit logger ID; raise if the named logger is absent or points to a different App Insights resource ID.
* notebooks/demo2-token-metrics.ipynb: pass the explicit logger ID `demo2-application-insights`, the App Insights resource ID, and `APIM_IDENTITY_CLIENT_ID` from config. Allow only the precisely named first-run "logger absent" and "diagnostic absent" preflight states; re-check logger, diagnostic, and identity after configuration.
* Platform logger `apimlogger` is Bicep-owned; notebook helpers must never write it. Add a guard that rejects `logger_id == "apimlogger"` in notebook helpers.

Discrepancy references: addresses F9, P06 dimension readback, R14; implements DD-01.

Success criteria:

* Unit tests show the logger PUT body contains `identityClientId`, defaults to `SystemAssigned` when `APIM_IDENTITY_CLIENT_ID` is unset, rejects the local-auth flag in headless mode, and never selects "first available" logger.
* A connection-string-only request fails with a clear error instead of silently enabling local auth.

Context references:

* .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 107-117) - metrics and privacy contract
* .copilot-tracking/research/subagents/2026-09-28/adversarial-telemetry-review.md (section HIGH F9) - logger authentication and ownership

Dependencies:

* None

### Step 1.3: Disable LLM message capture

* shared/apim.py `ensure_api_diagnostic` (around line 521, API version 2025-09-01-preview): remove request/response `messages: "all"` capture. Disable LLM logging for the diagnostic per the pinned schema (omit the `largeLanguageModel` block or set its `logs` to `disabled`, whichever the schema accepts on readback). Keep `metrics: true` and custom-dimension behavior required by Demo 2. Keep HTTP body bytes at 0 and do not log credential headers.
* Verify the helper docstring claim that `logs` is invalid against the pinned schema and readback; update the docstring to state only verified behavior.
* Add a readback check helper `assert_no_llm_message_capture(diagnostic)` used by Demo 2 after configuration.

Discrepancy references: addresses P01, F1, R01.

Success criteria:

* Unit test asserts the diagnostic PUT body contains no `messages` key and no nonzero body byte settings.
* Demo 2 fails visibly if readback shows message capture.

Context references:

* .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 107-117) - metrics and privacy contract
* .copilot-tracking/research/subagents/2026-09-28/adversarial-telemetry-review.md (section HIGH F1) - unsupported privacy configuration

Dependencies:

* None

### Step 1.4: User-assigned identity client ID support

Implement DD-01 while keeping existing interactive users working.

* Add config key `APIM_IDENTITY_CLIENT_ID` (optional) in shared/config.py; add it to .env.example with an empty value.
* policies/demo1-token-limit.xml, demo2-emit-token-metric.xml, demo3-content-safety.xml: add `<set-header name="Ocp-Apim-Subscription-Key" exists-action="delete" />` and `<set-query-parameter name="subscription-key" exists-action="delete" />` in inbound before forwarding so client keys never reach the real model backend (F8). Leave policies/demo4-resilient-pool.xml credential flow unchanged; its mock backend authentication is verified in Step 1.7 and Phase 6.
* Notebooks inject `client-id="..."` into `<authentication-managed-identity ...>` when `APIM_IDENTITY_CLIENT_ID` is set; the XML files keep no hardcoded client ID. Add one helper in shared/apim.py, `apply_identity_client_id(policy_xml, client_id)`, and call it from each notebook's policy-load cell (demo1, demo2, demo3, and demo4 including the inline string near demo4 source line 190).
* shared/apim.py backend credentials (around line 202): when a client ID is configured, emit `{"managedIdentity": {"clientId": <id>, "resource": "https://cognitiveservices.azure.com"}}`; used by Demo 3 Content Safety backend.
* When unset, behavior is unchanged (system-assigned identity).

Discrepancy references: implements DD-01; supports P04 and F10 least privilege.

Success criteria:

* Unit tests cover injection for self-closing and multi-line `authentication-managed-identity` elements, idempotency, and the unset case.

Context references:

* policies/demo4-resilient-pool.xml (Lines 1-10) - managed-identity element
* shared/apim.py (Lines 195-210) - backend credential doc

Dependencies:

* None

### Step 1.5: Headless configuration contract

* shared/config.py: add `AIGOV_HEADLESS=1` mode. In headless mode `_prompt()` (lines 118-127) raises `ConfigError` naming the missing key instead of calling `input`/`getpass`.
* In headless mode, detect conflicts: if a key exists in both process environment and .env with different values, raise `ConfigError` listing key names only (no values). Exempt nothing silently; `DEMO_RUN` must come from .env only, so an inherited `DEMO_RUN` environment variable is a conflict.
* Keep existing interactive behavior unchanged when the flag is absent.
* Map nothing here; the `AZURE_RESOURCE_GROUP` to `APIM_RESOURCE_GROUP` mapping belongs to the .env writer (Step 2.1).

Discrepancy references: addresses A09, R15 config portion.

Success criteria:

* tests/test_config.py cases: missing key raises in headless mode; conflicting inherited value raises; empty optional keys (AOAI_KEY, CONTENT_SAFETY_KEY, six DEMO4 keys) are accepted; DEMO_RUN reset persists across a fresh `load_config()`.

Context references:

* shared/config.py (Lines 113-136, 216, 225, 244-253, 308, 375) - loader and prompts

Dependencies:

* None

### Step 1.6: Setup notebook portability

* notebooks/00-setup-and-validation.ipynb cell 4: replace `shell=True` with `shell=(sys.platform == "win32")`, or resolve `az` with `shutil.which("az")` and call without a shell. Never pass tokens on the command line.

Success criteria:

* Static test confirms no `shell=True` literal remains in notebooks.

Dependencies:

* None

### Step 1.7: Structured objective results and semantic classifiers

Create shared/results.py with a small contract:

* `record_objective(notebook, objective_id, status, evidence)` where status is `passed`, `failed`, or `inconclusive`; evidence is a dict of allowlisted scalar fields (counts, status codes, member names, UTC timestamps). Writes `outputs/results/<session_id>/<notebook>.json` atomically (`session_id` from `SESSION_ID`, falling back to `DEMO_RUN` interactively). No free text from responses.
* Each notebook records its required objectives with stable IDs:
  * 00 setup: `setup.identity`, `setup.endpoints`, `setup.apim_sku`.
  * demo1: `demo1.baseline`, `demo1.rate_limit_429` (gateway provenance: `remaining-tokens`/policy headers present, not a backend 429), `demo1.quota_exhausted`, `demo1.reset_recovery`.
  * demo2: `demo2.logger_configured`, `demo2.no_message_capture`, `demo2.metrics_reconciled` (prompt and completion sums vs response usage within tolerance), `demo2.dimensions_observed`.
  * demo3: `demo3.safe_prompt`, `demo3.prompt_shield_block`, `demo3.stream_intervention`.
  * demo4: `demo4.routing_paths`, `demo4.fault_observed`, `demo4.alternate_routing`, `demo4.recovery`.
* Demo 3 (cell 18 line 15, cell 20 lines 30 and 48-52): classify responses as `transport_error`, `policy_block_confirmed`, `not_tripped`, or `inconclusive`. Require `text/event-stream`, parse SSE events, and require policy-specific evidence (APIM error body or header identifying the content-safety policy) for `policy_block_confirmed`. Missing `[DONE]` alone is `inconclusive`. A 403 without safety provenance is `failed` for the safety objective. Put the classifier in shared/results.py as a pure function for unit testing.
* Demo 4 (cell 7 line 35, cell 8 line 4): change mock operation URL templates to `/{member}/*`, keeping operation IDs. Cells 16, 18, 20: record `fault_observed` only when East returns the injected fault statuses; `alternate_routing` only when Central then PAYG `x-served-by` values appear in the intended phases; `recovery` only after a recorded fault. Unknown or missing `x-served-by`, 404s, and unexpected statuses fail the phase. Accept approximate weights. After switching to real inference, read back backends and fail if mock credentials remain.
* Demo 4 cleanup cell 25 remains optional and is recorded as intentionally excluded.

Discrepancy references: addresses A05, A06, A07, R07, R08, R09.

Success criteria:

* tests/test_results.py: SSE fixtures (empty 200, HTML 200, malformed SSE, truncated SSE, complete safe SSE, unrelated 403, confirmed interruption) where only the last passes; Demo 4 fixtures (all-404, unknown member, no fault, no Central, no PAYG, recovery without fault, mock call without backend credential returning 401) all fail except where the 401 is the expected negative-auth probe.
* Demo 4 adds one negative probe: a direct call to the mock API without the named-value credential must be rejected; recorded as `demo4.mock_auth_enforced`.
* Every notebook writes its result file; banners remain for humans but are not the acceptance API.

Context references:

* .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 189-217) - notebook completion and semantic evidence
* .copilot-tracking/research/subagents/2026-09-28/adversarial-automation-review.md (sections HIGH A06 and HIGH A07) - safety and failover attribution

Dependencies:

* None

### Step 1.8: Session-wide dispatch guard

Create shared/budget.py and route every inference or safety request through it.

* Inventory every HTTP inference call site in notebooks and shared (search `requests.post`, `requests.get`, `httpx`, `stream=True`, chat completions paths). Record per-notebook expected attempts, prompt token estimates, max output tokens, stream use, and retries in config/session-envelope.json (nonsecret, committed).
* `guarded_request(kind, estimated_input_tokens, max_output_tokens, send)` requires a nonzero `max_output_tokens` for model calls (the request body must set `max_tokens` to that value), reserves attempts, tokens, and estimated USD spend before sending (in headless mode a missing or ambiguous price for a model call raises before dispatch; interactive mode without a snapshot records tokens only), persists counters atomically to `outputs/session/<session_id>/budget.json` where `session_id` is `SESSION_ID` from .env (distinct from `DEMO_RUN`, which Demo 1 may reset), counts timeouts and ambiguous failures as consumed, and raises `BudgetExceeded` before dispatch when the reservation does not fit. Missing state file in headless mode is a hard failure.
* Limits come from environment/.env keys `SESSION_ID`, `SESSION_MAX_ATTEMPTS`, `SESSION_MAX_RESERVED_TOKENS`, `SESSION_MAX_ESTIMATED_USD`, `SESSION_DEADLINE_UTC`. `lab_session.py init-session` initializes budget.json once per session before any Azure call. Budget state lives on the single cloud-job runner for the whole session (Step 5.2), so notebooks, readiness, probes, traffic, and showback share one counter. Each workflow run attempt is a separately approved envelope (environment approval is per attempt); init-session refuses `GITHUB_RUN_ATTEMPT` greater than 2, and every session's spent totals are written to evidence.json (and to a manifest record when the session created one) so reviewers see cumulative spend. Interactive use without these keys keeps current behavior (guard in record-only mode).
* Mock-only Demo 4 calls count as attempts but use zero model-token reservation; tag them `kind="mock"`.
* Management-plane calls (ARM) are not budgeted so cleanup is never starved.

Discrepancy references: addresses F4, P08, R13 whole-session envelope.

Success criteria:

* tests/test_budget.py: zero budget, insufficient reservation, timeout counted, burst and retry share the same counters, missing state in headless mode fails, mock calls counted without token reservation.
* config/session-envelope.json lists every notebook call site; a static test fails if a notebook contains a direct inference call not wrapped by `guarded_request`.

Dependencies:

* Step 1.7 (shared run ID conventions)

### Step 1.9: Validate phase changes

Validation commands:

* `python -m unittest discover -s tests -t .` - all existing and new tests
* Notebook JSON validity: `python -c "import nbformat,glob;[nbformat.validate(nbformat.read(p,4)) for p in glob.glob('notebooks/*.ipynb')]"`

## Implementation Phase 2: Automation scripts with synthetic fixtures

<!-- parallelizable: false -->

Runs after Phase 1 (imports shared/results.py and shared/budget.py). May run concurrently with Phases 3 and 4. Files: scripts/*.py, scripts/prices/, requirements-ci.txt, tests/test_automation.py, tests/fixtures/.

### Step 2.1: Session orchestrator scripts/lab_session.py

One CLI with subcommands; each prints only nonsecret status. Every subcommand that retrieves a secret prints `::add-mask::<value>` immediately after retrieval and before any other output when running in GitHub Actions.

* `init-session`: first step of every cloud mode. Refuses `GITHUB_RUN_ATTEMPT` greater than 2. Creates `SESSION_ID=<run_id>-<run_attempt>`, `SESSION_DEADLINE_UTC` from the job start and the configured caps, the budget keys, `AIGOV_HEADLESS=1`, and initializes `outputs/session/<session_id>/budget.json`. Writes these to a private session file merged later by write-env. No Azure call.
* `preflight --params infra/main.bicepparam`: validate the approved model tuple (name, version, SKU, region, capacity), reject Global* SKUs unless `allowGlobalProcessing=true`, check provider registration, Basic v2 region availability, model quota/usage via ARM, and Content Safety availability. Check soft-deleted APIM services, Cognitive Services accounts, and Log Analytics workspaces for every planned name; stop on any collision. Uses the `AIGov Preflight Reader` role from Step 3.1. Read-only.
* `what-if`: run `az deployment group what-if` for the exact parameters and print the change summary; fail on unexpected deletes or changes outside planned resource IDs. `dry-run` mode stops here.
* `manifest create`: build the expected-target manifest (tenant, subscription, full RG ID, generation, deployment name, expected resource IDs and names, source revision, `created_by_session` = SESSION_ID, mode, content SHA-256) BEFORE mutation. Persist it per DD-03 as an append-only ARM deployment record in the lab RG using an empty template with `--mode Incremental` pinned, named `aigov-manifest-<generation>-<attempt>-<hash8>`; never overwrite an existing record. Also upload the same JSON as a workflow artifact backup. Fail before mutation if either persistence fails. Refuse when the RG contains resources not in the approved inventory or has locks. Recovery reads the newest valid record per generation and verifies its hash.
* `manifest verify`: used by run-existing and report-only; loads and hash-checks the newest record for the generation and confirms live resources match. Never creates a record.
* `deploy`: `az deployment group create --mode Incremental` of infra/main.bicep with the approved parameters; append a new manifest record with observed IDs after each attempt, including on failure. Keep deployment history well below the ARM limit (ARM auto-deletes the oldest records near 800 regardless of name) by deleting this lab's superseded `aigov-main-*` records and their nested module deployment records after each successful deploy; manifest records are never deleted by automation, and the workflow-artifact backup covers loss.
* `readiness`: bounded polls (deadline per check) for APIM gateway reachability, model inference through the platform API, Content Safety call through the gateway, logger/diagnostic readback including custom-metric dimensions opt-in on the App Insights component, and first metric ingestion. Inference and safety probes go through `guarded_request`. Writes an allowlisted `outputs/readiness/<session_id>/summary.json`. Report the failing check and scope; never broaden permissions.
* `probe-scopes`: runs after readiness and before the traffic window, through `guarded_request`. Records enforcement on product-scoped team keys and behavior for a temporary API-scoped test subscription (deleted afterwards) and the anonymous path (expect 401); never prints keys. Built-in all-access key is not used; its bypass is documented from Microsoft guidance.
* `write-env`: merge the private session file from init-session; read group-scope deployment outputs by exact name, map `AZURE_RESOURCE_GROUP` to `APIM_RESOURCE_GROUP`, fetch the App Insights connection string privately (masked on retrieval), and write the complete root .env including required empty keys and a fresh `DEMO_RUN`. Validate with `load_config()` under headless mode before any notebook runs.
* `run-notebooks --init`: create a clean `outputs/executed/<session_id>/` once and an empty `execution.json`. `run-notebooks --only <nb>`: run papermill for one notebook with `--cwd notebooks` and without `--log-output`, then append its exit code, start/end UTC, and source hash to `execution.json` atomically; never clear the directory.
* `cleanup --execute/--dry-run`: load the manifest record, validate tenant/subscription/RG and ownership, refuse unexpected resources and locks, delete model deployments first, then owned resources in dependency order, keep the RG, keep bootstrap-owned resources (UAMI, manifest records). Process targets independently, bounded retries, treat 404 as absent and 403/timeouts as errors, and emit a residual report (active resources, tombstones, failures, exposure). Expected soft-deleted tombstones of owned resources are listed separately and do not cause failure; any active owned resource, unexpected resource, or failed deletion causes non-success exit. Writes an allowlisted `outputs/residual/<session_id>/report.json`.
* `cleanup --auto --mode <mode>`: the workflow entry point. Reads `DEPLOY_OUTCOME` and `READINESS_OUTCOME` (GitHub step outcomes passed as environment variables) and `KEEP_ENVIRONMENT`. Acts only on manifest records whose `created_by_session` equals the current `SESSION_ID`; if this session created no record (for example `manifest create` refused a pre-existing environment), it is a no-op. Applies the mode-by-outcome table below. Records the session's spent budget totals in a new append-only manifest record when one exists for this session; otherwise spend is reported only in evidence.

Mode-by-outcome cleanup table (the only source of cleanup authority in lab-session; scope is always resources recorded by this session's own manifest):

| Mode | Creates manifest | Deploys | Cleanup on success | Cleanup on failure |
| --- | --- | --- | --- | --- |
| full-session | yes; refuses any live owned resource | yes | yes unless `keep_environment=true` | yes unless `keep_environment=true` |
| deploy-only | yes; refuses any live owned resource | yes | no (environment kept for run-existing) | yes, when `DEPLOY_OUTCOME` or `READINESS_OUTCOME` is not success |
| run-existing | no; `manifest verify` | no | no | no |
| report-only | no; `manifest verify` | no | no | no |
| dry-run | no | no | no | no |
| lock-test | no | no | no | no |

`keep_environment` applies only to full-session and preserves resources on both success and failure, with the residual exposure report (research Lines 127-135). teardown.yml is the only other deletion path.
* `purge --execute`: human-operator only (DD-02). Lists exact tombstones from the manifest; requires typed confirmation of each name; refuses anything not inventoried. Not invoked by any workflow.

Discrepancy references: addresses A03, A04, A09, P05, R04, R06.

Success criteria:

* tests/test_automation.py with stubbed ARM client: failure after manifest, after partial deploy, after RG content deleted, 403 vs 404, unexpected resource refusal, lock refusal, residual report non-success, one case per cell of the mode-by-outcome table, a full-session that fails at `manifest create` against a kept environment performs no deletion, run-notebooks append across five `--only` calls, and run_attempt greater than 2 refused by init-session.

Context references:

* .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 119-161) - lifecycle, modes, inventory, recovery
* .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 163-187) - headless configuration and authentication

Dependencies:

* Phase 1 completion

### Step 2.2: Notebook completion checker scripts/check_notebook_outputs.py

* Require exactly the five executed notebooks in `outputs/executed/<session_id>/` and matching `execution.json`; reject missing, extra, stale (source hash mismatch), or failed runs.
* Require every required objective ID from Step 1.7 in the result files; report `passed`, `failed`, `inconclusive`; write `outputs/results/<session_id>/verdict.json` (allowlisted) before exiting; exit nonzero unless all required objectives passed. Print a per-objective table.
* Reject any error output after an earlier pass.

Success criteria:

* Fixture tests: empty directory, missing notebook, renamed notebook, stale output, killed kernel, traceback after pass, inconclusive safety objective all fail.

Dependencies:

* Step 2.1 execution.json format

### Step 2.3: Sanitized evidence and rendering scripts/render_evidence.py

* `sanitize`: runs inside the same cloud job that holds the secrets (Step 5.2), regardless of checker outcome. Build `outputs/evidence/<session_id>/evidence.json` only from allowlisted scalar fields of: notebook result files, verdict.json, readiness summary.json, showback report JSON, budget.json spent totals, and (on the post-cleanup run) residual report.json. Inputs absent because of the mode or a skipped step are recorded as `not_run` for that item and are not sanitizer errors; only malformed inputs or scan hits fail. Scan against known secret values (read from private .env and runtime secrets list) and credential patterns (GUID-like keys, 32+ hex, JWT, `InstrumentationKey=`, `AccountKey=`, `sig=`); fail closed on any hit or sanitizer error.
* `render`: in a credential-free job, render charts with matplotlib and tables to PNG from evidence.json only; file names use the canonical map `lab00-environment-*.png` through `lab07-teardown-*.png`. Status sources: lab00 from readiness summary, lab01-lab05 from notebook objectives, lab06 from showback coverage and reconciliation status, lab07 from the residual report status. `inconclusive`, `failed`, `incomplete`, or residual-exposure states render a status card, never a success image. No notebook HTML, no network.
* Never read raw executed notebooks in the renderer.

Discrepancy references: addresses A01, A10, R10.

Success criteria:

* Fixture tests inject fake keys, bearer tokens, and connection strings into result evidence, error strings, and metadata; sanitize fails; no PNG produced.

Dependencies:

* Step 1.7 result schema

### Step 2.4: Traffic and showback scripts

* scripts/generate_traffic.py: three team subscriptions (team-retail, team-finance, team-hr) on the platform API; retrieves keys privately via ARM `listSecrets` and never prints them; serial, nonstreaming, no retries; defaults 1 worker, 30 attempts, 128 max output tokens, 10,000 reserved tokens, 5 minute deadline; all calls through `guarded_request`; records a response-usage manifest and a fixed UTC half-open window in `outputs/showback/<session_id>/manifest.json`.
* scripts/showback_report.py: query one representation (App Insights `customMetrics` with `sum(valueSum)`) scoped to the component, observed namespace, API, teams, and window; bounded polling; reconcile against the manifest with explicit tolerance; mark `incomplete` instead of zero. Price with one record from scripts/prices/<snapshot>.json keyed by model, version, SKU, region, currency, effective period, and unit; suppress totals when coverage is missing or duplicated. Label every output `Estimated model-token showback (USD retail)` with interval, snapshot ID, coverage, and exclusions.
* Report-only path (`showback_report.py --window-start --window-end` without a traffic manifest): validates the window (UTC, start before end, end not in the future, length at most 24 hours), queries the same single representation, sets reconciliation status `unreconciled`, and never claims a complete total.
* scripts/prices/README-free schema: commit `scripts/prices/schema.json` and a fixture snapshot for tests only; the real snapshot is created in Phase 6 after the model tuple is approved.

Discrepancy references: addresses P07, F2-F7, R11-R13.

Success criteria:

* Tests: per-thousand vs per-million units, missing price, duplicate price, cached tokens not added on top, metric double counting prevented, contaminated window rejected, missing telemetry reported incomplete, report-only window validation (reversed, future, over 24 hours) and `unreconciled` labelling.

Dependencies:

* Step 1.8

### Step 2.5: CI dependencies

* requirements-ci.txt: `-r requirements.txt`, pinned `papermill`, `nbformat`, `matplotlib`, `azure-monitor-query` (if not already in requirements.txt), `playwright` only if the renderer needs HTML screenshots.

### Step 2.6: Validate phase changes

* `python -m unittest discover -s tests -t .`
* `python scripts/lab_session.py --help` and each subcommand `--help`

## Implementation Phase 3: Infrastructure and bootstrap

<!-- parallelizable: true -->

Files: infra/**, scripts/bootstrap-lab.ps1, scripts/roles/*.json, policies/platform-ai-gateway.xml, policies/platform-team-product.xml, tests/test_infra.py.

### Step 3.1: Administrative bootstrap scripts/bootstrap-lab.ps1

Dry-run by default (`-Execute` switch required). Run by an administrator once; never by workflows.

* Create the dedicated RG with ownership tags.
* Create a separate identity RG `rg-aigov-<env>-identity` and the user-assigned identity `id-aigov-apim-<env>` in it (DD-01, DD-04). No CI identity has write access to this RG. Assign the identity, at lab RG scope: Cognitive Services OpenAI User (5e0bd9bd-7b93-4f28-af87-19fc36ad61bd), Cognitive Services User (a97b65f3-24c7-4388-baec-2e87135dc908), Monitoring Metrics Publisher (3913510d-42f4-4e42-8a64-420c390055eb).
* Create custom roles:
  * `AIGov APIM Lab Operator` (assignable scope: lab RG): `Microsoft.ApiManagement/service/read` plus exact read/write/delete actions for the child types that shared/apim.py and the notebooks actually call (derive the list by inventorying every ARM path in shared/apim.py; expected: apis, apis/operations, apis/policies, apis/diagnostics, products, products/apis, products/policies, subscriptions, subscriptions/listSecrets/action, backends, namedValues, namedValues/listValue/action if used, loggers, diagnostics); no `Microsoft.ApiManagement/service/write` or `/delete` (DD-05). Commit the resulting action list in scripts/roles/aigov-apim-lab-operator.json and test it against the inventory.
  * `AIGov Preflight Reader` (assignable scope: subscription): exact read actions for deleted resources and capacity checks only: `Microsoft.ApiManagement/deletedservices/read`, `Microsoft.CognitiveServices/deletedAccounts/read`, `Microsoft.CognitiveServices/locations/resourceGroups/deletedAccounts/read`, `Microsoft.OperationalInsights/deletedWorkspaces/read`, `Microsoft.CognitiveServices/locations/usages/read`, `Microsoft.CognitiveServices/locations/models/read`, `Microsoft.CognitiveServices/skus/read`, `Microsoft.ApiManagement/locations/read` or equivalent SKU availability read, and `Microsoft.Resources/subscriptions/providers/read`. Verify every action name against `az provider operation show` before creation; committed in scripts/roles/aigov-preflight-reader.json.
* Create two Entra app registrations, both with a federated credential on the single protected environment `lab` subject only. Determine the subject from actual repository metadata (immutable subject format when applicable); no branch subject.
  * Deploy identity (also recovery identity, DD-08): Contributor on the lab RG; Managed Identity Operator on the user-assigned identity only; AIGov Preflight Reader at subscription. No role-assignment write.
  * Runtime identity: AIGov APIM Lab Operator, Reader, Log Analytics Reader, and Monitoring Reader at lab RG scope.
* Create GitHub environment `lab` with required reviewers and deployment branch policy `main`; set repository variables (tenant, subscription, lab RG, identity RG, two client IDs, identity resource ID and client ID, location). No secrets.
* Accepted residual risk (DD-06): any approved job using environment `lab` on `main` could obtain either identity; only lab-session's cloud job and teardown's job use that environment, and code on `main` is reviewed.
* Print a nonsecret summary. Use deterministic role-assignment names.

Discrepancy references: addresses P04, F10, R03; implements DD-01.

Context references:

* .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 82-105) - identity and ownership contract

Success criteria:

* Dry run prints every planned change; script is idempotent; PSScriptAnalyzer clean.

Dependencies:

* None (execution deferred to Phase 6)

### Step 3.2: RG-scoped Bicep

* infra/main.bicep (targetScope resourceGroup) with modules infra/modules/monitoring.bicep, ai.bicep (model account, deployment, Content Safety), apim.bicep (Basic v2, UAMI, `apimlogger` with `identityClientId`, service diagnostic `metrics: true`, no LLM message logging), platform-api.bicep (api `ai-gateway-api`, backend `ai-gateway-foundry` with UAMI client ID, three products and subscriptions, token-metric API policy, product token-limit policies).
* infra/main.bicepparam: required parameters with no defaults for `chatModelName`, `chatModelVersion`, `chatDeploymentSku`, `chatDeploymentCapacity`, `aiLocation`; `allowGlobalProcessing` default false; `generation` required. LZA-aligned names `environmentName`, `instanceNumber`, `publisherEmail`, `publisherName`, `sku` (allowed BasicV2 and StandardV2), `skuCount` (1).
* App Insights `DisableLocalAuth: true`; enable custom metrics with dimensions via the component property `CustomMetricsOptedInType: 'WithDimensions'` (untyped in Bicep; use a single documented `#disable-next-line BCP037`) and verify by readback in `readiness`. Model and Content Safety accounts `disableLocalAuth: true`. Outputs are nonsecret IDs, names, endpoints only.
* Pin API versions per resource after checking schemas with the Bicep MCP tools. Do not add Key Vault, workbook, or diagnostic settings for GatewayLlmLogs.

Discrepancy references: addresses P01, P02, P03, P06, R02; F8 platform API scope.

Success criteria:

* `az bicep build --file infra/main.bicep` and `az bicep build-params --file infra/main.bicepparam` succeed with no warnings except documented suppressions.

Context references:

* .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 68-80) - platform preconditions

Dependencies:

* None

### Step 3.3: Platform policies

* policies/platform-ai-gateway.xml: `<base />`, `set-backend-service backend-id="ai-gateway-foundry"`, `authentication-managed-identity` with `client-id` from a named value, strip `Ocp-Apim-Subscription-Key` header and `subscription-key` query parameter before forwarding, `llm-emit-token-metric` with dimensions `API ID`, `Subscription ID`, and `ClientApp` normalized by a gateway allowlist expression (unknown maps to `unknown`).
* policies/platform-team-product.xml template: `llm-token-limit` with `counter-key="@(context.Subscription.Id)"`, per-team TPM and daily quota parameters.
* Bicep loads both with `loadTextContent`. Notebook policy files remain unchanged in path.

Success criteria:

* New tests/test_infra.py (owned by this phase) asserts one emitter, `<base />` present, credential header stripped, allowlist present, and no hardcoded client IDs or keys in infra/ or policies/platform-*.xml.

Dependencies:

* None

### Step 3.4: Validate phase changes

* `az bicep build --file infra/main.bicep`
* `az bicep lint --file infra/main.bicep`
* `Invoke-ScriptAnalyzer -Path scripts/bootstrap-lab.ps1`

## Implementation Phase 4: Bilingual lab site

<!-- parallelizable: true -->

Files: docs/** except docs/ai-governance-flows.svg (preserved), README.md.

### Step 4.1: Jekyll scaffold matching the sibling

* docs/_config.yml (Just the Docs remote theme, `baseurl: "/AIGovernanceOffering"`, callouts), docs/Gemfile (github-pages), docs/_includes/head_custom.html (language nav filter), docs/index.md, docs/fr/index.md.
* docs/_data/labs.yml: canonical map of 8 slugs, EN and FR titles, image prefixes, and evidence owners from the research page map.

Context references:

* .copilot-tracking/research/subagents/2026-09-28/sibling-fsi-lab-pattern-research.md - structure only
* .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 283-304) - canonical page map

### Step 4.2: Lab pages EN and FR

* docs/labs/lab-00-environment.md through lab-07-teardown.md and docs/fr/labs/ mirrors with paired permalinks, sibling section order, identical technical caveats, translated titles and alt text.
* lab-06 title: "Estimated model-token showback" / "Répartition estimée des coûts de jetons". lab-05 states the pool is mocked. lab-04 documents inconclusive states. lab-07 documents dry run, residual exposure, and human-only purge.
* No placeholder success images; image sections say evidence is pending until Phase 7.
* Use `relative_url` for all images, switchers, and navigation.

### Step 4.3: README update

* Add "Lab site" and "Automated environment" sections linking to docs and the workflows; keep the SVG path; avoid forbidden terms.

### Step 4.4: Validate phase changes

* `bundle exec jekyll build --source docs --destination _site --baseurl /AIGovernanceOffering` (in a container or local Ruby)
* Crawl of `_site` (for example `htmlproofer` or a small Python crawler) for both languages: internal links, anchors, images, EN/FR switchers in both directions, duplicate permalinks, and stale sibling baseurls
* Manual desktop and mobile review of navigation and callout rendering (browser tools may be used)
* `python -m unittest discover -s tests -t .` for README vocabulary

## Implementation Phase 5: GitHub workflows

<!-- parallelizable: false -->

Requires Phases 2, 3, and 4. Files: .github/workflows/ci.yml, lab-session.yml, teardown.yml. Pin every third-party action to a reviewed commit SHA.

### Step 5.1: ci.yml (credential-free)

* Triggers: push, pull_request. `permissions: contents: read`. No Azure login.
* Jobs: unit tests; `az bicep build` and lint; actionlint; Jekyll build and link crawl; PSScriptAnalyzer.

### Step 5.2: lab-session.yml (protected, manual)

* `workflow_dispatch` inputs: `mode` (full-session, deploy-only, run-existing, report-only, dry-run, lock-test), `keep_environment` (default false; full-session only), `generation`, `confirm_resource_group`, `report_window_start` and `report_window_end` (report-only).
* Workflow-level `permissions: {}` and `concurrency: { group: aigov-lab-env, cancel-in-progress: false }`. No job-level concurrency and no workflow_call.
* Job `cloud` (skipped for lock-test) with `environment: lab`, `permissions: { id-token: write, contents: read }`, and one runner for the whole session so .env, budget state, and secrets never cross jobs. EVERY step has `timeout-minutes`; the job `timeout-minutes` equals the sum of all step caps plus a margin and must not exceed the hosted-runner job limit (360 minutes); the contract test enforces both. init-session computes `SESSION_DEADLINE_UTC` = job start + job timeout - (cleanup login cap + cleanup cap + post-cleanup sanitize cap + upload cap + margin), so budgeted work stops before post-work steps could be cut off.
* Step matrix (conditions are literal `if:` expressions; `M` is `inputs.mode`; `ok(x)` means `steps.x.outcome == 'success'`; `live()` means `!cancelled()`, used for paid steps so a cancelled run stops spending; `always()` is used only for sanitize and cleanup):

| Step | Identity | Condition |
| --- | --- | --- |
| init-session | none | M != lock-test |
| login-deploy | deploy | M in (dry-run, full-session, deploy-only) |
| preflight, what-if | deploy | same as login-deploy |
| manifest-create | deploy | M in (full-session, deploy-only) |
| deploy | deploy | ok(manifest-create) |
| account-clear, login-runtime | runtime | live() and ok(init-session) and M in (full-session, deploy-only, run-existing, report-only) |
| manifest-verify | runtime (Reader) | M in (run-existing, report-only) |
| write-env | runtime | ok(deploy) or ok(manifest-verify) |
| readiness | runtime | ok(write-env) and M in (full-session, deploy-only, run-existing) |
| probe-scopes | runtime | ok(readiness) and M in (full-session, run-existing) |
| run-notebooks-init (`run-notebooks --init`) | runtime | ok(probe-scopes) and M in (full-session, run-existing) |
| per notebook N: login-runtime-N | runtime | live() and ok(run-notebooks-init) |
| per notebook N: notebook-N (`run-notebooks --only`) | runtime | live() and ok(run-notebooks-init) and ok(login-runtime-N) |
| login-runtime-traffic, traffic | runtime | live() and ok(run-notebooks-init); traffic additionally requires ok(login-runtime-traffic) |
| showback-report | runtime | live() and ((ok(run-notebooks-init) and ok(traffic)) or (M == report-only and ok(write-env))); report-only uses the validated input window and is labelled unreconciled |
| check-notebooks | none | live() and ok(run-notebooks-init) |
| sanitize and upload (id `sanitize`) | none | always() and ok(init-session) and M != dry-run |
| account-clear, login-deploy-cleanup, cleanup | deploy | always() and ok(init-session) and M in (full-session, deploy-only) |
| post-cleanup sanitize and upload (`overwrite: true`) | none | always() and ok(init-session) and M in (full-session, deploy-only) |

* A readiness or probe-scopes failure skips all notebooks, traffic, and showback in that session (research Lines 358-378); evidence and cleanup still run.

* Notebook, traffic, and showback steps set `ACTIONS_ID_TOKEN_REQUEST_TOKEN` and `ACTIONS_ID_TOKEN_REQUEST_URL` to empty in their env so notebook code cannot mint tokens; the Log Analytics audience is acquired right after the login preceding Demo 2 and showback. Papermill runs without `--log-output`. Later notebooks and traffic still run after an earlier notebook failure, bounded by the budget guard.
* The cleanup step passes `DEPLOY_OUTCOME: ${{ steps.deploy.outcome }}`, `READINESS_OUTCOME: ${{ steps.readiness.outcome }}`, and `KEEP_ENVIRONMENT` as environment variables and runs `lab_session.py cleanup --auto --mode <mode>`; it never reads job outputs. It exits nonzero for cleanup failures; the job keeps any earlier failure.
* The first sanitize step (id `sanitize`) sets job output `evidence_ready=true` on success; the post-cleanup sanitize only overwrites the same artifact and never sets the output.
* Job `render` (no environment, no Azure, `permissions: { contents: read }`, `needs: cloud`, `if: always() && needs.cloud.outputs.evidence_ready == 'true'`): renders PNGs from evidence.json only inside `docker run --network none` (or `unshare -rn`); uploads the PNG artifact.
* Job `lock-test` (only for mode lock-test, no environment, no Azure, `permissions: {}`): sleeps a bounded period to rehearse the workflow-level lock.

### Step 5.3: teardown.yml (protected, manual)

* Same workflow-level concurrency group. Inputs: `confirm_resource_group`, `generation`, `execute` (default false), `lock_test` (default false; when true only a no-environment, no-Azure job sleeps and the protected cleanup job is skipped by condition, so no approval is requested). Runs `lab_session.py cleanup` in dry-run unless `execute`, with step timeouts and a job timeout above them. Never purges; prints the human purge instructions.

### Step 5.4: Validate phase changes

* `actionlint`
* Contract test in tests/test_automation.py parsing workflow YAML: workflow-level `permissions: {}`, single concurrency group on both cloud workflows, no `workflow_call`, no `schedule`, exactly one job per cloud workflow uses `environment: lab`, lock-test jobs have no environment and no `id-token: write`, every step in the cloud job has `timeout-minutes` and the job timeout is at least their sum and at most 360, each step's `if:` matches the Step 5.2 matrix, cleanup steps never reference job outputs, notebook/traffic/showback steps blank the OIDC request variables, renderer job has no `id-token: write`, no environment, and runs with networking disabled, artifact re-upload uses `overwrite: true`, papermill invocations lack `--log-output`, all third-party actions pinned by SHA.

Discrepancy references: addresses A02, A03, A04, A08, A10, R05, R06.

## Implementation Phase 6: Approved bootstrap and live acceptance

<!-- parallelizable: false -->

Stop and obtain explicit user approval before each step. All steps are operator-driven.

### Step 6.1: Record decisions

* Fill infra/main.bicepparam with the approved model tuple and residency flag; record approved processing and storage locations for inference, Content Safety, and telemetry; create scripts/prices/<date>.json from the Azure Retail Prices API for the exact meters; set session envelope values; name environment reviewers and the recovery/purge operator. Resolves G1 inputs.

### Step 6.2: Run bootstrap and lock rehearsal

* Administrator runs `scripts/bootstrap-lab.ps1` dry run, then `-Execute`; this creates environment `lab` with protection rules before any workflow references it. Verify negative access: deploy identity cannot write role assignments or modify the identity RG; runtime identity cannot create or delete the APIM service or other resources. Resolves G2.
* Then dispatch lab-session `lock-test` twice and teardown with `lock_test=true` concurrently (no Azure, no approval needed) to rehearse the workflow-level lock before any paid session (G4 part 1). Expected: only one runs at a time; none cancels a running member; with default concurrency a later pending dispatch may replace an earlier pending one (GitHub pending-replacement behavior, research Lines 119-141), which is recorded, not treated as failure.

### Step 6.3: Deploy-only session

* Dispatch lab-session `dry-run` and review the what-if summary (G1). Then `deploy-only` and confirm readiness checks pass. Verify readback: logger identity, `metrics: true`, custom dimensions, no LLM message capture, ingestion working, canary prompts absent from telemetry (G3).

### Step 6.4: Run-existing session

* Dispatch `run-existing` against the environment from Step 6.3. Review check_notebook_outputs results (G5), `probe-scopes` output, and showback reconciliation (G6). Inconclusive objectives stay inconclusive.

### Step 6.5: Teardown, full lifecycle, and recovery rehearsal

* Teardown dry run, then execute against the Step 6.3 environment. Verify residual report and quota release (G8). Before executing, run a manual recovery drill: the named operator runs `lab_session.py cleanup --dry-run` locally from the manifest record alone (no workflow state) and confirms it lists the same targets.
* Then dispatch one `full-session` (default `keep_environment=false`) from the emptied RG with a new generation or after operator purge. This validates the complete lifecycle, produces the lab07 residual evidence used in Step 7.1, and confirms redeploy behavior (G8).

## Implementation Phase 7: Evidence curation and publishing

<!-- parallelizable: false -->

### Step 7.1: Curate images

* Maintainer reviews the render artifact from a run whose sanitizer passed and copies approved PNGs into docs/assets/images/ only for items whose status source (Step 2.3) is `passed`: notebook objectives, readiness (lab00), reconciled showback with full price coverage (lab06), and a residual report with no active owned resources (lab07). Items that are `inconclusive`, `incomplete`, or `failed` are published as explicitly unverified with a status card and no success image (DD-10). Update both languages.

### Step 7.2: Enable Pages and verify

* With approval, configure Pages from main /docs; verify a maintainer-merged image update is published and crawl the live site in both languages (G9).

## Implementation Phase 8: Validation

<!-- parallelizable: false -->

### Step 8.1: Run full project validation

* `python -m unittest discover -s tests -t .`
* `az bicep build --file infra/main.bicep` and lint
* `actionlint`
* Jekyll build and crawl for both languages
* PSScriptAnalyzer on scripts/bootstrap-lab.ps1

### Step 8.2: Fix minor validation issues

Iterate on lint errors, build warnings, and test failures. Apply direct fixes when isolated.

### Step 8.3: Report blocking issues

Document gates still OPEN (G1-G9) and failures requiring more research, with next steps. Do not claim live success for gates not executed.

## Dependencies

* Python 3.11+, papermill, nbformat, matplotlib, azure-identity, azure-monitor-query
* Azure CLI with Bicep, PowerShell 7 and PSScriptAnalyzer, GitHub CLI
* Ruby with github-pages gem (or container) for Jekyll builds; actionlint

## Success Criteria

* Phases 1-5 complete with all local tests, Bicep builds, workflow lint, and site builds passing, and no Azure credentials used.
* Phases 6-7 executed only with approval; G1-G9 each recorded as passed, failed, or open with evidence.
