---
permalink: /labs/lab-02-token-limits
title: "Lab 02 - Token limits and quotas"
description: "Apply llm-token-limit at API scope, trip a gateway 429 and a daily-quota 403 within a bounded envelope, and reset the counters instantly."
nav_order: 12
---

**[Version française]({{ "/fr/labs/lab-02-token-limits" | relative_url }})**

> [!IMPORTANT]
> Use synthetic prompts only. LLM message logging stays off on every API, so the lab never records prompts or completions in telemetry; only token counts and bounded dimensions leave the gateway. Session images appear on this site only after a maintainer reviews sanitized evidence.

## Overview

{% assign prerequisite_url = "/labs/lab-01-setup-validation" | relative_url %}

| Item | Value |
| --- | --- |
| **Duration** | 30 minutes |
| **Level** | Intermediate |
| **Prerequisites** | [Lab 01]({{ prerequisite_url }}) completed with a persisted `.env` |

AI workloads are billed and throttled by tokens, not requests. `notebooks/demo1-token-limits.ipynb` applies the provider-agnostic `llm-token-limit` policy at API scope so one element enforces both a tokens-per-minute limit, returning `429` with `Retry-After`, and a daily token quota, returning `403`.

A dedicated APIM subscription and an `x-demo-run` suffix in the policy counter key isolate this lab's counters from other runs, other demonstrations, and any other traffic on the same instance.

> [!NOTE]
> A backend `429` is not proof of the gateway limit. The `demo1.rate_limit_429` objective passes only with gateway provenance, such as the `remaining-tokens` policy headers, and a quota `403` is never evidence of a content safety decision.

## Learning Objectives

By the end of this lab, you will be able to:

* Read an `llm-token-limit` policy and name the attribute behind each observed status
* Interpret the `tokens-consumed`, `remaining-tokens`, and `remaining-quota-tokens` headers
* Distinguish a gateway tokens-per-minute `429` from a backend throttle and from a quota `403`
* Reset every counter for the lab without waiting for a window to roll over
* Explain how the session budget bounds the burst and accumulation loops

## Exercises

### Exercise 2.1: Read the policy

```powershell
Get-Content policies/demo1-token-limit.xml
```

Expected result: one `llm-token-limit` element sets `tokens-per-minute`, `token-quota`, `token-quota-period="Daily"`, `estimate-prompt-tokens="false"`, and a `counter-key` that combines the subscription ID with the `x-demo-run` header.

The limit values come from named values rather than literals, and the backend authenticates with the APIM managed identity. The policy strips the client subscription key header and query parameter before forwarding, so the key never reaches the model backend.

### Exercise 2.2 (Hands-on): Make a baseline call

Open `notebooks/demo1-token-limits.ipynb` and run the cells through the baseline call.

The baseline cell first sends unscored warm-up calls until the new API, subscription, and policy answer through the gateway. APIM applies new configuration asynchronously, so a fresh instance can return `404` or `401` for about a minute. The warm-up uses its own `x-demo-run` value, so the Demo 1 counters start clean.

Expected result: one `200` response with the three token headers present. This records the `demo1.baseline` objective.

With `estimate-prompt-tokens="false"`, `tokens-consumed` reflects the prompt and completion usage the model reported.

### Exercise 2.3 (Hands-on): Burst to a 429

Run the burst section.

Expected result: a bounded loop of rapid requests ends in a `429` with a `Retry-After` header, and the chart shows `remaining-tokens` falling across the burst. This records `demo1.rate_limit_429` when the gateway headers confirm the source.

### Exercise 2.4 (Hands-on): Accumulate to the daily 403

Run the accumulation section.

Expected result: the loop honors each `Retry-After`, `remaining-quota-tokens` decreases toward zero, and the gateway returns `403` once the daily quota is exhausted. This records `demo1.quota_exhausted`.

Both loops stop at a maximum iteration count and a wall-clock limit. In an automated session, every call also reserves input and maximum output tokens against the shared session envelope before it is sent, and a reservation that does not fit stops the loop with `BudgetExceeded`.

### Exercise 2.5 (Hands-on): Reset the counters

Run the reset section.

Expected result: a new `DEMO_RUN` value is persisted to `.env`, and the follow-up call succeeds immediately. This records `demo1.reset_recovery`.

The resources stay in place because later labs reuse the same APIM instance.

After the last cell, confirm the recorded objectives in a terminal:

```powershell
./scripts/show-results.ps1 -Notebook demo1-token-limits
```

```text
notebook           objective             status
--------           ---------             ------
demo1-token-limits demo1.baseline        passed
demo1-token-limits demo1.quota_exhausted passed
demo1-token-limits demo1.rate_limit_429  passed
demo1-token-limits demo1.reset_recovery  passed
```

### Exercise 2.6: Review the session evidence

> [!NOTE]
> Reviewed evidence from session `36608221120-1` ([workflow run](https://github.com/devopsabcs-engineering/AIGovernanceOffering/actions/runs/36608221120)), rendered on 2026-09-29 from sanitized results only.

![Objective results for Lab 02 from the reviewed session]({{ '/assets/images/lab02-token-limits-summary.png' | relative_url }})

This image comes from an automated workflow session, not from your notebook run; your own results are the `show-results.ps1` table above. To see the same tables and images for your own sessions, run `./scripts/show-evidence.ps1 -OpenPng` after the `run-existing` session in Lab 06. A `deploy-only` session reports this lab as `not_run`.

## Validation Checklist

* [ ] The baseline response carried all three token headers
* [ ] The `429` carried `Retry-After` and gateway provenance
* [ ] The `403` appeared only after `remaining-quota-tokens` reached zero
* [ ] A new `DEMO_RUN` value restored service immediately
* [ ] All four Demo 1 objectives have a recorded status

## Knowledge Check

* Which `llm-token-limit` attribute produces the `429`, and which produces the `403`?
* Why does a `429` from the model backend fail the `demo1.rate_limit_429` objective?
* How does changing `DEMO_RUN` reset the counters without touching the policy?
* Why can APIM token limits overshoot under concurrent traffic?

## Next Steps

Continue to [Lab 03: Token metrics]({{ "/labs/lab-03-token-metrics" | relative_url }}).
