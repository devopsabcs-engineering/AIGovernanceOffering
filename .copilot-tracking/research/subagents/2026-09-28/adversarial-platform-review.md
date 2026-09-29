---
title: Adversarial platform review
description: High-risk review of APIM Basic v2 lab infrastructure research
ms.date: 2026-09-28
---

## Status and scope

Complete as a document-based adversarial review. Live acceptance gates remain open. Research only; the only edited file is this output.

Primary: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md.
Supporting capability research: .copilot-tracking/research/subagents/2026-09-28/apim-basicv2-capabilities-research.md.

Review questions cover Basic v2 policy support, cost, soft delete, model availability and residency, API schemas, identity bootstrap, and teardown safety. Basic v2 remains a defensible candidate for public-endpoint labs, but the primary research is not ready for implementation unchanged. No CRITICAL finding was established. HIGH findings concern a schema error, fresh-subscription model eligibility, unresolved residency, excessive CI privilege, and destructive teardown. MAJOR findings concern verification claims, financial accuracy, and cost controls.

All primary line references below refer to the primary document above as reviewed on 2026-09-28. Platform documentation is time-sensitive; quoted evidence is from the pages fetched during this review.

## Evidence collection

Official Microsoft Learn and Azure pricing pages were fetched directly. Azure MCP tools are deferred, and no tool-search capability is exposed in this session, so dedicated Azure best-practice and documentation tools could not be discovered or invoked. No deployment, resource mutation, or installation was performed.

## Findings

### HIGH: Invalid privacy setting in the diagnostic contract

Primary lines 335 and 180 specify `messages: 'none'` with API version `2024-06-01-preview`.

The [API diagnostic schema](https://learn.microsoft.com/azure/templates/microsoft.apimanagement/2024-06-01-preview/service/apis/diagnostics) states: "Currently there is only 'all' option." It enumerates only `'all'` for `LLMMessageDiagnosticSettings.messages`. This is a contract mismatch, not just an untested region. Replacing it with `'all'` would also violate the stated token-only logging intent.

Correction: remove the unsupported request/response message configuration; test whether `logs: 'enabled'` with those blocks omitted preserves usage metadata without bodies. Treat that behavior as an acceptance gate, not an established fix. Keep prompt/completion logging disabled unless explicitly approved, and verify both returned configuration and actual rows before publishing artifacts. Do not suppress the enum diagnostic.

### HIGH: Model defaults do not establish fresh-subscription eligibility

Primary lines 48-49, 124, 176, and 211-218 select `gpt-4o-mini` or `gpt-4.1-mini` based on regional availability and compatibility with existing request parameters, without a lifecycle/access gate.

The current [retirement schedule](https://learn.microsoft.com/azure/foundry/openai/concepts/model-retirement-schedule) lists `gpt-4o-mini` version `2024-07-18` and `gpt-4.1-mini` version `2025-04-14` as "Deprecated", with retirement date `2027-04-14`. The [lifecycle policy](https://learn.microsoft.com/azure/foundry/openai/concepts/model-retirements) says deprecated versions are "No longer available to new customers" and defines an existing customer at the subscription level, based on whether it ever deployed the specific version. These sources do not mean the models are already retired. They do invalidate assuming that every new lab subscription can deploy them.

Correction: require an explicit model name/version/deployment-type/region tuple and preflight lifecycle, subscription eligibility, available quota, and deployable capacity before starting billable APIM provisioning. Use an eligible GA replacement only after checking the notebook request parameters, policy compatibility, and pricing; do not silently substitute a reasoning model or another region. Existing eligible subscriptions may retain the proposed versions with a documented retirement/revalidation date. A public region matrix is not a capacity reservation.

The [quota guide](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/quota) says quota is per subscription, region, model, and deployment type, and that RPM/TPM ratios "can vary by model." It distinguishes the Usages API from the Model Capacities API. Replace the generic 50 K TPM example with the smallest supported allocation that passes the lab, recording the capacity-unit conversion for the selected model. TPM quota is not a monetary budget.

### HIGH: Canadian resource placement is not Canadian inference residency

Primary lines 21, 176, 215, and 604 leave residency unresolved while hardcoding `GlobalStandard` into the proposed deployment.

The [deployment-type documentation](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/deployment-types) states that Global deployments may process data "in any Azure region." The [regional availability table](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability) lists Canada East Global Standard for both proposed versions, and Canada East Standard for `gpt-4.1-mini`, but not Standard for `gpt-4o-mini`. Availability still does not override the lifecycle restriction above. The deployment-type page describes Standard processing within the selected Azure geography, while the availability page uses region wording; do not promise stricter region-only processing without resolving that documentation difference.

Correction: make residency approval a pre-deployment gate. With Canada-only processing required, reject Global Standard and use only an eligible, approved Canadian Standard deployment; otherwise stop. With no such requirement, explicitly approve global processing and synthetic-only prompts. Never change geography as an automatic quota fallback. Check Content Safety/Prompt Shields and telemetry locations separately; they process or store different parts of the data flow.

### HIGH: Routine CI receives unnecessary subscription-wide authority

Primary lines 20, 174, and 476 combine subscription Contributor with role-assignment administration and trust both an environment subject and a branch subject. Limiting assignable role names alone does not limit the target principals or resources throughout that subscription. A job trusted through the branch subject need not pass the `lab` environment approval boundary.

The [Azure RBAC guidance](https://learn.microsoft.com/azure/role-based-access-control/best-practices) says: "Avoid assigning broader roles at broader scopes even if it initially seems more convenient." The [conditional delegation examples](https://learn.microsoft.com/azure/role-based-access-control/delegate-role-assignments-examples) distinguish constraints on roles from constraints on roles and principals, and require separate handling of role-assignment write and delete. [GitHub's Azure OIDC guidance](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure) recommends environment protection rules and warns that newer or renamed repositories may use immutable subject claims rather than the older name-only format.

Correction: separate human/bootstrap authority from routine deploy/lab/report jobs. Bootstrap a dedicated lab RG and grant its deployment identity only the needed RG-scoped permissions; retain the empty RG between sessions. Grant constrained role-assignment authority only within that lab scope, or perform the small identity/RBAC bootstrap separately. Where conditions are used, constrain both permitted roles and the APIM principal where practical, and cover write and delete. Recreated system identities need revalidated principal IDs. Use only the protected environment trust for privileged jobs, approved branches, and a subject/audience verified against actual repository claims. Document separate Entra application-registration rights, Azure RBAC-assignment rights, and GitHub administration prerequisites. Subscription access required for purge is not a reason to grant every workflow subscription Contributor.

### HIGH: Teardown can irreversibly delete unrelated resources

Primary lines 27, 396, and 440-473 describe safety based on a typed RG name, but the executable outline deletes every Cognitive Services account and force-deletes every workspace in that RG. It uses the first APIM instance only, suppresses APIM discovery errors, does not verify ownership, and cannot reliably resume a purge after RG deletion without persisted inventory. A correctly typed but incorrect configured RG still passes confirmation.

The [Foundry deletion guidance](https://learn.microsoft.com/azure/ai-services/recover-purge-resources) states: "Once a resource is purged, it's permanently deleted and can't be restored." The [workspace deletion guidance](https://learn.microsoft.com/azure/azure-monitor/logs/delete-workspace) calls permanent deletion "a non-recoverable operation." The [APIM soft-delete guidance](https://learn.microsoft.com/azure/api-management/soft-delete) requires additional subscription-scope deleted-service permissions for purge. The [quota guide](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/quota) also explains that deleting model deployments first releases quota, whereas programmatic account deletion can leave quota unavailable until purge or retention expiry.

Correction: default `execute=false` and `purge=false` independently. Validate tenant, subscription, full RG ID, lab ownership tags, and a deployment inventory containing exact resource IDs, names, locations, and run identity. Refuse unexpected resources or multiple unexpected APIM instances; tags alone are not proof of ownership. Never remove locks automatically. Persist the inventory before deletion and reuse it for recovery from partial failure. Delete model deployments before accounts, wait for each state transition with bounded retries, and distinguish absent resources from permission/discovery failures. Keep purge as a separately approved operation over exact inventoried tombstones, using a dedicated operator identity. Confirm irreversible data loss separately from ordinary teardown. Report residual billable resources and failed deletions; do not report success merely because the RG is absent.

### MAJOR: Policy eligibility is overstated as a verified complete lab

Primary lines 8 and 105-115 say "verified sufficient" and "is sufficient", while lines 48-51 and 595 defer region, quota, diagnostic, and metric validation. The claim exceeds the evidence.

The [token-limit policy](https://learn.microsoft.com/azure/api-management/llm-token-limit-policy) and [Content Safety policy](https://learn.microsoft.com/azure/api-management/llm-content-safety-policy) explicitly include Basic v2. The [backend documentation](https://learn.microsoft.com/azure/api-management/backends) excludes circuit breakers on Consumption, not Basic v2, but says breaker behavior is "approximate" across gateway instances. The [tier comparison](https://learn.microsoft.com/azure/api-management/api-management-features) shows no inbound private endpoint or private-backend connectivity for Basic v2. These facts support a public-endpoint candidate, not an executed end-to-end result.

Correction: replace the verdict with "Basic v2 is the recommended lowest-cost candidate among the considered v2 tiers for these public-endpoint labs, subject to the acceptance gates below." Do not certify live multi-region resilience using mock backends. Make a breaker trip and later recovery required evidence, rather than allowing primary line 527's `NOT TRIPPED` warning to pass that demo. Retain the upgrade decision if private access becomes mandatory; Standard v2 offers more than outbound VNet integration, including inbound private endpoints.

The custom-metric property at primary lines 192-193 also remains a gate. The [App Insights integration guide](https://learn.microsoft.com/azure/api-management/api-management-howto-app-insights) requires "With dimensions" and `metrics: true`, but a suppressed `BCP037` does not prove the untyped property was honored. Verify readback and emitted dimensions. The same guide explicitly supports connection-string-only loggers, so the missing `identityClientId` at primary line 236 is not itself an invalid schema. It does mean the Monitoring Metrics Publisher grant at line 127 is unused by that logger; either remove the unused grant or deliberately migrate and validate every logger before disabling local authentication.

### MAJOR: Telemetry-derived estimates are not billing source of truth

Primary lines 304 and 337 label a log join with a static price table as "source of truth"; lines 340-355 omit pricing coverage and join-cardinality checks. Unknown models have null rates and can disappear from summed cost. Multiple correlated rows can multiply token totals. A version-stripped model name alone does not identify the region, deployment type, currency, effective date, or applicable cached-input price.

The [LLM logging guide](https://learn.microsoft.com/azure/api-management/api-management-howto-llm-logs) warns that, for broken streams or terminated connections, "token usage might not be logged or is inaccurate." It also documents separate correlated request/response entries and message chunks. This does not prove every proposed join duplicates rows; it requires a cardinality check before trusting totals.

Correction: call the output estimated token-cost allocation or showback. Preserve unpriced, unattributed, failed, and incomplete records with explicit counts instead of treating missing rates as zero. Scope by the lab resource/API and verify one usage record and one attribution record per intended request before joining. Key rate snapshots by the verified model/version, deployment type, region, unit, currency, and effective period; use appropriate cached-input treatment if applicable. Show token-derived cost separately from shared APIM/monitoring/Content Safety charges. Reconcile aggregates with provider usage and actual Azure billing before calling the result chargeback. Identify backend-originated 429s separately; primary line 361's assertion that all 429s never reach the backend is too broad.

### MAJOR: Cost estimates lack an enforceable workload envelope

Primary lines 374, 394-397, and 576-582 combine per-run caps without numeric defaults, twice-hourly traffic, and an approximately 2M-token monthly assumption. A run cap resets on each scheduled run; it is not a monthly cap. Optional cleanup also leaves continuing APIM charges possible after failure.

The [APIM pricing page](https://azure.microsoft.com/en-us/pricing/details/api-management/) fetched in this review displays Basic v2 first-unit pricing of $150.01/month and Standard v2 $700/month. It says prices are "estimates only" and actual prices vary by agreement, date, and currency. Thus the primary's roughly $150 figure is not disproved, but it is not a Canadian region/offer-specific quote. The [token-limit policy](https://learn.microsoft.com/azure/api-management/llm-token-limit-policy) warns that concurrent requests can temporarily exceed limits. Such enforcement is not a strict spend ceiling.

Correction: publish a dated estimate with region, currency, offer, unit count, billable lifetime, prompt/output/cache assumptions, telemetry volume, and Content Safety volume. Label $5-7/day illustrative, not guaranteed. Disable traffic cron by default. Add numeric attempted-request, token-reservation, output-token, retry, and wall-clock limits shared across all traffic rounds. Count retries and failed/unknown-usage attempts conservatively. Use failure-path cleanup and an ownership-checked expiry process, with explicit residual-resource reporting when cleanup cannot finish. Budget alerts are notifications, not automatic spending caps.

## Claims not rejected by the evidence

* Basic v2 policy support is documented. No evidence found here requires upgrading to Standard v2 for the stated public-endpoint policy demonstrations alone.
* The roughly $150/month Basic v2 starting figure matches the fetched public pricing view. The defect is unsupported total-cost precision and uncontrolled duration/traffic, not an established fivefold pricing error.
* The current [APIM soft-delete page](https://learn.microsoft.com/azure/api-management/soft-delete) says "APPLIES TO: All API Management tiers" and gives a 48-hour retention period. Do not assert classic-only support. Lack of v2 backup/restore is a different feature and does not establish lack of soft delete. Basic v2 delete/purge/name-reuse behavior remains a disposable-environment acceptance gate; same-subscription reuse and cross-subscription reuse have different constraints.
* Cognitive Services has documented 48-hour retention/name blocking. Purge releases the name; it is not automatically required just to stop pay-per-token inference costs. Provisioned deployments have a separate continuing-charge warning and should be deleted first. Log Analytics documents 14-day recoverability and permanent-delete name release.
* The diagnostic schema documents `largeLanguageModel` on `2024-06-01-preview`; the concrete error is the unsupported `'none'` enum. This does not validate every proposed API version or every Basic v2 runtime combination.

## Recommended design and acceptance gates

### Smallest defensible design

1. Bootstrap one dedicated lab RG and protected GitHub environment. Keep the empty RG as a low-privilege deployment boundary. Use RG-scoped Bicep for session resources; reserve whole-RG removal and tombstone purge for the approved operator path. If zero retained resources and immediate deterministic-name reuse are mandatory, explicitly accept the additional bootstrap/purge boundary instead of assigning its privileges to all CI jobs.
2. Deploy one Basic v2 unit, one eligible chat deployment, one Content Safety account, one Log Analytics workspace, and one workspace-based App Insights component. No second live model region is needed to teach the existing mock pool. Describe the mock demonstration accurately.
3. Preserve notebook ownership of demo objects. Keep one separate platform API with three small team subscriptions for showback. Use static, dated pricing data and a simple query/chart report; defer dynamic price ingestion, APIOps pipelines, and a portal workbook until the core loop is accepted.
4. Use on-demand deploy, run, report, and teardown workflows plus credential-free CI and docs build. Schedule traffic only as an explicit bounded option. Design concurrency at one orchestration layer so a reusable caller cannot hold a lock that its child needs; verify failure and cancellation cleanup paths.
5. Publish the EN/FR static lab site from the same validated templates, screenshots, and numeric defaults. Publish only sanitized copies. Browser-only screenshot redaction at primary line 529 does not sanitize raw notebooks or HTML uploaded at line 393. Keep raw output private and short-lived, or omit it; secret scanning is a publication gate.

### Proposed safe defaults

These are conservative design defaults, not measured platform guarantees.

* One APIM unit; no autoscaling; one approved model deployment with the smallest supported quota allocation that meets a serial smoke test. Revalidate units when changing models.
* `allowGlobalProcessing=false` until explicitly approved; synthetic prompts only; request/response bodies not logged; no silent region or model fallback.
* Traffic schedule disabled; one worker; at most 30 attempted requests per invocation including retries; 128 maximum output tokens; 10,000 reserved total input-plus-maximum-output tokens per invocation; five-minute wall-clock limit. Reject prompts that cannot be conservatively bounded. Smaller intentional throttle demonstrations may need dedicated lower policy thresholds.
* At most two retries for transient failures within the same request/token/time budget; no retries for intended policy rejections. Stop rather than sleeping past the job deadline for a long Retry-After.
* Default session expiry four hours; `keep_environment=false` for the composed session. Expiry is metadata unless a separately validated cleanup mechanism enforces it. Always surface failed cleanup to the operator.
* `execute=false`, `purge=false`, and `publish_raw_outputs=false`; separate approvals for deletion, irreversible purge, and public artifact publication.
* Environment-only OIDC trust for privileged workflows; no Azure credentials for PR/static-site jobs; no subscription Owner or subscription Contributor for routine traffic/reporting.

### Acceptance gates before implementation is certified

| Gate | Required evidence | Current state |
| --- | --- | --- |
| Region and model | Approved residency decision; exact model/version/SKU; lifecycle and subscription eligibility; quota and deployable capacity; Content Safety/Prompt Shields availability; target region supports Basic v2. | Open |
| IaC contract | Pinned Bicep/CLI versions; compile every module/parameter file; validate exact API schemas; review what-if; resolve unsupported enums; document any remaining type suppression with readback evidence. | Open; `'none'` is a confirmed blocker |
| Identity | Entra bootstrap prerequisites; protected environment trust matches actual subject; least-privilege role scopes; tested rejection of an unapproved principal/role or out-of-lab target. | Open |
| Inference and policies | Successful MI call using actual endpoint/path; token limit and quota cases; benign Content Safety pass and bounded Prompt Shields rejection; mock pool breaker trip, alternate routing, and recovery. | Open |
| Telemetry | Usage rows and all expected dimensions arrive; no message bodies/secrets; verified correlation cardinality; unmatched price/attribution records remain visible; finite ingestion timeout produces failure rather than a blank success chart. | Open |
| Cost controls | Bounded requests, retries, and tokens; current region/offer quote; no default cron; cleanup on failure/cancellation; residual-resource alerting and reviewed ownership inventory. | Open |
| Teardown | Dry run rejects wrong subscription, wrong ownership, and unrelated resources; partial failure resumes from inventory; separate purge approval; proven Basic v2 deletion/name reuse in the same subscription. | Open |
| Documentation | EN/FR parity, links and rendered pages validated; sanitized outputs scanned before public upload; cost, privacy, lifecycle, and cleanup caveats match actual configuration. | Open |

No live gate was executed during this research-only review. Do not convert these gates into claims of tested success.

## Instruction constraints for the parent

* Every new Markdown file requires YAML frontmatter. A frontmatter title replaces the H1; begin content at H2.
* Use ATX headings without skipped levels, blank lines around blocks, consistent star bullets, language-tagged fences, ASCII punctuation, and one final newline.
* Avoid em dashes, bold-prefix list items, filler, unsupported certainty, and unnecessary inline HTML. Keep the technical voice precise and professional.
* Research artifacts under .copilot-tracking use plain workspace-relative file references, not linked local paths. External URLs may be linked.
* No repository instruction files were found by the initial instruction-file search; the root has no .github directory.
* Changes are restricted to this output file and must use apply_patch.

## Open questions

* Must inference and Content Safety processing remain in Canada, or is globally processed synthetic traffic acceptable?
* Has the intended subscription previously deployed either proposed mini-model version? Which currently eligible GA model should be the approved fallback, if any?
* Is retaining an empty bootstrap RG acceptable, or is whole-RG removal and immediate deterministic-name reuse a hard requirement?
* Who owns purge approval, the spending ceiling, and failed-cleanup response? May executed notebooks/HTML ever be published, or only sanitized screenshots?

## Recommended next research not completed

* [ ] After authorization, collect the target subscription's model lifecycle, quota/capacity, region, and policy restrictions without mutation.
* [ ] Validate actual Bicep and logger/diagnostic readbacks in a disposable environment, including privacy-preserving token-only logging and dimension opt-in.
* [ ] Run the ownership and partial-failure teardown acceptance cases with explicit approval; verify residual resources, quota release, and same-subscription name reuse.
* [ ] Record the chosen region/offer pricing snapshot and reconcile bounded sample usage with billing before claiming financial chargeback accuracy.

## Re-review addendum 2026-09-28

Status: Complete as a focused document re-review of the revised 392-line primary.
The original findings and their historical primary line references above remain
unchanged. Only references in this addendum address the revised primary:
.copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md.

Compared the entire revised primary with the original eight platform, eleven
automation, and ten telemetry findings. Research questions were whether the
replacement contracts contradict one another, still recommend an unsafe executable
path, or present unresolved service behavior as already remediated. The local
hypothesis was that the revision removes the original contradictions while keeping
implementation and live acceptance explicitly blocked. Counterexamples sought were
unguarded alternate paths, incompatible selected credentials, missing historical
dispositions, and unqualified financial or live-success claims.

### Remaining severity findings

No remaining CRITICAL, HIGH, or MAJOR contradiction or unsafe executable
recommendation was established in this revision. There is consequently no new
severity/file-line/remedy finding. This verdict applies to the research design,
not to the unchanged application, future implementation, or live environment.

No implementation-stopping legacy behavior is recommended as ready to run. The
required compatibility changes and the nine OPEN gates are explicit. In particular,
the local prerequisite sequence at primary lines 372-376 does not require live
ingestion to have passed before a disposable acceptance session can be authorized.
It does require the finite budget and local safety contracts first.

### Coverage of the 29 original entries

All 29 entries have substantive design dispositions, not merely matching IDs.
There are 22 HIGH and 7 MAJOR entries, including overlapping findings; none is
counted as an implemented or live-verified remediation.

* P01 and F1: primary lines 109-117 remove unsupported message settings, keep LLM capture off on notebook APIs too, and require canary absence with working permitted metrics.
* P02 and P03: lines 70-78 require the explicit eligible model/version/SKU/capacity tuple and separate processing/storage approvals. Global processing and silent substitutions fail closed.
* P04 and F10: lines 84-103 separate bootstrap, deployment, runtime/query, and purge authority. Bootstrap updates principal constraints after APIM recreation and reapplies runtime grants on recreated resource scopes. The three-role deploy condition is not claimed to authorize those runtime grants.
* P05 and A04: lines 131-161 distinguish retention modes, failure cleanup, and manual recovery. Expected inventory is persisted before mutation, independent of successful deployment outputs; deletion and irreversible purge have separate authorities and approvals.
* P06: lines 12, 76-80, 115-117, and 215-217 retain conditional platform suitability, schema/readback checks, and actual fault/alternate/recovery requirements. Mock evidence is not live multi-region certification.
* P07, F2, F3, and F6: lines 239-247 and 261-267 label retail estimates, preserve incomplete price/usage coverage, account for units and cache exclusions, and block event accounting pending grain/privacy validation. No correlation-only accounting recommendation survives.
* P08 and F4: lines 249-259 distinguish generator defaults from the required session envelope. Shared reservation state spans notebook kernels/jobs, bursts, retries, and ambiguous attempts. G6 blocks paid runs until the tested envelope exists; cleanup retains separate deadlines.
* A01 and A10: lines 271-281 prevent source leaks before logs, sanitize allowlisted evidence before summaries/render/upload, reject raw raster sources, isolate rendering, and defer automated image PRs. Internal recovery records have their own pre-persistence allowlist at line 145.
* A02 and A03: lines 86 and 121-141 select protected repository/environment trust and two cloud entry workflows sharing one workflow-level lifecycle lock. No nested acquisition, per-phase release, inherited runner state, or unconditional deletion authority is selected.
* A05, A06, and A07: lines 191-217 require exact current-run notebook completion and causal safety/failover evidence. Arbitrary 403, missing DONE, or healthy recovery alone cannot establish success. Inconclusive required objectives prevent all-labs success.
* A08 and A09: lines 165-187 correct deployment scope, physical configuration keys and precedence, file-owned DEMO_RUN, explicit login boundaries, and separate token audiences/lifetimes. These are required changes, not claims about present helper behavior.
* A11: lines 283-304 provide one EN/FR page/image map, baseurl-aware links, matching builds/crawl, and human-merge publishing verification without introducing automatic publication credentials.
* F5: lines 229-233 require exclusive complete metric buckets, control human traffic, and reject contaminated windows. Request manifests reconcile the window; they do not split aggregates into precise concurrent per-run allocations.
* F7: lines 223-237 bound gateway-normalized dimensions, retain caller-label limitations, select one metric representation/emitter, and require observed schema plus response-usage reconciliation. Missing telemetry is not zero.
* F8: lines 225-227 explicitly recognize privileged subscription bypass, effective inheritance, backend credential stripping, and failure provenance. Product quotas are not presented as universal spending controls.
* F9: lines 105-115 and 314 require explicit logger ownership plus compatible helper and Demo 2 changes before use. MI ingestion is selected consistently; connection-string-only fallback is rejected.

### Specific boundary checks

The official [Application Insights integration reference](https://learn.microsoft.com/azure/api-management/api-management-howto-app-insights)
was fetched narrowly to test the selected logger contract. Its REST example supports
connectionString together with identityClientId set to SystemAssigned, and its
prerequisites require Monitoring Metrics Publisher on the component. Thus the
selected helper migration is supported at the configuration-contract level. No
notebook execution or ingestion success is inferred from that example.

The workflow lock is evaluated within the selected repository's two cloud entries,
not as a cross-repository or human-operator Azure mutex. The primary does not select
a second repository, an untrusted privileged entry, or a parallel bootstrap workflow.
Adding any of those would require a new coordination/trust decision, not invalidate
the chosen same-repository baseline. Human traffic is separately addressed for
measurement windows at line 231.

Inventory storage technology, actual role definitions/conditions, helper signatures,
gate fixtures, and observed metric schemas remain implementation work. Their absence
from a research-only document is not a new HIGH/MAJOR finding when mutation or use
is explicitly conditioned on implementing and verifying those contracts.

### Financial and live-remediation claim check

No affirmative claim of financial exactness or successful live remediation remains.
Primary lines 10-16 and 324 explicitly distinguish design corrections from execution.
Lines 28, 239-259, and 384 reserve actual charges for billing reconciliation, qualify
retail/cache/platform exclusions, and reject a hard bill ceiling or daily guarantee.
Lines 233 and 267 expressly defer exact concurrent allocation. The word authoritative
at line 287 describes a page/image manifest, not accounting. Exact identifiers,
required file sets, and one applicable price are validation constraints, not financial
accuracy claims. Historical supporting claims are explicitly superseded at line 16.

### Validation and remaining work

* Read all four review documents, including the automation review's final sections; compared each original finding with its replacement contract in the primary.
* Ran read-only local PowerShell checks: exactly 392 primary lines; exactly one of each P01-P08, A01-A11, and F1-F10 disposition; original and mapped counts both 22 HIGH plus 7 MAJOR; exactly nine OPEN gate rows.
* Checked every fenced block: only two text inventory blocks remain, with no executable code fences. Manually reviewed surrounding imperative recommendations as well; fence absence alone was not treated as proof of safety.
* Searched and context-reviewed exact, source-of-truth, authoritative, verified, validated, remediation, guarantee, and ceiling language, plus identity, lock, pre-mutation inventory, budget, and pre-publication anchors.
* Fetched only the cited official logger reference to resolve the concrete MI credential question. Deferred Azure tool discovery is unavailable in this session; no deferred tool was invoked.
* Post-edit comparison passed: the primary, automation review, and telemetry review are unchanged; the original platform text is preserved with only this addendum appended. Addendum ASCII, trailing-whitespace, and final-newline checks passed.
* get_errors reported no errors in all four reviewed documents. No application tests, notebook execution, deployment, cloud command, workflow dispatch, pricing lookup, or live acceptance was performed.

Recommended next verification remains implementation and separately authorized G1-G9
acceptance, not additional broad research:

* [ ] Implement and run local budget, sanitizer, ownership, recovery, configuration, and semantic assertion fixtures before paid execution.
* [ ] Verify protected trust and same-lock behavior with harmless workflow stand-ins; test bootstrap/recreation grants without broadening deploy authority.
* [ ] Perform authorized finite live acceptance for MI ingestion, privacy, metric windows, safety/failover, and recovery, retaining inconclusive results.

No new clarifying question is required to close this re-review. The existing user
decisions at primary line 390 remain prerequisites: geography/model, session budget
and approver, trusted refs/reviewers, recovery/purge ownership, publication approval,
and acceptable safety-causation evidence.
