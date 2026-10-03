---
permalink: /labs/lab-06-chargeback
title: "Lab 06 - Estimated model-token showback"
description: "Generate bounded team traffic on the platform API, reconcile token metrics against a usage manifest, and read an estimated model-token showback with its coverage and exclusions."
nav_order: 16
---

**[Version française]({{ "/fr/labs/lab-06-chargeback" | relative_url }})**

> [!IMPORTANT]
> Use synthetic prompts only. LLM message logging stays off on every API, so the lab never records prompts or completions in telemetry; only token counts and bounded dimensions leave the gateway. Session images appear on this site only after a maintainer reviews sanitized evidence.

## Overview

{% assign prerequisite_url = "/labs/lab-03-token-metrics" | relative_url %}

| Item | Value |
| --- | --- |
| **Duration** | 30 minutes, including ingestion delay |
| **Level** | Advanced |
| **Prerequisites** | [Lab 03]({{ prerequisite_url }}) completed and a deployed session environment |

The platform API `ai-gateway-api`, served at `/ai-gateway`, has three team products, `team-retail`, `team-finance`, and `team-hr`. Each has its own product-scoped subscription (`team-retail-sub`, `team-finance-sub`, and `team-hr-sub`) and its own limits: 3,000, 2,000, and 1,000 tokens per minute, and 30,000, 20,000, and 10,000 tokens per day. The gateway derives the team from the authenticated subscription, never from a caller header. `scripts/generate_traffic.py` sends a small, bounded workload per team, and `scripts/showback_report.py` turns the resulting token metrics into an estimated showback.

> [!WARNING]
> Every output is labelled `Estimated model-token showback (USD retail)` with its UTC interval, price snapshot, coverage state, and exclusions. It is an estimate at uncached retail prices, not a billed chargeback. It excludes shared APIM, logging, Content Safety, networking, taxes, contract discounts and adjustments, prompt-cache discounts, and provisioned-throughput pricing. Missing, duplicated, or unpriced coverage suppresses the total, and missing telemetry is reported as incomplete, never as zero. Reconcile with Cost Management or the invoice before using any figure financially.

## Learning Objectives

By the end of this lab, you will be able to:

* Explain how team attribution comes from subscription mapping and why `ClientApp` stays a caller assertion
* Describe the bounded traffic envelope and its fixed half-open UTC window
* Reconcile metric sums against the response-usage manifest
* Read the coverage state, reconciliation status, and exclusions of a showback report
* Explain which subscriptions can bypass product quotas

## Exercises

### Exercise 6.1: Read the team attribution design

```powershell
Get-Content policies/platform-ai-gateway.xml
Get-Content policies/platform-team-product.xml
```

Expected result: the platform policy emits one token metric with the dimensions `API ID`, `Subscription ID`, and `ClientApp`, normalizes `ClientApp` against the allowlist `retail-web`, `finance-batch`, and `hr-assistant`, reporting any other value as `unknown`, and deletes the `Ocp-Apim-Subscription-Key` header, the `subscription-key` query parameter, and any `api-key` header before forwarding. The team product policy applies `llm-token-limit` with a `counter-key` of the subscription ID.

### Exercise 6.2 (Hands-on): Run the bounded traffic session

Traffic runs inside a `full-session` or `run-existing` session after readiness and scope probes pass. Start a `run-existing` session against the generation you deployed in Lab 00:

```powershell
./scripts/run-lab-workflow.ps1 -Mode run-existing
```

Approve the run on the page that opens. The session reruns the five notebooks headlessly, sends the team traffic, writes the showback report, and never deletes resources. It takes about 15 minutes, and the script then prints the evidence.

Expected result: every lab from `lab00-environment` to `lab06-chargeback` is `passed`, and `lab07-teardown` is `not_run`. You can state the traffic defaults: one worker, 30 attempts, 128 maximum output tokens, 10,000 reserved tokens, a five-minute deadline, serial non-streaming calls, and no retries. Keys are retrieved privately and never printed, and every call reserves against the session envelope.

The generator records a response-usage manifest and a fixed half-open UTC window in `outputs/showback/<session_id>/manifest.json`. A workflow lock does not stop human traffic, so a window that contains unaccounted calls is rejected as contaminated.

### Exercise 6.3: Read the showback report

The evidence the script printed ends with the showback. To print it again for the latest session:

```powershell
./scripts/show-evidence.ps1
```

```text
Estimated model-token showback (USD retail) | 2026-10-03T09:25:00Z to 2026-10-03T09:27:00Z (half-open UTC)
coverage complete | reconciliation reconciled | snapshot retail-2026-09-29-gpt-4.1-mini-canadaeast

team         prompt_tokens completion_tokens estimated_usd
----         ------------- ----------------- -------------
team-finance           190               155 0.00039204
team-hr                180               221 0.000514976
team-retail            190               237 0.000550792

total estimated_usd 0.001457808 (complete)
```

Expected result: the report queries one representation only, the Application Insights `customMetrics` table summed by `valueSum`, scoped to the component, the observed metric namespace, the platform API, the three teams, and the window. It reconciles prompt and completion sums against the manifest within an explicit tolerance and prices them with exactly one rate per model, version, SKU, region, currency, effective period, and unit from `scripts/prices/<snapshot>.json`.

A report with complete coverage shows totals. A report with partial coverage labels known values as partial. A report with missing usage, attribution, or prices suppresses the total and records the unattributed, unpriced, failed, and ambiguous counts.

### Exercise 6.4 (Hands-on): Run a report-only session

```powershell
./scripts/run-lab-workflow.ps1 -Mode report-only
```

Without a window, the script reuses the interval from the latest successful `run-existing` or `full-session` session. To choose your own window, pass `-WindowStart 2026-10-03T09:00:00Z -WindowEnd 2026-10-03T10:00:00Z`. The equivalent raw command is:

```powershell
gh workflow run lab-session.yml -f mode=report-only -f generation=<generation> -f confirm_resource_group=<resource-group> -f report_window_start=<start-utc> -f report_window_end=<end-utc>
```

Expected result: the window is accepted only when both values are UTC, the start precedes the end, the end is not in the future, and the span is at most 24 hours. Without a traffic manifest, the report is labelled `unreconciled` and never claims a complete total. The environment is preserved whatever the outcome.

### Exercise 6.5: Know the quota bypass

Expected result: you can explain that product policies do not apply to API-scoped, all-APIs, or built-in all-access subscriptions. The session's scope probe records the behavior of product-scoped team keys, a temporary API-scoped test subscription that is deleted afterwards, and the anonymous path, which must return `401`. The built-in all-access key is never used.

### Exercise 6.6: Review the session evidence

> [!NOTE]
> Reviewed evidence from session `36608221120-1` ([workflow run](https://github.com/devopsabcs-engineering/AIGovernanceOffering/actions/runs/36608221120)), rendered on 2026-09-29 from sanitized results only. Amounts are estimated model-token showback at retail prices, not billed charges.

![Estimated model-token showback by team from the reviewed session]({{ '/assets/images/lab06-chargeback-summary.png' | relative_url }})

![Prompt and completion tokens by team from the reviewed session]({{ '/assets/images/lab06-chargeback-tokens.png' | relative_url }})

## Validation Checklist

* [ ] Every chart and table carries the estimated showback label, interval, snapshot, coverage, and exclusions
* [ ] The window was exclusive to the approved traffic
* [ ] Metric sums reconciled with the usage manifest, or the report says why not
* [ ] No complete total appears when any coverage is missing
* [ ] Report-only output is labelled `unreconciled`

## Knowledge Check

* Why does the slug say chargeback while every output says estimated showback?
* Why is summing both `customMetrics` and workspace `AppMetrics` a double count?
* Which costs does the estimate exclude, and why?
* What makes a measurement window contaminated?

## Next Steps

Continue to [Lab 07: Teardown and residual cost exposure]({{ "/labs/lab-07-teardown" | relative_url }}).
