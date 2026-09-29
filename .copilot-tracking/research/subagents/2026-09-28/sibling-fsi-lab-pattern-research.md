<!-- markdownlint-disable-file -->

> Historical sibling-pattern snapshot, superseded on 2026-09-28 where it conflicts with .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md. Copying sibling behavior does not establish safe privileges, deletion, publication, or site-link correctness. Follow the primary's selected contracts and gates. Original content is retained as evidence; historical line references predate this notice.

# Sibling repo pattern research: foundry-hosted-agents-fsi

* Source repo (read-only): `C:\src\GitHub\devopsabcs-engineering\foundry-hosted-agents-fsi`
* Target repo: `AIGovernanceOffering` (public; currently `docs/ai-governance-flows.svg`, `Presentation/Module 8 - Gateway and Metering Plane.pptx`, `notebooks/`, `policies/`, `shared/`, `tests/`)
* Status: Complete
* Date: 2026-09-28

## Research questions

1. Top-level tree and README structure
2. Lab publishing: tool, config, i18n, nav, theme, language switcher, lab location/naming, front matter, admonitions, images, publish workflow
3. Bicep: layout, params, modules, param files, naming, tags, azd vs az, scope, RBAC, MI
4. Workflows: triggers, OIDC, deploy, teardown/purge, schedules, notebook/screenshot runs, artifacts
5. Setup scripts (OIDC app reg / federated credential) and docs
6. `.github/copilot-instructions.md` / conventions docs
7. Presentation / slide conventions

---

## 1. Top-level tree and README

Tracked files (from `git ls-files`), 2-3 levels:

```text
.copilot-tracking/          # RPI artifacts (research/plans/changes/reviews) - committed
.github/workflows/          # 9 workflows (no copilot-instructions.md, no other .github files)
apps/
  reviewer-app/  (Dockerfile, VERSION, app.py, frontend/ Vite+React, tests/)
  web-chat/      (same shape)
  workshop/      (calculator.py, approval_repository.py, tests/)
assets/                     # README-only screenshots: web-chat-ui.png, reviewer-app-ui.png
azure.yaml                  # azd project
data/synthetic/             # fixtures/*.json, schema, rulebook.json
docs/                       # Jekyll site root (GitHub Pages "deploy from branch /docs")
  _config.yml  Gemfile  _includes/head_custom.html
  index.md  labs/index.md  labs/lab-00-setup.md ... lab-14-pilot-operations.md
  fr/index.md  fr/labs/index.md  fr/labs/lab-00-setup.md ... lab-14-...
  assets/images/*.png       # lab screenshots (7 files)
eval/                       # golden dataset, gates, judge
infra/
  README.md  main.bicep  main.json  main.parameters.json
  network.bicep network.json  web-chat.bicep web-chat.json
  modules/{ai-foundry,cosmos-db,cosmos-rbac,mcp-container-apps,monitoring,rbac,reviewer-app}.bicep (+ .json)
mcp/{application-server,rulebook-server}/
scripts/                    # *.py, *.ps1, *.sh, build-workshop-deck.js
src/quote-preparation-agent/
package.json  requirements.txt  pyrightconfig.json  .gitignore  .dockerignore
```

Not present: `.github/copilot-instructions.md`, `CONTRIBUTING.md`, `Presentation/`, `mkdocs.yml`, any Pages workflow, any OIDC bootstrap script.

README.md (159 lines) structure:

* Lines 1-4: YAML front matter (`title`, `description`) — even the README carries front matter.
* L6 `## Overview` → L17-21 `> [!IMPORTANT]` synthetic-data disclaimer.
* L23 `## Learner path` (explicit "does not require GitHub Copilot" + AI-assistance disclosure).
* L31 `## Repository layout` — bullet per top folder; L33-36:

  ```markdown
  * `docs/` holds the English workshop site (Jekyll, Just the Docs theme);
    start at [docs/index.md](docs/index.md).
  * `docs/fr/` holds the French workshop site, structurally paired with
    `docs/`; start at [docs/fr/index.md](docs/fr/index.md).
  ```
* L59 `## Getting started` — links both EN/FR landing pages + published URL `https://devopsabcs-engineering.github.io/foundry-hosted-agents-fsi/`.
* L67 `## Try the web chatbot`, L96 `## Try the reviewer app` — each ends with a screenshot `![Quote preparation chat UI](assets/web-chat-ui.png)` (root `assets/`, not `docs/assets`).
* L107 `## Deployment links` — points to wiki Home "Deployment Links" table auto-refreshed by CI (no hardcoded live URLs).

---

## 2. Lab publishing

### Tool: Jekyll + Just the Docs via GitHub Pages legacy build (no workflow)

* Pages config (via `gh api repos/devopsabcs-engineering/foundry-hosted-agents-fsi/pages`):
  `"build_type":"legacy","source":{"branch":"main","path":"/docs"}`, `html_url: https://devopsabcs-engineering.github.io/foundry-hosted-agents-fsi/`.
* Therefore there is **no** `pages.yml`/docs workflow — GitHub builds `docs/` on every push to `main` using the `github-pages` gem set.

`docs/_config.yml` (full file, 28 lines):

```yaml
title: "Foundry Hosted Agents Workshop (FSI)"
description: "Bilingual hands-on workshop hosting ..."
remote_theme: just-the-docs/just-the-docs
# Private repos serve Pages at a root-served *.pages.github.io proxy domain
# (baseurl ""); a public repo serves at the standard <owner>.github.io/<repo>
# path instead, so both fields change together when visibility changes.
baseurl: "/foundry-hosted-agents-fsi"
url: "https://devopsabcs-engineering.github.io"

exclude:
  - Gemfile.lock

defaults:
  - scope:
      path: ""
    values:
      layout: "default"
  - scope:
      path: "assets"
    values:
      nav_exclude: true

nav_order_base: 0
heading_anchors: true

mermaid:
  version: "10.9.1"
```

`docs/Gemfile` (lines 1-3):

```ruby
source "https://rubygems.org"
gem "github-pages", group: :jekyll_plugins
gem "webrick", "~> 1.8"
```

### i18n mechanism: parallel `docs/fr/` tree + `lang: fr` front matter + CSS nav filter

No i18n plugin. French is a structurally mirrored subtree (`docs/fr/labs/lab-NN-*.md` pairs 1:1 with `docs/labs/lab-NN-*.md`, same slugs, English filenames).

* EN pages: no `lang` key. FR pages: `lang: fr` (e.g. `docs/fr/index.md` L2, `docs/fr/labs/lab-13-reviewer-ui.md` L3).
* Explicit `permalink` on every page: EN `/labs/lab-13-reviewer-ui`, FR `/fr/labs/lab-13-reviewer-ui`.
* **Language switcher** = a blockquote link on line right after front matter, relative path:
  * EN (`docs/labs/lab-13-reviewer-ui.md` L7): `> 🇫🇷 **[Version française](../fr/labs/lab-13-reviewer-ui)**`
  * FR (`docs/fr/labs/lab-13-reviewer-ui.md` L8): `> 🇬🇧 **[English version](../../labs/lab-13-reviewer-ui)**`
  * Home EN `docs/index.md` L9: `> 🇫🇷 **[Version française](fr/)**`; Home FR `docs/fr/index.md` L10: `> 🇬🇧 **[English version](../)**`
* **Sidebar language split** — `docs/_includes/head_custom.html` (Just the Docs hook injected into `<head>`). Just the Docs builds one nav for the whole site; this hides the other language's entries:

  ```liquid
  {%- assign is_fr_page = false -%}
  {%- if page.lang == 'fr' or page.url contains '/fr/' -%}
    {%- assign is_fr_page = true -%}
  {%- endif -%}
  {%- assign fr_href = "/fr" | relative_url -%}
  {%- assign fr_href_prefix = fr_href | append: "/" -%}
  <style>
    {%- if is_fr_page %}
    #site-nav .nav-list-item:has(> a.nav-list-link[href]:not([href="{{ fr_href }}"]):not([href^="{{ fr_href_prefix }}"])) { display: none; }
    {%- else %}
    #site-nav .nav-list-item:has(> a.nav-list-link:is([href="{{ fr_href }}"], [href^="{{ fr_href_prefix }}"])) { display: none; }
    {%- endif %}
    .nav-list-item.lang-hidden { display: none !important; }
  ```

  (L1-15), plus site-title/header height CSS (L17-35) and a JS `DOMContentLoaded` fallback for browsers without `:has()` that adds `lang-hidden` (L37-51).

### Nav structure

* Only home pages set `nav_order: 0` (`docs/index.md` L5, `docs/fr/index.md` L6). Lab pages set **no** `nav_order`/`parent`/`has_children` — Just the Docs sorts by title, and titles are prefixed `Lab NN - ...` / `Atelier NN - ...` so they order naturally.
* `docs/labs/index.md` (L1-5 front matter: `permalink: /labs/`, `title: "Labs"`, `description`) is the curriculum hub with markdown tables grouping labs (L20 `### Local Foundations`, L35 `### The Pilot Surfaces`), columns `Lab | Title | What you will do`, links like `[00](lab-00-setup.md)`.
* FR hub `docs/fr/labs/index.md`: `permalink: /fr/labs/`, `lang: fr`, `title: "Ateliers"`.

### Lab naming and front matter

* File pattern: `lab-NN-kebab-slug.md`, NN = 00..14 (two digits, zero-padded). Lab 00 = setup, Lab 09 and Lab 14 = teardown/operations.
* Front matter (EN, `docs/labs/lab-13-reviewer-ui.md` L1-5):

  ```yaml
  ---
  permalink: /labs/lab-13-reviewer-ui
  title: "Lab 13 - The Reviewer UI"
  description: "Seed a local case queue, sign in as a reviewer, approve a case, and read the audit trail the decision leaves behind."
  ---
  ```
* FR (`docs/fr/labs/lab-13-reviewer-ui.md` L1-6): same plus `lang: fr`, title `"Atelier 13 - L'interface de révision"`, translated description.

### Lab body template (identical section order EN/FR)

From `docs/labs/lab-13-reviewer-ui.md` and `docs/labs/lab-00-setup.md`:

1. Language switcher blockquote (L7)
2. `> [!IMPORTANT]` standing disclaimer (L9-10) — repeated at top of every lab
3. `## Overview` (L12) — table `| Item | Value |` with **Duration**, **Level**, **Prerequisites** (L14-18)
4. Optional `> [!NOTE]` (L24-25)
5. `## Learning Objectives` (L27) — "By the end of this lab, you will be able to:" + `*` bullets
6. `## Exercises` (L37) → `### Exercise 13.N: Title` or `### Exercise 13.N (Hands-on): Title` (L102). Each: fenced `powershell` command → `Expected result: ...` sentence → optional `text` block of expected output → explanation paragraph.
7. `## Validation Checklist` (L190) — `* [ ]` items
8. `## Knowledge Check` (L200) — question bullets
9. `## Next Steps` (L208) — `Continue to [Lab NN+1: Title](lab-...md).`

FR headings (`docs/fr/labs/lab-13-reviewer-ui.md`): `## Aperçu` (L13), `## Objectifs d'apprentissage` (L28), `## Exercices` (L38), `### Exercice 13.2 (pratique) : ...` (L50, note French space before colon), `## Liste de vérification` (L191), `## Vérification des connaissances` (L201), `## Étapes suivantes` (L209). Code blocks stay identical; placeholders translated (`<id-client-revision>`).

### Admonitions

GitHub-style alert syntax `> [!IMPORTANT]`, `> [!NOTE]`, `> [!TIP]`, `> [!WARNING]`, `> [!CAUTION]` (e.g. lab-14 L171 WARNING, L190 CAUTION, L218 NOTE). Same markers in FR (not translated). Note: Just the Docs on the legacy github-pages build does not natively render `[!NOTE]` as callouts (they render as plain blockquotes with the literal marker) — no `callouts:` config exists in `_config.yml`. This is a gap worth fixing in a new repo (add `callouts:` config or use MkDocs Material admonitions).

### Images / screenshots

* Lab screenshots: `docs/assets/images/<surface>-<state>.png` kebab-case, no numbering, no language suffix: `reviewer-sign-in.png`, `reviewer-queue.png`, `reviewer-case-detail.png`, `reviewer-case-not-priced.png`, `reviewer-approve-confirm.png`, `reviewer-case-approved.png`, `web-chat-sign-in.png`.
* **One image shared by EN and FR** (UI captured in English). Referenced with Liquid `relative_url` so it works under any `baseurl`:

  ```markdown
  ![The reviewer queue listing five pending cases with columns for case, state, revision, preparer, submitted time, and premium; two rows read Not priced]({{ "/assets/images/reviewer-queue.png" | relative_url }})
  ```
  (EN `docs/labs/lab-13-reviewer-ui.md` L117; FR L118 with translated, very descriptive alt text.)
* Pattern: image placed immediately after the action instruction, followed by `Expected result: ...`.
* `_config.yml` `defaults` sets `nav_exclude: true` for `assets` path.
* README screenshots live separately in root `assets/` (`assets/web-chat-ui.png`, `assets/reviewer-app-ui.png`).
* Capture method (from `.copilot-tracking/plans/logs/2026-09-15/workshop-ui-labs-log.md` L53-54, ID-06): screenshots were captured by the agent driving the VS Code integrated/automated browser with real interactive Entra sign-in against locally running apps (not stubbed). DD-01 (L19-22): no screenshot is fabricated when a surface cannot be run — the lab documents the boundary instead.
* `scripts/capture-release-evidence.ps1` (L1-14): headless Edge `--screenshot` of a local HTML report to `assets/release-evidence/<name>.png`:

  ```powershell
  $arguments = "--headless --disable-gpu --no-first-run --hide-scrollbars --force-device-scale-factor=1 --window-size=1500,1000 --user-data-dir=`"$edgeProfile`" --screenshot=`"$output`" `"$url`""
  ```
  No CI workflow captures screenshots; no Playwright in CI.

### Publish workflow

None. Legacy Pages "Deploy from branch: main /docs". Only automated publishing is to the **GitHub wiki** (`publish-test-trends.yml`, see §4).

---

## 3. Bicep / infra

Layout (`infra/README.md` L17-45):

| File | Role |
| --- | --- |
| `infra/network.bicep` | VNet, 5 subnets, Cosmos private DNS zone; deployed once per RG as deployment name `network-foundation` |
| `infra/main.bicep` + `main.parameters.json` | per-environment stack, deployed twice (staging, production) into ONE shared RG |
| `infra/web-chat.bicep` | applied out-of-band via `az deployment group create` |
| `infra/modules/*.bicep` | monitoring, ai-foundry, mcp-container-apps, cosmos-db, cosmos-rbac, rbac, reviewer-app |
| `*.json` | committed `az bicep build` outputs (README L67-72) |

* Scope: `targetScope = 'resourceGroup'` (`infra/main.bicep` L12). RG is pre-created and supplied via `vars.AZURE_RESOURCE_GROUP`; no subscription-scope RG creation.
* Naming: **no `uniqueString`/resourceToken** (explicitly noted `infra/main.bicep` L77). Names derive from `environmentName` with CAF-ish prefixes:

  ```bicep
  param accountName string = 'aif-${environmentName}'           // L20
  param projectName string = 'proj-${environmentName}'           // L23
  param logAnalyticsWorkspaceName string = 'log-${environmentName}'  // L56
  param applicationInsightsName string = 'appi-${environmentName}'   // L59
  param cosmosAccountName string = toLower('cosmos-${environmentName}') // L83
  ```
  Environment branching by suffix: `var isStaging = endsWith(environmentName, '-staging')`; `@minLength/@maxLength` guards on globally unique names (L80-83, L91-94).
* `main.parameters.json` (azd-style substitution with defaults):

  ```json
  "environmentName": { "value": "${AZURE_ENV_NAME}" },
  "location": { "value": "${AZURE_LOCATION}" },
  "reviewerClientId": { "value": "${REVIEWER_CLIENT_ID=}" },
  "reviewerAppImage": { "value": "${REVIEWER_APP_IMAGE=mcr.microsoft.com/k8se/quickstart:latest}" }
  ```
  No `.bicepparam` files.
* azd: `azure.yaml` (L11 `name: desjardins-quote-preparation-workshop`) with `azure.ai.project`, `azure.ai.connection`, `azure.ai.toolbox`, `azure.ai.agent` hosts. CI uses `azd provision`/`azd deploy` for main stack, plain `az deployment group create` for `network.bicep` and `web-chat.bicep`, and `az deployment group what-if` for preview.
* Tags: minimal — only `modules/reviewer-app.bicep` L91-94 (`environment`, `purpose`) and `web-chat.bicep` L95. No global tag object, no `azd-env-name` tag.
* RBAC (`infra/modules/rbac.bicep`): role GUID list param, cartesian product via `map`/`reduce`, deterministic names:

  ```bicep
  param roleDefinitionIds array = [
    '53ca6127-db72-4b80-b1b0-d745d6d5456d' // Foundry User
    'eadc314b-1a2d-4efa-be10-5d325db5065e' // Foundry Project Manager
    'eed3b665-ab3a-47b6-8f48-c9382fb1dad6' // Foundry Agent Consumer
  ]
  ...
  resource roleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
    for pair in assignmentPairs: {
      name: guid(account.id, pair.principalId, pair.roleDefinitionId)
      scope: account
      properties: {
        roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', pair.roleDefinitionId)
        principalId: pair.principalId
        principalType: principalType
      }
    }
  ]
  ```
  `main.bicep` L169-176 passes `concat([aiFoundry.outputs.projectPrincipalId], principalIds)` (project MI always + optional CI principals). Cosmos data-plane uses a separate `cosmos-rbac.bicep`, serialized with `dependsOn` to avoid 409s (L233-240).
* Managed identity: Foundry account and project `SystemAssigned` (`modules/ai-foundry.bicep` L63-66, L101-103); Container Apps use `UserAssigned` (`reviewer-app.bicep` L95-97).
* Outputs in UPPER_SNAKE for azd env consumption (`FOUNDRY_PROJECT_ENDPOINT`, `AZURE_AI_PROJECT_ID`, `COSMOS_ENDPOINT`, L247-265).
* Security posture: no hardcoded tenant/sub/secret (`infra/README.md` L74-75); `@secure()` on App Insights connection string param.

---

## 4. GitHub Actions workflows

| File | Triggers | Azure? | Purpose |
| --- | --- | --- | --- |
| `continuous-validation.yml` | `push: [main]`, `pull_request`, `workflow_dispatch` (L12-16) | No (`permissions: contents: read`) | pytest suites, deterministic gate, `az bicep build` for every template (L157-163), JUnit artifact upload |
| `deploy-and-evaluate.yml` | `workflow_call` + `workflow_dispatch` input `golden_dataset_path` (L31-44) | OIDC | lint → bicep-validate (what-if + idempotency assert) → deploy-staging (azd) → evaluate → promote-production |
| `hosted-agent-cd.yml` | `workflow_dispatch` only | via reusable | thin wrapper: `uses: ./.github/workflows/deploy-and-evaluate.yml` + `secrets: inherit` |
| `full-teardown.yml` | `workflow_dispatch` (target choice, confirm string, execute bool) | OIDC | whole-RG delete with Foundry purge |
| `network-rebuild-teardown.yml` | `workflow_dispatch` (environment choice, confirm, execute) | OIDC | delete Container Apps/env/Foundry account for network rebuild |
| `reviewer-app-teardown.yml` | `workflow_dispatch` (+ `remove_entra_objects` bool) | OIDC | per-app teardown |
| `reviewer-app-build.yml` / `web-chat-build.yml` | push/PR with `paths:` filters + dispatch | OIDC in `release` job | node/python tests, version bump, git tag push, `az acr build` |
| `publish-test-trends.yml` | `workflow_run` of 4 workflows `types: [completed]`, `branches: [main]` + dispatch (L29-42) | No | downloads artifacts, regenerates wiki pages, pushes with `secrets.WIKI_PUSH_TOKEN` |

No `schedule:`/cron anywhere. No workflow runs notebooks, and none captures screenshots.

### OIDC auth pattern

Top-level `permissions: id-token: write, contents: read` (`deploy-and-evaluate.yml` L47-49). Login uses **repository/environment variables, not secrets**:

```yaml
- name: Azure login with OIDC
  uses: azure/login@v3
  with:
    client-id: ${{ vars.AZURE_CLIENT_ID }}
    tenant-id: ${{ vars.AZURE_TENANT_ID }}
    subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}
```

(`deploy-and-evaluate.yml` L143, L233, L486, L639). Rationale documented in `docs/labs/lab-14-pilot-operations.md` L100-110 ("the only secret referenced across the pipeline is the wiki push token").

Variables used: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_LOCATION`, `MCP_ACR_NAME`, `APPLICATION_MCP_IMAGE`, `RULEBOOK_MCP_IMAGE`, `REVIEWER_APP_IMAGE`, `REVIEWER_CLIENT_ID`, `AGENT_PRINCIPAL_ID`, `WEB_CHAT_APP_NAME`, `WEB_CHAT_URL`. Secret: `WIKI_PUSH_TOKEN`.

GitHub Environments: `staging` (bicep-validate L137, deploy-staging L213, evaluate L480) and `production` (promote-production L625, full-teardown L83) — production has required reviewers = manual approval gate.

Shared concurrency group prevents deploy/teardown interleave:

```yaml
concurrency:
  group: desjardins-quote-preparation-shared-environments
  queue: max
```

### Deploy steps (deploy-and-evaluate.yml)

1. `az bicep build --file infra/main.bicep` (L149-150)
2. `az deployment group create --name network-foundation --template-file infra/network.bicep` (L165)
3. `az deployment group what-if ... --no-pretty-print > whatif-candidate.json` (L190) then `python3 scripts/assert_bicep_idempotent.py --candidate whatif-candidate.json` (L204) — fails if what-if shows Delete.
4. `Azure/setup-azd@v2` (L225), `azd extension install azure.ai.agents`, `azd config set auth.useAzCliAuth true`, `azd env new/select`, `azd env set ...`
5. `az acr build` → digest-pinned image refs
6. `azd provision --no-prompt` with 3-attempt retry (L300-305), `azd deploy --no-prompt` (L313)
7. `$GITHUB_STEP_SUMMARY` markdown summaries everywhere; `actions/upload-artifact@v6` for evidence (retention 1-30 days; azd `.azure/` state passed between jobs with `include-hidden-files: true`).

### Teardown steps (full-teardown.yml)

Safety posture (header L28-39): dispatch-only; typed confirmation must equal target; `execute` defaults `false` (dry run inventories resources into step summary); `environment: production` approval; RG name allowlist regex; every step existence-checked for safe rerun. Inputs passed via `env:` (not interpolated into script) to prevent injection (L85-86).

```yaml
on:
  workflow_dispatch:
    inputs:
      target:  { type: choice, options: [poc, shared, both], default: poc }
      confirm: { type: string, required: true }
      execute: { type: boolean, default: false }
```

Order per RG:

1. Delete Foundry projects, then account via raw ARM `az rest --method delete` with retries; wait; `az cognitiveservices account purge` (L167, L270) — purge **before** RG delete because the OIDC identity's RG-scoped roles vanish with the RG.
2. Force-delete Log Analytics: `az monitor log-analytics workspace delete ... --force true --yes` (L275).
3. `az group delete --name "$RG" --yes` (L289).

Login uses `allow-no-subscriptions: true` (L128) plus `ensure_fresh_login()` (L143-155) that re-mints the GitHub OIDC token via `$ACTIONS_ID_TOKEN_REQUEST_URL&audience=api://AzureADTokenExchange` every 30 min for long waits:

```bash
OIDC_TOKEN=$(curl -sSf -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
  "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=api://AzureADTokenExchange" | jq -r .value)
az login --service-principal --username "$AZURE_CLIENT_ID" --tenant "$AZURE_TENANT_ID" \
  --federated-token "$OIDC_TOKEN" --allow-no-subscriptions --output none
```

No APIM purge exists (no APIM in this repo). For AIGovernanceOffering, add `az apim deletedservice purge --service-name <n> --location <loc>` alongside Cognitive Services purge.

### Wiki publishing (publish-test-trends.yml)

Clones `https://github.com/$GITHUB_REPOSITORY.wiki.git` using basic auth header built from `WIKI_PUSH_TOKEN` (L166-168), regenerates `Continuous-Test-Trends.md` and `Home.md` deployment-link table via `scripts/ci_results.py` / `scripts/update_wiki_deployment_links.py`, commits and pushes. Fails with an actionable `::error::` if the secret or the wiki is missing (L155-170).

---

## 5. Scripts / setup

`scripts/` contents: `assert_bicep_idempotent.py`, `bump_version.py`, `capture-release-evidence.ps1`, `ci_results.py`, `deployment_summary.py`, `record-production-version.sh`, `remove-reviewer-identity.ps1`, `seed_review_queue.py`, `setup-reviewer-identity.ps1`, `setup-web-chat-identity.ps1`, `test-agent-response.sh`, `test-production-version.sh`, `update_wiki_deployment_links.py`, `validate-agent-response.jq`, `wipe_review_cases.py`, `build-workshop-deck.js`, plus `scripts/tests/` pytest for scripts.

* **No script creates the GitHub OIDC app registration / federated credential.** It was provisioned manually by an admin; only referenced in docs (`docs/labs/lab-14-pilot-operations.md` L108-110; `full-teardown.yml` L40-43 "Rebuilding after a `shared` teardown needs the group recreated and the OIDC identity's role assignments re-granted by a subscription administrator").
* Identity scripts pattern (`scripts/setup-reviewer-identity.ps1` L1-41): comment-based help, `[CmdletBinding(SupportsShouldProcess)]` for `-WhatIf`, idempotent (resolve by exact display name, patch if exists), fixed GUIDs for scope/role IDs, mandatory `-TenantId`; paired `remove-*.ps1`.

---

## 6. Copilot instructions / conventions

* No `.github/copilot-instructions.md`, no `.github/instructions/`, no `CONTRIBUTING.md`.
* Conventions are carried by: heavy top-of-file comment banners in workflows/Bicep (why, safety posture, gates), `infra/README.md`, and committed `.copilot-tracking/` RPI artifacts (research/plans/changes/reviews/logs dated folders).
* Lab/README convention: disclosure of AI-assisted authoring in "Learner path"; standing `[!IMPORTANT]` synthetic-data disclaimer on every page.

---

## 7. Presentation / slides

* No `Presentation/` folder. Decks are **generated**: `scripts/build-workshop-deck.js` (PptxGenJS, ESM) → `docs/assets/decks/foundry-hosted-agents-workshop-fsi-{en,fr}.pptx` (L1-19); one script, one language parameter per deck, shared `SLIDES` content. `package.json` script `"build-workshop-deck": "node scripts/build-workshop-deck.js"`, dependency `pptxgenjs ^4.0.1`.
* Style constants: Segoe UI, Microsoft blue `0078D4`, 13.33 x 7.5 in (16:9), header bar + kicker + title + footer helpers (L21-60).
* `docs/assets/decks/` is not committed currently (not in `git ls-files`; not gitignored either — simply not generated/committed yet).

---

## Reusable template for AIGovernanceOffering

Target repo is **public**, so `baseurl: "/AIGovernanceOffering"`, `url: "https://devopsabcs-engineering.github.io"`.

### Folder layout

```text
docs/
  _config.yml  Gemfile  _includes/head_custom.html
  index.md                     # EN home (nav_order: 0, permalink: /)
  labs/index.md                # EN curriculum table
  labs/lab-00-setup.md ... lab-0N-*.md
  fr/index.md                  # lang: fr, permalink: /fr/
  fr/labs/index.md             # lang: fr, permalink: /fr/labs/
  fr/labs/lab-00-setup.md ...  # same slugs as EN
  assets/images/<demo>-<state>.png   # shared EN/FR screenshots
  assets/decks/                # optional generated pptx
  ai-governance-flows.svg      # existing; move to assets/images/ and reference with relative_url
infra/
  README.md  main.bicep  main.bicepparam|main.parameters.json  modules/*.bicep
scripts/
  setup-github-oidc.ps1        # NEW (gap in sibling): app reg + federated creds + role assignment + gh variable set
  capture-screenshots.*        # optional
.github/workflows/
  validate.yml                 # push/PR: pytest + az bicep build (no Azure login)
  deploy.yml                   # dispatch: OIDC, what-if, deploy, run demos
  teardown.yml                 # dispatch: confirm+execute dry-run pattern, purge APIM + Cognitive Services
```

Suggested lab mapping from existing notebooks: `lab-00-setup` (00-setup-and-validation), `lab-01-token-limits` (demo1), `lab-02-token-metrics` (demo2), `lab-03-content-safety` (demo3), `lab-04-resilient-pool` (demo4), `lab-05-teardown`.

### i18n mechanism (copy verbatim)

* Copy `docs/_config.yml` (change title/description/baseurl), `docs/Gemfile`, `docs/_includes/head_custom.html` as-is.
* FR pages add `lang: fr` + `permalink: /fr/...`; titles `Atelier NN - ...`.
* Line after front matter: EN `> 🇫🇷 **[Version française](../fr/labs/<slug>)**`; FR `> 🇬🇧 **[English version](../../labs/<slug>)**`.
* Enable Pages: Settings → Pages → Deploy from branch `main` `/docs` (or `gh api -X POST repos/{owner}/{repo}/pages -f "source[branch]=main" -f "source[path]=/docs"`). No workflow required.
* Improvement: add Just the Docs `callouts:` to `_config.yml` so `> [!NOTE]`-style content renders, or use `{: .note }` syntax.

### Lab page skeleton

````markdown
---
permalink: /labs/lab-01-token-limits
title: "Lab 01 - Token Limits"
description: "..."
---

> 🇫🇷 **[Version française](../fr/labs/lab-01-token-limits)**

## Overview

| Item | Value |
| --- | --- |
| **Duration** | 30 minutes |
| **Level** | Intermediate |
| **Prerequisites** | [Lab 00](lab-00-setup.md) |

## Learning Objectives

By the end of this lab, you will be able to:

* ...

## Exercises

### Exercise 1.1 (Hands-on): ...

```powershell
...
```

Expected result: ...

![Descriptive alt text of exactly what is visible]({{ "/assets/images/token-limits-429.png" | relative_url }})

## Validation Checklist

* [ ] ...

## Knowledge Check

* ...

## Next Steps

Continue to [Lab 02: Token Metrics](lab-02-token-metrics.md).
````

### Screenshot conventions

* Path `docs/assets/images/<surface>-<state>.png`, kebab-case, no numbering, no language suffix, shared by EN/FR.
* Reference with `{{ "/assets/images/x.png" | relative_url }}`; long descriptive alt text translated per language.
* Place image after the action step, before `Expected result:`.
* Capture from real running systems; never fabricate. For file persistence use Playwright `page.screenshot({ path })` (per user memory, `screenshot_page` output cannot be saved) or headless Edge `--screenshot` like `scripts/capture-release-evidence.ps1`.

### Workflow skeletons

```yaml
# .github/workflows/deploy.yml
name: Deploy
on:
  workflow_dispatch:
permissions:
  id-token: write
  contents: read
concurrency:
  group: aigov-shared-environment
  queue: max
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: lab
    steps:
      - uses: actions/checkout@v6
      - uses: azure/login@v3
        with:
          client-id: ${{ vars.AZURE_CLIENT_ID }}
          tenant-id: ${{ vars.AZURE_TENANT_ID }}
          subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}
      - run: az bicep build --file infra/main.bicep
      - name: What-if
        env: { RG: "${{ vars.AZURE_RESOURCE_GROUP }}", LOC: "${{ vars.AZURE_LOCATION }}" }
        run: az deployment group what-if -g "$RG" -f infra/main.bicep -p location="$LOC" --no-pretty-print > whatif.json
      - name: Deploy
        env: { RG: "${{ vars.AZURE_RESOURCE_GROUP }}", LOC: "${{ vars.AZURE_LOCATION }}" }
        run: az deployment group create -g "$RG" -n main -f infra/main.bicep -p location="$LOC"
      - uses: actions/upload-artifact@v6
        if: always()
        with: { name: whatif, path: whatif.json, retention-days: 14 }
```

```yaml
# .github/workflows/teardown.yml (sibling full-teardown.yml pattern)
on:
  workflow_dispatch:
    inputs:
      confirm: { description: "Type the resource group name to confirm", type: string, required: true }
      execute: { description: "Actually delete (unchecked = dry run)", type: boolean, default: false }
permissions: { id-token: write, contents: read }
jobs:
  teardown:
    runs-on: ubuntu-latest
    environment: production        # required reviewers
    steps:
      - name: Verify confirmation
        env: { TYPED: "${{ inputs.confirm }}", RG: "${{ vars.AZURE_RESOURCE_GROUP }}" }
        run: '[ "$TYPED" = "$RG" ] || { echo "::error::Confirmation mismatch"; exit 1; }'
      - uses: azure/login@v3
        with: { client-id: "${{ vars.AZURE_CLIENT_ID }}", tenant-id: "${{ vars.AZURE_TENANT_ID }}", subscription-id: "${{ vars.AZURE_SUBSCRIPTION_ID }}" }
      - name: Delete + purge
        if: inputs.execute
        env: { RG: "${{ vars.AZURE_RESOURCE_GROUP }}" }
        run: |
          # inventory to $GITHUB_STEP_SUMMARY, then:
          # az cognitiveservices account delete/purge (per account, before RG delete)
          # az monitor log-analytics workspace delete --force true --yes
          # az group delete --name "$RG" --yes
          # az apim deletedservice purge --service-name <n> --location <loc>  (after RG delete; needs sub-scope permission)
```

Validation workflow: copy `continuous-validation.yml` shape (push main + PR + dispatch, `contents: read`, pytest + `az bicep build` loop over `infra/main.bicep infra/modules/*.bicep`, summary to `$GITHUB_STEP_SUMMARY`, JUnit upload).

### Bicep conventions to replicate

* `targetScope = 'resourceGroup'`; RG pre-created by admin / OIDC setup script.
* `environmentName`-derived names with CAF prefixes (`apim-`, `aif-`, `log-`, `appi-`); add `@maxLength` guards. Consider adding `uniqueString(resourceGroup().id)` suffix for globally unique names (APIM, Cognitive Services subdomain) since the sibling explicitly lacks one.
* RBAC module with role GUID array + `guid(scope.id, principalId, roleId)` names.
* SystemAssigned MI on AI account; UPPER_SNAKE outputs for downstream scripts/notebooks.
* Commit `infra/README.md` with module table and "no hardcoded IDs" statement.

## Follow-on questions / gaps

* No OIDC bootstrap script in sibling — AIGovernanceOffering needs its own (`az ad app create`, `az ad sp create`, `az ad app federated-credential create` for `repo:devopsabcs-engineering/AIGovernanceOffering:environment:<env>` and `:ref:refs/heads/main`, role assignment on the RG, `gh variable set AZURE_CLIENT_ID/AZURE_TENANT_ID/AZURE_SUBSCRIPTION_ID/AZURE_RESOURCE_GROUP/AZURE_LOCATION`).
* Admonition rendering (`[!NOTE]`) on the Jekyll legacy build is unverified; verify on the live site or add `callouts:` config.
* Parent sibling `foundry-hosted-agents` (non-FSI) may contain a Pages workflow / `docs/assets/decks` publishing pattern — not investigated.

## Clarifying questions

* Should AIGovernanceOffering keep Jekyll/Just the Docs parity with the sibling, or adopt MkDocs Material (native admonitions + `mkdocs-static-i18n`)?
* Should notebook outputs/screenshots be captured in CI (headless Playwright against notebooks) or manually by an author as in the sibling?
