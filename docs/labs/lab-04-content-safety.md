---
permalink: /labs/lab-04-content-safety
title: "Lab 04 - Content safety"
description: "Apply llm-content-safety inbound and outbound, run a versioned test matrix, and classify every result as confirmed block, not tripped, transport error, or inconclusive."
nav_order: 14
---

**[Version française]({{ "/fr/labs/lab-04-content-safety" | relative_url }})**

> [!IMPORTANT]
> Use synthetic prompts only. LLM message logging stays off on every API, so the lab never records prompts or completions in telemetry; only token counts and bounded dimensions leave the gateway. Session images appear on this site only after a maintainer reviews sanitized evidence.

## Overview

{% assign prerequisite_url = "/labs/lab-03-token-metrics" | relative_url %}

| Item | Value |
| --- | --- |
| **Duration** | 35 minutes |
| **Level** | Intermediate |
| **Prerequisites** | [Lab 03]({{ prerequisite_url }}) completed and an Azure AI Content Safety resource configured in `.env` |

`notebooks/demo3-content-safety.ipynb` applies one policy in two directions. The inbound `llm-content-safety` instance checks prompts with the prompt shield and four harm categories (`Hate`, `SelfHarm`, `Sexual`, and `Violence`) on the 0 to 7 scale. The outbound instance re-checks completions with a sliding window, because models can produce unsafe content from benign prompts.

Choosing a threshold is a business decision for your Responsible AI reviewers, not an engineering default. The shipped defaults are `4` for every category.

> [!WARNING]
> Content safety results can be inconclusive. Every response is classified as `policy_block_confirmed`, `not_tripped`, `transport_error`, or `inconclusive`. A block counts only with policy-specific evidence, such as the content-safety error body or headers; a `403` without that provenance fails the safety objective. For streaming, a missing `[DONE]` event alone is `inconclusive`. An inconclusive required objective prevents any claim that every lab succeeded, and the privacy baseline is never weakened to obtain a result.

## Learning Objectives

By the end of this lab, you will be able to:

* Explain why inbound checks alone cannot protect completions
* Run a versioned fixture matrix instead of improvising harmful examples
* Classify each result by provenance rather than by status code alone
* Interpret a `not_tripped` result and choose an approved next step
* Explain how a streaming intervention differs from a `403`

## Exercises

### Exercise 4.1: Read the policy

```powershell
Get-Content policies/demo3-content-safety.xml
```

Expected result: two `llm-content-safety` elements. The inbound element sets `shield-prompt="true"`, the category thresholds from named values, and `enforce-on-completions="true"`; the outbound element sets `window-size` and `window-overlap-size`.

On a block, the `<on-error>` section returns a JSON body and the `x-content-safety-decision` and `x-content-safety-reason` headers as evidence.

### Exercise 4.2: Review the fixture rule

```powershell
Select-String -Path shared/fixtures.py -Pattern "FIXTURE_SET_VERSION"
```

Expected result: the fixture set carries a version stamp.

The shipped prompt-attack, harm-threshold, and streaming fixtures are mild, non-graphic placeholders that exercise the mechanism only. Replace them with your organization's pre-approved evaluation set before delivering the lab to an audience. Never improvise harmful examples live.

### Exercise 4.3 (Hands-on): Run the test matrix

Open `notebooks/demo3-content-safety.ipynb` and run through the test matrix.

Expected result: the safe business prompt returns `200` and records `demo3.safe_prompt`. The prompt attack returns `403` with content-safety provenance and records `demo3.prompt_shield_block`. The harm-threshold row is shown for discussion and may report **NOT TRIPPED**.

A **NOT TRIPPED** row means the fixture scored below the threshold. The approved responses are to substitute a pre-approved evaluation fixture or to lower the relevant `CONTENT_SAFETY_THRESHOLD_*` value for the demonstration only.

The automated lab session reads optional `AIGOV_CONTENT_SAFETY_THRESHOLD_*` repository variables, defaults each to `4`, and applies them as the Demo 3 threshold named values. Lowering a threshold is for demonstration only; production thresholds remain a Responsible AI business decision. A lower threshold does not guarantee a streaming intervention, because the model may keep its completion below every category threshold.

### Exercise 4.4 (Hands-on): Observe the streaming case

Run the streaming section.

Expected result: the notebook checks the HTTP status, requires `text/event-stream`, and parses the server-sent events. A confirmed intervention needs policy-specific evidence and records `demo3.stream_intervention` as passed; a stream that ends early without that evidence is `inconclusive`; a stream that completes with `[DONE]` is `not_tripped`.

The streaming objective is observational: whether the model's own completion crosses a category threshold is not deterministic, so `inconclusive` is reported as not verified and does not fail the session verdict. A `failed` result, such as a transport or protocol error, still fails it.

When the outbound policy detects a violation in a stream, APIM stops forwarding further events instead of returning `403`.

### Exercise 4.5: Review the session evidence

> [!NOTE]
> Reviewed evidence from session `36608221120-1` ([workflow run](https://github.com/devopsabcs-engineering/AIGovernanceOffering/actions/runs/36608221120)), rendered on 2026-09-29 from sanitized results only. The streaming check is observational: `inconclusive (not verified)` means the model output stayed below every category threshold, which is not proof of an intervention.

![Objective results for Lab 04 from the reviewed session]({{ '/assets/images/lab04-content-safety-summary.png' | relative_url }})

## Validation Checklist

* [ ] Both inbound and outbound `llm-content-safety` elements are present
* [ ] The fixture set version is recorded with the results
* [ ] Every matrix row has a classification, not only a status code
* [ ] Any `403` counted as a block carried content-safety provenance
* [ ] The three Demo 3 objectives have a recorded status

## Knowledge Check

* Why is a missing `[DONE]` event alone not proof of a safety intervention?
* Why does an unrelated authorization `403` fail the safety objective?
* Who decides the category thresholds, and why?
* What are the two approved responses to a **NOT TRIPPED** result?

## Next Steps

Continue to [Lab 05: Mock resilient backend pool]({{ "/labs/lab-05-resilient-pool" | relative_url }}).
