---
permalink: /labs/lab-01-setup-validation
title: "Lab 01 - Setup and validation"
description: "Confirm identity, capture configuration, and validate the APIM instance and Content Safety resource with the setup notebook, interactively or headlessly."
nav_order: 11
---

**[Version française]({{ "/fr/labs/lab-01-setup-validation" | relative_url }})**

> [!IMPORTANT]
> Use synthetic prompts only. LLM message logging stays off on every API, so the lab never records prompts or completions in telemetry; only token counts and bounded dimensions leave the gateway. Session images appear on this site only after a maintainer reviews sanitized evidence.

## Overview

{% assign prerequisite_url = "/labs/lab-00-environment" | relative_url %}

| Item | Value |
| --- | --- |
| **Duration** | 20 minutes |
| **Level** | Beginner |
| **Prerequisites** | [Lab 00]({{ prerequisite_url }}) environment or an existing APIM instance, Python 3.10 or newer, and the Azure CLI |

`notebooks/00-setup-and-validation.ipynb` is the shared prerequisite for every demonstration notebook. It confirms your Azure CLI identity, captures the resource group and APIM instance name, verifies that the gateway is reachable, reports the SKU, and checks the Content Safety resource that Lab 04 needs. It creates or modifies no Azure resources.

Interactively, the notebook reads a local `.env` file that is never committed. `./scripts/sync-lab-env.ps1` writes that file from the deployment outputs of the generation that is deployed right now, so you never type a resource name. Without a deployed lab, the notebook prompts for missing values and persists them to `.env` instead. In an automated session, `scripts/lab_session.py write-env` writes the complete `.env`, and `AIGOV_HEADLESS=1` turns every would-be prompt into an error that names the missing key.

## Learning Objectives

By the end of this lab, you will be able to:

* Confirm the signed-in Azure identity and subscription without exposing credentials
* Explain the configuration precedence of environment variables, the `.env` file, and interactive prompts
* Validate that the APIM gateway is reachable and supports the policies the labs use
* Explain why headless mode fails instead of prompting
* Read the structured objective results that replace console banners as the acceptance record

## Exercises

### Exercise 1.1: Prepare the Python environment

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
az login
az account show --query "{name:name, id:id}" -o table
```

Expected result: the last command prints the subscription you intend to use.

The notebooks use `AzureCliCredential` and fall back to `DefaultAzureCredential`. They never open an interactive browser sign-in.

### Exercise 1.2 (Hands-on): Point `.env` at the deployed generation

```powershell
./scripts/sync-lab-env.ps1
```

Expected result:

```text
Subscription: <your subscription>
local-env: wrote 39 keys to .env for generation g05 (secrets not shown)
local-env: APIM apim-aigov-lab-g05-001-<suffix> at https://apim-aigov-lab-g05-001-<suffix>.azure-api.net
Cleared from this terminal: AIGOV_GENERATION
Ready: .env and this terminal now target generation g05. Restart Jupyter if it was already running.
```

The script finds the newest generation whose APIM instance exists, writes `.env` from that deployment's outputs, and saves any previous `.env` as `.env.bak`. It then removes from the current terminal any variable that would override or conflict with `.env`, such as the `AIGOV_*` values loaded in Lab 00 or `AIGOV_HEADLESS` and `SESSION_*` values from an automated session. It also warns when the repository variable `AIGOV_GENERATION` names a different generation.

VS Code terminals can also start with the values that `.env` held when the terminal opened, because the Python extension may load `.env` into new terminals. That is another way a stale generation reaches a notebook, and the script clears those values as well.

Run it again after every deployment or teardown. If it reports `No active generation`, deploy one first in [Lab 00]({{ prerequisite_url }}).

### Exercise 1.3 (Hands-on): Run the setup notebook

In the same terminal:

```powershell
jupyter notebook notebooks/00-setup-and-validation.ipynb
```

Jupyter opens the notebook in your browser. If the browser shows **File not found** for a `jpserver-<number>-open.html` file, select one of the `http://localhost:8888/...?token=...` links printed in the terminal instead. Keep that terminal open; closing it stops the notebook kernel.

Select **Run** > **Run All Cells**. You can also open the notebook in VS Code, select the `.venv` interpreter as the kernel, and select **Run All**.

Expected result: the notebook prints the lab generation, the gateway URL, and the SKU, and reports the Content Safety resource check. Secrets such as API keys and connection strings appear masked, never in full.

If cell 3 reports that the APIM instance does not exist, `.env` points to a generation that was torn down. Stop Jupyter with Ctrl+C, run `./scripts/sync-lab-env.ps1`, start Jupyter again, and select **Kernel** > **Restart Kernel and Run All Cells**.

Demo 1 and Demo 3 need `llm-token-limit` and `llm-content-safety`, which Basic v2 supports. Demo 4 needs backend pools and circuit breakers, which Basic v2, Standard v2, Premium v2, and classic Standard and Premium support.

### Exercise 1.4: Observe headless behavior

Open a second terminal in the repository root, activate the environment, and run:

```powershell
.venv\Scripts\Activate.ps1
$env:AIGOV_HEADLESS = "1"
python -c "from shared.config import load_config; load_config(); print('headless load_config: OK')"
$env:AIGOV_GENERATION = "g00"
python -c "from shared.config import load_config; load_config()"
Remove-Item Env:AIGOV_GENERATION, Env:AIGOV_HEADLESS
```

Expected result: with a complete `.env` and a clean terminal, the first command prints `headless load_config: OK` without prompting. After you set a different `AIGOV_GENERATION` in the terminal, the second command raises `ConfigError: Inherited environment variables conflict with .env in headless mode: AIGOV_GENERATION`. It lists key names only, never values. With a missing required key, headless mode raises `ConfigError` naming the key.

In interactive mode a terminal variable silently wins over `.env`, which is how a stale value from an earlier session can point a notebook at the wrong resources. Headless mode refuses instead. If you see this error unexpectedly, run `./scripts/sync-lab-env.ps1` in that terminal.

`DEMO_RUN` must come from `.env` alone, so an inherited `DEMO_RUN` environment variable counts as a conflict in headless mode.

### Exercise 1.5: Read the objective results

```powershell
./scripts/show-results.ps1 -Notebook 00-setup-and-validation
```

```text
notebook                objective       status recorded_at
--------                ---------       ------ -----------
00-setup-and-validation setup.apim_sku  passed 2026-10-03 8:18:36 AM
00-setup-and-validation setup.endpoints passed 2026-10-03 8:18:36 AM
00-setup-and-validation setup.identity  passed 2026-10-03 8:18:28 AM
```

Expected result: the setup result file records `setup.identity`, `setup.endpoints`, and `setup.apim_sku`, each with the status `passed`, `failed`, or `inconclusive` and allowlisted scalar evidence only. The script reads the newest `outputs/results/<run>/00-setup-and-validation.json`; open that file to see the evidence values. Without `-Notebook`, it prints every notebook, which is how you check Labs 02 to 05.

The banners in the notebook are for people. The result file is the acceptance record that the session checker reads.

### Exercise 1.6: Review the session evidence

> [!NOTE]
> Reviewed evidence from session `36608221120-1` ([workflow run](https://github.com/devopsabcs-engineering/AIGovernanceOffering/actions/runs/36608221120)), rendered on 2026-09-29 from sanitized results only.

![Objective results for Lab 01 from the reviewed session]({{ '/assets/images/lab01-setup-validation-summary.png' | relative_url }})

This image comes from an automated workflow session, not from your notebook run; your own results are the `show-results.ps1` table above. To see the same tables and images for your own sessions, run `./scripts/show-evidence.ps1 -OpenPng` after the `run-existing` session in Lab 06. A `deploy-only` session reports this lab as `not_run`.

## Validation Checklist

* [ ] `az account show` returns the intended subscription
* [ ] `sync-lab-env.ps1` reported the deployed generation
* [ ] The setup notebook printed the gateway URL and SKU
* [ ] `.env` exists locally and is not tracked by Git
* [ ] Headless mode fails on a missing key instead of prompting
* [ ] All three setup objectives have a recorded status

## Knowledge Check

* Which source wins when the same key is set in the environment and in `.env` during an interactive run?
* Why does headless mode treat an inherited `DEMO_RUN` value as a conflict?
* Why is a printed PASS banner not accepted as completion evidence?

## Next Steps

Continue to [Lab 02: Token limits and quotas]({{ "/labs/lab-02-token-limits" | relative_url }}).
