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

### Exercise 2.6: Review the session evidence

> [!NOTE]
> Evidence pending review. The images `lab02-token-limits-summary.png` (passed) or `lab02-token-limits-status.png` (any other status) are rendered from the Demo 1 objective results and appear here only after a maintainer reviews the sanitized session evidence.

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
