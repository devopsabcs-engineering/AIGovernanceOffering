---
title: Adversarial telemetry and estimated showback review
description: Correctness review of APIM telemetry, pricing, ownership, and privacy proposals.
ms.date: 2026-09-28
---

## Research scope

Status: Complete as a source-backed research review. Runtime acceptance remains
unverified. No deployments or application changes were performed.

Primary: .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md

Supporting: .copilot-tracking/research/subagents/2026-09-28/chargeback-traffic-research.md

Questions cover join cardinality, retries and multirow logs, resource and run isolation,
model-price mapping, cached tokens, pricing units, estimated versus billed cost,
metric aggregation and attribution, budget semantics, policy inheritance, logger
ownership and authentication, privacy, and provisioning dependencies.

Working hypothesis: the proposed event-log query does not establish a unique
billable observation or complete price coverage. The cheapest discriminating
checks are the official table and diagnostic schemas, followed by synthetic
cardinality cases and a gated live reconciliation before implementation acceptance.

## Findings

### HIGH F1 Unsupported privacy configuration blocks deployment

Primary lines 335 and 605 prescribe or offer `messages: 'none'`. The pinned
[2024-06-01-preview diagnostic schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.apimanagement/2024-06-01-preview/service/apis/diagnostics#llmmessagediagnosticsettings)
allows only `messages: 'all'`; `maxSizeInBytes` has a minimum of 1. Therefore
neither `none` nor a zero-byte LLM message block is a documented solution.
The separate HTTP `body.bytes: 0` setting does not prove that LLM message
capture is disabled. Supporting section 2 acknowledges uncertainty but the
primary converts it into selected implementation syntax.

Replacement: leave LLM diagnostics disabled for the first estimated-showback
lab. Use token metrics and HTTP body logging disabled. A later, explicitly
approved experiment may test `logs: 'enabled'` without request/response blocks,
but omission is not evidence of privacy or token-row availability. Do not
fall back to `messages: 'all'` to make a deployment pass.

Acceptance gate: inspect deployed diagnostics and send unique synthetic prompt
and completion canaries; confirm their absence from all relevant telemetry
tables and exported artifacts after ingestion settles. Require approval,
access controls, and retention limits before enabling any body capture.
No live privacy test was performed in this review.

Existing-code evidence strengthens this finding: shared/apim.py line 521 sets
both LLM request and response `messages` to `all`, with 8192-byte limits, in
`ensure_api_diagnostic`. Demo 2 invokes that helper for its own API. Its preview
version is `2025-09-01-preview`, while the primary proposal pins an older
version. The [newer schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.apimanagement/2025-09-01-preview/service/apis/diagnostics)
also permits only `all` and still lists `logs`; the helper docstring's claim
that `logs` is invalid is not established by that published schema. Do not
treat a diagnostic fallback or a comment as privacy evidence. Include notebook
APIs, not only the platform API, in the canary test and ownership contract.

### HIGH F2 Event-log joins do not establish accounting cardinality

Primary lines 343 through 355 filter `DeploymentName != ''`, discard backend
request identity, and join on `CorrelationId` alone before `count()` and sums.
The [LLM table schema](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/apimanagementgatewayllmlog)
defines `RequestId` as the language model request ID and `SequenceNumber` as
the index in a message exchange. It does not promise one nonempty deployment
row per gateway request. The
[gateway table](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/apimanagementgatewaylogs)
also carries resource and API identifiers omitted by the query.

Two usage rows joined to two matching gateway rows yield four rows, not two.
Conversely, deduplicating everything by correlation can discard distinct
backend attempts. Retries and message fragments must not be conflated.
This is a proven query vulnerability, not a claim that duplicates necessarily
occur on every Basic v2 deployment.

Replacement: keep event-log accounting optional. Retain `_ResourceId`,
`CorrelationId`, `RequestId`, `SequenceNumber`, model/deployment, timestamps,
and usage fields during characterization. Establish separately the identities
of frontend requests, backend attempts, message fragments, and usage records.
Require unique gateway attribution on resource plus correlation before a
many-to-one join. Quarantine conflicting rows; do not use arbitrary `arg_max`,
`distinct`, or `max(TotalTokens)` as an accounting repair. Sum distinct
attempt usage only after proving how retries are represented.

Acceptance gate: exercise one normal call, a multirow exchange, client retry,
gateway retry, repeated telemetry delivery, and a failure after backend work.
Synthetic two-by-two joins must be detected; repeated copies must not inflate
totals; distinct billable attempts must remain distinct. Report gateway request
count separately from observed backend attempt count. If attempt coverage
cannot be proven, label it incomplete and do not promote it to chargeback.

### HIGH F3 Token-price telemetry is an estimate, not billed cost

Primary lines 304 and 337 call the joined logs the source of truth; supporting
section 3a calls single-model datatable pricing exact and its summary calls
LLM logs best for billing. These claims exceed the available evidence.
[Microsoft cost guidance](https://learn.microsoft.com/en-us/azure/foundry/concepts/manage-costs)
explicitly assigns financial reconciliation to Cost Management and invoiced
charges, and says HTTP status alone does not determine billing.

Replacement: call the output `Estimated model-token showback (USD retail)`.
State that it allocates observed gateway token usage, excludes platform,
Content Safety, logging, networking, taxes, and contract adjustments, and may
miss backend work without usage telemetry. Use Cost Management meter records
and the invoice for actual charges. Neither APIM subscriptions nor client-app
headers automatically become Azure billing dimensions.

Acceptance gate: every table, chart, lab description, and workflow summary
must carry the estimate label, price snapshot and UTC interval. Any later
financial chargeback must reconcile the same resource and time scope to
billing meters and document allocation of shared costs and residual variance.

### HIGH F4 Claimed caps are not financial hard ceilings

Primary line 374 inherits the supporting section 5 budget design. That script
tests the token budget only before normal calls, records missing usage as zero,
and executes `HR_BURST` outside both `MAX_REQUESTS` and `RUN_TOKEN_BUDGET` guards.
The supporting claim that APIM caps worst case is also too strong:
[token-limit documentation](https://learn.microsoft.com/en-us/azure/api-management/llm-token-limit-policy#considerations-for-token-counts-and-estimation)
allows overshoot before responses arrive, especially with concurrent calls or
prompt estimation disabled. TPM capacity is a rate allocation, not a monetary
budget. [Azure budgets](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets)
notify on delayed cost data; they do not stop consumption.

Replacement: use one serial dispatch guard for normal calls, every retry, and
the HR burst. Bound prompt size, completion size, attempts, elapsed time, and
estimated spend; reserve conservative input/output cost before dispatch. Stop
on unpriced usage or ambiguous failed requests rather than assuming zero.
Describe the result as bounded lab traffic, not a guaranteed Azure bill limit.
Keep scheduled traffic opt-in and require an environment expiry/teardown plan.

Acceptance gate: zero request budget, insufficient remaining reservation,
missing usage, timeout, retry, and burst tests must all stop dispatch correctly.
All HTTP attempts count against the same limit. Document possible overshoot
and costs that accrue even with no model calls. A delayed suspension workflow
is a soft circuit breaker, not a hard ceiling.

### HIGH F5 Resource and run isolation are absent from cost queries

Primary lines 343 through 355 use rolling 30-day filters without fixed run
boundaries or APIM resource, API, revision, or run filtering. A shared
workspace can contain multiple gateways and notebook APIs. A time filter does
not identify a run; simultaneous traffic and subsequent reruns can contaminate
results. Joining on correlation alone also ignores resource boundaries. The
[gateway schema](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/apimanagementgatewaylogs)
provides `_ResourceId`, `ApiId`, and `ApiRevision` for explicit scoping.

Replacement: persist a run manifest with normalized resource IDs, API/revision,
deployment configuration, request identifiers, and a fixed UTC start/end.
Use the same half-open interval, `start <= timestamp < end`, across all queries.
For optional event logs, use a validated bounded run marker or a manifest
request set in addition to the interval, and join on resource plus correlation.
Validate captured header names and casing rather than assuming
`RequestHeaders['x-client-app']` resolves. Missing attribution must appear as
unknown, not silently disappear. Define how attempts spanning the interval
boundary are assigned and fetch the needed correlation context accordingly.

Acceptance gate: seed unrelated API, resource, prior-run, concurrent-run, and
boundary-time observations. None may affect the target run totals. A metric
baseline without a run dimension must use exclusive traffic windows and reject
overlap; preaggregated metric buckets cannot be split into exact per-run usage.
Use bounded ingestion polling and report incomplete telemetry rather than
equating a fixed sleep with completeness. APIM logging is
[asynchronous](https://learn.microsoft.com/en-us/azure/api-management/observability).

### HIGH F6 Model normalization cannot establish complete prices

Primary lines 339 through 359 hard-code family rates and use a regex to strip
model dates. This is not demonstrated to be a syntactically broken regex; the
defect is treating its output as a pricing identity. It accepts only `gpt-`
names, loses versions, and cannot resolve arbitrary deployment aliases. A
deployment fallback is not a model-family lookup. An unmatched
[extract](https://learn.microsoft.com/en-us/kusto/query/extract-function)
returns null; the left price join then produces null cost. Kusto
[sum](https://learn.microsoft.com/en-us/kusto/query/sum-aggregation-function)
ignores nulls, and [summarize](https://learn.microsoft.com/en-us/kusto/query/summarize-operator)
defaults sums to zero. Unknown-price usage can therefore look free or disappear
inside an understated total. Duplicate price keys produce another fan-out.

Replacement: map the configured resource/deployment to a pinned model, version,
deployment SKU, pricing region, currency, effective interval, and explicit rate
unit. Record the price source and retrieval date. Enforce one applicable price
record per observation; surface unpriced request/token counts and suppress any
complete-cost claim when coverage is missing or ambiguous. Do not repair this
with `coalesce(CostUsd, 0)` or an inner join that drops unknowns. The
[Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
requires interpreting meter, SKU, region, effective dates, units, and pagination;
its retail rates do not establish a customer's negotiated charges. Global
deployment pricing must not be inferred from an assumed execution region.

The [prompt caching documentation](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/prompt-caching)
also identifies discounted cached input in `prompt_tokens_details.cached_tokens`.
For applicable token-priced models, cached input is a subset of prompt tokens:
price uncached input as `PromptTokens - CachedTokens`, cached input separately,
and completion tokens once, each divided by its stated rate unit. The published
LLM table has no dedicated cached-token column. Missing cache detail is not
evidence of zero cached tokens. Provisioned throughput and other billing modes
must not use a pay-as-you-go token formula without qualification.

Acceptance gate: fixtures cover versioned names, deployment aliases, non-GPT
models, unknown models, duplicate prices, price-effective boundaries, and
per-million versus per-thousand rates. Cached input must never be added on top
of prompt input. For the first lab, permit an explicitly labeled uncached
retail-rate approximation with cache discounts excluded; remove supporting
line 354's claim that a single model makes datatable pricing exact.

### HIGH F7 Metric completeness and attribution need explicit contracts

Primary line 304 selects metrics for dashboards, and the API policy preceding
line 335 uses caller-supplied app labels. Supporting lines 326 through 352
correctly distinguish component `customMetrics` from workspace `AppMetrics`,
but this alone does not establish complete or trusted allocation. The
[token metric policy](https://learn.microsoft.com/en-us/azure/api-management/llm-emit-token-metric-policy)
limits custom dimensions and active series; excessive cardinality can discard
data. An arbitrary `x-client-app` can spoof an app or exhaust cardinality even
when the supplied traffic generator uses an allow-list.

Replacement: derive team identity from the authenticated subscription; perform
app allow-list normalization at the gateway, assigning unknown values to one
bounded label. Treat app labels as caller assertions, not authenticated identity.
Keep run IDs, prompts, user IDs, and arbitrary headers out of metric dimensions.
Reserve the five-custom-dimension, 100-values-per-dimension, and 1000-active-series
limits in the design, accounting for automatic dimensions and actual traffic.

Use `sum(valueSum)` in the component representation or `sum(Sum)` in the
workspace representation, never both added together. In
[AppMetrics](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/appmetrics),
`ItemCount` counts measurements represented by the aggregate; it is not another
multiplier for `Sum`. Do not add prompt, completion, and total-token metrics
together, or use metric row count as request count. Custom metrics are distinct
from sampled request events; do not copy event sampling weights into metric
queries. Diagnostic sampling at 100% does not prove lossless delivery.

Acceptance gate: scope the chosen App Insights component/resource, observed
namespace, API dimension, team mapping, and interval. Validate the emitted
dimension names against a captured metric, and reconcile prompt/completion
sums with a small non-streaming response manifest. Inject unknown app values
and inspect effective policies for one emitter execution per intended request.
Streaming interruptions and retries require separate reconciliation before
inclusion. Inspect all inherited scopes for duplicate policy emissions.
[API-level diagnostics normally override service-level diagnostics](https://learn.microsoft.com/en-us/azure/api-management/api-management-howto-app-insights);
their coexistence is not itself proof of duplicate emission. Avoid automatic
deduplication of identical aggregate rows, which may represent real measurements.

### HIGH F8 Product quotas are bypassable by other subscription scopes

Primary line 335 places team token limits at product scope. According to
[APIM subscriptions](https://learn.microsoft.com/en-us/azure/api-management/api-management-subscriptions),
product policies do not apply to API-scoped, all-APIs, or built-in all-access
subscriptions. API and operation
[policy inheritance](https://learn.microsoft.com/en-us/azure/api-management/api-management-howto-policies)
also depends on `<base />`. A product policy alone cannot be described as a
universal gateway budget control.

Replacement: constrain the supported traffic path to approved product-scoped
team subscriptions, validate subscription requirements and product membership,
and explicitly document privileged-key bypass. If enforcement must cover other
scopes, design the control at the relevant API/service scope and retain trusted
team attribution. Review effective policy ordering, not just individual XML
files. Do not unintentionally count the same counter at multiple scopes.

Primary line 361 also says all 429s avoid backend work. Backend 429s and retries
invalidate that claim. The [token-limit policy](https://learn.microsoft.com/en-us/azure/api-management/llm-token-limit-policy)
uses 429 for rate limits and 403 for quotas; 403 is not uniquely a safety block.
Use backend status and policy/error provenance to classify failures rather than
HTTP status alone. The [retry policy](https://learn.microsoft.com/en-us/azure/api-management/retry-policy)
executes the child once before retrying, so a retry count is not total attempts.

Acceptance gate: exercise product, API, all-access, and anonymous access paths;
confirm expected enforcement and inherited policy order. Distinguish gateway
throttle, quota rejection, backend throttle, and safety rejection with controlled
fixtures. Strip subscription credentials before forwarding where applicable;
APIM forwards subscription keys by default.

### HIGH F9 Logger authentication and notebook ownership conflict

Primary lines 191 and 230 through 237 deliberately retain local authentication
and connection-string-only logger credentials. Supporting lines 167 and 200
instead prescribe disabled local auth and a managed-identity logger. These are
different configurations, not interchangeable hardening options. Per
[APIM App Insights integration](https://learn.microsoft.com/en-us/azure/api-management/api-management-howto-app-insights),
managed-identity ingestion requires the identity credential on the logger plus
Monitoring Metrics Publisher on the component. A role assignment alone does
not convert a connection-string-only logger to managed-identity ingestion.

Local evidence: shared/apim.py line 426 performs a logger PUT whose credentials
contain only `connectionString`; line 470 discovers the first Application
Insights logger rather than a named owner. Demo 2 uses its own
`demo2-application-insights` logger, so direct overwrite of platform `apimlogger`
is not proven. However, reusing the helper with a platform ID can replace its
credential configuration, and first-logger discovery can select the wrong
destination when more than one exists. Primary line 568's cleanup must preserve
the same resource ownership boundary.

Replacement: declare one owner for each logger and diagnostic, pin resource
IDs, and keep platform resources separate from notebook resources. Select one
explicit lab authentication contract. Retaining local auth for compatibility
is a documented exception, not MI-only security; adopting MI-only requires
compatible notebook behavior first. Do not silently enable local auth as a
fallback. Include the body-logging behavior in F1 in this contract.

Acceptance gate: capture redacted logger/diagnostic configuration before and
after notebook configure, rerun, and cleanup. Platform IDs, destination, identity
credential, and privacy settings must remain unchanged. Test ingestion under
the selected local-auth setting, including a deliberate incompatible-credential
case. Do not print credentials or subscription keys into workflow artifacts.

### MAJOR F10 Bootstrap permissions and readiness need separate gates

Primary line 176 proposes optional grants of API Management Service Contributor
and Log Analytics Reader to `ciPrincipalId`, while line 476 constrains bootstrap
role assignment to three other roles. A condition allowing only those three
does not authorize the optional grants. Deployment permissions, runtime model
permissions, telemetry ingestion permissions, and telemetry query permissions
are separate prerequisites.

Replacement: publish an explicit permission matrix by principal and scope.
Either authorize the optional grants during bootstrap or make them a separately
performed administrator step; do not assume subscription Contributor can assign
roles. Validate `Microsoft.Authorization/roleAssignments/write` and applicable
conditions. Follow [RBAC troubleshooting guidance](https://learn.microsoft.com/en-us/azure/role-based-access-control/troubleshooting)
for principal replication and role propagation; use service-principal type for
new managed identities and deterministic role-assignment names incorporating
scope, principal ID, and role ID to handle recreation.

Acceptance gate: a preflight verifies subscription deployment scope, provider
registration, supported API versions/locations, Basic v2 availability, model
version/SKU availability and quota, and network reachability. The
[resource-provider guidance](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/resource-providers-and-types)
does not make provider registration proof of model capacity. Separate ARM
success from bounded readiness checks for APIM, backend inference, safety,
ingestion, and log queries. Retry transient propagation with a deadline and a
specific failure report, not an indefinite delay or broader permission grant.

## Recommended minimal baseline

Replace primary line 304's selected architecture with the following contract:

> The first lab provides estimated model-token showback for one pinned
> deployment using one effective App Insights token-metric emitter. It uses
> bounded non-streaming synthetic traffic, trusted subscription-to-team mapping,
> gateway-normalized app labels, and exclusive fixed UTC measurement windows.
> Prompt and completion metric sums are priced once using a versioned retail
> rate snapshot with explicit units and exclusions. Unknown usage or incomplete
> telemetry prevents a complete-total claim. Cached-token discounts are excluded
> unless separately observed and validated. Azure billing meters and invoices
> remain the financial source of truth. Prompt/completion body capture is off.
> Event-log detail is optional and gated by privacy, grain, join, and retry tests.

Keep deployment/model identity in the run manifest and price snapshot for this
single-model path; do not infer it from a regex or imply a metric contains model
dimensions it has not emitted. Disable retries initially to simplify observed
usage reconciliation, while retaining conservative handling of ambiguous failures.
Use a dedicated API/window or reject overlap with notebook and scheduled runs.
If exact per-run isolation is required during concurrent activity, metric-only
aggregation is insufficient; defer that requirement to the validated event path.

## Acceptance gates

These are implementation acceptance criteria, not tests passed by this review.

* Validate diagnostic schemas at the pinned API versions and inspect effective diagnostics after notebook execution. Privacy canaries must be absent from telemetry and exported artifacts, not merely hidden by workbook projection.
* Replay deterministic join fixtures: two-by-two matches must not multiply cost; repeated telemetry must not inflate usage; legitimate retry attempts must not be erased. Characterize real rows before selecting a deduplication key.
* Reject unknown/duplicate prices and validate units, effective dates, model version/SKU, cached input, and explicit exclusions with hand-calculated cases.
* Scope all queries to fixed resource/API/window identifiers and prove unrelated and overlapping traffic cannot enter accepted totals. Mark missing telemetry as incomplete; do not turn it into zero usage.
* Verify one effective emitter, one chosen metric representation, correct sums, bounded dimension values, and gateway-enforced header normalization.
* Exercise all traffic dispatch paths against one reservation and attempt cap, including burst, retry, timeout, missing usage, and zero-budget cases.
* Test quota inheritance and bypass scopes; classify gateway and backend errors independently of financial billing assumptions.
* Verify logger ownership and ingestion authentication before/after notebook setup, rerun, cleanup, and environment recreation. Prove runtime/query access independently of provisioning success.
* Keep scheduled traffic disabled until the above baseline gates pass. Enable optional LLM event logging only after explicit privacy approval and live validation of attempt coverage, event grain, join cardinality, and price coverage.

No KQL, regex fixtures, live traffic, price-meter lookup, or deployment was
executed. Published schemas and source inspection establish the defects and
risks above; actual ingestion shape and privacy guarantees remain live gates.
The reviewed rates are examples, not a validated current pricing snapshot.

## Instruction constraints for the parent

Both requested instruction files were read in full. Use YAML frontmatter first;
with a title field, start content at H2 and omit H1. Use ASCII punctuation, no em
dashes, sequential heading levels, blank lines around headings and blocks,
consistent asterisk bullets, language-tagged fences, no trailing whitespace, and
exactly one final newline. Align table pipes if tables are used. Use precise,
professional, actionable prose; avoid filler and bolded-prefix bullet labels.
For research artifacts under .copilot-tracking, use plain workspace-relative
paths for local evidence and linked external URLs, following researcher mode.

## Follow-up and clarifications

* [ ] Obtain a redacted live event/metric fixture from the target Basic v2 version in an approved test environment; establish retry and multirow semantics.
* [ ] Resolve whether token-only event logging is supported without message capture for the selected API version; retain metric-only default until proven.
* [ ] Resolve the deployment's exact model/version/SKU and applicable price meters, including cached-input treatment and effective dates.
* [ ] Confirm the deployment principal's actual role-assignment conditions and query rights, then perform the acceptance gates in a separate authorized run.

User decisions still required: whether the deliverable is illustrative showback
or financially reconciled chargeback; whether local-auth compatibility is an
accepted lab exception; whether any prompt/completion logging is permitted;
and whether concurrent runs require exact independent allocation. None prevents
adopting the minimal estimated-showback baseline with body capture disabled.

Azure tool discovery was unavailable in this session. Official Microsoft Learn
schemas and documentation were fetched directly as the permitted fallback.
