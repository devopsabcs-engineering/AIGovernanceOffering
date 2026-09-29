<!-- markdownlint-disable-file -->
# Release Changes: APIM Basic v2 IaC, Automated Labs, Showback, Teardown, and Bilingual Site

**Related Plan**: apim-basicv2-iac-labs-plan.instructions.md
**Implementation Date**: 2026-09-29

## Summary

Local-first implementation of the plan: notebook and shared-module safety fixes, automation scripts, RG-scoped Bicep and bootstrap, bilingual Jekyll site, and three GitHub workflows. Phases 6-7 (live Azure and publishing) require explicit user approval and are not executed without it.

## Changes

### Added

* shared/results.py - Objective result files, SSE/block/token-limit classifiers, Demo 4 routing evaluators (Phase 1)
* shared/budget.py - Session-wide dispatch guard with attempt/token/USD reservation, fail-closed headless state (Phase 1)
* config/session-envelope.json - Inventory of every notebook inference/safety/mock call site: 171 attempts, 6,113 reserved tokens (Phase 1)
* tests/test_results.py, tests/test_budget.py - Classifier, evaluator, and budget fixtures (Phase 1)
* infra/main.bicep, infra/main.bicepparam, infra/modules/{monitoring,ai,apim,platform-api}.bicep, infra/README.md - RG-scoped Basic v2 platform, env-variable-only parameters, Global/DataZone SKU guard (Phase 3)
* policies/platform-ai-gateway.xml, policies/platform-team-product.xml - Platform API policy (UAMI auth, key stripping, one metric emitter, allowlisted ClientApp) and team token-limit policy (Phase 3)
* scripts/bootstrap-lab.ps1, scripts/roles/aigov-apim-lab-operator.json, scripts/roles/aigov-preflight-reader.json - Admin bootstrap (dry run default) and custom role definitions (Phase 3)
* tests/test_infra.py - 19 static infra/policy/role tests (Phase 3)
* docs/_config.yml, docs/Gemfile, docs/_includes/head_custom.html, docs/_data/labs.yml - Jekyll + Just the Docs scaffold and canonical page map (Phase 4)
* docs/index.md, docs/fr/index.md, docs/labs/index.md, docs/fr/labs/index.md - EN/FR home and hub pages (Phase 4)
* docs/labs/lab-00..lab-07-*.md, docs/fr/labs/lab-00..lab-07-*.md - 16 paired lab pages (Phase 4)
* scripts/aigov_common.py - Shared ARM client (az CLI, list args, no shell), secret registry (hashes only), pattern scanning, pricing, output paths (Phase 2)
* scripts/lab_session.py - Session orchestrator: init-session, preflight, what-if, manifest create/verify, deploy, readiness, probe-scopes, write-env, run-notebooks, cleanup (mode table), human-only purge (Phase 2)
* scripts/check_notebook_outputs.py - Five-notebook completion and objective checker writing verdict.json (Phase 2)
* scripts/render_evidence.py - Fail-closed sanitizer and credential-free matplotlib renderer (Phase 2)
* scripts/generate_traffic.py, scripts/showback_report.py, scripts/prices/schema.json - Bounded team traffic and estimated showback with exact pricing identity (Phase 2)
* requirements-ci.txt - papermill, nbformat, matplotlib pins (Phase 2)
* tests/__init__.py, tests/automation_fakes.py, tests/test_lab_session.py, tests/test_evidence.py, tests/test_showback.py, tests/fixtures/prices/fixture-snapshot.json - 107 automation tests with FakeArm (Phase 2)
* .github/workflows/ci.yml - Credential-free CI: unit tests, Bicep build/lint/build-params, actionlint, Jekyll build and link crawl, PSScriptAnalyzer (Phase 5)
* .github/workflows/lab-session.yml - Protected manual session: workflow-level lock, single cloud job implementing the Step 5.2 matrix, network-isolated render job, lock-test mode (Phase 5)
* .github/workflows/teardown.yml - Protected manual teardown, dry run default, same lock, no purge (Phase 5)
* tests/test_workflows.py - 34 workflow contract tests (Phase 5)

### Modified

* shared/apim.py - Secret redaction/truncation in errors, MI logger credentials, explicit logger lookup, no LLM message capture, identity client ID helpers (Phase 1)
* shared/config.py - Headless mode, ConfigError, env/.env conflict detection, APIM_IDENTITY_CLIENT_ID (Phase 1)
* notebooks/*.ipynb (all 5) - Key masking, guarded requests, objective recording, classifiers, Demo 4 wildcard routing, Linux-safe subprocess (Phase 1)
* policies/demo1-token-limit.xml, demo2-emit-token-metric.xml, demo3-content-safety.xml - Delete subscription key header and query parameter before forwarding (Phase 1)
* .env.example - Identity client ID, local-auth logger flag, commented headless/session keys (Phase 1)
* tests/test_apim.py, tests/test_config.py, tests/test_notebooks.py - New and updated tests (Phase 1)
* README.md - Lab site and Automated environment sections (Phase 4)
* shared/results.py - Bounded PermissionError retry in atomic_write_json for Windows file-replace races (Phase 2 bug fix)
* requirements-ci.txt - Added PyYAML for workflow contract tests (Phase 5)
* shared/config.py - Bounded PermissionError retry around dotenv set_key (Phase 8 flaky-test fix)
* scripts/lab_session.py - purge --help description and option help (Phase 8)
* scripts/bootstrap-lab.ps1, infra/README.md - Document AIGOV_PRICE_SNAPSHOT and optional variables (Phase 8)
* README.md, .env.example, docs/_data/labs.yml, docs/labs/lab-00..07, docs/fr/labs/lab-00..07 - Aligned with real workflows, CLIs, variables, platform API facts, and evidence PNG names (Phase 8)
* .gitignore - Ignore _site/, .sass-cache/, .jekyll-cache/ (Phase 8)

### Removed

## Additional or Deviating Changes

* Phase 6 (user-approved 2026-09-29, executed locally under the admin CLI session because workflows are not yet pushed):
  * Bootstrap applied in subscription 64c3d212-40ed-4c6d-a825-6adfbdf25dad: rg-aigov-lab, rg-aigov-lab-identity, id-aigov-apim-lab, two custom roles, apps aigov-lab-deploy (8834887f-...) and aigov-lab-runtime (3291c2b0-...) with OIDC federation to environment `lab` only, 11 role assignments, GitHub environment `lab` (reviewer emmanuelknafo, main only), 22 repository variables. No client secrets and no GitHub secrets were created (OIDC needs none).
  * Model tuple: gpt-4.1-mini 2025-04-14 Standard in canadaeast, capacity 30, allowGlobalProcessing=false. Chosen because it is the only chat model with a Canada-regional Standard SKU and existing subscription quota (OpenAI.Standard.gpt4.1-mini); lifecycle Legacy, retirement 2027-04-14.
  * Added scripts/prices/retail-2026-09-29-gpt-4.1-mini-canadaeast.json from the Azure Retail Prices API (input 0.000484, output 0.001936 USD per 1K tokens, regional meters).
  * Fixed scripts/lab_session.py quota check to match Azure's hyphenless usage names (OpenAI.Standard.gpt4.1-mini) with a new test.
  * Fixed scripts/aigov_common.py AzCliArmClient on Windows to call the Azure CLI's bundled Python instead of az.cmd, because cmd.exe mangled '&' and '%' in paginated nextLink URLs (tombstone listing failed).
  * Session local202609290249-1: preflight passed, what-if Create=26 with no deletes, manifest recorded, deploy aigov-main-g01 succeeded, write-env wrote 45 keys.

* Phase 1: notebooks gained stable cell IDs (nbformat 4.5 requirement) as a side effect of scripted edits.
  * Required for valid notebook format; no content change.
* Phase 1: Demo 3 streaming objective is `inconclusive` when a stream completes without intervention; prompt-shield not blocked is `failed`.
  * Matches research: absence of intervention is not proof either way for streaming.
* Phase 3: APIM pinned to GA 2024-05-01 (no `largeLanguageModel` block exists, so LLM message logging is impossible at service scope); model backend auth via `authentication-managed-identity client-id` named value.
  * Schema-verified; simpler than preview API.
* Phase 3: added `nameSuffix` and `contentSafetyLocation` parameters; explicit module deployment names `aigov-main-<gen>-<module>` to support deterministic history pruning.
  * Supports preflight name computation, DR-16, DR-24.
* Phase 3: `allowGlobalProcessing=false` also rejects DataZone* SKUs.
  * Conservative residency default; revisit if DataZone within Canada is approved.
* Phase 3: some custom role action names are unverified until an Azure session exists; bootstrap `-Execute` refuses unknown actions.
* Phase 4: language switcher is a bold paragraph (not blockquote) to satisfy MD028; head_custom.html converts GitHub alert syntax to Just the Docs callouts; Gemfile adds `rake`, config adds `jekyll-remote-theme` plugin for local builds.
* Validation: `python -m unittest discover -s tests -t .` fails (no tests/__init__.py); `discover -s tests` passes 144 tests. nbformat is not installed; a structural notebook check was used instead. Resolved in Phase 2 by adding tests/__init__.py; full suite now 251 tests OK (1 skipped: render test without matplotlib).
* Phase 2: added scripts/aigov_common.py shared helper (not in plan) to avoid duplicating the ARM client, masking, and pricing across five scripts.
* Phase 2: secret registry stores only length and SHA-256; sanitizer detects secrets by hashing same-length windows.
* Phase 2: readiness checks Content Safety by ARM provisioning state only (no gateway route exists before Demo 3); Demo 3 objectives cover the live safety call.
* Phase 2: showback filters by metric name, API ID, and Subscription ID; the namespace dimension is pinned after the first live sample (Phase 6).
* Phase 2: default session caps 207 attempts, ~16.3k reserved tokens, USD 2.00 are Phase 6 approval inputs, not measured values.
* Phase 5: added `upload_manifest` step before deploy so a failed manifest backup blocks mutation; upload steps also require sanitize success so a failed post-cleanup sanitize cannot overwrite good evidence.
  * Enforces Step 2.1 "fail before mutation if persistence fails" and DR-44.
* Phase 5: init_session validates `confirm_resource_group` against `vars.AIGOV_LAB_RESOURCE_GROUP` and rejects keep_environment outside full-session.
* Phase 5: render job isolates network with `sudo unshare --net` plus `setpriv` back to the runner user, with an outbound-connection check that must fail; chosen over docker because a host venv cannot be mounted into an unverified container image.
* Phase 5: new repository variable `AIGOV_PRICE_SNAPSHOT` required for full-session, deploy-only, and run-existing (init-session requires a price).
* Phase 5: actions pinned to SHAs verified with `git ls-remote`: checkout v7.0.1, setup-python v7.0.0, azure/login v3.1.0, upload-artifact v7.0.1, download-artifact v8.0.1, ruby/setup-ruby v1.327.0; actionlint v1.7.12 via go install.
* Phase 5: Bicep CLI install in CI and cloud job is not version-pinned yet.
* Phase 8: policies/demo4-resilient-pool.xml does not strip the client subscription key; deferred (WI-08) because it can affect the mock-auth probe and needs a live run.

## Release Summary

Phases 1-5 and local validation (Phase 8 Steps 8.1-8.2) are complete. Phases 6 (bootstrap and live acceptance) and 7 (evidence curation and Pages) are not started and require explicit approval. No Azure resources, GitHub settings, pushes, or workflow runs were made. All acceptance gates G1-G9 remain OPEN.

* Files added: about 60 (infra: 7; policies: 2; scripts: 9 plus 2 role JSON and 1 price schema; shared: 2; config: 1; tests: 9 plus fixtures; workflows: 3; docs: 24; requirements-ci.txt).
* Files modified: shared/apim.py, shared/config.py, shared/results.py, 5 notebooks, 3 demo policies, .env.example, .gitignore, README.md, 3 existing test files.
* Files removed: none.
* Dependencies: requirements-ci.txt adds papermill 2.6.0, nbformat 5.10.4, matplotlib 3.9.2, PyYAML 6.0.3 for CI; runtime requirements.txt unchanged.
* Infrastructure: RG-scoped Bicep for APIM Basic v2 (UserAssigned identity), AI Services model deployment, Content Safety, Log Analytics, App Insights (local auth disabled), platform API with three team products; admin bootstrap creates lab RG, identity RG, UAMI, two custom roles, two federated app registrations, protected `lab` environment.
* Validation: 285 unit tests OK (1 skipped without matplotlib); Bicep build and lint clean; actionlint clean (no shellcheck locally); Jekyll build and link crawl clean for 20 pages; PSScriptAnalyzer clean.
* Deployment notes: set repository variables listed in README before the first session; run bootstrap as an administrator; follow Phase 6 order (decisions, bootstrap and lock rehearsal, dry-run and deploy-only, run-existing, teardown and full-session).
