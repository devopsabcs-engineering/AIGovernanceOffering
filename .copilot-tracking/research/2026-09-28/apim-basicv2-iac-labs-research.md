<!-- markdownlint-disable-file -->
---
title: APIM Basic v2 lab automation consolidated research
description: Conditional platform design, adversarial finding dispositions, and unexecuted acceptance gates for bounded AI gateway labs.
ms.date: 2026-09-28
---

## Scope and status

Research only. This revision consolidates the primary and three completed adversarial reviews; it makes zero application, notebook, infrastructure, workflow, resource, or repository-setting changes. No live tests, deployments, pricing lookups, or workflow dispatches were performed for this consolidation. All implementation acceptance gates remain OPEN.

Basic v2 is the selected conditional public-endpoint candidate, not a verified end-to-end lab. The first release targets a protected manual session: provision, execute five notebooks, collect bounded synthetic usage, produce estimated showback, and clean up owned resources. Publish only validated sanitized evidence to a bilingual Jekyll site.

The reviews contain 29 overlapping entries: 22 HIGH and 7 MAJOR, with no established CRITICAL finding. Their design defects are dispositioned below through selected controls or blocked extensions. Writing a control does not eliminate the corresponding implementation or live-service risk.

This primary supersedes unsafe recommendations in the six original reports: current-repo-research.md, apim-basicv2-capabilities-research.md, chargeback-traffic-research.md, headless-notebooks-screenshots-research.md, sibling-fsi-lab-pattern-research.md, and apim-lza-apiops-research.md, all under .copilot-tracking/research/subagents/2026-09-28/. Their evidence remains useful; their conflicting snippets are not implementation authority. Their original bodies are preserved with supersession notices added above them; historical line references predate those notices.

Review sources under that same directory are adversarial-platform-review.md (P), adversarial-automation-review.md (A), and adversarial-telemetry-review.md (F). P01-P08 below assign sequential IDs to the eight platform findings; A01-A11 and F1-F10 retain the reviewers' IDs. Old primary line references in those reviews identify the superseded version, not this revision.

## Selected design and boundaries

* Bootstrap one dedicated resource group (RG) administratively; retain the empty RG between sessions. Routine Bicep deployment is RG-scoped.
* Use one Basic v2 unit, one explicitly approved model deployment, Content Safety, Log Analytics, and workspace-based Application Insights. Require public-endpoint approval; select Standard v2 when private networking is required and validate that topology separately.
* Select managed-identity Application Insights ingestion with local authentication disabled. Migrate both platform and notebook logger behavior before use; do not fall back to local authentication.
* Keep LLM message diagnostics OFF on platform and notebook APIs. Use token metrics for the initial showback baseline, with HTTP body capture disabled too.
* Use three entry workflows: credential-free ci, protected manual lab-session, and protected manual teardown/recovery. No schedules or reusable workflow call graph initially.
* Keep notebook-owned demo APIs separate from the three-team platform API. Use one fixed model and nonstreaming traffic without retries for the showback measurement window.
* Produce `Estimated model-token showback (USD retail)`, not billed chargeback. Cost Management and invoices remain authoritative for actual charges.
* Publish sanitized artifacts with manual review and curated images initially. Automatic image PRs, LLM event accounting, a portal workbook, dynamic price ingestion, and APIOps publishing are deferred.

## Source-backed evidence log

The following local anchors were verified in the completed reviews, not re-executed here. Notebook references are visible cell numbers and source-line numbers within each cell; implementation must re-anchor them after edits.

| Evidence | Consequence |
| --- | --- |
| shared/config.py lines 21-22, 135-136, 216, 225, 244, 308, 375 | Root .env loading uses override=False; physical key presence suppresses prompts. Inherited conflicts can override new file values. |
| shared/auth.py lines 19-40; shared/apim.py lines 43-48 and 760 | Cached credential objects are not cached access tokens; ARM and Log Analytics token acquisition have separate audiences. |
| shared/apim.py lines 30-40 | Complete response bodies enter exceptions; sanitize error paths before logging or publishing. |
| shared/apim.py lines 426 and 470 | Logger PUT uses connectionString alone; first-logger discovery can select the wrong owner/destination. |
| shared/apim.py line 521, ensure_api_diagnostic | Existing helper captures request/response messages with 8192-byte limits; platform-only privacy changes are insufficient. |
| notebooks/00-setup-and-validation.ipynb cell 4 | List-form subprocess invocation with shell=True is not portable to Linux; fix before headless acceptance. |
| notebooks/demo3-content-safety.ipynb cell 18 line 15; cell 20 lines 30 and 48-52 | Arbitrary 403 or 200 without [DONE] can become false safety PASS evidence. |
| notebooks/demo4-resilient-pool.ipynb cell 7 line 35; cell 8 line 4; policies/demo4-resilient-pool.xml | Member-only operation templates do not match the forwarded chat-completions suffix. |
| notebooks/demo4-resilient-pool.ipynb cell 10 lines 1-8 | REQUEST_HEADERS prints a subscription key before screenshot redaction. |
| notebooks/demo4-resilient-pool.ipynb cells 16, 18, 20, 25 | Weighted samples/failover permit warnings; East recovery alone is weak proof; cleanup cell is disabled. |
| notebooks/demo1-token-limits.ipynb cell 19; notebooks/demo2-token-metrics.ipynb cell 21 | Existing charts are limited; rerender safe numeric evidence instead of trusting embedded images. |
| tests/test_apim.py line 11; tests/test_notebooks.py | Default ARM version is 2024-06-01-preview; content checks forbid M8-dot, slide, and deck terms on selected application surfaces. |

The original inventory found no .github directory or infrastructure implementation and only docs/ai-governance-flows.svg in docs. Preserve that image path and policies/. Notebooks depend on notebooks/ as their working directory and load ../policies/ paths.

The sibling pattern evidence is recorded in sibling-fsi-lab-pattern-research.md: Jekyll/Just the Docs, main/docs Pages, mirrored fr paths, shared images, and language navigation. The LZA evidence in apim-lza-apiops-research.md identifies BasicV2/StandardV2, system identity, apimlogger, and APIOps v6.0.2 ownership. Adopt useful conventions, not unsafe credentials or teardown examples.

Official evidence captured by the reviews on 2026-09-28 supports the following decisions; time-sensitive availability must be checked again before authorization.

* [Token limits](https://learn.microsoft.com/azure/api-management/llm-token-limit-policy), [token metrics](https://learn.microsoft.com/azure/api-management/llm-emit-token-metric-policy), [Content Safety](https://learn.microsoft.com/azure/api-management/llm-content-safety-policy), and [backends](https://learn.microsoft.com/azure/api-management/backends) support policy eligibility, not demonstrated runtime success or exact distributed breaker behavior.
* [Tier comparison](https://learn.microsoft.com/azure/api-management/api-management-features) distinguishes Basic v2 public connectivity from Standard v2 private-network options.
* [Diagnostic schema](https://learn.microsoft.com/azure/templates/microsoft.apimanagement/2024-06-01-preview/service/apis/diagnostics) allows only all for LLM messages; [the newer schema](https://learn.microsoft.com/azure/templates/microsoft.apimanagement/2025-09-01-preview/service/apis/diagnostics) does not establish a no-message enum either.
* [Application Insights integration](https://learn.microsoft.com/azure/api-management/api-management-howto-app-insights) defines managed-identity ingestion, metrics enablement, and dimension opt-in requirements.
* [Retirement schedule](https://learn.microsoft.com/azure/foundry/openai/concepts/model-retirement-schedule), [lifecycle policy](https://learn.microsoft.com/azure/foundry/openai/concepts/model-retirements), [deployment types](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/deployment-types), and [quota guidance](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/quota) separate availability, eligibility, residency, quota, and capacity.
* [Conditional RBAC delegation](https://learn.microsoft.com/azure/role-based-access-control/delegate-role-assignments-examples) and [GitHub Azure OIDC](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure) require explicit scope, principal, and trust-boundary decisions.
* [Concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency), [reusable workflows](https://docs.github.com/en/actions/reference/reusable-workflows-reference), and [status functions](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#status-check-functions) establish lock, runner, permission, and failure-path constraints.
* [APIM soft delete](https://learn.microsoft.com/azure/api-management/soft-delete), [Foundry purge](https://learn.microsoft.com/azure/ai-services/recover-purge-resources), and [workspace deletion](https://learn.microsoft.com/azure/azure-monitor/logs/delete-workspace) distinguish ordinary deletion, recoverability, name reuse, and irreversible purge.
* [AppMetrics](https://learn.microsoft.com/azure/azure-monitor/reference/tables/appmetrics), [LLM event schema](https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewayllmlog), and [gateway schema](https://learn.microsoft.com/azure/azure-monitor/reference/tables/apimanagementgatewaylogs) do not justify correlation-only accounting or duplicate metric summation.
* [Cost guidance](https://learn.microsoft.com/azure/foundry/concepts/manage-costs), [retail prices](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices), and [prompt caching](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/prompt-caching) require qualified prices, units, exclusions, and billing reconciliation.
* [GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use), [workflow triggering](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-when-your-workflow-runs/triggering-a-workflow), and [Pages publishing](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) govern artifact trust, token-event behavior, and publication actors.

## Platform and paid-provisioning preconditions

Record an approved tuple before any paid provisioning: model name, exact version, deployment SKU, pricing region, resource locations, capacity units, quota allocation, subscription eligibility, and retirement/revalidation date. No default deprecated mini-model, GlobalStandard SKU, hardcoded 50 K TPM, or silent model/region substitution is selected.

The reviews found gpt-4o-mini 2024-07-18 and gpt-4.1-mini 2025-04-14 listed as deprecated, not already retired. Eligibility can depend on whether that subscription previously deployed the version. A public region matrix does not establish eligibility or reserve capacity. Validate the selected replacement's request parameters, API style, token policies, and pricing before approving it.

Canadian resource placement does not approve global inference processing. Default allowGlobalProcessing=false; a Canada-only requirement rejects global deployment types. Validate the approved geography guarantee rather than promising narrower region-only processing. Assess Content Safety/Prompt Shields processing and telemetry storage locations separately. Use synthetic prompts only.

G1 requires provider registration, supported API versions, Basic v2 location availability, quota/capacity, public endpoint reachability, and schema validation before mutation. ARM success is followed by bounded readiness checks for gateway, inference, safety, ingestion, and queries. Provider registration is not model capacity evidence.

Pin CLI/Bicep and resource API versions during implementation. The existing default 2024-06-01-preview and diagnostic helper's 2025-09-01-preview are evidence to reconcile, not permission to mix contracts blindly. Compile and validate every template and parameter file, review RG-scoped what-if, and verify effective readback. A suppressed type warning is not schema or runtime proof.

No executable Bicep, policy, KQL, or workflow skeleton is retained here: the former examples encoded unresolved contracts. Generate those only during authorized implementation with schema-specific validation. The mock pool does not prove live multi-region resilience or provisioned-throughput (PTU) behavior.

## Identity and ownership contract

One-time bootstrap requires separately authorized Entra application-registration rights, Azure RBAC-assignment rights, provider registration where needed, and GitHub environment administration. It creates the dedicated RG and records its full identity. Routine identities do not create/delete arbitrary RGs or receive subscription Contributor/Owner.

Privileged jobs use protected environment-only OIDC trust. Verify actual subject and audience metadata for this repository, including immutable subject formats when applicable; do not print the JWT. Restrict approved refs and reviewers in environment rules. No additional branch-subject trust may bypass environment approval. Untrusted PR CI receives no Azure identity.

| Principal | Authority and scope | Assignment owner |
| --- | --- | --- |
| Bootstrap administrator | Dedicated RG creation, initial identities, trust, runtime grants, constrained delegation | Authorized human/bootstrap process |
| Deployment identity | RG Contributor plus narrowly constrained role-assignment authority for the APIM identity's three grants | Bootstrap administrator |
| Runtime identity | API Management Service Contributor on the lab APIM; scoped telemetry-query role on the chosen component/workspace | Bootstrap administrator, not the three-role deployment condition |
| APIM system identity | OpenAI User on model account; Cognitive Services User on safety account; Monitoring Metrics Publisher on App Insights | Deployment identity within approved conditions |
| Recovery identity | Exact owned-resource deletion using lab RG authority; no irreversible purge by default | Protected recovery entry |
| Purge operator | Separate, approved deleted-resource permissions limited to required providers and inventoried targets | Administrator-approved operator boundary |

APIM role IDs: OpenAI User 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd; Cognitive Services User a97b65f3-24c7-4388-baec-2e87135dc908; Monitoring Metrics Publisher 3913510d-42f4-4e42-8a64-420c390055eb. The publisher grant is used by the selected MI ingestion design, not granted for unspecified future use.

Contributor does not grant RBAC assignment authority or establish telemetry data-query access. Grant runtime/query permissions explicitly during bootstrap, including narrowly required configuration-read operations. Test negative access as well as successful calls. Never broaden a role to work around propagation delays; use bounded retries and report the missing action/scope.

Delegation conditions must constrain principal, role, target scope, write, and delete. New APIM system identities have new principal IDs. Use a staged creation/RBAC boundary: after APIM identity creation or recreation, bootstrap updates and approves conditions before delegated assignments execute. Do not temporarily allow arbitrary principals. Assignment names incorporate scope, principal, and role.

Recreated APIM/component/workspace resources also require explicit runtime-role verification or reapplication by bootstrap, even if names are unchanged. Verify stale assignments are removed only within the approved ownership set. Identity recreation is a documented administrative boundary, not assumed automatic Contributor behavior.

Platform owner IDs include ai-gateway-api, ai-gateway-foundry, and apimlogger. Notebook owners retain their existing demo IDs, including demo2-application-insights. Diagnostics use explicit full logger IDs and destination resource IDs; eliminate first-logger discovery. Notebook setup, rerun, and cleanup must not overwrite platform objects.

## Metrics and privacy contract

Select connection string plus the documented managed-identity logger credential and Monitoring Metrics Publisher grant, with Application Insights local authentication disabled. shared/apim.py logger PUT behavior and Demo 2 must be changed compatibly before this is runnable. A connection string alone or a role alone is insufficient. An incompatible logger must fail visibly, not enable local auth.

LLM message diagnostics remain OFF across service/platform and all notebook APIs. Remove the helper's message-capture defaults and verify reruns cannot restore them. HTTP body.bytes=0 is an additional HTTP setting, not proof that LLM capture is off. The schema's only message option is all; the former none value is invalid. There is no automatic fallback to capturing all messages.

Do not enable GatewayLlmLogs in the baseline. An experiment enabling LLM logs while omitting message blocks is deferred until explicit privacy approval and live proof of both usage availability and no body capture. Projection that hides a captured body is not a privacy control. Configure headers/errors conservatively so credentials and prompts do not enter other telemetry either.

Require effective metrics:true and custom-metric dimensions opt-in on the selected destination. Check redacted configuration before and after notebook configure, rerun, and cleanup, then verify ingestion. API diagnostics can override service diagnostics; coexistence alone does not prove duplicate emission. Inspect effective policy inheritance for exactly one metric emitter per intended request.

After authorized deployment, use unique synthetic prompt/completion canaries and confirm absence from all relevant telemetry and exported evidence after bounded ingestion settling. Check both platform and notebook APIs. Missing telemetry is not proof of privacy: first establish that permitted metrics are arriving. Until these checks pass, G3 is OPEN and public evidence is blocked.

## Workflow lifecycle and mode semantics

The initial entries are .github/workflows/ci.yml, .github/workflows/lab-session.yml, and .github/workflows/teardown.yml. These are proposed surfaces, not existing workflows. CI runs local tests, workflow lint/contract checks, Bicep compilation, and matching Jekyll build/crawl without cloud credentials.

Both cloud entry workflows acquire the same WORKFLOW-LEVEL environment lock. lab-session holds it across deploy, run, collect, and cleanup, including failure paths; teardown/recovery acquires it at entry only. Ordinary jobs/steps never reacquire it. No nested workflow_call, per-phase locks, per-branch locks for the same environment, or cron are selected.

Set cancel-in-progress=false, but do not claim FIFO or durable queuing: default pending replacement can discard a waiting request. Test two harmless sessions and one teardown concurrently before cloud execution. No second mutation may interleave inside an active session, and no caller may cancel itself.

Each job has a fresh runner and explicit identity/permissions. Reconstruct configuration and fetch required secrets locally; never transfer .env or Azure credential caches through outputs/artifacts. Pass only validated nonsecret manifest identifiers. Renderer and CI jobs have neither Azure access nor repository-write access.

| lab-session mode | Authorization and preservation/deletion behavior |
| --- | --- |
| full-session | keep_environment=false by default; approval explicitly authorizes deletion of this generation's owned resources after success or failure. Reject pre-existing environments; use run-existing instead. keep_environment=true preserves resources and reports continuing exposure. |
| deploy-only | No traffic. Successful deployment is intentionally retained and reported; advance approval authorizes cleanup of this attempt's newly created resources on failure. Refuse unapproved pre-existing targets. |
| run-existing | Validate an existing owned manifest and approve finite traffic/child-object mutations. Preserve the environment on success or failure; deletion requires a separate explicit teardown approval. |
| report-only | Read-only telemetry/evidence collection. Preserve all resources even if reporting fails; no inferred cleanup authority. |
| teardown/recovery entry | execute=false and purge=false independently by default. Typed target confirmation plus manifest/ownership validation precede ordinary deletion; purge requires the separate operator approval. |

Mode-specific permissions and guards must enforce these distinctions. A report failure never licenses deletion of a pre-existing environment. A keep_environment flag is not a substitute for validating the target and its creation provenance.

Use an explicit always/status function for cleanup, combined with validated target, advance deletion authorization, applicable mode, and mutation-attempt guards. Do not require successful deployment outputs. Give cleanup fresh authentication and its own deadline; preserve the original failed verdict even when cleanup succeeds. Sanitized failure diagnostics may be collected without implying successful lab completion.

Runner loss, force-cancellation, or a cleanup job that never starts cannot be solved by always(). Name a manual recovery owner and make the durable inventory available independently of the runner. Four-hour expiry is metadata until an independently validated enforcement mechanism exists; no automatic cleanup guarantee or schedule is implied.

## Durable inventory and recovery

Persist a nonsecret expected-target manifest BEFORE first mutation. Storage must survive runner loss, be access-controlled, retain provenance/integrity, and be retrievable for manual recovery; fail before mutation if persistence fails. It is an internal recovery record, not public evidence, and must pass its allowlist/secret checks before persistence.

Record exact tenant/subscription/full RG/resource IDs, provider types, names, locations, ownership generation, source revision, workflow run/attempt, deployment name/scope, expected child IDs, and approved mode. Capture baseline live resources and matching tombstones. Enrich with observed identities/states after each attempt; missing deployment-success outputs must not erase intended targets.

Use stable generation naming derived from approved environment identity. Reuse only after checking live resources and tombstones. A name collision stops the session; a new generation needs approval after residual live-resource review, not automatic random renaming that strands paid resources. Tags corroborate ownership but do not replace exact IDs and provenance.

Refuse tenant/subscription/RG mismatches, unexpected resources, unapproved existing instances, ambiguous ownership, and locks. Never remove locks automatically. Dry-run lists exact planned targets and distinguishes active resources from recoverable tombstones. Refusal is safer than broad enumeration followed by deletion.

Delete model deployments before their accounts to release quota and avoid provisioned-capacity exposure where applicable. Process the remaining owned resources in dependency order; retain the empty RG by default. Do not force permanent Log Analytics deletion or delete the whole RG as an ordinary cost-control shortcut.

Process independent cleanup targets even if one fails, record errors, and use bounded polling/retry for each state transition. Confirmed 404 can mean absent; 403, discovery failure, timeout, or missing permission cannot. Re-run from persisted inventory when the RG/account is already absent. Preserve the original session failure and return non-success when active residuals or required deletions remain unresolved.

Purge is irreversible and separate from ordinary deletion. The dedicated operator handles exact approved APIM/Cognitive Services/workspace tombstones with provider-specific scope and confirmation. Do not perform subscription-wide purge. Name reuse is a live acceptance gate, not an assumed reason to purge every session or a mandatory cost-saving step.

Reviewed documentation lists APIM and Cognitive Services 48-hour recoverability and workspace 14-day recovery; APIM documentation applies to all tiers. Validate Basic v2 same-subscription delete/name-reuse behavior, and do not confuse backup/restore support with soft delete. Cross-subscription reuse has separate constraints.

Final recovery output lists active residual resources, tombstones, failed actions, quota-release status, known or unknown continuing charge exposure, and the named next operator. No claim of zero spend follows merely from absent RG output or requested deletion. Resource duration and provider state determine remaining exposure.

## Headless configuration and authentication

Read outputs from the exact RG-scoped deployment name in the approved manifest. The former subscription-deployment reader is withdrawn. Map AZURE_RESOURCE_GROUP output to APIM_RESOURCE_GROUP consumed by shared/config.py; validate tenant/subscription and resource IDs against the manifest before notebook mutation.

Write a complete private root .env, preserving required empty key lines. Required physical keys include the following inventory; this is not a deployable configuration or a secret-bearing example.

```text
AZURE_SUBSCRIPTION_ID, APIM_RESOURCE_GROUP, APIM_NAME
AOAI_ENDPOINT, AOAI_DEPLOYMENT, AOAI_KEY, AOAI_API_STYLE
APP_INSIGHTS_NAME, APP_INSIGHTS_RESOURCE_ID, APP_INSIGHTS_CONNECTION_STRING
CONTENT_SAFETY_ENDPOINT, CONTENT_SAFETY_KEY, CONTENT_SAFETY_BLOCKLIST_ID
CONTENT_SAFETY_THRESHOLD_HATE, CONTENT_SAFETY_THRESHOLD_SELFHARM
CONTENT_SAFETY_THRESHOLD_SEXUAL, CONTENT_SAFETY_THRESHOLD_VIOLENCE
DEMO4_PTU_EAST_ENDPOINT, DEMO4_PTU_CENTRAL_ENDPOINT, DEMO4_PAYG_ENDPOINT
DEMO4_PTU_EAST_DEPLOYMENT, DEMO4_PTU_CENTRAL_DEPLOYMENT, DEMO4_PAYG_DEPLOYMENT
DEMO_RUN
```

Fetch the real connection string into private configuration; never persist a masking placeholder as its value. Empty optional Demo 4 endpoint/deployment keys can fall back to AOAI values and therefore do not demonstrate multiple regions. Validate chosen API paths against real endpoint readback, not a guessed hostname alone.

Reject conflicting inherited configuration because override=False would otherwise win over the file. DEMO_RUN remains file-owned across quota resets and subsequent kernels; never export an old inherited value over it. Test with stdin disabled and fail before mutation if any prompt would be required. Keep .env out of logs, caches, summaries, and artifacts.

Execute papermill with notebooks/ as cwd. Fix setup cell 4's Linux subprocess behavior first. Use explicit azure/login action boundaries before deployment, each bounded notebook phase, reporting, and cleanup. Acquire the Log Analytics audience immediately after fresh login before Demo 2 and reporting; do not describe a comment inside a shell loop as a login action.

The short GitHub OIDC assertion lifetime is distinct from Azure access-token lifetime. AzureCliCredential object reuse does not promise token caching; ARM access can remain valid while an uncached Logs audience acquisition fails. Bound phases against actual expiry metadata, refresh at phase boundaries, and never print tokens or invent a per-request token cache.

## Notebook completion and semantic evidence

Require exactly the following five outputs in a clean directory for the current run/attempt. Persist source revision/hash, approved configuration identity, tool exit status, and completion metadata for every required nonempty code cell. Execution_count or a PASS substring is not completion proof.

```text
00-setup-and-validation.ipynb
demo1-token-limits.ipynb
demo2-token-metrics.ipynb
demo3-content-safety.ipynb
demo4-resilient-pool.ipynb
```

Reject missing, extra, stale, renamed, failed, skipped, or partial required notebooks, including a traceback after an earlier PASS banner. Maintain an explicit source-matched set of required cells/objectives so inserted markdown does not silently shift assertions. Disabled optional teardown cells are recorded as intentionally excluded, never counted as completed cleanup.

No entire Demo 2 preflight-cell exemption is allowed. Permit only the precisely named expected initial logger/diagnostic absence, and require post-configuration logger, diagnostic, identity, dimensions, and ingestion checks. Other failures in that cell remain failures. Diagnostic-only output from a failed run cannot become successful lab imagery.

* Setup must establish the approved resource identities, endpoint reachability, and authentication behavior without exposing credentials.
* Demo 1 must establish normal calls, policy-specific rate-limit and quota outcomes, and reset behavior within the authorized session envelope. A backend 429 is not gateway-limit proof; quota 403 is not safety proof.
* Demo 2 must reconcile observed prompt/completion metrics against bounded response usage and preserve platform logger ownership and privacy settings.
* Demo 3 must distinguish transport/protocol error, confirmed policy block, not-tripped, and inconclusive. A required inconclusive objective prevents an all-labs-success claim.
* Demo 4 must establish fault, alternate routing, and subsequent recovery; a healthy East response without the preceding evidence is insufficient.

For Demo 3 streaming, validate HTTP status, content type, and parsed SSE events. Missing [DONE] alone does not identify a safety interruption. Require correlated policy-specific evidence without body logging; if unavailable under the privacy baseline, keep that objective inconclusive. An unrelated authorization 403 also fails the safety claim. Existing mild fixtures are not promised deterministic model/safety triggers.

Test empty 200, HTML 200, malformed SSE, truncated valid SSE, complete safe SSE, unrelated 403, and confirmed safety interruption using synthetic fixtures. Do not weaken the privacy baseline or invent harmful fixtures to manufacture a passing demonstration.

For Demo 4, retain operation IDs and test the candidate /{member}/* templates for v1 and classic paths on the actual gateway. Verify subscription-protected mock credential precedence, and verify real-mode backend readback removes mock credentials instead of assuming credentials=None clears them. Never make the mock anonymous to solve routing.

Require named healthy primary responses, observed fault statuses, successful Central then PAYG routing in the relevant phases, and recovery after those faults. Reject unknown/missing x-served-by and unexpected statuses in every phase. Accept approximate weights, not an exact 2:1 distribution or inferred distributed breaker state. A failure to trip is not a warning compatible with complete success.

## Team attribution and estimated showback

Use a platform-owned ai-gateway-api separate from demo1..4. Initial teams are team-retail, team-finance, and team-hr with approved product-scoped subscriptions. Derive team from authenticated subscription mapping; do not accept a caller's team header. Retrieve subscription keys privately and mask them before any possible output.

Normalize x-client-app at the gateway against a small per-team allowlist, with a single bounded unknown label. App labels remain caller assertions, not authenticated app identity. Keep prompts, users, arbitrary headers, and run IDs out of metric dimensions. Account for automatic dimensions and the documented five-custom-dimension, 100-values-per-dimension, and 1000-active-series limits.

Product quotas are not universal: API-scoped, all-APIs, and built-in all-access subscriptions can bypass product policies. Restrict the supported team path and test/document privileged-key bypass. If broader enforcement is required, implement it at the appropriate API/service scope with trusted mapping and no double counting. Review effective base inheritance and policy order for one emitter and one intended counter application.

Strip client subscription credentials before forwarding to real inference backends. Keep distinct mock-backend authentication intact. Classify gateway throttling, quota rejection, backend throttling, and safety rejection through provenance, not status alone; HTTP failure does not prove no billable backend work.

Use one pinned nonstreaming model, no client/gateway retries, and a small response-usage manifest for the baseline showback window. Record normalized component/APIM/API/revision/deployment IDs, source revision/run-attempt, request identifiers, prompt/completion usage, and a fixed half-open UTC interval. Model identity comes from deployment configuration, not a regex over an alias.

An environment workflow lock does not block human traffic. Reserve exclusive measurement windows for the platform API, control access/keys during measurement, and corroborate exclusivity with an approved request manifest or privacy-safe request audit. Reject contaminated or overlapping windows, including unaccounted human calls. No exclusivity proof means no accepted complete total.

Allow the actual metric bucket width and delayed delivery to determine window boundaries and quiet margins; include only complete exclusive buckets. Preaggregated buckets cannot be split into exact per-run totals. Requests spanning boundaries must be included in a validated complete window or make the result incomplete. Exact concurrent per-run allocation is deferred.

Choose ONE representation: component customMetrics summed by valueSum, or workspace AppMetrics summed by Sum and scoped to the component. Never add both, multiply Sum by ItemCount, sum total plus prompt plus completion, count metric rows as requests, or apply event sampling weights to metrics. Do not deduplicate identical aggregate rows without evidence.

Pin observed metric names and dimension names/casing after a live sample. Scope queries by component, observed namespace, API/revision mapping where available, approved teams/apps, and the fixed window. Do not invent dimensions absent from emitted data. Reconcile prompt/completion sums against the response manifest with an explicit tolerance and bounded polling deadline. Incomplete or missing telemetry is not zero usage.

Every accepted chart, table, and summary carries `Estimated model-token showback (USD retail)`, the UTC interval, price snapshot identity, coverage state, and exclusions. Persist unattributed/unpriced/failed/ambiguous counts. Suppress any complete-cost claim when usage, attribution, or price coverage is incomplete; known partial values may be labeled partial only.

## Prices and whole-session workload envelope

Price identity includes resource/deployment mapping, exact model/version, deployment SKU, pricing region, currency, effective period, meter identity, and rate unit. Record source and retrieval date. Require exactly one applicable rate for each input/output category; unknown, missing, duplicate, or ambiguous prices suppress complete totals. Do not convert null cost to zero or drop unpriced usage.

Initial pricing is an explicitly uncached retail-rate approximation. Cache discounts are excluded, not assumed absent. If cached usage is later reliably observed and priced, subtract cached tokens from the prompt-token subset before applying uncached rates, then price cached input and completion once. Do not add cached input on top of all prompt tokens. Per-million and per-thousand units must be tested explicitly.

Shared APIM, logging, Content Safety, networking, taxes, and contract adjustments are excluded from model-token allocation. Pay-as-you-go token formulas do not price provisioned throughput. Cost Management/invoice reconciliation is mandatory before any financially authoritative chargeback extension.

Proposed generator defaults are one worker, 30 attempted HTTP calls, 128 maximum output tokens, 10,000 conservatively reserved input-plus-maximum-output tokens, five minutes, and no retries. These are design defaults, not measured success requirements or hard Azure bill caps. Lower policy thresholds may be needed for intentional throttling within the envelope.

One shared dispatch guard reserves conservative input plus maximum output and estimated spend BEFORE each inference/safety attempt, counts all attempted calls, and applies attempt/time/token limits to ordinary calls, bursts, retries, and ambiguous failures. Unknown usage is not free and does not refund a reservation. Reject unbounded prompts, unknown prices, or insufficient reservations before dispatch; stop and report ambiguous usage.

The generator cap alone is insufficient. BEFORE authorizing a full session, inventory every existing notebook loop, stream, safety call, fault phase, and client/gateway retry and establish a finite approved session-wide attempt/token/spend/time envelope. Enforce it through shared request dispatch and reviewed gateway retry limits across all kernels/jobs; preserve counters in the session manifest and fail closed on missing state.

No numeric whole-session budget is claimed proven here. G6 blocks paid runs until that inventory and tested envelope exist. Model-bound paths must support the approved output cap. Demonstrations cannot bypass the guard; if an objective cannot fit, request a revised finite budget or mark it unverified. Metadata/cleanup management calls get separate bounded deadlines so exhausting inference budget does not prevent cleanup.

Notebook retries, if an approved objective needs them, reserve and count every potential backend attempt within that same session envelope; the baseline showback window still has none. APIM token limits may overshoot under concurrency; TPM quota and Azure budget alerts are not spending ceilings. Schedules remain disabled.

The platform review captured illustrative public pricing of $150.01/month for the first Basic v2 unit and $700/month for Standard v2, not a current Canadian offer quote. Do not reuse the former $5-7/day total guarantee. A fresh estimate needs region, offer, currency, unit count, billable lifetime, token/cache assumptions, telemetry and safety volume, and residual-resource exposure.

## Deferred event accounting

The former CorrelationId-only log join is withdrawn, not repaired by a warning. Event accounting remains blocked behind explicit privacy approval and grain/retry tests. Enabling logs with omitted message blocks is not evidence that bodies stay absent or that token rows exist.

If later authorized, retain _ResourceId, CorrelationId, RequestId, SequenceNumber, deployment/model, timestamps, and usage fields. Distinguish frontend request, backend attempt, message fragment, and usage observation. Require unique resource-plus-correlation attribution before a many-to-one join and quarantine conflicts.

Never use arbitrary arg_max, distinct, or maximum token counts as an accounting repair. Test two-by-two join fan-out, repeated telemetry, distinct retries, fragments, and failure after backend work. Preserve distinct billable attempts, report request and attempt counts separately, and label incomplete coverage. This extension does not block the metrics-only baseline, but it cannot be used to claim exact concurrent allocation yet.

## Evidence publication and image trust

Prevent secret output at source, beginning with Demo 4 cell 10 and response-body exceptions. Dynamically register secrets for masking before logs can contain them. Masking is defense in depth, not artifact sanitization; disabling log-output alone is insufficient. Remove secret-bearing headers from displayed request objects.

Never upload raw executed ipynb, HTML, .env, credential caches, error dumps, or notebook image outputs. Keep necessary raw outputs runner-local and short-lived. Public evidence is newly constructed from an allowlisted structured result schema, with known-value and credential-pattern scans before summaries, rendering, or upload. Internal recovery manifests use their own nonsecret allowlist and access controls.

Test fake keys of multiple shapes, bearer tokens, and connection strings across stdout, exceptions, HTML, metadata, and images. Include fake secrets drawn into raster images: reject raw image sources and rerender charts from approved numeric evidence instead of trusting text redaction or OCR. Sanitizer failure prevents all evidence uploads and summaries; only a fixed nonsecret failure status is permitted.

Render on a separate fresh runner with no Azure identity, no repository-write permission, no external requests, and no execution of untrusted notebook scripts/HTML. Consume only provenance-validated sanitized data from the expected run/revision. Pin dependencies/actions and apply path/symlink checks before reading artifacts. Renderer errors must not dump untrusted payloads.

Initially, humans review sanitized artifacts and curate PNGs for documentation. Defer automatic image PRs. Any later approved publisher is a separate no-cloud job with minimal contents/pull-requests write permissions, allowed repository policy, exact trusted-run provenance, docs/assets/images path allowlisting, PNG decoding/type checks, symlink/traversal rejection, and human review.

Do not run untrusted PR code with cloud/write credentials or trust workflow_run artifacts by filename alone. Ordinary GITHUB_TOKEN-generated pushes do not trigger downstream builds; current PR opened/synchronize/reopened behavior has approval-required exceptions. Avoid the outdated blanket claim that token-created PRs never trigger CI, and do not introduce a PAT merely to bypass this boundary.

## Bilingual site and canonical page map

Use the sibling's Jekyll/Just the Docs pattern with main/docs branch Pages and human-merged changes initially. Confirm repository visibility, Pages availability, approved publishing source, and intended URL before any settings mutation. No Pages settings are changed by this research.

One authoritative manifest maps pages and shared images. EN and FR use matching slugs with paired /labs/ and /fr/labs/ permalinks; render translated French titles, alt text, and the same technical caveats during implementation. The chargeback slug remains stable, but its title must say estimated showback, never billed chargeback.

| Canonical slug | EN topic/title | Shared image prefix | Evidence owner |
| --- | --- | --- | --- |
| lab-00-environment | Deploy the lab environment | lab00-environment | Session deployment |
| lab-01-setup-validation | Setup and validation | lab01-setup | Setup notebook |
| lab-02-token-limits | Token limits and quotas | lab02-token-limits | Demo 1 |
| lab-03-token-metrics | Token metrics | lab03-token-metrics | Demo 2 |
| lab-04-content-safety | Content safety | lab04-content-safety | Demo 3 |
| lab-05-resilient-pool | Mock resilient backend pool | lab05-resilient-pool | Demo 4 |
| lab-06-chargeback | Estimated model-token showback | lab06-showback | Bounded traffic/report |
| lab-07-teardown | Teardown and residual cost exposure | lab07-teardown | Recovery inventory |

Use baseurl-aware image, switcher, hub, next/previous, and anchor links under /AIGovernanceOffering/. README repository links remain distinct from site URLs. Preserve docs/ai-governance-flows.svg. Keep the sibling section order: overview, objectives, exercises/expected results, validation checklist, knowledge check, next steps.

Credential-free CI builds with matching github-pages/Jekyll dependencies and crawls rendered EN/FR output. Check switchers both ways, images, anchors, duplicate permalinks, old sibling baseurls, mobile/desktop navigation, and actual alert rendering. Callouts configuration alone is not proof that GitHub alert syntax renders correctly.

Verify one maintainer-merged image update reaches Pages. Document token-push suppression; do not assume a bot push/merge republishes. A future explicit Pages workflow is an approved alternative, not an initial fourth workflow. Do not publish placeholder success images for OPEN or inconclusive objectives.

## Small implementation surfaces and APIOps boundary

Proposed changes are grouped by responsibility rather than a new framework. Reuse existing tests and helpers; exact new filenames below are implementation targets, not created files.

* infra/main.bicep and parameters: RG-scoped platform resources, approved model tuple, stable generation/ownership outputs, explicit MI loggers and diagnostics. Split modules only where resource responsibility warrants it.
* scripts/setup-github-oidc.ps1 and scripts/lab_session.py: administrative bootstrap contract, phase dispatch, manifest/configuration, shared budget state, and resumable cleanup. Keep bootstrap separate from runtime authority.
* scripts/check_notebook_outputs.py and scripts/render_evidence.py: exact notebook/objective validation, sanitization, and safe rendering. Use small structured contracts, not PASS-text scraping.
* scripts/generate_traffic.py and scripts/showback_report.py: bounded team traffic, fixed-window metrics reconciliation, and versioned price coverage; reuse the session guard rather than duplicating it.
* shared/apim.py, shared/config.py, shared/auth.py, and the five notebooks: only compatible logger/privacy, headless configuration/authentication, budget dispatch, assertion, and routing changes supported by tests.
* tests/test_apim.py, tests/test_config.py, tests/test_notebooks.py plus a focused automation test surface if needed: extend existing fixtures for privacy, ownership, provenance, and failure cases.
* The three workflow entries and docs/ Jekyll EN/FR pages share canonical manifests; add pinned CI dependencies only when required. Preserve policies/ and the README-linked image.

Adopt stable lowercase platform IDs and useful LZA parameters such as environmentName, instanceNumber, publisherEmail, publisherName, sku, and skuCount. Existing notebook policy files remain in policies/. Add platform policy content there with distinct ownership initially; avoid a second competing policy tree solely to resemble APIOps.

Later APIOps adoption requires explicit ownership transfer of platform child objects from Bicep to the publisher, with import/readback and a no-dual-writer test. Notebook-owned teaching objects stay separate. Do not copy the entire LZA, client-secret patterns, committed credentials, or unneeded Key Vault/workbook resources now.

## Disposition of all adversarial entries

R01-R15 group overlapping root causes. Selected controls resolve contradictory research recommendations; every mapped implementation gate remains OPEN. No row claims runtime remediation completed.

| Entry | Severity | Root | Disposition in this design | Gate |
| --- | --- | --- | --- | --- |
| P01 | HIGH | R05 privacy | Unsupported message enum removed; platform/notebook LLM diagnostics OFF | G3 |
| P02 | HIGH | R02 model/residency | Explicit lifecycle, eligibility, quota/capacity and model tuple before paid deployment | G1 |
| P03 | HIGH | R02 model/residency | No default global processing; separate inference/safety/storage approval | G1 |
| P04 | HIGH | R03 identity | RG boundary, environment-only actual claims, constrained grants and recreation bootstrap | G2 |
| P05 | HIGH | R07 recovery | Exact durable inventory, unrelated-resource refusal, separate purge operator | G8 |
| P06 | MAJOR | R01 platform claims | Conditional Basic v2; policy support is not executed success; dimensions/readback gated | G1, G3, G5 |
| P07 | MAJOR | R12 accounting | Estimated showback; no correlation-only join or financial-source claim | G6 |
| P08 | MAJOR | R15 budgets | Finite generator and session envelopes; no schedules or daily cost guarantee | G6, G8 |
| A01 | HIGH | R10 publishing | Source leak prevention, structured sanitizer, fake-secret/image tests, no raw uploads | G7 |
| A02 | HIGH | R06 workflow locks | One workflow-level session lock, no nested acquisition, pending replacement documented | G4 |
| A03 | HIGH | R06 workflow contracts | Three entries with ordinary jobs; explicit modes, fresh runners and nonsecret manifests | G4 |
| A04 | HIGH | R07 recovery | Pre-mutation manifest, guarded always cleanup, independent errors, manual recovery | G8 |
| A05 | HIGH | R08 execution contract | Exact five files, revision/hash/attempt, code-cell completion and semantic outcomes | G4, G5 |
| A06 | HIGH | R09 objective proof | SSE and policy-specific causation; arbitrary 403/missing DONE cannot pass | G5 |
| A07 | HIGH | R09 objective proof | Wildcard/credential live gate; fault then Central/PAYG then recovery; unknowns fail | G5 |
| A08 | MAJOR | R08 execution contract | Real login boundaries, fresh Logs audience, assertion/access distinction | G4 |
| A09 | MAJOR | R08 execution contract | Exact RG output scope/mapping, physical .env keys, conflict rejection, file-owned DEMO_RUN | G4 |
| A10 | HIGH | R10 publishing | Image PRs deferred; later isolated no-cloud least-privilege publisher | G7 |
| A11 | MAJOR | R11 site contract | Canonical lab00-07 map, paired languages, matching build/crawl and publishing actor | G9 |
| F1 | HIGH | R05 privacy | Fix helper body capture too; no fallback to all; canaries and effective readback | G3 |
| F2 | HIGH | R12 accounting | Event extension blocked on grain/retry/cardinality proof; no arbitrary deduplication | G6 |
| F3 | HIGH | R12 accounting | Retail estimate labels/exclusions; Cost Management/invoices authoritative | G6 |
| F4 | HIGH | R15 budgets | One reservation/attempt guard includes bursts/retries/unknowns and notebook envelope | G6 |
| F5 | HIGH | R13 metric isolation | Fixed exclusive complete buckets, human-traffic controls, overlap rejection | G6 |
| F6 | HIGH | R12 accounting | Exact unique rate identity/units/period; partial coverage blocks complete totals | G6 |
| F7 | HIGH | R13 metric isolation | One representation/emitter, bounded gateway labels, observed dimension mapping | G3, G6 |
| F8 | HIGH | R14 policy scope | Test product/API/all-access/anonymous paths, inherited counters, real-backend key stripping | G5, G6 |
| F9 | HIGH | R04 logger ownership | MI-only selected for both owners; explicit IDs and compatible helper/Demo 2 changes | G2, G3 |
| F10 | MAJOR | R03 identity | Bootstrap owns runtime/query grants; three-role delegation is not optional-role authority | G2 |

## Acceptance gates and implementation order

| Gate | Required discriminating evidence | State |
| --- | --- | --- |
| G1 platform | Approved model/version/SKU/residency/capacity; pinned schema compile/what-if; readiness and public/private topology checks | OPEN |
| G2 identity | Actual OIDC claims/environment approval; denied out-of-scope principal/role/write/delete; identity recreation and runtime/query grant tests | OPEN |
| G3 privacy/metrics | MI logger ingestion with local auth disabled; incompatible credentials fail; effective dimensions/privacy before/after notebooks; canary absence with working metrics | OPEN |
| G4 workflows/config | Harmless concurrent sessions/recovery; workflow lint; fresh-runner contracts; no-stdin .env mapping/conflicts/reset; delayed audience and expiry cases | OPEN |
| G5 assertions | Empty/stale/partial notebook failures; precise Demo 2 initial-absence test; SSE/403 causation fixtures; mock path/auth/fault/alternate/recovery evidence | OPEN |
| G6 usage/pricing/budget | Hand-calculated units/cache/unknown/duplicate-price cases; exclusive-window contamination tests; response reconciliation; finite session dispatch inventory and caps | OPEN |
| G7 publishing | Fake secrets across logs/errors/HTML/metadata/raster sources; sanitizer fail-closed; renderer network/script isolation; provenance/path/PNG rejection tests | OPEN |
| G8 recovery | Dry-run refusal; failure after each mutation/phase; missing outputs/RG; 404 versus 403; independent retry; retained modes; approved delete/name-reuse rehearsal | OPEN |
| G9 site | Matching Jekyll build; EN/FR crawl, switchers, assets, anchors, alerts and mobile/desktop review; confirmed human-merge Pages update | OPEN |

1. Obtain residency, model/region eligibility, spending envelope owner, protected-ref/reviewer, and manual recovery-owner decisions. Confirm repository visibility/Pages without changing settings. No paid deployment yet.
2. Implement local tests and minimal shared/notebook compatibility changes, including source secret prevention, MI logger ownership, disabled message capture, Linux setup, semantic classifiers, and the session-wide dispatch guard. Reject unsafe legacy behavior before automation.
3. Implement manifest/configuration, price coverage, sanitizer/renderer, and recovery contracts with synthetic fixtures. Rehearse every partial-failure and preservation mode before enabling paid resources; run harmless GitHub lock/permission tests.
4. Bootstrap the dedicated RG/environment and constrained identities under separate approval. Compile schema-validated RG-scoped IaC and review what-if; collect fresh capacity/pricing evidence. Gate the APIM identity creation/RBAC bootstrap boundary explicitly.
5. Authorize a finite disposable session only after prerequisite local gates pass. Verify MI readiness, logger readback, privacy and metric ingestion before running the full notebook set. Stop on inconclusive required objectives and retain their true status.
6. Run the isolated bounded showback window, reconcile response usage, sanitize evidence, and execute the approved cleanup regardless of ordinary success/failure. Rehearse manual recovery and separately approved purge/name reuse when required.
7. Build/crawl both languages using only reviewed evidence, then obtain publishing approval and verify a human-merged Pages update. Keep optional event logging, automated image PRs, workbook, and APIOps transfer blocked until their own gates pass.

## Rejected alternatives and remaining decisions

Subscription-wide routine Contributor/RBAC administration and a branch OIDC bypass are rejected because convenience does not justify authority outside the dedicated lab. Whole-RG/force-purge teardown is rejected as the default because it conflates cost control with irreversible deletion and loses recovery boundaries.

Connection-string-only telemetry with local auth enabled is rejected for this design; compatible notebook changes are required instead. Token-only LLM event logging through an unsupported enum or untested omission is rejected. Metrics-only showback avoids asserting an unproved event grain, but does not promise exact allocation under concurrent traffic.

Seven independently callable/scheduled workflows and nested shared locks are rejected for lifecycle interleaving/contract risks. Raw notebook/HTML uploads, browser-only redaction, and direct embedded-image extraction are rejected because they cannot establish artifact sanitization. Automatic image PRs and extra publishing credentials are deferred.

Premature full LZA copying, APIOps pipelines, dynamic price ingestion, and a workbook are deferred until the core loop passes. MkDocs is not selected because matching the sibling Jekyll site is the stated requirement. Standard v2 remains the required reconsideration when private networking becomes mandatory, not a rejected security requirement.

User decisions still required: approved processing/storage geographies and model tuple; finite whole-session budget and approver; protected refs/reviewers; recovery/purge operator and response expectation; repository visibility/Pages approval; and approved safety-causation evidence. Retaining the empty RG, manual curated images, metrics-only showback, and MI-only ingestion are selected defaults, not reopened options.

Recommended next verification, not completed: G1-G9 implementation tests and authorized live acceptance. No broad additional research is needed to replace the unsafe proposal. If a required safety or telemetry objective cannot be proved within these constraints, publish it as unverified and do not claim all labs succeeded.
