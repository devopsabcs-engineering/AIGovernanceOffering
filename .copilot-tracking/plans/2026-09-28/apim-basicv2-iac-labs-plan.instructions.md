---
applyTo: '.copilot-tracking/changes/2026-09-28/apim-basicv2-iac-labs-changes.md'
---
<!-- markdownlint-disable-file -->
# Implementation Plan: APIM Basic v2 IaC, Automated Labs, Showback, Teardown, and Bilingual Site

## Overview

Add RG-scoped Bicep, an admin bootstrap, three GitHub workflows, safe headless notebook execution with semantic evidence, bounded estimated showback, owned-resource teardown, and a bilingual EN/FR lab site, with all local safety fixes landing before any paid Azure deployment.

## Objectives

### User Requirements

* Provision APIM Basic v2 and all prerequisites with Bicep and GitHub workflows, keeping it simple - Source: original request; research Lines 8-29
* Run all labs automatically and produce pictures - Source: original request; research Lines 189-217, 269-281
* Tear down to save costs - Source: original request; research Lines 143-161
* Workflows that run everything with real traffic to show chargeback and usage with real data - Source: original request; research Lines 219-259
* Publish a bilingual lab site following foundry-hosted-agents-fsi - Source: original request; research Lines 283-304
* Stay compatible with a future APIOps merge - Source: original request; research Lines 306-320
* Eliminate critical/major/high issues identified by adversarial review - Source: previous turn; research Lines 322-356

### Derived Objectives

* Fix existing notebook/shared defects (key printing, LLM body capture, false safety/failover passes, Linux subprocess) before automation - Derived from: research evidence table Lines 31-66
* Use a retained user-assigned identity in a separate identity RG so routine CI needs no role-assignment rights, and a custom APIM child-object role for the runtime identity - Derived from: P04/F10 principal-constraint problem with per-session system identities (log DD-01, DD-04, DD-05)
* Run all cloud work in one protected job so cleanup, budget, and sanitization never depend on cross-job state or a second approval - Derived from: validation round 1 (log DR-06 to DR-08)
* Keep irreversible purge out of workflows - Derived from: P05 and simplicity (log DD-02)
* Persist the recovery manifest as an ARM deployment record in the retained RG - Derived from: research requirement for runner-loss-safe storage (log DD-03)
* Label showback as an estimate, never billed chargeback - Derived from: F3, P07

## Context Summary

### Project Files

* shared/apim.py - ARM helpers; lines 30-40 exception bodies, ~202 backend MI credentials, ~426 logger, ~470 first-logger discovery, ~521 LLM message capture
* shared/config.py - .env loading (override=False line 136), prompts lines 216/225/308/375, parser line 244
* shared/auth.py - credential selection lines 19-40
* notebooks/00-setup-and-validation.ipynb - cell 4 shell=True
* notebooks/demo1-token-limits.ipynb, demo2-token-metrics.ipynb - limits, metrics, logger creation
* notebooks/demo3-content-safety.ipynb - cells 18 and 20 false-pass logic
* notebooks/demo4-resilient-pool.ipynb - cell 7/8 path mismatch, cell 10 key print, cells 16/18/20 weak assertions
* policies/demo*.xml - notebook-owned policies; system-assigned MI today
* tests/test_apim.py, test_config.py, test_notebooks.py - unittest suite and forbidden-vocabulary rule

### References

* .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md - authoritative research and gates G1-G9
* .copilot-tracking/research/subagents/2026-09-28/adversarial-*-review.md - defect evidence
* .copilot-tracking/research/subagents/2026-09-28/sibling-fsi-lab-pattern-research.md - site conventions
* .copilot-tracking/research/subagents/2026-09-28/apim-lza-apiops-research.md - LZA naming and APIOps layout

### Standards References

* c:\Users\emknafo\.vscode\extensions\ise-hve-essentials.hve-core-3.2.2\.github\instructions\hve-core\markdown.instructions.md - Markdown rules for docs pages and README
* c:\Users\emknafo\.vscode\extensions\ise-hve-essentials.hve-core-3.2.2\.github\instructions\hve-core\writing-style.instructions.md - voice and tone for lab pages
* c:\Users\emknafo\.vscode\extensions\ise-hve-essentials.hve-core-3.2.2\.github\instructions\hve-core\commit-message.instructions.md - commit messages

## Implementation Checklist

### [x] Implementation Phase 1: Local safety, privacy, and headless compatibility

<!-- parallelizable: true -->

* [x] Step 1.1: Prevent secret output at source
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 30-53)
* [x] Step 1.2: Explicit logger ownership and managed-identity ingestion
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 54-78)
* [x] Step 1.3: Disable LLM message capture
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 79-100)
* [x] Step 1.4: User-assigned identity client ID support and subscription-key stripping
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 101-125)
* [x] Step 1.5: Headless configuration contract
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 126-146)
* [x] Step 1.6: Setup notebook portability
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 147-158)
* [x] Step 1.7: Structured objective results and semantic classifiers
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 159-190)
* [x] Step 1.8: Session-wide dispatch guard
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 191-211)
* [x] Step 1.9: Validate phase changes (144 tests pass via `discover -s tests`; nbformat absent, structural check used)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 212-218)

### [x] Implementation Phase 2: Automation scripts with synthetic fixtures

<!-- parallelizable: false -->

Not parallelizable with Phase 1 (imports its shared modules). Once Phase 1 completes, it touches no files owned by Phases 3 or 4 and may run alongside them.

* [x] Step 2.1: Session orchestrator scripts/lab_session.py (init-session, preflight with tombstone check, what-if, append-only session-scoped manifest, deploy, readiness, probe-scopes, write-env, run-notebooks, mode-table cleanup, human-only purge)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 225-270)
* [x] Step 2.2: Notebook completion checker
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 271-284)
* [x] Step 2.3: Sanitized evidence and rendering
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 285-300)
* [x] Step 2.4: Traffic and showback scripts
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 301-317)
* [x] Step 2.5: CI dependencies
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 318-321)
* [x] Step 2.6: Validate phase changes
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 322-326)

### [x] Implementation Phase 3: Infrastructure and bootstrap

<!-- parallelizable: true -->

* [x] Step 3.1: Administrative bootstrap scripts/bootstrap-lab.ps1 (separate identity RG, custom APIM child-object and preflight-reader roles; author only, execution in Phase 6)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 333-362)
* [x] Step 3.2: RG-scoped Bicep
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 363-383)
* [x] Step 3.3: Platform policies and tests/test_infra.py
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 384-397)
* [x] Step 3.4: Validate phase changes
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 398-403)

### [x] Implementation Phase 4: Bilingual lab site

<!-- parallelizable: true -->

* [x] Step 4.1: Jekyll scaffold matching the sibling
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 410-419)
* [x] Step 4.2: Lab pages EN and FR
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 420-426)
* [x] Step 4.3: README update
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 427-430)
* [x] Step 4.4: Validate phase changes
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 431-437)

### [x] Implementation Phase 5: GitHub workflows

<!-- parallelizable: false -->

Requires Phases 2, 3, and 4.

* [x] Step 5.1: ci.yml (credential-free)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 444-448)
* [x] Step 5.2: lab-session.yml (workflow-level lock; one protected cloud job governed by a per-mode step matrix; paid steps use !cancelled() and require readiness; always() only for sanitize and cleanup; full step timeouts; credential-free render job; lock-test mode)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 449-485)
* [x] Step 5.3: teardown.yml (protected, manual, dry run default, no purge)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 486-489)
* [x] Step 5.4: Validate phase changes
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 490-496)

### [ ] Implementation Phase 6: Approved bootstrap and live acceptance

<!-- parallelizable: false -->

Stop for explicit user approval before each step. No Azure or GitHub-settings mutation happens in Phases 1-5.

* [x] Step 6.1: Record decisions (model tuple, processing/storage locations, price snapshot, envelope, reviewers, operators)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 503-506)
* [x] Step 6.2: Run bootstrap, then no-cloud lock rehearsal (G2, G4 part 1) (bootstrap applied; lock rehearsal pending push)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 507-511)
* [ ] Step 6.3: What-if review and deploy-only session with readiness (G1, G3)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 512-515)
* [ ] Step 6.4: run-existing session with scope probes (G5, G6)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 516-519)
* [ ] Step 6.5: Teardown, one full-session lifecycle, and recovery rehearsal (G8; produces lab07 evidence)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 520-524)

### [ ] Implementation Phase 7: Evidence curation and publishing

<!-- parallelizable: false -->

* [ ] Step 7.1: Curate reviewed images for passed items (objectives, readiness, reconciled showback, clean residual report); mark others unverified (G7)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 529-532)
* [ ] Step 7.2: Enable Pages with approval and verify live site (G9)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 533-536)

### [ ] Implementation Phase 8: Validation

<!-- parallelizable: false -->

Run Steps 8.1-8.2 once after Phase 5 (local, credential-free) and again after Phase 7 if Phases 6-7 are approved. If approvals are not given, finish after Phase 5 and report G1-G9 as OPEN.

* [x] Step 8.1: Run full project validation (local run after Phase 5: 285 tests OK, Bicep build/lint clean, actionlint clean, Jekyll build + crawl clean, PSScriptAnalyzer clean; repeat after Phase 7)
  * Unit tests, Bicep build and lint, actionlint, Jekyll build and crawl, PSScriptAnalyzer
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 541-548)
* [x] Step 8.2: Fix minor validation issues (12 doc/code drift fixes, Windows dotenv retry)
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 549-552)
* [ ] Step 8.3: Report blocking issues and gate status G1-G9
  * Details: .copilot-tracking/details/2026-09-28/apim-basicv2-iac-labs-details.md (Lines 553-556)

## Planning Log

See .copilot-tracking/plans/logs/2026-09-28/apim-basicv2-iac-labs-log.md for discrepancy tracking, implementation paths considered, and suggested follow-on work.

## Dependencies

* Python 3.11+ with requirements.txt plus papermill, nbformat, matplotlib, azure-monitor-query
* Azure CLI with Bicep; Azure MCP best-practice and Bicep schema tools during authoring
* PowerShell 7 with PSScriptAnalyzer; GitHub CLI for bootstrap
* Ruby github-pages gem (or container) and a link crawler; actionlint
* Phase 6: dedicated subscription access, administrator for bootstrap, approved model quota

## Success Criteria

* No code path prints or uploads secrets; fake-secret fixtures fail sanitization - Traces to: A01, G7
* Notebooks capture no prompts/completions and use managed-identity ingestion with explicit logger owners - Traces to: P01, F1, F9, G3
* Checker rejects partial, stale, and inconclusive runs; Demo 3 and Demo 4 require causal evidence - Traces to: A05-A07, G5
* One workflow-level lock, no nested calls, no schedules; cleanup runs after failures from a pre-mutation manifest - Traces to: A02-A04, G4, G8
* Routine CI identities hold only RG-scoped rights, no role-assignment write, no purge - Traces to: P04, F10, G2
* Showback output labelled as estimate with price coverage, exclusive window, and reconciliation - Traces to: P07, F2-F7, G6
* Eight EN/FR page pairs build and crawl cleanly; images only from checker-passed, sanitized runs - Traces to: A11, G9
* Gates G1-G9 reported with evidence; none claimed passed without execution - Traces to: research Lines 358-378
