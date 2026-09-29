<!-- markdownlint-disable-file -->

> Historical research snapshot, superseded on 2026-09-28. Do not execute or copy the checker, raw-artifact publication, browser-redaction, authentication, or workflow examples below. Adversarial review rejected incomplete-run certification and unproven safety/failover outcomes. The authoritative design and canonical lab/image map are in .copilot-tracking/research/2026-09-28/apim-basicv2-iac-labs-research.md. Original content is retained as evidence, not current implementation guidance; historical line references predate this notice.

# Headless Notebook Execution + Lab Screenshots Research

Status: Complete (research only; no repo files modified)

Builds on: `.copilot-tracking/research/subagents/2026-09-28/current-repo-research.md`.

Conventions: notebook references are `<notebook> cell N L<m>` where N is the 1-based cell number (markdown + code, as seen in VS Code) and L is the 1-based line inside that cell's source. Python file references are file line numbers.

## Research Questions

1. Every interactive `input()`/`getpass` path, what bypasses it, required env vars, how `.env` is loaded, and the exact `.env` a workflow should write.
2. Subprocess `az` calls, Linux compatibility, Windows-only assumptions.
3. Waits/timeouts and total runtime estimate.
4. How PASS/FAIL is reported and a minimal CI failure detector that does not change notebook semantics.
5. Demo 4 mock routing path: does the forwarded path match the mock operations? Fix needed?
6. Chart/visual outputs and how to turn them into `docs/assets/images/labNN-<slug>-<n>.png`.
7. requirements.txt gaps for CI.
8. papermill version and CLI usage; whether a `parameters` tag is needed.

---

## 1. Interactive prompts, env vars, and `.env` loading

### 1.1 How config is loaded

* `.env` path is fixed to the **repo root**, independent of cwd: `shared/config.py` L21-L22 (`REPO_ROOT = Path(__file__).resolve().parent.parent`, `ENV_PATH = REPO_ROOT / ".env"`).
* Loader: **python-dotenv** (`from dotenv import load_dotenv, set_key`, L17). `load_config()` L130 calls `load_dotenv(dotenv_path=ENV_PATH, override=False)` at L136 -> **process env vars win over `.env`**.
* Writes back to `.env` via `set_key(..., quote_mode="never")` (`_persist`, L113-L115). `_ensure_env_file()` creates `.env` if missing. `.env` must therefore be **writable** in CI.
* Prompt-suppression checks use a **custom line parser** `_dotenv_keys()` (L244-L253): it reads raw `.env` lines and collects `KEY` from `KEY=...`. It does **not** look at `os.environ`. So a key set only as a GitHub `env:` variable (especially with an empty value) does NOT suppress these prompts.
* `_prompt()` L118-L127 uses `getpass.getpass` (L123, secrets) or `input()` (L125). Under papermill/nbclient the kernel has `allow_stdin=False`, so any prompt raises `StdinNotImplementedError` -> the cell errors -> papermill exits non-zero (deterministic failure, not a hang).

### 1.2 Every prompt path and what bypasses it

| Location | Prompt | Fires when | Bypass (headless) |
| --- | --- | --- | --- |
| config.py ~L196-L198 | resource group | `APIM_RESOURCE_GROUP` empty | set `APIM_RESOURCE_GROUP` (env or .env) |
| config.py ~L200-L202 | APIM name | `APIM_NAME` empty | set `APIM_NAME` |
| config.py ~L204-L208 | AOAI endpoint | `AOAI_ENDPOINT` empty | set `AOAI_ENDPOINT` |
| config.py ~L210-L212 | AOAI deployment | `AOAI_DEPLOYMENT` empty | set `AOAI_DEPLOYMENT` |
| config.py L216-L223 | AOAI key (getpass) | `AOAI_KEY` falsy AND no `AOAI_KEY` line in `.env` | write line `AOAI_KEY=` in `.env` |
| config.py L225-L235 | AOAI API style | **no `AOAI_API_STYLE` line in `.env` (even if env var is set)** | write line `AOAI_API_STYLE=v1` in `.env` |
| config.py L301-L306 (`ensure_content_safety_config`, Demo 3 only) | CS endpoint | `CONTENT_SAFETY_ENDPOINT` empty | set `CONTENT_SAFETY_ENDPOINT` |
| config.py L308-L315 | CS key (getpass) | `CONTENT_SAFETY_KEY` falsy AND no `CONTENT_SAFETY_KEY` line in `.env` | write line `CONTENT_SAFETY_KEY=` |
| config.py L355-L380 (`ensure_resilient_pool_config`, Demo 4 only; check at L375) | six DEMO4_* values | value empty AND key line not in `.env` | write six lines `DEMO4_*=` (empty OK; they default to AOAI values L382-L394) |

Callers (all with `interactive=True`):

* 00 cell 6 L1 `config.load_config(interactive=True)`.
* demo1 cell 3 L9; demo2 cell 3 L14; demo3 cell 3 L19 + L21 `ensure_content_safety_config(cfg, interactive=True)`; demo4 cell 3 L11 + L13 `ensure_resilient_pool_config(cfg, interactive=True)`.

No other `input()`/`getpass` exists in notebooks or `shared/` (grep confirmed).

Side effects every run: `load_config` always persists `AZURE_SUBSCRIPTION_ID` (L237-L238) and `DEMO_RUN` (L239). Demo 1 cell 25 and Demo 2 cell 28 regenerate and persist `DEMO_RUN` (`config.persist_demo_run`, L256-L258), which later notebooks read.

### 1.3 Required env vars (CI)

Hard-required (validate_config L261-L290 raises): `APIM_RESOURCE_GROUP`, `APIM_NAME`, `AOAI_ENDPOINT` (resource root, no path), `AOAI_DEPLOYMENT`.

Required for prompt suppression (must be **lines in `.env`**): `AOAI_KEY`, `AOAI_API_STYLE`, `CONTENT_SAFETY_KEY`, `DEMO4_PTU_EAST_ENDPOINT`, `DEMO4_PTU_CENTRAL_ENDPOINT`, `DEMO4_PAYG_ENDPOINT`, `DEMO4_PTU_EAST_DEPLOYMENT`, `DEMO4_PTU_CENTRAL_DEPLOYMENT`, `DEMO4_PAYG_DEPLOYMENT`.

Required per demo: Demo 2 `APP_INSIGHTS_RESOURCE_ID` + `APP_INSIGHTS_CONNECTION_STRING` (logger creation needs the connection string; `ensure_logger` raises otherwise). Demo 3 `CONTENT_SAFETY_ENDPOINT`.

Recommended: `AZURE_SUBSCRIPTION_ID` (avoids the `az account show` fallback), `DEMO_RUN` (fresh per run - see 1.5).

### 1.4 Proposed generated `.env` (write to repo root before the first notebook)

```dotenv
# generated by CI from Bicep outputs - do not commit (.env is gitignored)
AZURE_SUBSCRIPTION_ID=<subscriptionId>
APIM_RESOURCE_GROUP=<resourceGroupName>
APIM_NAME=<apimName>
AOAI_ENDPOINT=https://<foundryCustomSubdomain>.services.ai.azure.com
AOAI_DEPLOYMENT=<chatDeploymentName, e.g. gpt-4o-mini>
AOAI_KEY=
AOAI_API_STYLE=v1
AOAI_API_VERSION=2024-10-21
APP_INSIGHTS_NAME=<appInsightsName>
APP_INSIGHTS_RESOURCE_ID=/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Insights/components/<appInsightsName>
APP_INSIGHTS_CONNECTION_STRING=<InstrumentationKey=...;IngestionEndpoint=...;LiveEndpoint=...;ApplicationId=...>
CONTENT_SAFETY_ENDPOINT=https://<contentSafetyCustomSubdomain>.cognitiveservices.azure.com
CONTENT_SAFETY_KEY=
CONTENT_SAFETY_BLOCKLIST_ID=
CONTENT_SAFETY_THRESHOLD_HATE=4
CONTENT_SAFETY_THRESHOLD_SELFHARM=4
CONTENT_SAFETY_THRESHOLD_SEXUAL=4
CONTENT_SAFETY_THRESHOLD_VIOLENCE=4
DEMO4_PTU_EAST_ENDPOINT=
DEMO4_PTU_CENTRAL_ENDPOINT=
DEMO4_PAYG_ENDPOINT=
DEMO4_PTU_EAST_DEPLOYMENT=
DEMO4_PTU_CENTRAL_DEPLOYMENT=
DEMO4_PAYG_DEPLOYMENT=
DEMO_RUN=<fresh 8-hex per run, e.g. $(openssl rand -hex 4)>
```

Notes:

* Keep values **unquoted**, one per line (matches `set_key(quote_mode="never")`; python-dotenv reads unquoted values to end of line, and the App Insights connection string contains `;`/`=` but no ` #`, so it parses fine; `_dotenv_keys` splits on the first `=`).
* Get `APP_INSIGHTS_CONNECTION_STRING` via `az monitor app-insights component show -a <name> -g <rg> --query connectionString -o tsv` (or a Bicep output) and `echo "::add-mask::$CS"` before writing.
* `AOAI_ENDPOINT` host: `.env.example` uses `*.services.ai.azure.com`; the v1 path `/openai/v1/chat/completions` is also served on `*.openai.azure.com`. Note an AIServices account's `properties.endpoint` output is the `*.cognitiveservices.azure.com` host - build the URL from the custom subdomain instead of using that output blindly (verify on first run; a wrong host shows up as 404 in Demo 1 baseline via `explain_failure`).
* Optional: set `CONTENT_SAFETY_THRESHOLD_VIOLENCE=2` to reduce Demo 3 `NOT TRIPPED` outcomes (documented remediation in demo3 cell 18 L37-L43).
* Do not also export these as job-level `env:` with different values: env vars override `.env` (`override=False`).

### 1.5 DEMO_RUN must be fresh per run

Demo 1's `llm-token-limit` counter-key is `Subscription.Id + "-" + x-demo-run` with a **daily** quota of 400 tokens (demo1 cell 3 L20-L21). A re-run on the same day with the same `DEMO_RUN` gets 403 at the baseline call. Always write a new `DEMO_RUN` to `.env` per workflow run/attempt.

---

## 2. Subprocess `az` calls, Linux compatibility, Windows-only assumptions

| Location | Call | Linux behavior | Impact |
| --- | --- | --- | --- |
| 00 cell 4 L4-L7 | `subprocess.run(["az","account","show","-o","json"], ..., shell=True)` | POSIX + `shell=True` + list: first item is the shell command, the rest become **shell arguments** -> runs bare `az` (prints the Azure CLI welcome text), exit 0 | Cell passes and shows "az login is active." but prints the CLI banner, not the account. Misleading, not failing. Also prints tenant/user JSON on Windows - avoid screenshotting this cell. |
| shared/auth.py L44-L58 `get_current_subscription_id` | `["az","account","show","--query","id","-o","tsv"]`, no shell | Works on Linux. (On Windows `az` is `az.cmd`, so without shell it may fail and return None - already harmless.) | None in CI if `AZURE_SUBSCRIPTION_ID` is set. |
| shared/auth.py L19-L34 `get_credential` | `AzureCliCredential` (spawns `az account get-access-token` per token request) | Works after `azure/login` | Every ARM call calls `get_arm_token()` via `_headers()` (apim.py L43-L48) -> one `az` subprocess per ARM request (~0.5-1.5 s each on Linux). Adds minutes across ~120 ARM calls. |

Minimal optional fix for 00 cell 4: `shell=sys.platform == "win32"` (or drop `shell=True` and resolve `shutil.which("az")`). Not required for CI to pass.

Other portability checks (all OK on Linux):

* Policy file paths are relative and forward-slash: `../policies/demo1-token-limit.xml` (demo1 cell 11 L3), demo2 cell 12 L1, demo3 cell 11 L1, demo4 cell 7 L36 and cell 8 L16. File name casing matches the files on disk.
* `sys.path.append("..")` in every notebook (e.g. demo1 cell 3 L2) is **cwd-relative** -> the kernel cwd must be `notebooks/` (papermill `--cwd notebooks`). Setting `PYTHONPATH=$GITHUB_WORKSPACE` as a belt-and-braces is harmless.
* No PowerShell, backslash paths, `os.name`/`sys.platform` checks elsewhere (grep confirmed).

### 2.1 OIDC token lifetime risk (important for CI, not a code issue)

* GitHub OIDC ID tokens are short-lived (docs example: `iat`->`exp` = 300 s): https://docs.github.com/en/actions/concepts/security/openid-connect. `azure/login` hands that assertion to `az login --federated-token`. Tokens for **new audiences** requested after the assertion expires fail (`AADSTS700024`).
* ARM tokens are acquired at login and cached ~60-90 min (azure/login README: SP access tokens ~1 h). All ARM calls are fine within a ~30 min run.
* Demo 2 cell 21 calls `LogsQueryClient(get_credential())` (apim.py L760) -> new audience `https://api.loganalytics.io` several minutes after login. Failure is **swallowed** by demo2 cell 21 L26-L28 (`print(f"Metric candidate ... was not queryable here: {exc}")`) -> no rows -> PASS 01-03 all FAIL.
* Mitigation (no code change): re-run `azure/login@v3` immediately before each notebook step (cheap), and pre-warm right before Demo 2: `az account get-access-token --scope https://api.loganalytics.io/.default -o none`.
* The CI identity also needs data read on App Insights (e.g. Monitoring Reader / Log Analytics Reader on the AI component or its workspace).

---

## 3. Waits, timeouts, runtime

| Notebook | Waits / bounds (refs) | Est. runtime |
| --- | --- | --- |
| 00 | none; 30 s subprocess timeout (cell 4 L6) | < 0.5 min |
| demo1 | burst max 20 calls (cell 18 L1); daily loop max 60 iterations / 180 s wall clock (cell 21 L1-L2) + `time.sleep(Retry-After)` on 429 (cell 21 L29-L31, up to ~60 s); requests timeout 60 s (cell 14 L30, L40-L43) | 2-5 min |
| demo2 | 1 s spacing x8 calls (cell 19 L22); ingestion backoff `[15,30,45,60,75]` s = up to 225 s, sleeps even after the 5th miss (cell 21 L124-L133); requests timeout 90 s | 4-7 min |
| demo3 | none; requests timeout 90 s (cell 16 L43, cell 20 L11) | 1-2 min |
| demo4 | `RECOVERY_WAIT_SECONDS = 65` (cell 3 L26-L27, slept in cell 20 L2); ~80 pool calls (cells 12/14/16/18/20); ~50 ARM writes (named values, backends re-PUT in `configure_mode` cell 10 L47-L61, `heal_all` 6 PUTs); ARM 202 polling every 5 s up to 300 s (apim.py L26-L27, L103-L120) | 6-12 min |

Shared: every ARM call spawns `az` for a token (see 2). APIM named-value/backends PUTs can return 202 and take several seconds each.

Total: roughly **15-27 min** of notebook execution, plus ~2-3 min setup (pip + Playwright Chromium). Recommend job `timeout-minutes: 60` and papermill `--execution-timeout 900` (per cell; the longest cell is demo2 cell 21 at <= ~5 min). papermill's default per-cell timeout is "forever".

---

## 4. PASS/FAIL reporting and CI failure detection

### 4.1 How notebooks report status

* Rendering: `display.banner(text, kind)` (shared/display.py L24-L42) emits HTML (`text/html` output) with a colored left border; `kind="error"` = `#cf222e`. Tables are pandas DataFrames (`text/html` + `text/plain`) via `show_table` (L45-L56).
* Hard raises (papermill exits non-zero on these): config validation (all notebooks), `ApimError` on any failed ARM call (apim.py `_request` L61-L79), demo2 cell 21 L114-L120 `RuntimeError` (diagnostic/policy missing), demo4 cell 5 L11-L12 (`RuntimeError` unsupported SKU), any prompt (StdinNotImplementedError).
* Soft signals (do NOT fail execution):
  * demo1: no PASS/FAIL strings at all. Success = banners "Baseline call succeeded" (cell 16 L15), "429 observed at request #" (cell 18 L20), "Daily token budget exhausted -- 403 returned." (cell 21 L26 - note this is `kind="error"` but is the **expected** outcome), "Reset confirmed" (cell 25 L15). Failure = "Call did not return 200" (`explain_failure`, cell 14 L69).
  * demo2: preflight banners `PASS:/FAIL:/MANUAL:` (cell 5 L72-L74). **On a fresh APIM, preflight shows `FAIL: Application Insights connected` (L20: PASS only if an APIM AI logger already exists) and `FAIL: LLM API logging enabled` (diagnostic is created later in cell 10) - these FAILs are expected on first run.** Acceptance banners `PASS: PASS 01...`/`FAIL: PASS 01...` (cell 23 L42-L43) are the real result.
  * demo3: preflight banners (cell 5 L60-L62), matrix banners `PASS: <Case>` / `FAIL: <Case>` / NOT TRIPPED warning (cell 18 L34-L49); streaming `PASS:`/`FAIL:`/NOT TRIPPED (cell 20 L50-L68). Case names: "Safe business prompt", "Prompt attack", "Harm threshold", "Streaming completion" (shared/fixtures.py L26/L36/L49/L63).
  * demo4: preflight table with `PASS`/`FAIL` (cell 5 L5-L10); routing evidence only via warnings ("Fewer than two observed East 429", "No observed PAYG spillover", "East was not observed") and success "East was observed healthy again" (cell 20 L5-L8). A broken mock route shows `served_by = "not returned"` in the tables (cell 10 L17).

Conclusion: a naive global "FAIL:" grep would **false-fail** Demo 2 on every fresh environment and would **miss** Demo 1/Demo 4 failures. Use a small manifest-based checker.

### 4.2 Minimal checker (new file, e.g. `scripts/check_notebook_outputs.py`; notebooks unchanged)

```python
"""Fail CI on lab regressions by scanning executed notebook outputs."""
import html, re, sys
from pathlib import Path
import nbformat

TAG_RE = re.compile(r"<[^>]+>")
# cell numbers are 1-based, matching the notebook editor
RULES = {
    "00-setup-and-validation": {"must": ["is reachable"]},
    "demo1-token-limits": {
        "must": ["Baseline call succeeded", "429 observed at request #",
                 "Daily token budget exhausted", "Reset confirmed"],
        "must_not": ["Call did not return 200"],
    },
    "demo2-token-metrics": {
        "must": ["PASS: PASS 01", "PASS: PASS 02", "PASS: PASS 03"],
        "ignore_fail_cells": {5},  # preflight runs before configure on a fresh APIM
    },
    "demo3-content-safety": {
        "must": ["PASS: Safe business prompt", "PASS: Prompt attack"],
        "warn": ["NOT TRIPPED"],
    },
    "demo4-resilient-pool": {
        "must": ["Routing mode is ready", "East was observed healthy again"],
        "must_not_in_cells": {14: ["not returned"], 16: ["not returned"]},
        "warn": ["do not claim", "No observed PAYG spillover", "do not infer"],
    },
}

def cell_text(cell):
    parts = []
    for out in cell.get("outputs", []):
        if out.output_type == "stream":
            parts.append(out.text)
        elif out.output_type == "error":
            parts.append(f"ERROR {out.ename}: {out.evalue}")
        else:
            data = out.get("data", {})
            parts.append(data.get("text/plain", ""))
            parts.append(html.unescape(TAG_RE.sub(" ", data.get("text/html", ""))))
    return "\n".join(parts)

def main(out_dir):
    failed = False
    for nb_path in sorted(Path(out_dir).glob("*.ipynb")):
        rules = RULES.get(nb_path.stem, {})
        nb = nbformat.read(nb_path, as_version=4)
        texts = {i: cell_text(c) for i, c in enumerate(nb.cells, start=1) if c.cell_type == "code"}
        blob = "\n".join(texts.values())
        errs = []
        for i, t in texts.items():
            if "ERROR " in t and any(o.output_type == "error" for o in nb.cells[i-1].outputs):
                errs.append(f"cell {i} raised")
            if i not in rules.get("ignore_fail_cells", set()) and re.search(r"\bFAIL:", t):
                errs.append(f"cell {i} reported FAIL")
        errs += [f"missing '{s}'" for s in rules.get("must", []) if s not in blob]
        errs += [f"found '{s}'" for s in rules.get("must_not", []) if s in blob]
        for cell_no, needles in rules.get("must_not_in_cells", {}).items():
            errs += [f"cell {cell_no} contains '{s}'" for s in needles if s in texts.get(cell_no, "")]
        for s in rules.get("warn", []):
            if s in blob:
                print(f"::warning file={nb_path}::{nb_path.stem}: '{s}'")
        for e in errs:
            print(f"::error file={nb_path}::{nb_path.stem}: {e}")
        failed |= bool(errs)
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "outputs/executed")
```

Caveats:

* Cell numbers shift if papermill injects error-marker cells (only on failure) or an `injected-parameters` cell (only if `-p` is passed). Run without `-p`; on failure papermill already exits non-zero.
* Decide policy for `NOT TRIPPED` (currently warning) and for Demo 2 acceptance (depends on App Insights "custom metric dimensions" + ingestion latency; may need to be a warning until proven stable).
* Run the checker with `if: always()` after the notebook steps; run screenshot extraction `if: always()` too, so partial runs still yield artifacts.

---

## 5. Demo 4 mock routing path

### 5.1 What is configured

* Client API: path `demo4-resilient-pool` (demo4 cell 3 L19), serviceUrl = AOAI endpoint (cell 8 L2-L3), operation `chat-completions` POST `/openai/v1/chat/completions` (v1) or `/openai/deployments/{d}/chat/completions` (classic) (cell 8 L4-L6). Policy `policies/demo4-resilient-pool.xml` L5 `<set-backend-service backend-id="demo4-aoai-pool" />`, L6 MI auth.
* Client request URL: `{gateway}/demo4-resilient-pool/openai/v1/chat/completions` (cell 10 L2).
* Routing-mode member backends: `url = f"{GATEWAY_URL}/{MOCK_PATH}/{member}"` = `{gateway}/demo4-mock-origin/east|central|payg` (cell 7 L39-L43; re-applied in `configure_mode("routing")` cell 10 L48-L60).
* Mock API: path `demo4-mock-origin` (cell 3 L23), serviceUrl = gateway (cell 7 L23-L24), **operations POST `/east`, `/central`, `/payg`** (cell 7 L33-L35: `ensure_operation(..., member, ..., "POST", f"/{member}")`).
* Mock policy `policies/demo4-mock-origin.xml` branches on `context.Operation.Id` (`east`/`central`/`payg`, L5, L17, L29, L41, L50, L59); `<otherwise>` returns 404 (L68-L73).

### 5.2 What APIM forwards

APIM builds the backend request URL as **backend base URL + the request path remaining after the API suffix** (the operation-relative path). With `set-backend-service` to the pool, the selected member's URL is the base:

`{gateway}/demo4-mock-origin/east` + `/openai/v1/chat/completions` = `{gateway}/demo4-mock-origin/east/openai/v1/chat/completions`

In the mock API that is operation-relative path `/east/openai/v1/chat/completions` (classic: `/east/openai/deployments/{d}/chat/completions`).

### 5.3 Verdict: mismatch - fix needed

* APIM operation matching is full-template matching; `/east` does not match `/east/openai/v1/chat/completions`. Unmatched requests get the gateway's 404 "Resource not found" **before** API-scope policy runs (so even the mock's `<otherwise>` 404 body/`x-served-by` is not produced). Microsoft Learn (https://learn.microsoft.com/en-us/azure/api-management/add-api-manually): calling a path not exposed as an APIM operation returns 404; wildcard operations use a `*` URL template segment.
* Effect: every routing-mode call (demo4 cells 14, 16, 18, 20) returns 404 with `served_by = "not returned"`; 404 is outside the breaker's status ranges (cell 7 L9: 429 and 500-599), so the breaker never trips. The notebook still completes (only warnings) -> silent CI pass unless the checker in 4.2 is used.
* Commit history shows Demo 4 routing was authored in PR #31 (`5d05434 Add observable Demo 4 mock routing` ... `81590b4`) with no evidence of a live run; the prior research also flagged this.

Minimal fix (one line, notebook only): make the mock operations wildcards so the member segment matches any suffix and `context.Operation.Id` is unchanged:

```python
# demo4 cell 7 L34-L35
apim.ensure_operation(cfg.subscription_id, cfg.resource_group, cfg.apim_name, MOCK_API_ID,
                      member, f"Demo 4 mock {member}", "POST", f"/{member}/*")
```

Verify on the first live run that `/east/*` matches multi-segment suffixes (expected). Fallback if not: a single mock operation `/*` and branch in `demo4-mock-origin.xml` on `context.Request.Url.Path` (contains `/east/`, `/central/`, `/payg/`) instead of `context.Operation.Id` (larger change; tests in tests/test_apim.py L103+ assert the mock policy structure and would need review).

Secondary item to verify live (not proven): the client's `Ocp-Apim-Subscription-Key` (demo4-resilient-pool-sub) may be forwarded to the mock alongside the backend credential header `Ocp-Apim-Subscription-Key: {{demo4-mock-origin-key}}` (cell 7 L32). If the mock returns 401, add `<set-header name="Ocp-Apim-Subscription-Key" exists-action="delete" />` to `demo4-resilient-pool.xml` inbound (backend credentials are applied at forwarding time, after inbound policy).

### 5.4 Secret leak in Demo 4 output (fix recommended)

demo4 cell 10 L8 prints `REQUEST_HEADERS` as JSON, which contains the **unmasked** `Ocp-Apim-Subscription-Key` (L3). With papermill `--log-output` this lands in the Actions log (not a registered secret, so not masked) and always lands in the executed `.ipynb`/HTML artifacts and any screenshot of that cell. Minimal fix: print `{**REQUEST_HEADERS, "Ocp-Apim-Subscription-Key": auth.mask_secret(SUBSCRIPTION_KEY)}` (`auth` is already imported, cell 3 L9). Until fixed: do not use `--log-output` for demo4, do not screenshot cell 10, and keep artifact retention short.

Other sensitive-but-not-secret outputs to redact in screenshots: subscription id / RG / APIM name / endpoints in 00 cell 6 (config table) and cell 8; gateway URLs printed in demo1 cell 14 L8, demo2 cell 15 L6, demo3 cell 16 L6.

---

## 6. Visual outputs and docs images

### 6.1 What each notebook renders

* PNG charts (matplotlib, inline `image/png` display_data; ipykernel's inline backend is used automatically under papermill):
  * demo1 cell 19 L11 `plot_remaining_tokens` (display.py L66-L85).
  * demo2 cell 21 L149 `plot_token_series_by_dimension` (display.py L88-L121) - only if metric rows were returned; otherwise a markdown "_No token metric rows to plot yet._".
  * Cells assign `_ = ...` so the returned `fig` is not displayed twice.
* HTML tables (pandas) + HTML banners - everything else, e.g.: 00 cells 6, 8, 10; demo1 cells 16, 18, 21, 23, 25; demo2 cells 5, 17, 19, 21, 23, 25; demo3 cells 5, 14, 18, 20; demo4 cells 5, 12, 14, 16, 18, 20.
* No plotly, no widgets.

### 6.2 Approach A - extract embedded PNGs with nbformat (charts)

```python
"""Extract image/png outputs from executed notebooks into docs/assets/images."""
import base64
from pathlib import Path
import nbformat

LABS = {
    "00-setup-and-validation": ("lab00", "setup"),
    "demo1-token-limits": ("lab01", "token-limits"),
    "demo2-token-metrics": ("lab02", "token-metrics"),
    "demo3-content-safety": ("lab03", "content-safety"),
    "demo4-resilient-pool": ("lab04", "resilient-pool"),
}
out_dir = Path("docs/assets/images"); out_dir.mkdir(parents=True, exist_ok=True)
for nb_path in sorted(Path("outputs/executed").glob("*.ipynb")):
    lab, slug = LABS[nb_path.stem]
    nb = nbformat.read(nb_path, as_version=4)
    n = 0
    for cell in nb.cells:
        for out in cell.get("outputs", []):
            png = out.get("data", {}).get("image/png")
            if png:
                n += 1
                (out_dir / f"{lab}-{slug}-chart-{n}.png").write_bytes(base64.b64decode(png))
```

Lossless, no browser, but only covers the 2 charts.

### 6.3 Approach B - nbconvert HTML + Playwright element screenshots (tables/banners)

1. `jupyter nbconvert --to html --template lab --output-dir outputs/html outputs/executed/*.ipynb` (add `--no-input` for output-only pages). nbconvert does not sanitize output HTML by default, so banner inline styles render.
2. Python Playwright (`pip install playwright && python -m playwright install --with-deps chromium`):

```python
from pathlib import Path
from playwright.sync_api import sync_playwright

# (notebook stem, 1-based cell number, output file stem)
SHOTS = [
    ("demo1-token-limits", 16, "lab01-token-limits-1"),
    ("demo1-token-limits", 18, "lab01-token-limits-2"),
    ("demo1-token-limits", 19, "lab01-token-limits-3"),
    ("demo1-token-limits", 21, "lab01-token-limits-4"),
    ("demo2-token-metrics", 19, "lab02-token-metrics-1"),
    ("demo2-token-metrics", 21, "lab02-token-metrics-2"),
    ("demo2-token-metrics", 23, "lab02-token-metrics-3"),
    ("demo3-content-safety", 18, "lab03-content-safety-1"),
    ("demo3-content-safety", 20, "lab03-content-safety-2"),
    ("demo4-resilient-pool", 16, "lab04-resilient-pool-1"),
    ("demo4-resilient-pool", 18, "lab04-resilient-pool-2"),
    ("demo4-resilient-pool", 20, "lab04-resilient-pool-3"),
]
REDACT_JS = r"""() => {
  const re = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32}/gi;
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) w.currentNode.nodeValue = w.currentNode.nodeValue.replace(re, "<redacted>");
}"""
with sync_playwright() as p:
    page = p.chromium.launch().new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2)
    for stem, cell_no, name in SHOTS:
        page.goto(Path(f"outputs/html/{stem}.html").resolve().as_uri())
        page.evaluate(REDACT_JS)
        cell = page.locator(".jp-Cell").nth(cell_no - 1)
        cell.locator(".jp-OutputArea").first.screenshot(path=f"docs/assets/images/{name}.png")
```

Selector notes: nbconvert 7 `lab` template renders each notebook cell as `div.jp-Cell` (markdown and code, in order, so `nth(cell_no - 1)` maps to the editor cell number) with outputs under `.jp-OutputArea`; newer nbconvert also emits `id="cell-id=<cell.id>"` on each cell div, which is more robust than index if cell ids are stable (verify on first run). Keep a fixed viewport and `device_scale_factor=2` for crisp docs images.

### 6.4 Recommendation

Use **Approach B for all docs images** (single consistent look, covers tables + banners + charts, supports redaction), and Approach A only if a raw lossless chart is wanted. Naming: `docs/assets/images/labNN-<slug>-<n>.png` with `lab00`..`lab04` and slugs `setup`, `token-limits`, `token-metrics`, `content-safety`, `resilient-pool`; `n` = 1-based order within the lab from a checked-in manifest (the `SHOTS` list), so filenames are stable across runs. Skip 00 cell 4 (az output), demo4 cell 10 (key), and demo2 cell 5 (first-run preflight FAILs) unless redacted/fixed.

Publishing: executed notebooks/HTML go to `outputs/` (already gitignored) and are uploaded as artifacts; images are committed via a PR (or a `docs-images` artifact the docs job consumes) rather than pushed directly.

---

## 7. requirements.txt

Current (requirements.txt L1-L9): azure-identity, azure-monitor-query, requests, python-dotenv, pandas, **matplotlib>=3.7.0**, **ipykernel>=6.29.0**, **jupyter>=1.0.0** (pulls nbconvert, nbclient, nbformat, jupyter_client), tabulate.

Missing for CI: `papermill` (not included), `playwright` (screenshots), optionally `pytest`. `nbformat`/`nbconvert` are transitively present via `jupyter`; pin explicitly in a CI file for reproducibility.

Suggested `requirements-ci.txt` (keeps workshop requirements unchanged):

```text
-r requirements.txt
papermill>=2.7.0
nbformat>=5.10
nbconvert>=7.16
playwright>=1.47
```

Kernel: installing `ipykernel` in the job interpreter provides the native `python3` kernelspec, so `-k python3` resolves to that interpreter; no `ipykernel install` step needed (harmless to add `python -m ipykernel install --user --name python3`).

---

## 8. papermill (web-checked)

* Current version **2.7.0** (released 2026-02-27), Python >= 3.10: https://pypi.org/project/papermill/
* CLI (https://papermill.readthedocs.io/en/latest/usage-cli.html): `papermill [OPTIONS] NOTEBOOK_PATH [OUTPUT_PATH]`; relevant options `-k/--kernel`, `--cwd` ("Working directory to run notebook in"), `--log-output`, `--execution-timeout` ("default: forever"), `--request-save-on-cell-execute` (default on), `--report-mode`, `--start-timeout`.
* `parameters` tag: **not needed** when no parameters are passed. Parameterization only runs `if parameters:` (papermill `execute.py`); docs: "if no cell is tagged parameters, the injected-parameters cell is inserted at the top of the notebook" - which only happens when `-p` is used: https://papermill.readthedocs.io/en/latest/usage-parameterize.html
* Paths: `execute_notebook` wraps IO in `local_file_io_cwd()` and only the kernel runs under `chdir(cwd)`, so input/output paths resolve against the invoking directory (source: https://raw.githubusercontent.com/nteract/papermill/main/papermill/execute.py). Absolute paths are still recommended.
* Failure: on a cell error papermill inserts an error-marker markdown cell at the top and before the failing cell, writes the output notebook, and raises `PapermillExecutionError` (non-zero exit).

Example command:

```bash
papermill notebooks/demo1-token-limits.ipynb "$GITHUB_WORKSPACE/outputs/executed/demo1-token-limits.ipynb" \
  --cwd notebooks -k python3 --log-output --execution-timeout 900
```

(Omit `--log-output` for demo4 until the key print in cell 10 is masked.)

---

## CI execution outline (ubuntu-latest)

```yaml
permissions: { id-token: write, contents: read }
jobs:
  run-labs:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    env: { PYTHONUNBUFFERED: "1" }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: pip install -r requirements-ci.txt && python -m playwright install --with-deps chromium
      - uses: azure/login@v3
        with: { client-id: ..., tenant-id: ..., subscription-id: ... }
      - name: Write .env from deployment outputs
        run: |  # az deployment group show ... --query properties.outputs; add-mask the connection string
          ...  # writes the template in section 1.4 to $GITHUB_WORKSPACE/.env
      - run: mkdir -p outputs/executed
      - name: 00 setup
        run: papermill notebooks/00-setup-and-validation.ipynb "$PWD/outputs/executed/00-setup-and-validation.ipynb" --cwd notebooks -k python3 --log-output --execution-timeout 900
      - uses: azure/login@v3   # refresh OIDC assertion before each notebook
      - name: Lab 1
        run: papermill notebooks/demo1-token-limits.ipynb "$PWD/outputs/executed/demo1-token-limits.ipynb" --cwd notebooks -k python3 --log-output --execution-timeout 900
      - uses: azure/login@v3
      - run: az account get-access-token --scope https://api.loganalytics.io/.default -o none
      - name: Lab 2
        run: papermill notebooks/demo2-token-metrics.ipynb "$PWD/outputs/executed/demo2-token-metrics.ipynb" --cwd notebooks -k python3 --log-output --execution-timeout 900
      - uses: azure/login@v3
      - name: Lab 3
        run: papermill notebooks/demo3-content-safety.ipynb "$PWD/outputs/executed/demo3-content-safety.ipynb" --cwd notebooks -k python3 --log-output --execution-timeout 900
      - uses: azure/login@v3
      - name: Lab 4
        run: papermill notebooks/demo4-resilient-pool.ipynb "$PWD/outputs/executed/demo4-resilient-pool.ipynb" --cwd notebooks -k python3 --execution-timeout 900
      - name: Check lab outcomes
        if: always()
        run: python scripts/check_notebook_outputs.py outputs/executed
      - name: Render HTML + screenshots
        if: always()
        run: |
          jupyter nbconvert --to html --template lab --output-dir outputs/html outputs/executed/*.ipynb
          python scripts/capture_lab_images.py
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: lab-outputs, path: "outputs/\ndocs/assets/images/", retention-days: 7 }
```

Order must stay sequential (00 -> demo1 -> demo2 -> demo3 -> demo4): shared APIM, and `DEMO_RUN` is persisted to `.env` between notebooks. Teardown of APIM child resources is out of scope here (demo4 cell 25 is gated by hardcoded `REMOVE_WORKSHOP_ARTIFACTS = False`).

---

## Key discoveries (summary)

1. Headless runs need **no code change** for prompts if CI writes a repo-root `.env` containing the key **lines** `AOAI_KEY=`, `AOAI_API_STYLE=v1`, `CONTENT_SAFETY_KEY=`, and six `DEMO4_*=` (env vars alone do not suppress those prompts; `_dotenv_keys()` reads the file).
2. `DEMO_RUN` must be fresh per run (daily token quota counter-key).
3. Only Windows assumption: 00 cell 4 `shell=True` with a list - harmless on Linux (runs bare `az`), misleading output.
4. OIDC assertion lifetime (~5 min) breaks Demo 2's Log Analytics token request unless `azure/login` is re-run / token pre-warmed; the failure is swallowed into a Demo 2 FAIL.
5. Demo 2 preflight shows expected `FAIL:` on fresh environments; Demo 1/Demo 4 have no PASS/FAIL strings -> use a manifest checker, not a global grep.
6. **Demo 4 routing mode is broken as written**: forwarded path `/east/openai/v1/chat/completions` does not match mock operation `/east` -> 404, `x-served-by` "not returned", breaker never trips. Minimal fix: mock operation template `f"/{member}/*"` (demo4 cell 7 L35).
7. Demo 4 cell 10 L8 prints the APIM subscription key unmasked.
8. Only 2 PNG charts exist; all other lab evidence is HTML tables/banners -> nbconvert HTML + Playwright element screenshots with redaction.
9. Add `papermill>=2.7.0` (+ `playwright`) via a CI requirements file; no `parameters` tag needed.
10. Runtime ~15-27 min execution + setup; set per-cell `--execution-timeout 900`, job timeout 60 min.

## Recommended next research (not done)

- [ ] Live-verify APIM wildcard template `/east/*` matches multi-segment suffixes (Basic v2) and whether the client subscription key header is forwarded to the mock.
- [ ] Confirm nbconvert 7 lab template cell selectors/`cell-id` attribute on the pinned version.
- [ ] Confirm IaC mechanism for App Insights "custom metric dimensions" (drives Demo 2 PASS 01-03) and typical `customMetrics` ingestion latency through a buffered APIM logger vs the 225 s backoff.
- [ ] Decide whether Bicep pre-creates an APIM App Insights logger (would turn Demo 2 preflight row 1 into PASS).
- [ ] Measure actual per-notebook runtime on the first run and tune timeouts.

## Clarifying questions

1. Should `NOT TRIPPED` (Demo 3) and Demo 2 acceptance FAILs fail the build or only warn until the environment is proven stable?
2. Are the two minimal code fixes (Demo 4 wildcard operation, Demo 4 key masking) in scope for the implementation phase? Optional third: 00 cell 4 `shell=sys.platform == "win32"`.
3. Should docs images be committed by the workflow via PR, or produced as an artifact for a separate docs build?

## References

* shared/config.py, shared/auth.py, shared/apim.py, shared/display.py, shared/fixtures.py
* notebooks/00-setup-and-validation.ipynb, notebooks/demo1-token-limits.ipynb, notebooks/demo2-token-metrics.ipynb, notebooks/demo3-content-safety.ipynb, notebooks/demo4-resilient-pool.ipynb
* policies/demo4-mock-origin.xml, policies/demo4-resilient-pool.xml
* requirements.txt, tests/test_apim.py
* [papermill CLI](https://papermill.readthedocs.io/en/latest/usage-cli.html), [papermill parameterize](https://papermill.readthedocs.io/en/latest/usage-parameterize.html), [papermill on PyPI](https://pypi.org/project/papermill/), [papermill execute.py](https://raw.githubusercontent.com/nteract/papermill/main/papermill/execute.py)
* [Azure/login README](https://github.com/Azure/login), [GitHub OIDC concepts](https://docs.github.com/en/actions/concepts/security/openid-connect)
* [APIM: manually add an API / wildcard operations](https://learn.microsoft.com/en-us/azure/api-management/add-api-manually)
