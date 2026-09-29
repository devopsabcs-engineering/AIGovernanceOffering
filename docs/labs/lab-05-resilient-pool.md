---
permalink: /labs/lab-05-resilient-pool
title: "Lab 05 - Mock resilient backend pool"
description: "Observe priority, weight, circuit-breaker, and spillover decisions in an APIM backend pool of mock members, then confirm real inference uses the same pool."
nav_order: 15
---

**[Version française]({{ "/fr/labs/lab-05-resilient-pool" | relative_url }})**

> [!IMPORTANT]
> Use synthetic prompts only. LLM message logging stays off on every API, so the lab never records prompts or completions in telemetry; only token counts and bounded dimensions leave the gateway. Session images appear on this site only after a maintainer reviews sanitized evidence.

## Overview

{% assign prerequisite_url = "/labs/lab-04-content-safety" | relative_url %}

| Item | Value |
| --- | --- |
| **Duration** | 35 minutes |
| **Level** | Advanced |
| **Prerequisites** | [Lab 04]({{ prerequisite_url }}) completed on an APIM tier that supports backend pools and circuit breakers |

`notebooks/demo4-resilient-pool.ipynb` builds a pool backend, `demo4-aoai-pool`, with two priority-1 members, `demo4-ptu-east` (weight 2) and `demo4-ptu-central` (weight 1), and a priority-2 spillover member, `demo4-payg`. Each member has a circuit breaker that trips on `429` and `5xx` responses and honors `Retry-After`. The API policy delegates selection to APIM with a single `set-backend-service` line, so the client request never changes.

> [!WARNING]
> The pool routes to mock members hosted on the same APIM instance. It demonstrates priority, weight, circuit-breaker, and spillover decisions; it does not prove live multi-region resilience or provisioned-throughput (PTU) behavior. The member names are labels, not real regions or reserved capacity. Real pool members must use the same model and version, or successful calls can silently drift.

## Learning Objectives

By the end of this lab, you will be able to:

* Explain per-call routing by priority, then weight, then health
* Distinguish routing mode, which uses mock members, from inference mode, which uses the real model
* Observe a circuit breaker trip on injected `429` responses and route to the alternate member
* Confirm recovery only after a recorded fault
* Explain why the mock API still requires its credential

## Exercises

### Exercise 5.1: Read the pool policy

```powershell
Get-Content policies/demo4-resilient-pool.xml
Get-Content policies/demo4-mock-origin.xml
```

Expected result: the API policy contains `<set-backend-service backend-id="demo4-aoai-pool" />`, and the mock-origin policy returns a chat-completions-shaped body with an `x-served-by` header, or an origin `429` with `Retry-After` when its fault switch is set.

### Exercise 5.2 (Hands-on): Make the inference baseline call

Open `notebooks/demo4-resilient-pool.ipynb` and run through the inference mode section.

Expected result: one call reaches the real model through the same pool policy. It proves the pool governs inference traffic; it does not identify a member, because real responses carry no `x-served-by` header.

### Exercise 5.3 (Hands-on): Observe routing and weighting

Run the CALL 1 and CALL 2 sections in routing mode.

Expected result: each unchanged client call shows its serving member in `x-served-by`, and 30 healthy calls split approximately 2:1 between East and Central. This records `demo4.routing_paths`.

The ratio is approximate. A small sample never promises an exact distribution, but an unknown or missing `x-served-by` value, a `404`, or an unexpected status fails the phase.

### Exercise 5.4 (Hands-on): Fault a member and spill over

Run the FAULT section.

Expected result: East returns the injected `429` responses and its breaker opens, Central then serves the priority-1 traffic, and when Central is also faulted, PAYG serves the spillover. This records `demo4.fault_observed` and `demo4.alternate_routing`.

A breaker that fails to trip is a failed objective, not a warning compatible with success. Every fault switch is healed in `finally`, and a separate heal-everything cell restores all mock members at any time.

### Exercise 5.5 (Hands-on): Recover

Run the RECOVER section.

Expected result: after the breaker period expires, East appears again in `x-served-by`. This records `demo4.recovery` only after a recorded fault.

### Exercise 5.6: Confirm the mock credential is enforced

Expected result: a direct call to the mock API without its credential is rejected. This negative probe records `demo4.mock_auth_enforced`. The mock is never made anonymous to fix routing.

### Exercise 5.7: Review the session evidence

> [!NOTE]
> Evidence pending review. The images `lab05-resilient-pool-summary.png` (passed) or `lab05-resilient-pool-status.png` (any other status) are rendered from the Demo 4 objective results and appear here only after a maintainer reviews the sanitized session evidence.

## Validation Checklist

* [ ] The client request was byte-identical in every phase
* [ ] Every routed call returned a known `x-served-by` member
* [ ] East faults preceded Central routing, and Central faults preceded PAYG routing
* [ ] Recovery was observed only after a recorded fault
* [ ] The mock API rejected a call without its credential

## Knowledge Check

* In what order does APIM evaluate pool members for each call?
* Why does a healthy East response without a preceding fault fail the recovery objective?
* What would you need to add to claim live multi-region resilience?
* Why must every real pool member use the same model and version?

## Next Steps

Continue to [Lab 06: Estimated model-token showback]({{ "/labs/lab-06-chargeback" | relative_url }}).
