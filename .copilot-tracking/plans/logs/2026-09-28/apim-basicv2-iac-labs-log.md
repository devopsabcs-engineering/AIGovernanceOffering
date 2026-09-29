<!-- markdownlint-disable-file -->
# Planning Log: APIM Basic v2 IaC, Automated Labs, Showback, Teardown, and Bilingual Site

## Discrepancy Log

Gaps and differences identified between research findings and the implementation plan.

### Unaddressed Research Items

* DR-01: Optional LLM event-log accounting path
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 261-267)
  * Reason: Deferred by research; blocked on privacy approval and grain/retry tests
  * Impact: low
* DR-02: Automatic image PRs
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 269-281)
  * Reason: Deferred; manual curation selected
  * Impact: low
* DR-03: APIOps ownership transfer, workbook, dynamic pricing ingestion
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 306-320)
  * Reason: Deferred until core loop passes
  * Impact: low
* DR-04: Automated expiry enforcement for the four-hour session metadata
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 119-141)
  * Reason: Research treats expiry as metadata only; no schedules selected
  * Impact: medium (cost exposure if an operator forgets teardown; mitigated by keep_environment=false default and residual report)
* DR-05: LICENSE file referenced by README
  * Source: .copilot-tracking/research/subagents/2026-09-28/current-repo-research.md
  * Reason: Unrelated to requested scope; needs license choice from owner
  * Impact: low
* DR-06: Failure cleanup depends on per-job environment approval and deploy job outputs
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 127-139); adversarial-automation-review.md A04 ("A guard must not require deployment success")
  * Reason: details Line 424 puts preflight, deploy, run, showback, evidence, and cleanup each under `environment: lab`, so every job waits for its own reviewer approval, and cleanup is gated on `needs.deploy.outputs.mutation_attempted`
  * Impact: HIGH (A04, P08). Paid resources persist when no reviewer approves the cleanup job after a failure, or when the deploy job fails or loses its runner before emitting outputs. Remedy: one protected cloud job with sequential steps and a step-level `if: always()` cleanup guarded by the persisted manifest record (not job outputs); keep only the no-cloud render job separate
* DR-07: Session budget counters do not span jobs
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 251-255)
  * Reason: details Lines 192-193 persist counters to runner-local `outputs/session/<run_id>/budget.json`, while details Line 424 runs notebooks and showback traffic in separate fresh-runner jobs
  * Impact: HIGH (F4, P08). The showback job starts with missing state (hard failure) or a fresh counter (envelope reset). Remedy: single cloud job per DR-06, or persist counters in the manifest record and reload/fail closed in each job
* DR-08: Sanitization runs outside the secret-holding job
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 273-277)
  * Reason: details Line 424 `evidence` job runs after `run`/`showback`; it must either receive unsanitized result/showback files as artifacts or run without the private .env known values that details Line 264 requires
  * Impact: HIGH (A01). Upload before scan, or a weakened known-value scan. Remedy: run `render_evidence.py sanitize` as an `always()` step in the job that holds secrets and upload only the sanitized evidence.json
* DR-09: No RG-scoped what-if review or post-deploy readiness checks
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 76, 78, 375); G1
  * Reason: details Lines 227, 335-355, and 452-455 go from `az bicep build` to `az deployment group create` with no what-if; bounded readiness after ARM success is not specified
  * Impact: MAJOR (G1 cannot pass). Remedy: add a `lab_session.py what-if` step (review artifact, fail on unexpected delete/modify) before deploy and a bounded `readiness` subcommand covering gateway, inference through APIM, safety, ingestion, and query
* DR-10: Privileged subscription bypass and notebook key forwarding
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 225-227); adversarial-telemetry-review.md F8
  * Reason: details Line 104 keeps demo1-3 policies unchanged, so notebook APIs forward `Ocp-Apim-Subscription-Key` to real Azure OpenAI; details Lines 356-364 define no product/API-scoped/all-access/anonymous path test and no handling of the built-in all-access subscription on the platform API
  * Impact: MAJOR (F8). Remedy: delete the subscription-key header before forwarding in demo1-3 and platform policies (not the Demo 4 mock); add Phase 6.4 checks for all four access paths; document bypass and reject windows containing non-team subscriptions
* DR-11: Pre-deploy tombstone and name-collision checks absent
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 147-149)
  * Reason: details Line 226 checks live RG contents and locks only; no APIM deleted-service or Cognitive Services deleted-account lookup for the generation names
  * Impact: MAJOR (P05, A04). A same-name soft-deleted APIM or account fails deployment after partial mutation. Remedy: `preflight` lists matching tombstones and stops before manifest creation with "new generation or operator purge required"
* DR-12: Dynamic secret masking and papermill log output
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 271)
  * Reason: details Lines 228-229 and 424 fetch connection string and subscription keys without `::add-mask::` and do not forbid papermill `--log-output`
  * Impact: minor (defense in depth for A01). Remedy: register fetched secrets with `::add-mask::` before use; forbid `--log-output` in a workflow contract test
* DR-13: Spend reservation and model-bound output caps
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 251-257)
  * Reason: details Lines 192-193 reserve attempts/tokens/deadline only; no estimated-spend reservation, no unknown-price rejection, no requirement that each guarded inference body sets `max_tokens`
  * Impact: minor (token cap bounds model spend once a price snapshot exists). Remedy: add `SESSION_MAX_ESTIMATED_USD` derived from the snapshot and have `guarded_request` reject bodies lacking `max_tokens`
* DR-14: Site crawl contract partial
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 302)
  * Reason: details Lines 403-408 crawl links only
  * Impact: minor (A11). Remedy: add checks for duplicate permalinks, old sibling baseurls, paired switchers both ways, and alert rendering; manual mobile/desktop review in Step 7.2
* DR-15: Harmless lock rehearsal ordered after bootstrap
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 374)
  * Reason: details Line 454 rehearses locking in Phase 6.3 after bootstrap
  * Impact: minor. Remedy: rehearse with a no-cloud stand-in environment before Step 6.2, or record the reordering
* DR-16: Processing and storage location approvals beyond the model tuple
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 74)
  * Reason: details Line 446 records the model tuple and residency flag only
  * Impact: minor (P03). Remedy: add Content Safety/Prompt Shields processing and telemetry storage location approvals to Step 6.1
* DR-17: Mock credential precedence test
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 215)
  * Reason: details Line 168 checks mock credential removal but not subscription-protected mock credential precedence
  * Impact: minor (A07). Remedy: add a Demo 4 fixture and live check that the mock requires its own credential and is never anonymous

### Plan Deviations from Research

* DD-01: Retained user-assigned identity for APIM instead of per-session system-assigned identity
  * Research recommends: APIM system identity with deployment identity holding constrained role-assignment rights; principal pinning required, which forces an administrator approval each time the identity is recreated (research Lines 82-105)
  * Plan implements: Bootstrap creates a user-assigned identity in the retained RG and assigns its three data-plane roles once at RG scope; deployment identity gets Contributor plus Managed Identity Operator on that identity and no role-assignment write; notebooks inject `client-id` when `APIM_IDENTITY_CLIENT_ID` is set and keep system-assigned behavior otherwise
  * Validator note: deviation is sound in direction (removes role-assignment write from CI) but placement and scope defects are recorded in DD-04 and DD-05
  * Rationale: Full-session automation recreates APIM every session; a system identity would need either arbitrary-principal delegation (rejected by research) or a manual RBAC approval every session. The user-assigned identity removes role-assignment rights from CI, removes per-session principal replication delays, and keeps principal constraints strict. Trade-off: data-plane roles are RG-scoped rather than resource-scoped, acceptable because the RG is dedicated to lab resources. Verify Basic v2 user-assigned identity support and logger `identityClientId` shape against current docs during Phase 1/3.
* DD-02: Irreversible purge is human-operator only
  * Research recommends: Purge as a separately approved operator path, possibly via teardown workflow (research Lines 143-161)
  * Plan implements: `scripts/lab_session.py purge` run locally by a named operator; no workflow holds subscription-scope purge permissions
  * Rationale: Avoids granting any CI identity subscription-scope rights; purge is rare
* DD-03: Recovery manifest stored as an ARM deployment record in the retained RG
  * Research recommends: Durable, access-controlled, runner-independent storage, mechanism unspecified (research Lines 143-161)
  * Plan implements: Empty-template deployment named `aigov-manifest-<generation>` whose outputs hold the nonsecret manifest, written by the deploy identity before first mutation
  * Rationale: Free, survives runner loss, readable by RG readers only, no extra resource. Validate output size limits and that cleanup excludes these records.
  * Validator note: sound as storage; integrity defect recorded in DD-07
* DD-04: Retained UAMI co-located in the lab RG under deploy-identity Contributor (DD-01 defect)
  * Research recommends: runtime authority outside CI control; no trust path that bypasses environment approval (research Lines 86, 94-95)
  * Plan implements: details Lines 314-316 place `id-aigov-apim-<env>` in the lab RG where the deploy identity holds Contributor
  * Rationale: Validator severity MAJOR (P04). Contributor can write `federatedIdentityCredentials` on the UAMI (persistent out-of-band tokens with OpenAI/Cognitive Services data-plane rights, outside GitHub approval) and can delete the UAMI. Remedy: create the UAMI in a separate bootstrap-owned identity RG; deploy identity gets Managed Identity Operator on it only; data-plane roles stay scoped to the lab RG
* DD-05: Runtime identity holds API Management Service Contributor at RG scope
  * Research recommends: API Management Service Contributor on the lab APIM plus scoped telemetry query (research Line 92)
  * Plan implements: details Line 317 assigns it at RG scope because APIM is recreated per session
  * Rationale: Validator severity MAJOR (P04, F10). The role includes `Microsoft.ApiManagement/service/write` and `delete`, so the runtime identity can create billable APIM instances and delete the service; details Line 450 negative test ("runtime identity cannot delete resources") would fail. Remedy: bootstrap a custom RG-scoped role limited to APIM child objects (apis, backends, products, subscriptions, namedValues, loggers, diagnostics, policies, listSecrets) plus `service/read`
* DD-06: One environment subject federated to both deploy and runtime applications
  * Research recommends: explicit identity per job and mode-specific permissions (research Lines 86, 127, 137)
  * Plan implements: details Lines 315 and 318 federate both apps to the single `lab` environment subject
  * Rationale: Validator severity MAJOR (P04). Any `environment: lab` job, including preflight and report-only, can mint deploy-identity tokens; separation is convention only. Remedy: two protected environments (for example `lab-deploy` and `lab-run`), each federated to one app, or document the accepted equivalence
* DD-07: Manifest record updated in place (DD-03 defect)
  * Research recommends: storage that retains provenance and integrity (research Lines 145-147)
  * Plan implements: details Lines 226-227 create `aigov-manifest-<generation>` and update the same record after each attempt
  * Rationale: Validator severity MAJOR (A04, P05). Overwrite loses per-attempt history; the same identity can rewrite or delete it; RG deployment history auto-prunes near 800 entries (Bicep modules add nested deployments). Remedy: append-only names `aigov-manifest-<generation>-<run>-<attempt>` with a content hash, never overwrite, pin `--mode Incremental` (an empty template in Complete mode deletes RG contents), and keep a workflow-artifact copy as secondary
* DD-08: Recovery authority merged into the deploy identity; telemetry query roles at RG scope
  * Research recommends: separate recovery identity row and component/workspace-scoped query role (research Lines 92-94)
  * Plan implements: details Lines 230 and 427-430 use the deploy identity for cleanup; details Line 317 grants readers at RG scope
  * Rationale: Validator severity minor. Acceptable in a dedicated RG with guarded cleanup; record the equivalence rather than leaving it implicit
* DD-09: Logger refuses missing identity instead of using SystemAssigned
  * Research recommends: connection string plus identity credential; the reviewed reference uses `identityClientId: SystemAssigned` (adversarial-platform-review.md addendum)
  * Plan implements: details Line 56 rejects a missing client ID while details Line 106 keeps system identity when `APIM_IDENTITY_CLIENT_ID` is unset
  * Rationale: Validator severity minor. Contradictory contract breaks Demo 2 for interactive users. Remedy: default `identityClientId` to `SystemAssigned` when unset and document the Monitoring Metrics Publisher prerequisite
* DD-10: Publication requires a fully passed checker run
  * Research recommends: publish verified evidence and mark inconclusive objectives unverified (research Lines 304, 392)
  * Plan implements: details Line 470 curates only from a run whose checker passed
  * Rationale: Validator severity minor. A likely-inconclusive Demo 3 stream objective blocks every lab page. Needs user decision
* DD-11: Full-session suggested against an existing deploy-only environment
  * Research recommends: full-session rejects pre-existing environments; use run-existing (research Line 131)
  * Plan implements: details Line 458 offers `full-session` with `keep_environment=true` after Step 6.3
  * Rationale: Validator severity minor. Remedy: use `run-existing` only in Step 6.4

### Validation Round 1 Resolutions

Line references in DR-06 to DD-11 above describe the details file before this round; resolved text now lives in the steps named below.

* DR-06, DR-07, DR-08 (HIGH): resolved. Step 5.2 uses one protected `cloud` job with sequential steps, a step-level `if: always()` cleanup guarded by the persisted manifest record in Azure, runner-local budget state for the whole session, and sanitization inside that job. Only the credential-free `render` job is separate.
* DR-09 (MAJOR): resolved. Step 2.1 adds `what-if` (fails on unexpected deletes/changes) and bounded `readiness`; Step 6.3 reviews what-if.
* DR-10 (MAJOR): resolved. Step 1.4 strips `Ocp-Apim-Subscription-Key` in demo1-3 policies; Step 3.3 strips it in the platform policy; Step 2.1 `probe-scopes` checks product, API-scoped, and anonymous paths and documents all-access bypass.
* DR-11 (MAJOR): resolved. Step 2.1 `preflight` checks APIM and Cognitive Services tombstones for planned names via the `AIGov Tombstone Reader` custom role (Step 3.1).
* DR-12: resolved in Step 5.2 (`::add-mask::`, no `--log-output`) and Step 5.4 contract test.
* DR-13: resolved in Step 1.8 (`SESSION_MAX_ESTIMATED_USD`, required `max_tokens`).
* DR-14: resolved in Step 4.4 (extended crawl and manual review).
* DR-15: resolved in Step 6.1 (`lock-test` mode before bootstrap; Step 5.2 adds the mode).
* DR-16: resolved in Step 6.1 (Content Safety and telemetry location approvals).
* DR-17: resolved in Step 1.7 (`demo4.mock_auth_enforced` negative probe).
* DD-04 (MAJOR): resolved. Step 3.1 places the identity in a separate identity RG with no CI write access; deploy identity has Managed Identity Operator on the identity only.
* DD-05 (MAJOR): resolved. Step 3.1 defines `AIGov APIM Lab Operator` custom role limited to APIM child objects; Step 6.2 negative test updated.
* DD-06 (MAJOR): accepted and documented. A single job cannot use two environments, and DR-06 requires a single cloud job, so both apps federate to environment `lab`. Controls: only the lab-session `cloud` job and the teardown job use `lab`; required reviewers and `main`-only deployment policy; contract test in Step 5.4 enforces exactly one environment job per workflow. The runtime identity still limits notebook blast radius inside the job. Residual risk: approved code on `main` can use either identity.
* DD-07 (MAJOR): resolved. Step 2.1 uses append-only hashed record names, pinned `--mode Incremental`, artifact backup, newest-valid-record recovery, and bounded pruning of non-manifest deployment records.
* DD-08: accepted and documented in Step 3.1 (deploy identity is recovery identity; readers at lab RG scope).
* DD-09: resolved in Step 1.2 (`SystemAssigned` default when client ID unset; local-auth logger only by explicit interactive flag).
* DD-10: resolved with default in Step 7.1 (publish passed objectives; inconclusive ones marked unverified without success images).
* DD-11: resolved in Step 6.4 (`run-existing` only).
* Internal: Phase 1 file list now includes .env.example and root-anchored outputs; Step 3.3 test lives in new tests/test_infra.py owned by Phase 3; Step 1.3 docstring wording is "verify"; residual report treats expected tombstones separately (Step 2.1); Phase 8 local validation also runs after Phase 5 (plan note).

### Validation Round 2 Findings

Line references in this section point to the current details file (524 lines). Plan-to-details line ranges for all 36 steps were checked against current headings and are accurate.

Round 1 verification status:

* DR-06: verified resolved in structure (details Lines 436-440: one `cloud` job, cleanup `if: always()` guarded by the Azure manifest record). Residual timeout and login-step gaps recorded as DR-18.
* DR-07: verified resolved (details Lines 197, 436). Per-attempt reset residual recorded as DR-26.
* DR-08: verified resolved in placement (details Lines 271, 439). Sequencing gap recorded as DR-19.
* DR-09: verified resolved (details Lines 230, 233, 473).
* DR-10: verified resolved (details Lines 106, 234, 369). Query-parameter residual in DR-30.
* DR-11: verified resolved (details Lines 229, 324). Action pinning and workspace tombstones in DR-23.
* DR-12, DR-14, DR-15, DR-16, DR-17: verified resolved (details Lines 438, 452; 417-418; 465; 464; 179).
* DR-13: partially resolved (details Line 196); unknown-price residual in DR-27.
* DD-04, DD-05, DD-08, DD-11: verified resolved or documented (details Lines 321-327, 469, 477). DD-05 action completeness in DR-23.
* DD-06: verified accepted and documented (details Lines 325, 330, 452). Hardening in DR-31.
* DD-07: verified resolved (details Lines 231-232). Pruning residual in DR-24.
* DD-09: still open (minor). Details Line 58 defaults to `SystemAssigned`; details Line 67 success criterion still says "rejects missing identity by default". Recorded as DD-13.
* DD-10: text resolved (details Line 489) but not reachable at runtime; see DR-19.

New unaddressed research items:

* DR-18: Single cloud job has no timeout budget and the cleanup login step is not bound to `always()`
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 139-141)
  * Reason: details Lines 436-440 set no job `timeout-minutes`, no step caps for deploy, readiness, notebooks, traffic, or showback, and no relation between `SESSION_DEADLINE_UTC` and the job limit; a job-level timeout can terminate the job before or during cleanup. Line 440 puts the deploy-identity login inside "the cleanup step" while Line 437 models logins as separate `azure/login` steps, so a default-condition login step is skipped after failure and cleanup runs under the runtime identity, which cannot delete
  * Impact: MAJOR (A04, P08). Remedy: cap every long step with `timeout-minutes`; set job `timeout-minutes` above the step sum plus cleanup cap; require `SESSION_DEADLINE_UTC` to end before job start plus job timeout minus cleanup cap; give both the cleanup `azure/login` step and the cleanup script `if: always()` (skip only for lock-test); extend the Step 5.4 contract test to assert both conditions and the timeout arithmetic
* DR-19: Evidence is unreachable for any run with a failed or inconclusive objective, and lab00, lab06, lab07 have no evidence source
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 139, 279, 291-298)
  * Reason: details Line 439 orders checker then sanitize as default-condition steps, and details Line 258 makes the checker exit nonzero unless every objective passed, so sanitize, upload, and render never run when Demo 3 is inconclusive; DD-10 (details Line 489) cannot execute. Details Line 271 builds evidence from notebook result files only, so showback (outputs/showback), readiness, and the cleanup residual report never reach evidence.json; details Line 272 maps lab02 through lab07 only
  * Impact: MAJOR (user requirements "pictures" and "chargeback with real data"; G6, G7). Remedy: run sanitize and upload with `if: always()` once write-env succeeded, embedding the checker verdict and per-objective status; add allowlisted inputs for readiness summary and showback report; add a post-cleanup `always()` sanitize of the residual report; extend the render map to lab00-lab07
* DR-20: Per-notebook `run-notebooks --only` wipes earlier outputs
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 189-201)
  * Reason: details Line 236 cleans `outputs/executed/<run_id>/` on each invocation, while details Line 438 invokes it once per notebook; details Line 257 then requires all five outputs and a matching execution.json
  * Impact: MAJOR (G5 cannot pass as written; also blocks evidence via DR-19). Remedy: clean once in an explicit `run-notebooks --init` (or in write-env); each `--only` appends its record to execution.json atomically; checker requires five records from the same session ID
* DR-21: Readiness and scope probes send inference outside the guard; probe step missing from the workflow
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 225, 253-255)
  * Reason: details Line 233 polls inference and safety through the gateway before write-env creates budget state (Line 438); details Line 234 `probe-scopes` is absent from the Line 437-439 sequence and creates an API-scoped test subscription on the platform API
  * Impact: minor (bounded but unaccounted spend; potential window contamination). Remedy: initialize budget state before readiness and route readiness and probes through `guarded_request` with envelope entries; run `probe-scopes` after readiness and before the traffic window; delete the test subscription and exclude it from showback
* DR-22: dry-run cannot run what-if or tombstone preflight under the runtime identity
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 78)
  * Reason: details Line 443 restricts deploy-identity login to modes with deploy or cleanup; dry-run has neither, but what-if needs `Microsoft.Resources/deployments/whatIf/action` and tombstone reads need the deploy identity's AIGov Tombstone Reader (Line 326)
  * Impact: minor (blocks Step 6.3 as written). Remedy: allow deploy-identity login for dry-run and full-session/deploy-only preflight
* DR-23: Custom role action lists not pinned; workspace tombstones unchecked
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 99, 149, 159)
  * Reason: details Lines 323-324 name resource families, not action strings. Current ARM paths in shared/apim.py use apis, apis/operations, apis/policies, apis/diagnostics, products, products/apis, subscriptions and subscriptions/listSecrets, backends (including pools), namedValues, and loggers, plus Insights component reads. Details Line 229 checks APIM and Cognitive Services tombstones only; a same-name workspace recreated within 14 days recovers the old one
  * Impact: minor. Remedy: define `Actions` with explicit wildcards per child type (for example `Microsoft.ApiManagement/service/apis/*`) and `service/read` only; pin tombstone actions `Microsoft.ApiManagement/deletedservices/read`, `Microsoft.CognitiveServices/deletedAccounts/read`, `Microsoft.CognitiveServices/locations/resourceGroups/deletedAccounts/read`; add a per-notebook positive access check in Step 6.2; name workspaces per generation or check deleted workspaces
* DR-24: History pruning excludes Bicep module deployments; ARM auto-deletion ignores names
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 145)
  * Reason: details Line 232 prunes only `aigov-main-*`; the four modules in details Line 348 create nested deployment records, and ARM automatic history deletion removes the oldest records regardless of name, including manifest records
  * Impact: minor (long-lived RG only; artifact backup exists). Remedy: give modules deterministic names `aigov-main-<generation>-<module>` so pruning covers them; record the artifact retention period and make recovery fall back to it
* DR-25: Render job gating and network isolation underspecified
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 277)
  * Reason: details Line 441 says `if: always()` "with evidence present" (a job condition cannot inspect artifacts) and relies on "not installing browsers" for network isolation, which does not block requests
  * Impact: minor (A10). Remedy: gate on a cloud job output such as `needs.cloud.outputs.evidence_uploaded == 'true'` (allowed for render, not cleanup); install dependencies, then run the renderer in a container with `--network none` or `unshare -n`
* DR-26: Budget state resets per job attempt and the session ID is undefined
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 253)
  * Reason: details Line 196 keys budget by `<run_id>` but no step initializes budget.json; a GitHub re-run of `cloud` gets a fresh runner and fresh counters; details Lines 163 and 196 do not distinguish the session ID from `DEMO_RUN`, which Demo 1 rotates
  * Impact: minor (each re-run needs new approval, which bounds exposure). Remedy: write-env initializes budget.json keyed by `AIGOV_SESSION_ID=<run_id>-<run_attempt>`; record spent counters in the post-attempt manifest record and either seed the next attempt from them or document each attempt as a separately approved envelope
* DR-27: Unknown price does not fail closed
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 251)
  * Reason: details Line 196 reserves USD only "when present"
  * Impact: minor (F4, F6). Remedy: in headless mode require the approved snapshot and a matching rate before any model dispatch
* DR-28: Custom metric dimensions opt-in mechanism unspecified
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 115)
  * Reason: details Line 350 verifies the property by readback but does not name how it is set; the runtime identity has no App Insights write
  * Impact: minor (G3; Demo 2 dimensions query returns zero rows otherwise). Remedy: name the exact ARM property or API in Step 3.2, set it in Bicep or the deploy phase, and read it back in `readiness`
* DR-29: Pre-bootstrap lock rehearsal includes a teardown run that needs Azure and environment `lab`
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 374)
  * Reason: details Line 465 dispatches teardown dry run before bootstrap; details Line 447 runs `lab_session.py cleanup` after login, and a job referencing a nonexistent environment auto-creates it without protection rules
  * Impact: minor. Remedy: add a no-Azure lock-test path to teardown.yml or defer the teardown concurrency rehearsal to after Step 6.2
* DR-30: Subscription key stripping covers the header only
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 227)
  * Reason: details Lines 106 and 369 delete `Ocp-Apim-Subscription-Key`; a key sent as the `subscription-key` query parameter is still forwarded
  * Impact: minor (F8). Remedy: also `set-query-parameter name="subscription-key" exists-action="delete"`
* DR-31: DD-06 residual can be narrowed inside the shared job
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 86)
  * Reason: details Lines 437-438 switch identities without clearing the deploy account from the az profile; `id-token: write` exposes the OIDC request variables to every step, including notebook kernels and their dependencies. Details Line 452 says "exactly one job per workflow" although ci.yml has none
  * Impact: minor. Remedy: `az account clear` before runtime login; set `ACTIONS_ID_TOKEN_REQUEST_TOKEN` and `ACTIONS_ID_TOKEN_REQUEST_URL` to empty in `env:` of notebook, traffic, showback, and sanitize steps; reword the contract test to "exactly one per cloud workflow, none in ci.yml"

New plan deviations from research:

* DD-12: Cleanup and preservation keyed on `keep_environment` instead of a mode-by-outcome matrix
  * Research recommends: full-session rejects pre-existing environments and deletes on any outcome unless kept; deploy-only retains on success and cleans only this attempt's resources on failure; run-existing validates an existing manifest and never deletes; report-only never deletes (research Lines 131-137)
  * Plan implements: details Line 434 has one `keep_environment` input defaulting to false; details Line 440 cleanup guard is "mode allows cleanup, keep_environment false, manifest record for this run exists"; details Line 231 refuses only resources "not in the approved inventory"; no `manifest verify` for run-existing
  * Rationale: Validator severity MAJOR (A04 inverse, P05). With the default, a successful deploy-only deletes the environment that Step 6.4 (details Line 477) needs, and if run-existing reaches `manifest create`, cleanup would delete a pre-existing environment. Remedy: specify the matrix in Steps 2.1 and 5.2 (full-session: `manifest create` refuses any live owned resource, cleanup on any outcome unless keep; deploy-only: cleanup only when deploy or readiness failed; run-existing, report-only, dry-run, lock-test: no `manifest create`, no cleanup, `manifest verify` of the newest record for run-existing); add one fixture test per mode-outcome cell and a contract assertion
* DD-13: Logger success criterion contradicts the SystemAssigned default (DD-09 residual)
  * Research recommends: MI logger with a documented credential; incompatible credentials fail visibly (research Lines 109-111)
  * Plan implements: details Line 58 defaults to `SystemAssigned`; details Line 67 requires the test to reject a missing identity
  * Rationale: Validator severity minor. Remedy: change Line 67 to "defaults to `SystemAssigned` when unset; rejects connection-string-only unless the explicit interactive flag is set outside headless mode"

### Validation Round 2 Resolutions

Line references in round-2 findings describe the details file before this round.

* DD-12 (MAJOR): resolved. Step 2.1 adds the mode-by-outcome cleanup table (sole cleanup authority), `manifest verify` for run-existing/report-only, `cleanup --auto --mode`, and one test per table cell. Default for clarifying Q1: deploy-only keeps the environment on success; `keep_environment` applies to full-session only.
* DR-18 (MAJOR): resolved. Step 5.2 sets step and job `timeout-minutes`, derives `SESSION_DEADLINE_UTC` from job start minus cleanup cap, and puts `if: always()` on both the cleanup login and cleanup steps; Step 5.4 asserts it.
* DR-19 (MAJOR): resolved. Sanitize runs with `always()` after write-env succeeds; evidence includes verdict, readiness, showback, and (post-cleanup) residual reports; render map covers lab00-lab07 with status cards for non-passed objectives. Default for clarifying Q2: publish passed objectives and gate-passed showback/teardown evidence; inconclusive objectives shown as unverified.
* DR-20 (MAJOR): resolved. `run-notebooks --init` once, `--only` appends atomically; tested across five calls.
* DR-21: resolved (readiness and probe-scopes go through `guarded_request`; probe order fixed; temporary test subscription deleted).
* DR-22: resolved (dry-run logs in as deploy identity for preflight and what-if only).
* DR-23: resolved (exact action lists committed in scripts/roles/*.json and derived from shared/apim.py inventory; workspace tombstones checked).
* DR-24: resolved (prune non-manifest and nested module records; artifact backup).
* DR-25: resolved (render gated on `evidence_ready` output; `--network none`).
* DR-26: resolved (`SESSION_ID` distinct from `DEMO_RUN`; budget initialized in write-env). Default for clarifying Q3: each run attempt is a separately approved envelope, max 2 attempts, cumulative spend recorded in the manifest.
* DR-27: resolved (unknown price fails closed in headless mode).
* DR-28: resolved (`CustomMetricsOptedInType: 'WithDimensions'` with one documented suppression and readback).
* DR-29: resolved (lock rehearsal uses no-environment, no-Azure jobs; environment created in Step 6.2).
* DR-30: resolved (strip `subscription-key` query parameter too).
* DR-31: resolved (`az account clear` between identities; OIDC request variables blanked on notebook and traffic steps; contract wording per cloud workflow).
* DD-13: resolved (Step 1.2 success criterion updated).

### Validation Round 3 Findings

Line references in this section point to the current details file (541 lines). Plan-to-details line ranges for all 36 steps were rechecked against current headings (Step 1.1 Line 30 through Step 8.3 Line 528) and are accurate. The Step 6.4 heading at details Line 492 still reads "Full session" while its body and the plan describe a run-existing session (cosmetic).

Round 2 verification status:

* DD-12: partially resolved. Table at details Lines 241-252, `manifest verify` at Line 232, `cleanup --auto` at Line 239, and per-cell tests at Line 259 exist. Step 5.2 does not apply the table to step conditions (DR-32), and `cleanup --auto` lacks run provenance and outcome inputs (DD-14).
* DR-18: resolved in text (details Lines 451, 456, 469). Coverage residual in DR-36.
* DR-19: resolved in sanitize placement (details Lines 286-287, 455, 457-458). Step-condition residual in DR-34; post-cleanup residual in DR-37; image status sources in DR-39.
* DR-20: verified (details Lines 237, 259, 272).
* DR-21: text present (details Lines 234-235) but not effective; Step 5.2 runs readiness and probe-scopes before write-env creates `SESSION_ID` and budget.json (DR-33).
* DR-22: verified (details Line 452).
* DR-23: verified (details Lines 338-339). The expected child-type list matches every ARM path in shared/apim.py (Lines 135-920: apis, apis/operations, apis/policies, apis/diagnostics, backends, namedValues, products, products/apis, subscriptions, subscriptions/listSecrets, loggers). Missing tombstone action recorded in DR-35.
* DR-24, DR-25, DR-27, DR-28, DR-30, DR-31: verified (details Lines 233; 458; 196; 365; 106 and 384; 453-454 and 469).
* DR-26: verified (details Lines 196-197, 236). Recording residual in DR-38.
* DR-29: verified (details Line 482). Environment auto-creation residual in DR-40.
* DD-13: verified (details Line 67).

New unaddressed research items:

* DR-32: Step 5.2 step list is not gated by mode and contradicts the mode table
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 132-134, 137)
  * Reason: details Line 452 starts every non-lock-test mode with a deploy-identity login, preflight, and what-if and lists `deploy`, readiness, and probe-scopes without mode conditions; details Line 460 says run-existing and report-only never log in as the deploy identity. Details Lines 453-454 run notebooks, traffic, and showback for every mode, so deploy-only ("No traffic", research Line 132) and report-only ("Read-only telemetry/evidence collection", research Line 134) would send inference and mutate child objects. The table (details Lines 245-248) governs manifest and cleanup only
  * Impact: MAJOR (P04, P08, A04). Remedy: add a per-mode step matrix to Step 5.2 (full-session: all steps; deploy-only: through readiness, then cleanup-on-failure; run-existing: runtime login, manifest verify, readiness, probe-scopes, notebooks, traffic, showback, checker; report-only: runtime login, manifest verify, showback report only; dry-run: deploy login, preflight, what-if), express each as a step `if:`, make the deploy-identity login and `deploy` step conditional on full-session/deploy-only/dry-run, and extend the Step 5.4 contract test to assert the matrix
* DR-33: Readiness and probe-scopes run before budget state and `SESSION_ID` exist
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 251-255)
  * Reason: details Line 452 runs readiness and probe-scopes in the deploy-identity block; details Line 453 runs write-env afterwards, and write-env (details Line 236) is where `SESSION_ID`, `AIGOV_HEADLESS=1`, session limits, and budget.json are created. `guarded_request` (details Line 196) hard-fails on missing state in headless mode and runs record-only without headless mode, so readiness either fails every deploy mode or dispatches unbudgeted inference (DR-21 regression). Readiness writes `outputs/readiness/<session_id>/` (details Line 234) before `session_id` is defined, and probe-scopes fetches team keys before the `::add-mask::` step (details Line 453)
  * Impact: MAJOR (F4, P08, G1). Remedy: set `SESSION_ID` (`<run_id>-<run_attempt>`) and `SESSION_DEADLINE_UTC` as job-level env at job start; move write-env (or a `budget-init` subcommand) and secret masking before readiness; run readiness and probe-scopes after the identity switch under the runtime identity
* DR-34: Default step conditions skip later notebooks, traffic, showback, and the checker after any failure
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 139, 279, 291-298)
  * Reason: details Lines 453-454 give notebook, traffic, showback, and check_notebook_outputs steps default `success()` conditions; a failed or raising notebook skips all later notebooks, the traffic window, the showback report, and verdict.json, so sanitize (details Line 455) has no verdict or chargeback data to embed
  * Impact: MAJOR (user requirements "run all labs with pictures" and "real traffic for chargeback"; G5-G7; DR-19 resolution incomplete). Remedy: each notebook step `if: always() && steps.nb_init.outcome == 'success'`; traffic and showback `if: always() && steps.write_env.outcome == 'success'` (the guard still bounds spend and deadline); checker `if: always() && steps.nb_init.outcome == 'success'` so verdict.json always exists and the job still fails; add these to the contract test
* DR-35: Preflight needs subscription-scope reads the deploy identity lacks
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 76)
  * Reason: details Line 229 checks provider registration, Basic v2 region availability, model availability, and model quota/usage via ARM; these are subscription-scope reads (for example `Microsoft.CognitiveServices/locations/usages/read`, `Microsoft.CognitiveServices/locations/models/read`, and provider reads). Details Line 341 gives the deploy identity Contributor at lab RG scope plus AIGov Tombstone Reader, which details Line 339 limits to three deleted-resource actions. `az cognitiveservices account show-deleted` also needs `Microsoft.CognitiveServices/locations/resourceGroups/deletedAccounts/read`, absent from details Line 339
  * Impact: MAJOR (blocks dry-run, deploy-only, and full-session at preflight; G1). Remedy: replace AIGov Tombstone Reader with an `AIGov Preflight Reader` subscription-scope custom role holding only the needed read actions (verify each against provider operations), and add a positive access check for each preflight call to Step 6.2
* DR-36: Timeout arithmetic covers only "long" steps
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 139)
  * Reason: details Lines 451 and 469 cap only long steps; uncapped steps (checkout, setup-python, pip install, per-notebook `azure/login`, sanitize, uploads) default to 360 minutes, so "job timeout above the sum of step caps" does not guarantee cleanup starts. The deadline formula subtracts the cleanup cap but not the post-cleanup sanitize and upload caps. Workflow-level `permissions` are unspecified, so lock-test and render jobs could inherit `id-token: write`
  * Impact: minor. Remedy: cap every step; subtract cleanup plus post-cleanup caps in the deadline formula; keep the job total at or below the hosted-runner limit; set workflow-level `permissions: {}`; update the contract test to "every step"
* DR-37: Post-cleanup sanitize semantics on early failure
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 139, 273-277)
  * Reason: details Line 457 runs post-cleanup sanitize with bare `always()`; when write-env never ran there is no .env known-value list and no evidence.json (details Line 286 fails closed on sanitizer error). Re-uploading the same artifact name fails under upload-artifact v4 without `overwrite: true`
  * Impact: minor. Remedy: gate on write_env success or define a residual-only evidence path with pattern-only scanning; use `overwrite: true` or a distinct artifact name; set `evidence_ready` after the final upload
* DR-38: Spend recording conflicts with no-record modes; attempt limit enforced late
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 145-147, 253)
  * Reason: details Line 197 records each attempt's spent totals in the manifest, but run-existing and report-only never create records (details Line 232) and the runtime identity has no deployments write (details Line 342). The run_attempt > 2 refusal is described with write-env (details Lines 197, 236), after deploy has already run
  * Impact: minor. Remedy: record spend in sanitized evidence and the workflow artifact for no-record modes (or a spend-only record written after the cleanup login); refuse run_attempt > 2 in the first lab_session step
* DR-39: Image status sources for lab00, lab06, and lab07 undefined
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 279, 291-298)
  * Reason: details Line 287 labels images by "objective status" and details Line 506 publishes only objectives with status `passed`, but readiness, showback, and residual reports are not Step 1.7 objectives; the round 2 default ("gate-passed showback/teardown evidence") is not reflected in details Line 506
  * Impact: minor. Remedy: define `readiness.passed`, `showback.complete`, and `teardown.residual_clean` statuses in sanitize output and name them in Step 7.1
* DR-40: Lock rehearsal may auto-create an unprotected `lab` environment
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 374)
  * Reason: details Line 482 says the rehearsal has "no environment reference", but lab-session.yml's `cloud` job still references `environment: lab` while skipped (details Line 451); GitHub may create a referenced environment without protection rules
  * Impact: minor (no federated credential exists yet). Remedy: after rehearsal, confirm no `lab` environment exists, or have bootstrap (details Line 343) apply and read back reviewers and branch policy on an existing environment and fail otherwise

New plan deviations from research:

* DD-14: `cleanup --auto` lacks this-run provenance and outcome inputs
  * Research recommends: cleanup combined with validated target, advance deletion authorization, applicable mode, and mutation-attempt guards; a report failure never licenses deletion of a pre-existing environment (research Lines 137, 139)
  * Plan implements: details Lines 238-239 load "the manifest record" (newest valid record per generation, details Line 231) and apply the table; details Line 456 passes only `--mode`; details Line 246 conditions deploy-only failure cleanup on "deploy or readiness failed" without naming the signal
  * Rationale: Validator severity MAJOR (A04 inverse, P05). A full-session dispatched against a generation kept by an earlier deploy-only fails at `manifest create` (refusal), then cleanup loads the deploy-only record and deletes the kept environment. Remedy: `cleanup --auto` acts only on records whose run ID, run attempt, and mode match this run and that carry a mutation-attempted marker, deletes only IDs from those records, and is a no-op otherwise; pass `--deploy-outcome ${{ steps.deploy.outcome }}` and `--readiness-outcome ${{ steps.readiness.outcome }}` (step context, not job outputs) and treat unknown as failure; add a test cell for "manifest create refused, pre-existing environment untouched"
* DD-15: full-session cleans on failure even with `keep_environment=true`
  * Research recommends: keep_environment=true preserves resources and reports continuing exposure (research Line 131)
  * Plan implements: details Line 245 cleans full-session failures regardless of `keep_environment`
  * Rationale: Validator severity minor. Cost-safe and aligned with the teardown goal but deviates from research and the round 2 remedy ("unless keep"). Record as an accepted deviation or apply keep on failure too

### Validation Round 3 Resolutions

Line references in round-3 findings describe the details file before this round.

* DR-32 (MAJOR): resolved. Step 5.2 now has a literal per-mode step matrix; deploy identity is used only in dry-run, full-session, deploy-only and their cleanup; deploy-only sends no traffic; report-only only verifies the manifest and queries showback for an input window (labelled unreconciled).
* DR-33 (MAJOR): resolved. New `init-session` runs first (SESSION_ID, deadline, budget keys, budget.json, run-attempt limit) before any Azure call; readiness and probe-scopes run after write-env; every subcommand masks secrets immediately on retrieval.
* DR-34 (MAJOR): resolved. Notebook, traffic, showback, and checker steps use `always()` gated on write-env success; later notebooks still run after an earlier failure, bounded by the budget guard (default for clarifying Q2).
* DR-35 (MAJOR): resolved. Step 3.1 replaces the tombstone role with `AIGov Preflight Reader` (deleted-resource reads including the Cognitive Services location-scoped action, usages, models, SKUs, APIM locations, providers), verified against provider operations before creation.
* DD-14 (MAJOR): resolved. Manifest records carry `created_by_session`; `cleanup --auto` acts only on records created by the current SESSION_ID and receives `DEPLOY_OUTCOME` and `READINESS_OUTCOME` step outcomes as env; test added for a refused full-session leaving a kept environment untouched.
* DR-36: resolved (every step has timeout-minutes; job timeout is their sum plus margin; deadline subtracts all post-work caps; workflow-level `permissions: {}`).
* DR-37: resolved (post-cleanup sanitize gated on init-session; `overwrite: true`).
* DR-38: resolved (spend totals always in evidence, also in a manifest record when the session created one; run-attempt limit enforced by init-session before deploy).
* DR-39: resolved (status sources for lab00, lab06, lab07 in Step 2.3; Step 7.1 publishes passed items and marks others unverified).
* DR-40: resolved (bootstrap creates the protected `lab` environment first; lock rehearsal moved to Step 6.2 after bootstrap and before any paid session).
* DD-15: resolved by aligning with research: `keep_environment=true` preserves resources on success and failure, with the residual exposure report (default for clarifying Q1).
* Cosmetic: Step 6.4 heading renamed "Run-existing session".

### Validation Round 4 Findings

Line references point to the current details file (561 lines). All 36 plan-to-details line ranges (Step 1.1 Lines 30-53 through Step 8.3 Lines 548-551) match current headings.

Round 3 verification status:

* DR-32: verified. Step matrix at details Lines 455-474 matches the mode table (Lines 244-251); deploy identity only in dry-run, full-session, deploy-only (Lines 458-461, 473); deploy-only sends no traffic; report-only runs manifest-verify, write-env, showback only. `login-runtime` excludes dry-run (Line 462). `write-env` (Line 464) evaluates correctly for full-session with skipped manifest-verify (implicit `success()` plus `ok(deploy)`; a skipped step's outcome is `skipped`, not an error).
* DR-33: verified (Lines 229, 457, 464-466).
* DR-34: partially resolved; residual in DR-41 and DR-42.
* DR-35: verified (Lines 230, 340, 342).
* DD-14: verified (Lines 232, 240, 260, 477).
* DR-36: verified except upper bound (DR-45). DR-37: verified except output timing (DR-44). DR-38: text at Line 197 not carried into Step 2.3 (DR-43). DR-39: verified (Lines 288, 526). DR-40: verified (Lines 344, 506). DD-15: verified (Lines 246, 253). Step 6.4 heading verified (Line 512). Render gating verified (Line 479).

New unaddressed research items:

* DR-41: Notebooks and traffic run after readiness or probe-scopes failure, and without `run-notebooks --init`
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Line 376)
  * Reason: details Line 467 gates `--init` with implicit `success()`, so a readiness or probe-scopes failure skips it; details Lines 468-469 and 471 gate notebooks, traffic, and the checker only on `ok(write-env)`, so paid notebooks and the traffic window run against a gateway that failed readiness and write into an uninitialized `outputs/executed/<session_id>/` (Step 2.1 Line 238 assumes init ran). Research requires readiness, logger readback, privacy, and ingestion verification before the full notebook set. The round 3 remedy used `ok(nb_init)`
  * Impact: MAJOR (G3, P08). Remedy: per-notebook, traffic, and checker steps condition on `ok(run-notebooks-init)`; keep `--init` gated on `ok(probe-scopes)`; showback stays on `ok(write-env)` for report-only and `ok(run-notebooks-init)` otherwise; the checker still produces a failed verdict when init is skipped via the sanitize path; add both cases to the Step 5.4 contract test
* DR-42: `always()` on paid steps defeats operator cancellation and delays cleanup
  * Source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 139, 141, 251)
  * Reason: details Lines 462 and 468-471 use `always()`, which GitHub evaluates as true after a run is cancelled; cancelling a session to stop spend still runs every remaining notebook, the traffic window, and showback up to their step caps before cleanup (Line 473) starts
  * Impact: MAJOR (cost control, teardown requirement). Remedy: use `!cancelled()` for runtime login, notebook, traffic, showback, and checker steps; keep `always()` only on sanitize, cleanup login, cleanup, and post-cleanup sanitize; assert this split in the contract test
* DR-43: Spend totals are not a sanitize input
  * Source: research Line 253; details Line 197 promises spend in evidence.json, but the sanitize input list (Line 287) omits budget.json
  * Impact: minor. Remedy: add allowlisted budget.json totals to the sanitize inputs and fixture test
* DR-44: `evidence_ready` source ambiguous with two sanitize steps
  * Source: research Line 139; details Line 478 does not say which sanitize (Lines 472, 474) sets the output or how a failed post-cleanup sanitize affects render
  * Impact: minor. Remedy: set it from the last successful sanitize and document that render then uses the pre-cleanup artifact with lab07 as a status card
* DR-45: No upper bound on the cloud job timeout
  * Source: research Line 139; details Line 452 sets job timeout to the sum of step caps plus margin without a hosted-runner ceiling, so a runner cap below the configured timeout would invalidate the deadline formula
  * Impact: minor. Remedy: require the sum to stay at or below the hosted-runner job limit and assert it in the contract test
* DR-46: Lock rehearsal lacks an expected outcome for pending replacement
  * Source: research Lines 125, 337; details Line 506 dispatches three runs concurrently without stating that the default concurrency queue keeps one pending run and cancels the earlier pending one
  * Impact: minor. Remedy: state the expected result (one runs, one pending replaced, at most one pending) and verify no interleaving
* DR-47: Report-only showback path undefined in Step 2.4
  * Source: research Lines 134, 241-259; details Line 470 labels report-only output unreconciled, but Line 304 always reconciles against the traffic manifest and Line 311 has no no-manifest or input-window validation test
  * Impact: minor. Remedy: add `--window-start/--window-end` without a manifest producing `unreconciled` status, validate the window (half-open, bounded, not in the future), and test it
* DR-48: A notebook runs even when its own runtime login failed
  * Source: details Line 468 pairs login and `run-notebooks --only` under one condition
  * Impact: minor. Remedy: gate each `--only` step on its preceding login outcome and record a failed execution entry otherwise
* DR-49: The complete-lifecycle full-session is unnumbered and ordered before teardown
  * Source: research Lines 143-161; details Line 514 places the full-session "from an empty RG" in Step 6.4 before Step 6.5 teardown (Line 518); it is the only producer of lab07 evidence for Step 7.1 (Line 526) and needs a new generation or purge after teardown
  * Impact: minor. Remedy: make it a numbered step after Step 6.5 with the generation choice stated

New plan deviations from research: none.

### Validation Round 4 Resolutions

* DR-41 (MAJOR): resolved. Step 5.2 gates run-notebooks-init on ok(probe-scopes) and every notebook, traffic, showback, and checker step on ok(run-notebooks-init); a readiness or probe failure skips all paid lab work (default for clarifying Q1, per research Lines 358-378).
* DR-42 (MAJOR): resolved. Paid steps use live() = !cancelled(); always() is reserved for sanitize and cleanup (default for clarifying Q2).
* DR-43: resolved (budget.json spent totals added to sanitize inputs, Step 2.3).
* DR-44: resolved (only the first sanitize step sets evidence_ready).
* DR-45: resolved (job timeout capped at the 360-minute hosted limit and enforced by contract test).
* DR-46: resolved (Step 6.2 states the expected lock rehearsal result including pending replacement).
* DR-47: resolved (Step 2.4 report-only window validation and unreconciled labelling with tests).
* DR-48: resolved (each notebook step requires its own login step success).
* DR-49: resolved (Step 6.5 now runs teardown then one full-session lifecycle that produces lab07 evidence).

### Validation Round 5 Findings

Status: Passed. No CRITICAL, HIGH, or MAJOR discrepancy remains across plan, details, and log. Accepted residual risks DD-06 and DD-08 not re-raised.

Round 4 verification (details line numbers):

* DR-41: verified. run-notebooks-init gated on ok(probe-scopes) (Line 468); per-notebook login, notebook, traffic, and checker gated on ok(run-notebooks-init) (Lines 469-471, 473); showback on ok(run-notebooks-init) and ok(traffic), or report-only and ok(write-env) (Line 472); readiness-failure behavior stated (Line 478). Readiness, probe-scopes, and init carry implicit success(), so they are skipped after failure or cancellation.
* DR-42: verified. live() = !cancelled() on paid and runtime-login steps (Lines 463, 469-473); always() only on sanitize, cleanup login, cleanup, and post-cleanup sanitize (Lines 474-476). Deploy-path steps use implicit success().
* DR-43: verified (Line 287). DR-44: verified (Line 482). DR-45: verified in Step 5.2 (Line 453). DR-46: verified (Line 510). DR-47: verified (Lines 305, 310). DR-48: verified for notebooks (Line 470). DR-49: verified (Lines 520-523).
* Plan-to-details line references: spot-checked Steps 2.3, 2.4, 5.2, 5.3, 6.2, 6.5, 7.1, 8.3; all match headings.

Minor findings (5; no DR/DD entries added):

* Traffic step at Line 471 does not require ok(login-runtime-traffic), unlike notebooks (Line 470); a failed login yields failed ARM calls, not spend.
* Step 5.4 contract test (Line 493) asserts only "job timeout is at least their sum"; add the 360-minute ceiling stated at Line 453.
* Sanitize (Line 287) does not state that mode-absent or skipped inputs (no verdict.json after readiness failure; deploy-only, report-only) render as `incomplete`/`failed` rather than a sanitizer error that suppresses all evidence.
* Step 5.3 (Line 488) does not state that the environment-`lab` cleanup job is skipped when `lock_test=true`, which Step 6.2 (Line 510) assumes (no approval).
* Step 6.5 heading names a recovery rehearsal, but the body (Lines 522-523) does not name a manual recovery-from-manifest drill (research step 6); teardown execute against the persisted manifest partly covers it.

## Implementation Paths Considered

### Selected: Local-first hardening, then RG-scoped IaC and three manual workflows

* Approach: Fix notebook/shared defects and build fixture-tested scripts before any cloud access; RG-scoped Bicep with admin bootstrap; one workflow-level lock; metrics-only estimated showback; manual image curation
* Rationale: Removes every HIGH/MAJOR design defect before money is spent; smallest workflow surface
* Evidence: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md (Lines 20-29, 358-378)

### IP-01: Per-session system identity with constrained RBAC delegation

* Approach: Deployment identity assigns three roles to the new APIM system identity each session under an ABAC condition on role and principal type
* Trade-offs: No notebook changes; but cannot pin principal ID, so the condition allows any service principal in the tenant for those roles within the RG, and each session waits on principal replication
* Rejection rationale: Conflicts with research requirement not to allow arbitrary principals; per-session admin approval would defeat automation

### IP-02: Subscription-scoped deployment with CI purge

* Approach: Original draft design
* Trade-offs: Whole-RG recreate and automatic name reuse; broad authority
* Rejection rationale: Rejected by adversarial review (P04, P05)

### IP-03: Reusable workflow graph with seven workflows and schedules

* Approach: Original draft design
* Trade-offs: Modular; but nested lock deadlock/cancellation and incomplete contracts
* Rejection rationale: Rejected by adversarial review (A02, A03)

### IP-04: Separate protected jobs per phase with two environments

* Approach: preflight, deploy, run, showback, evidence, cleanup as separate jobs, deploy and runtime identities on different environments
* Trade-offs: Stronger identity separation; but each job needs its own approval, budget and secrets cannot cross jobs, and failure cleanup depends on a human approving at failure time
* Rejection rationale: Reintroduces A01, A04, F4 HIGH risks (DR-06 to DR-08)

## Suggested Follow-On Work

* WI-01: Optional LLM event accounting experiment - privacy canaries, grain and retry characterization (medium)
  * Source: DR-01
  * Dependency: G3 and G6 passed
* WI-02: Automated PNG-only image PR job with provenance checks (low)
  * Source: DR-02
  * Dependency: G7 passed and repository policy approval
* WI-03: APIOps ownership transfer for platform API objects (medium)
  * Source: DR-03
  * Dependency: core loop accepted; LZA publisher version pinned
* WI-04: Enforced session expiry via a separately validated mechanism (medium)
  * Source: DR-04
  * Dependency: G8 passed
* WI-05: Billing-reconciled chargeback using Cost Management exports (medium)
  * Source: research Lines 241-259
  * Dependency: G6 passed
* WI-06: Standard v2 private-network variant (low)
  * Source: research Lines 68-80
  * Dependency: private-networking requirement confirmed
* WI-07: Add LICENSE after owner selects a license (low)
  * Source: DR-05
  * Dependency: owner decision
