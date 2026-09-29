---
title: Adversarial Automation Review
description: Research-only review of the APIM lab automation proposal and headless execution evidence.
ms.date: 2026-09-28
---

## Status and Scope

Complete, research only. Only this document was intentionally modified.
No cloud operations, installation, notebook execution, or workflow dispatch occurred.

Primary source: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md.
All references labeled P below are exact line numbers in that file as inspected.
H denotes .copilot-tracking/research/subagents/2026-09-28/headless-notebooks-screenshots-research.md.
Notebook references use editor cell numbers and source-line numbers within each cell.

The repository has no .github directory; docs contains only ai-governance-flows.svg.
Workflow findings concern the proposed design and snippets, not a deployed workflow.
Confirmed means supported by inspected code or an internally inconsistent proposal.
Hypothesis means a conditional implementation risk requiring the stated test.
No CRITICAL compromise is established. HIGH findings block reliable or safe automation;
MAJOR findings block the advertised evidence or publishing contract.

## Research Questions

* Are reusable workflow contracts and environment-wide concurrency safe?
* Does cleanup run after failures and tolerate partial provisioning?
* Does authentication distinguish OIDC assertions from cached access tokens?
* Can notebook validation reject partial execution and false success?
* Are headless configuration and Demo 4 routing and credentials correct?
* Can logs, artifacts, screenshots, or image PRs disclose credentials or cross trust boundaries?
* Will bilingual links and Pages builds work after automated image updates?

## Severity-Ranked Findings

### HIGH A01 Raw evidence can publish a usable subscription key

Classification: confirmed local disclosure path and incomplete proposal mitigation.
Primary references: P393, P522, P529, P566.

notebooks/demo4-resilient-pool.ipynb cell 10 source lines 1-8 fetch and print
REQUEST_HEADERS containing the complete APIM subscription key. Papermill log output
and executed notebook output precede the browser redaction step. H section 5.4
correctly identifies this leak, but its temporary advice to shorten retention is not
a prevention measure. P566's source masking fix is necessary; it is not a substitute
for sanitizing all published evidence, including failures.

The H section 6.3 regex handles GUIDs and 32 hexadecimal characters, not arbitrary
keys, bearer tokens, connection strings, URL parameters, tracebacks, HTML attributes,
embedded JSON, or rasterized text. Editing browser text nodes changes neither the
saved HTML nor notebook JSON. GitHub masking applies to logs, not arbitrary artifact
bytes [S07]. shared/apim.py lines 30-40 include complete response bodies in exceptions;
whether a particular Azure error echoes a secret is a hypothesis, not an observed leak.

Replacement for P393/P529: prevent secret output at source; register dynamically
retrieved secrets before any possible log emission; keep .env and raw evidence private
to the runner. Create an allowlisted, sanitized output-only evidence copy before
HTML rendering, screenshots, summaries, or artifact upload. Scan that copy for known
secret values and credential patterns; fail closed on detection or sanitizer failure.
Render sanitized content in a separate job without Azure credentials or repository
write permission, block external browser requests, and do not execute notebook HTML
scripts. Publish only approved outputs; failure diagnostics must also be sanitized.
Deleting an environment later does not make an earlier credential publication safe.

Acceptance tests: inject fake APIM keys of several shapes, a bearer token, and a fake
connection string into stream, HTML, exception, metadata, and embedded-image outputs.
Verify no raw value reaches logs, summaries, notebook/HTML artifacts, PNGs, or PR diffs.
Make sanitizer failure prevent every upload and image PR. Do not use live secrets
for these tests. If prior publication is discovered, rotate keys and remove exposed
logs/artifacts as a separate authorized incident response.

### HIGH A02 Shared caller and callee locks cannot protect the lifecycle

Classification: confirmed design ambiguity; nested deadlock is a conditional inference,
not a reproduced GitHub failure. Primary references: P387, P397, P410, P444.

The proposal gives all workflows aigov-lab and composes them with workflow_call.
If the end-to-end caller holds that lock, a callee requesting the same group with
cancel-in-progress false can wait on the caller that is waiting for the callee.
Changing it to true is not a fix: GitHub explicitly documents cancellation of the
caller when caller and callee share the group [S01]. If only the individual callees
hold the lock, it is released between phases; standalone teardown or another deploy
can interleave before the next lab/report phase. Different names for every workflow
also remove the intended environment mutual exclusion.

cancel-in-progress false protects the running member, not all pending requests.
The default queue has one pending entry, and a later arrival replaces that entry
[S02]. Do not describe this as a guaranteed FIFO backlog of whole lab sessions.

Replacement for P387: one top-level lifecycle lock, held from the first mutation
through evidence collection and cleanup. Prefer one dispatch workflow and ordinary
steps/scripts initially. A standalone teardown wrapper must acquire that same lock;
internal tasks must not reacquire it. If reusable workflows are retained, separate
lock-owning entry wrappers from lock-free implementation workflows and define which
entry points are supported. No recursive shared lock and no per-branch lock for the
same Azure environment. Avoid adding schedules to solve queueing problems.

Acceptance tests: use harmless stand-in steps to run two lifecycle requests and one
teardown request concurrently. Neither teardown nor the second deploy may start
inside the first lifecycle; the active run must never cancel itself. Verify the
documented pending-replacement behavior, and that failure cleanup remains inside
the lock. These GitHub dispatch tests were not run in this review.

### HIGH A03 The reusable workflow graph has missing contracts

Classification: confirmed proposal inconsistency. Primary references: P392-P397,
P406-P409, P438-P442, P476, P487-P516.

generate-traffic and teardown are called in P397 but lack workflow_call in P394/P396
and the teardown snippet. Teardown defines only dispatch inputs; no reusable
confirm/execute contract exists. Deploy exposes only resource_group while subsequent
jobs need more deployment values. That is not inherently wrong if values are queried
again, but the retrieval scope and deployment identifier must be explicit.

Caller workflow env does not propagate to callees, and reusable calls occupy a job,
not a step [S01]. Caller jobs cannot also contain checkout/login steps or environment.
The actual called job must select environment lab and authenticate on its own runner.
Called workflows cannot elevate the caller's token permissions. .env and Azure CLI
login state are not transferable job outputs.

Replacement for P392-P397: either use the smaller single-workflow approach or declare
typed workflow_call inputs on every called workflow, including explicit cleanup
authorization. Pass subscription ID, expected RG, deployment scope/name, and run
identity as non-secret values. Map step outputs to job outputs to workflow outputs,
or query the exact subscription deployment again in each job. Reconstruct .env and
fetch secrets within the consuming job; never use artifacts to transport .env or
Azure credential caches. Declare minimal permissions at both call and implementation
boundaries. Standalone destructive dispatch retains typed confirmation and dry run.

Acceptance tests: workflow lint plus a schema/contract test must reject a call to a
dispatch-only workflow and missing typed inputs. Test a clean runner per phase with
no inherited env or files. A caller granting only contents read must not be assumed
to supply id-token write or PR write access. Verify dry-run remains non-destructive
through both supported entry paths.

### HIGH A04 Cleanup is success-dependent and cannot resume reliably

Classification: confirmed snippet defects and missing failure-path contract.
Primary references: P396-P397, P451-P473, P583, P598.

P397 only says teardown if keep_environment=false. An ordinary needs chain and an
if condition without a status function inherit success(), so a failed/skipped
upstream phase can skip teardown [S03]. A partial deploy may create billable resources
without producing deploy outputs. An end-of-notebook cleanup cell is not a fallback:
Demo 4 cell 25 is explicitly disabled and can never run after an earlier hard stop.

The shell snippet has independent recovery defects:

* P462/P467 stop all cleanup when the first purge fails, leaving other active resources.
* P457 requires an existing RG; a retry after RG deletion cannot reach the purge stage.
* P463 masks every APIM lookup error, including auth failures, and records only the first instance.
* P464 enumerates only live Cognitive Services accounts, missing already-deleted accounts on retry.
* P472/P473 retain APIM name/location only in shell memory; interruption loses that recovery input.
* P451 confirms a mutable repository variable rather than an independently verified deployment target.

Soft-deleted APIM and Cognitive Services resources require distinct discovery/purge
operations [S09, S10]. Immediate purge readiness and deletion duration are live-service
risks; the deterministic problem is having no bounded retry or resumable inventory.
The proposed GlobalStandard model is not provisioned-throughput billing; do not
misapply the documented provisioned-deployment charge warning to that model.

Replacement: establish and validate the dedicated lab subscription/RG and ownership
before deployment. Reject unrelated pre-existing resources instead of deleting a
group on name alone. Capture a non-secret resource identity/location manifest before
destruction. Run bounded cleanup after success or failure using an explicit status
condition, for example always() && !inputs.keep_environment, plus verified target and
mutation-attempt guards. Give cleanup its own timeout and fresh login. A guard must
not require deployment success. Preserve the original failure verdict after cleanup.

Process independent cleanup items even if one fails, collect errors, and exit nonzero
when anything remains. Treat confirmed absence as idempotent success, not arbitrary
403/transport errors. Discover deleted resources matching the exact approved scope
even when the live RG is gone. Poll completion with bounded retries and verify the
final live/deleted inventory. No subscription-wide purge. Provide manual dispatch
recovery for force-cancellation, runner loss, or a job that never started; always()
is not an execution guarantee under those conditions.

Acceptance tests: stub deletion APIs and inject failure after RG creation, during
each notebook, after account deletion but before purge, and after RG deletion.
Second cleanup must finish the exact manifest, leave unrelated resources untouched,
and preserve a failed lifecycle result. Exercise transient purge failure, permanent
403, absent RG, keep_environment=true, and invalid confirmation. A later authorized
live delete/purge/redeploy test is still required.

### HIGH A05 The checker can certify missing or partial runs

Classification: confirmed supporting-prototype defect, adopted by the primary.
Primary references: P393, P485, P520-P527. Evidence: H section 4.2.

The checker loops over globbed notebooks and returns success when none exist.
RULES.get(..., {}) accepts an unknown filename without required outcomes. It never
requires exactly all five notebook outputs, current-run provenance, completed code
cells, or successful execution of later cells. A partial notebook with earlier PASS
strings can satisfy its rules. Fresh execution tools may clear prior outputs, but
this independent checker has no basis for trusting arbitrary existing outputs.

The primary shell loop relies on the surrounding shell to stop on papermill errors;
as a generic script it does not explicitly preserve each command's exit status.
H recommends always-run checking and screenshots, which is useful for diagnostics
but must not authorize publication of partial results as successful lab evidence.

Replacement for P527: an explicit five-notebook manifest, one clean output directory
per run/attempt, and recorded source revision/hash and execution outcome. Reject
missing, extra, stale, failed, skipped, or incomplete required notebooks. Check
papermill exit status and completion metadata for every required nonempty code cell;
execution_count alone is not proof. Use a small structured result per learning
objective, not a general framework. Do not ignore an entire preflight cell: allow
only the precisely named expected initial conditions and recheck them after setup.
Diagnostic collection may run on failure; success images and PRs must require the
complete execution, semantic validation, and sanitization gates.

Acceptance tests: empty directory, one file missing, renamed notebook, unknown file,
stale successful output, killed kernel, skipped later cell, inserted markdown cell,
and a traceback after a PASS banner must all fail. A known first-run Demo 2 logger
absence may be allowed only if post-configuration logger/diagnostic checks pass.

### HIGH A06 Content Safety stream termination is falsely attributed

Classification: confirmed local logical defect; not an observed live safety bypass.
Primary reference: P527; omission from required fixes P565-P570.

notebooks/demo3-content-safety.ipynb cell 20 source line 30 defines success evidence
as status 200 and no [DONE]. Lines 48-52 then label it PASS. This includes a clean
empty 200, non-SSE HTML/JSON, or a cleanly truncated stream with no safety action.
iter_lines exceptions may instead raise and fail; the finding does not claim every
network failure passes. No content-type, valid SSE-event, or safety-correlation check
distinguishes these cases. Cell 18 source line 15 also accepts any expected 403 without
requiring the reported decision/reason to establish which control denied the request.

Microsoft documents that a safety violation stops forwarding streaming events without
returning 403 [S08]. It does not state that every missing [DONE] proves that violation.
P527 requires only the safe and prompt-attack banners; harm/stream NOT TRIPPED can
still produce an advertised all-labs success.

Replacement: classify transport/protocol error, policy-block confirmed, not-tripped,
and inconclusive separately. Validate status, content type, and parsed SSE shape.
Require correlated safety evidence when claiming a safety-caused stop. A valid SSE
stream without [DONE] but without that evidence is inconclusive, not PASS. For input
blocking, require policy-specific evidence rather than status alone. Keep the mild
fixtures; do not promise they deterministically trigger model or safety decisions.
Until approved fixtures and observability establish the causal result, report that
objective as unverified and do not publish it as a completed safety demonstration.

Acceptance tests: mocked empty 200, HTML 200, truncated valid SSE, malformed SSE,
complete safe stream, unrelated authorization 403, and confirmed safety interruption.
Only the last may pass the streaming safety objective. No harmful fixture generation
or live requests are required for the unit-level classification tests.

### HIGH A07 Healthy recovery alone does not prove Demo 4 failover

Classification: confirmed path mismatch and acceptance weakness; credential precedence
and wildcard behavior remain live-validation hypotheses. Primary references: P52-P53,
P527, P565. Evidence: Demo 4 cells 7, 8, 10, 16, 18, 20; H section 5.

Cell 7 source line 35 creates /east, /central, /payg. Cell 8 source line 4 retains the
chat-completions suffix, and cell 7 lines 39-43 set backend bases ending in the member.
There is no rewrite in policies/demo4-resilient-pool.xml. The documented backend-base
substitution retains the remaining path [S11], so the composed member path is not the
operation template. The primary already acknowledges the required wildcard fix;
its first-live-run qualification must remain, not become a claim of proven routing.

Even after that fix, cell 18 only warns when East's observed 429 count is insufficient
or PAYG never appears. Cell 20 declares recovery when any East 200 appears, which is
possible when East never became unavailable. Cell 16's aggregate table hides unknown
member identifiers among the weighted sample. P527/H allow those warnings, so the
proposed checker can certify a demo that never demonstrates failover.

The mock is subscription-protected and backends provide a named-value key while the
original request also has a subscription-key header. That is an authentication test
requirement, not proof of duplicate-header failure. Inference mode supplies
credentials=None; verify deployed backend state actually removes mock credentials
rather than assuming omitted properties clear them. Never solve routing by making
the mock unauthenticated or printing its key.

Replacement: retain operation identifiers and change templates to /{member}/*, then
test both supported API styles. Add bounded semantic assertions for healthy named
primary responses, observed fault statuses, successful Central/PAYG routing in the
proper phases, and subsequent recovery. Reject missing/unknown x-served-by values
and unexpected statuses in every routing phase. Accept approximate weighting, not
an exact 2:1 ratio or an inferred distributed breaker state. Validate the backend
credential received by the mock and its removal when switching to real inference.

Acceptance tests: path-construction cases for v1/classic, bad client/mock credential,
all-404 routing, unknown member in the weighted sample, no East fault, no Central
success, no PAYG spillover, and recovery without preceding fault evidence must not
pass. Subsequent authorized gateway testing must verify wildcard matching and
credential behavior without logging credential values.

### MAJOR A08 OIDC assertion expiry is not access-token expiry

Classification: confirmed misleading operational shorthand; runtime failure is
conditional on audience acquisition, expiry, and client versions.
Primary references: P393, P396, P521, P531; H section 2.1.

A comment inside a bash for-loop cannot rerun a GitHub uses action. The shown loop
therefore does not implement the repeated login it describes. GitHub's OIDC example
has a five-minute assertion lifetime [S04]; Azure Login describes an approximately
one-hour default service-principal access-token lifetime, configurable by Azure
[S05]. Neither means ARM calls automatically fail five minutes into a notebook.

shared/auth.py lines 19-40 cache a credential object, not an access token. The Azure
SDK implementation explicitly says AzureCliCredential does not cache acquired tokens
[S06]. The CLI cache and SDK pipeline cache are distinct. shared/apim.py lines 43-48
request ARM tokens repeatedly; the LogsQueryClient call at line 760 requests a
different audience later. Reusing an expired federation assertion for a new token
can fail even while an earlier ARM access token remains valid. Exact behavior and
error timing were not tested here; do not guarantee every 30-minute run succeeds.

Replacement for P520-P523: explicit action/step boundaries for login and each
notebook, with Log Analytics audience pre-acquisition immediately after the Demo 2
login. Authenticate separately for deploy, reporting, and cleanup. Ensure bounded
phases fit actual access-token expiry and retry with fresh authentication at phase
boundaries; a 60-minute job timeout is not a credential lifetime guarantee. Do not
add a hand-rolled token cache or re-login timer to every request. Keep tokens out of
outputs. Correct H's unqualified statements that all ARM calls are fine within 30
minutes and that the short assertion lifetime itself requires constant login.

Acceptance tests: use a fake clock/credential to distinguish valid cached ARM access,
expired assertion plus uncached Logs audience, expired access, and refreshed login.
Later authorized CI validation must cover delayed audience acquisition and a long
cleanup phase. Log only scope and expiration metadata, never token contents.

### MAJOR A09 Headless configuration needs a scope and precedence contract

Classification: confirmed supporting-example mismatch and known local prompt behavior;
the primary .env template is otherwise a workable mitigation.
Primary references: P272, P393, P426-P430, P487-P516.

H's CI outline says deployment group show, but P426/P429 deploy and retrieve at
subscription scope. A literal implementation of the supporting outline cannot
retrieve the intended deployment outputs. AZURE_RESOURCE_GROUP must also map to
APIM_RESOURCE_GROUP, which is the key shared/config.py consumes. P499's masked
placeholder must mean masked logging, not asterisks persisted as the real connection
string.

shared/config.py lines 135-136 use override=False; lines 216/225/308/375 check physical
.env key presence to suppress prompts, not merely environment variables. Supplying
only job env values does not implement the template. A conflicting inherited
DEMO_RUN overrides the regenerated file in later kernels and can resurrect used
quota counters. Empty optional Demo 4 values intentionally fall back to AOAI values;
they are not evidence of a real multi-region deployment.

Replacement: one structured subscription-deployment-output reader with validated
scope/name, explicit key mapping, and complete writable root .env. Check required
values before starting any notebook; preserve intentional empty key lines. Establish
one source of truth for overlapping job env keys, and keep DEMO_RUN file-owned when
notebook resets persist it. Validate config under disabled stdin. Keep .env out of
logs, artifacts, caches, and PRs. Retain the primary Linux subprocess fix at P567.

Acceptance tests: mocked subscription outputs, wrong group-scope lookup, missing
output, literal masked connection string, empty optional lines, absent optional lines,
inherited conflicting values, and a notebook reset followed by a fresh kernel.
No case should prompt; invalid cases must fail before any mutation.

### HIGH A10 Image PR publication lacks authorization and trust boundaries

Classification: confirmed permission gap in the supporting skeleton; trust exposure
is conditional because no publishing workflow or environment rules exist yet.
Primary references: P393, P395, P409, P476, P606; H CI outline.

The proposed PR operation cannot run with the shown contents read token and no
pull-requests write. A callee cannot elevate permissions denied by its caller [S01].
Repository/organization policy must separately permit Actions to create PRs [S12].
Subscription-scope Azure privileges make untrusted notebook execution a particularly
dangerous place to add repository write privileges or a broadly scoped PAT.

Replacement: keep images as sanitized artifacts for the initial version. If PR
automation is explicitly authorized, use a separate fresh job with no Azure login,
contents write and pull-requests write only, consuming only validated PNGs from the
exact successful trusted run/revision. Allowlist docs/assets/images paths, reject
symlinks/path traversal/non-PNG data and unexpected files, pin third-party actions,
and require human review. Do not checkout PR code under pull_request_target or trust
workflow_run artifacts solely by artifact name [S07]. Cloud jobs must run only from
approved refs under protected environment lab; never grant cloud credentials to
untrusted PR CI. Limit federation to the intended protected entry, rather than
silently adding a second branch-based trust path that bypasses environment gating.

Do not repeat the outdated blanket statement that GITHUB_TOKEN-created PRs never
trigger CI. Current GitHub documentation says opened/synchronize/reopened PR events
can create approval-required runs; ordinary token-generated push events still do not
trigger another run [S13]. A GitHub App or PAT changes that behavior and requires a
separate authorization decision. Do not introduce one solely to make checks green.

Acceptance tests: disabled create-PR policy, read-only caller, fork PR, non-main
dispatch, foreign/stale artifact, path traversal, and failed evidence validation must
not obtain write/cloud access or publish a PR. A permitted sanitized PNG-only PR must
show the expected approval/check behavior before a maintainer merges it.

### MAJOR A11 The bilingual site has no tested build and link contract

Classification: confirmed research naming conflict and verification gap, not proven
broken deployed links. Primary references: P391, P529, P540-P555, P599.

P529 maps token-limits images to lab02, consistent with the eight-lab table where
deployment is lab00 and setup is lab01. H sections 6.2-6.4 instead emit lab01 token
limits, lab02 metrics, lab03 safety, and lab04 pool. Copying both sources produces
incompatible asset references. There is currently no site source to build or crawl.

Replicating sibling relative switcher links is not proof they resolve with the new
permalinks, baseurl, and trailing-slash policy. The sibling uses .md links in hubs
alongside explicit extensionless permalinks; rewriting depends on the actual Pages
plugin/build configuration. P391 specifies only Python/Bicep/workflow checks, so it
does not catch missing EN/FR pages, images, navigation, or broken rendered links.

GitHub states that commits pushed using GITHUB_TOKEN do not trigger a branch-based
Pages build [S14]. That does not imply a human merge of the image PR is broken.
The publication actor matters. Keeping branch-based Pages is a valid small approach
when approved changes are merged by a maintainer; bot merge/push must not be assumed
to republish automatically. A later explicit Pages workflow is an alternative, not
a prerequisite for matching the sibling.

Replacement: one page/image manifest for lab00-lab07, paired EN/FR permalinks, and
baseurl-aware Liquid links for images, switchers, hub links, and next/previous links.
Keep README repository links distinct from site URLs. Build with the matching
github-pages/Jekyll dependencies in unprivileged CI, then crawl rendered output
under /AIGovernanceOffering/. Do not assume callouts configuration alone converts
GitHub alert syntax; visually verify or use the theme's supported markup.

Acceptance tests: build every EN/FR page, resolve each language switch in both
directions, check every image and internal anchor, and verify no old sibling baseurl
or duplicate permalink survives. Review mobile/desktop navigation and both home
pages. Verify one maintainer-merged image update reaches Pages; separately document
token-push suppression. These builds/browser checks were not run because no site
implementation exists and installation is out of scope.

## Small Recommended Approach

1. Keep unprivileged PR CI for unit tests, workflow validation, Bicep build, and a
	matching Jekyll build once the site exists. No Azure login in PR CI.
2. Implement one dispatch-only lifecycle workflow with a single lab lock and protected
	environment. Use ordinary scripts/steps for deployment, five notebook runs,
	bounded traffic, ingestion polling, report generation, and cleanup.
3. Establish target ownership before deployment. Add idempotent cleanup and a
	dispatch-only dry-run-first recovery entry using the same lock before enabling
	billable automation. Preserve initial failures after cleanup.
4. Add a five-notebook completion manifest and small structured objective results.
	Reject inconclusive safety/failover evidence as full demonstration success.
5. Publish sanitized artifacts first. Add PNG-only reviewed PRs only after the user
	chooses that publication model. Keep human-merged branch Pages initially.

Replace P394-P396's cron proposals with explicit dispatch for this first version.
Resource existence is not an authorization or spending-budget signal. A per-run
budget on a half-hourly schedule is not a total session budget. No automatic traffic,
nightly teardown, or recovery scheduling is recommended by this review.

## Official Evidence

Retrieved through fetch_webpage on 2026-09-28. These sources establish platform
semantics, not that the proposed workflows have passed a live test.

* S01: [Reusable workflow reference](https://docs.github.com/en/actions/reference/reusable-workflows-reference), supported caller keywords, env isolation, permission ceiling, and caller cancellation warning.
* S02: [Concurrency control](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency), running/pending semantics and default pending replacement. Current documentation also describes queue: max; this review does not require that additional feature.
* S03: [Workflow expressions](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#status-check-functions), implicit success(), always(), cancellation, and timeout cautions.
* S04: [GitHub OIDC](https://docs.github.com/en/actions/concepts/security/openid-connect), assertion exchange and example iat/exp difference of 300 seconds.
* S05: [Azure Login official action](https://github.com/Azure/login), Azure access-token lifetime, CLI login, action cleanup, and supported release guidance.
* S06: [Azure SDK AzureCliCredential implementation](https://raw.githubusercontent.com/Azure/azure-sdk-for-python/main/sdk/identity/azure-identity/azure/identity/_credentials/azure_cli.py), get_token cache disclaimer and CLI token acquisition. The Learn API page could not be extracted; official SDK source was used instead.
* S07: [GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use), register generated secrets, imperfect log masking, least privilege, third-party action pinning, and untrusted artifact/checkout risks.
* S08: [llm-content-safety](https://learn.microsoft.com/en-us/azure/api-management/llm-content-safety-policy), streaming violations stop forwarding events without a 403.
* S09: [APIM soft delete](https://learn.microsoft.com/en-us/azure/api-management/soft-delete), deleted-resource discovery, purge, name reuse, and subscription permissions. Current page states all tiers; this review does not assert that Basic v2 lacks soft delete.
* S10: [Foundry resource recovery and purge](https://learn.microsoft.com/en-us/azure/ai-services/recover-purge-resources), separate deleted-account namespace, retention, and subscription-level purge permission.
* S11: [set-backend-service](https://learn.microsoft.com/en-us/azure/api-management/set-backend-service-policy), base-URL substitution preserving the remaining request path.
* S12: [Repository Actions settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository), workflow permissions and allow-create/approve-PR policy.
* S13: [Triggering workflows](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-when-your-workflow-runs/triggering-a-workflow), current GITHUB_TOKEN PR approval exceptions and push suppression.
* S14: [Pages publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site), branch/docs builds, GITHUB_TOKEN push suppression, and custom-workflow alternative.

## Recommended Next Verification

* [ ] Run synthetic validator, sanitizer, teardown-resume, and config tests during implementation.
* [ ] Validate the lock/permission/call graph using harmless GitHub stand-in jobs.
* [ ] Verify actual OIDC subject and environment protections before federation bootstrap.
* [ ] Run an explicitly authorized Basic v2 wildcard/credential/failover and token-audience test.
* [ ] Confirm safety causation evidence with approved fixtures, or retain an unverified verdict.
* [ ] Perform an authorized partial-failure cleanup and same-name redeploy rehearsal.
* [ ] Build/crawl both languages and verify the chosen image-PR/Pages publishing actor.

GitHub's current OIDC overview notes immutable default subjects for repositories
created after 2026-07-15, while the Azure Login troubleshooting text discusses the
older subject format. P476 hardcodes the older format. Repository creation date and
actual subject were not inspected; match the actual non-secret subject metadata
rather than copying either format blindly. Do not print the JWT to determine it.

## Clarifying Questions

* Are sanitized artifacts plus maintainer-curated images acceptable for the first version,
  or must the first version create image PRs automatically?
* Who may approve cloud mutation, and is lab a dedicated RG with no shared resources?
* May automatic cleanup delete the dedicated environment after a failed run, and what
  manual recovery owner applies after force-cancellation or runner loss?
* Which approved safety fixtures and correlated evidence are available, or should the
  streaming objective remain explicitly unverified?

## Parent Instruction Requirements

Only this review file was authorized for changes. The primary and supporting research
remain untouched. Apply any accepted recommendations in a separately authorized task.
Markdown requires YAML frontmatter, ASCII punctuation, consistent asterisk bullets,
and no H1 when frontmatter contains title. Under .copilot-tracking, cite workspace
paths as plain relative paths, not links. Do not show notebook internal cell IDs.

Deferred tool discovery was unavailable in this agent's exposed tool set. No deferred
tool was invoked without discovery; official Azure/GitHub pages were verified with
the available fetch_webpage tool. Parent execution of Azure commands or code generation
must load the required Azure guidance and tool capabilities first. No live acceptance
test in this report should be interpreted as completed.