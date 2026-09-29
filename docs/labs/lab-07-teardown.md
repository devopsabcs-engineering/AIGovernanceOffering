---
permalink: /labs/lab-07-teardown
title: "Lab 07 - Teardown and residual cost exposure"
description: "Remove only the resources a session owns, starting with a dry run, and read the residual report of active resources, soft-deleted tombstones, failures, and continuing exposure."
nav_order: 17
---

**[Version française]({{ "/fr/labs/lab-07-teardown" | relative_url }})**

> [!IMPORTANT]
> Use synthetic prompts only. LLM message logging stays off on every API, so the lab never records prompts or completions in telemetry; only token counts and bounded dimensions leave the gateway. Session images appear on this site only after a maintainer reviews sanitized evidence.

## Overview

{% assign prerequisite_url = "/labs/lab-00-environment" | relative_url %}

| Item | Value |
| --- | --- |
| **Duration** | 30 minutes, plus approval and deletion time |
| **Level** | Intermediate |
| **Prerequisites** | [Lab 00]({{ prerequisite_url }}) completed and reviewer rights on the `lab` GitHub environment |

Two paths delete resources. In `lab-session.yml`, `cleanup --auto` applies the mode's cleanup rule to resources recorded by the current session's own manifest. The manual `teardown.yml` workflow is the only other path. Both validate the tenant, subscription, resource group, and manifest ownership, and both refuse unexpected resources and resource locks instead of broadening scope.

> [!CAUTION]
> Teardown runs as a dry run by default; deletion requires `execute=true` and a typed resource group confirmation. Ordinary deletion leaves soft-deleted tombstones: APIM and Cognitive Services are recoverable for 48 hours and the Log Analytics workspace for 14 days, so names stay reserved and exposure is reported rather than assumed to be zero. Purge is irreversible and human-only. No workflow ever purges.

## Learning Objectives

By the end of this lab, you will be able to:

* Name the two deletion paths and the scope each one may touch
* Read a dry-run plan that separates active resources from recoverable tombstones
* Execute an ownership-validated teardown that keeps the resource group and bootstrap-owned resources
* Interpret the residual report and its non-success conditions
* Explain why purge is a separate, human-only operation

## Exercises

### Exercise 7.1 (Hands-on): Run a teardown dry run

```powershell
gh workflow run teardown.yml -f confirm_resource_group=<resource-group> -f generation=<generation>
```

Expected result: after environment approval, the job loads the newest valid manifest record for the generation, verifies its hash, and lists the exact planned targets, distinguishing active resources from tombstones. Nothing is deleted.

A tenant, subscription, or resource group mismatch, an unexpected resource, ambiguous ownership, or a lock stops the run. Locks are never removed automatically.

### Exercise 7.2 (Hands-on): Execute the teardown

```powershell
gh workflow run teardown.yml -f confirm_resource_group=<resource-group> -f generation=<generation> -f execute=true
```

Expected result: model deployments are deleted first to release quota, then the remaining owned resources in dependency order. The empty lab resource group, the identity resource group with the APIM user-assigned identity, and the manifest records are kept.

Each target is processed independently with bounded retries. A confirmed `404` means absent; a `403`, a timeout, or a discovery failure is an error, not a success.

### Exercise 7.3: Read the residual report

```powershell
Get-Content outputs/residual/<session_id>/report.json
```

Expected result: the report lists active resources, soft-deleted tombstones, failed actions, quota-release status, and known or unknown continuing exposure. Expected tombstones of owned resources are listed separately and do not fail the run; any active owned resource, unexpected resource, or failed deletion produces a non-success exit.

An absent resource group or a requested deletion is not proof of zero spend. The residual report and each provider's state determine remaining exposure.

### Exercise 7.4: Understand the human-only purge

```powershell
python scripts/lab_session.py purge --help
```

Expected result: the help text describes `purge --execute`, which lists the exact tombstones recorded in the manifest, requires a typed confirmation of every name, and refuses anything not inventoried.

Only an approved operator runs purge, and only when a name must be reused before its recovery period ends. It is never a routine cost-saving step and never runs inside a workflow.

### Exercise 7.5: Clean up interactive notebook artifacts

The last section of `notebooks/demo4-resilient-pool.ipynb` offers an optional, gated cell that removes the Demo 1 to Demo 4 APIs, products, subscriptions, backends, named values, loggers, and diagnostics. Set `REMOVE_WORKSHOP_ARTIFACTS = True` only after the workshop.

Expected result: the demonstration artifacts are removed and the APIM instance remains. Automated sessions record this cell as intentionally excluded, never as completed cleanup.

### Exercise 7.6: Review the session evidence

> [!NOTE]
> Evidence pending review. The images `lab07-teardown-summary.png` (passed) or `lab07-teardown-status.png` (any other state) are rendered from the residual report status and appear here only after a maintainer reviews the sanitized session evidence. A residual-exposure state is published as a status card, never as a success image.

## Validation Checklist

* [ ] A dry run listed exact targets before any deletion
* [ ] Model deployments were deleted before their accounts
* [ ] The resource group, identity, and manifest records remain
* [ ] The residual report exists and its exit status matches its contents
* [ ] No purge ran unless an approved operator confirmed each name

## Knowledge Check

* Which resources does teardown intentionally keep, and why?
* Why is a `403` during deletion an error rather than proof that a resource is gone?
* How long do APIM, Cognitive Services, and Log Analytics tombstones remain recoverable?
* Why does no workflow have authority to purge?

## Next Steps

Return to the [Labs overview]({{ "/labs/" | relative_url }}) or start a new session from [Lab 00: Deploy the lab environment]({{ "/labs/lab-00-environment" | relative_url }}).
