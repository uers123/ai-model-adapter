# AI Model Adapter

**Plan, adapt, evaluate, monitor, resume, and export open-source AI models — only after explicit authorization.**

`ai-model-adapter` is a [Codex](https://openai.com/codex) Skill that turns a natural-language adaptation goal into a measurable, budgeted, isolated campaign and walks it through a fixed lifecycle — `plan → authorize → start → status/watch → pause/resume → stop → evaluate → export → update-db`.

> **Design principle: verification in code, not in the prompt.** Every gate — model qualification, budget fields, confidence intervals, blind human review, hash integrity — is enforced by Python scripts in `scripts/`, so no model can talk its way past a check.

[中文简介](#中文简介) · [中文版 README](README.zh.md)

## Why it exists
Adapting an open-source model is risky: implicit downloads, unapproved architecture changes, fabricated evaluation scores, and untracked state. This skill treats every adaptation as an isolated **campaign** with:

- **No implicit triggering** — the skill activates only on the exact `/ai-model-adapter` prefix (`agents/openai.yaml` sets `allow_implicit_invocation: false`).
- **AI plans, it does not act** — `plan` is analysis-only and leaves the campaign in `awaiting_authorization`.
- **Explicit authorization** — budget (iterations, GPU hours, disk, patience), allowed adaptation methods, architecture/base-model changes, WSL2/cloud execution, and data scope each require separate approval.
- **Local-first, link-only** — nothing is downloaded unless authorized; resource records must use `link-only` download policy.
- **Isolated campaigns** — each campaign owns a workspace with persistent local state, event history, heartbeats, checkpoints, failure memory, and a reversible cleanup plan.
- **No invented results** — open-ended and multimodal quality claims require blind human review; the skill refuses to fabricate human scores.

## The lifecycle

| Command | What it does |
|---|---|
| `plan` | Analysis only. Converts the goal into task type, modalities, metrics, baseline, limits, and acceptance criteria; creates an `awaiting_authorization` campaign. |
| `authorize <campaign_id>` | Explicit budget + allowed methods + environment approvals (architecture, WSL2, Linux, data scope). |
| `start <campaign_id>` | Creates isolated directories and spawns supervisor + monitor. The NExT-GPT adapter always runs a dry-run report and blocks real training. |
| `status <campaign_id>` | Reads `status/current.json` — the local authoritative state. |
| `watch` / `unwatch <campaign_id>` | Register or remove an independent monitor; `monitor_campaign.py` polls heartbeats. |
| `pause` / `resume <campaign_id>` | Pause at a safe point between iterations; resume only after hash-integrity verification. |
| `stop <campaign_id>` | Stop and preserve all evidence. |
| `evaluate <campaign_id>` | Automatic evaluation + optional blind human review; never invents human scores. |
| `export <campaign_id>` | Export an accepted version (with `checksums.sha256`) — only when completed with `acceptance_met`. |
| `update-db <campaign_id>` | Write an audited proposal under `pending-updates`; never mutates the formal catalog automatically. |

The runner must stop on acceptance, budget limits, no-improvement patience, blocking errors, pause, or stop — and may not tune on the final blind-test set.

## Installation

```powershell
# Copy into the Codex skills directory (auto-discovered)
Copy-Item -Recurse "ai-model-adapter" "$env:CODEX_HOME\skills\ai-model-adapter"
```

or, from Codex, use the skill installer:

```text
/install-skill uers123/ai-model-adapter
```

## Quick start

Set your own data paths first. The built-in defaults are the author's local Windows folders (defined in `scripts/common.py`) — **always override them**.

```powershell
$env:AI_MODEL_ADAPTER_DB    = "C:\ai-model-adapter\db"      # knowledge database
$env:AI_MODEL_ADAPTER_TASKS = "C:\ai-model-adapter\tasks"   # campaign workspace root
$env:AI_MODEL_ADAPTER_CACHE = "C:\ai-model-adapter\cache"   # read-only resource cache

# 1. Plan (analysis-only; prints a campaign id)
python scripts/cli.py plan --model mock --goal "Improve classification accuracy on the built-in synthetic fixture" `
  --task-type classification --input-modalities text --output-modalities label

# 2. Authorize budget and methods explicitly
python scripts/cli.py authorize campaign-20260802T120000Z `
  --max-iterations 5 --max-total-gpu-hours 4 --max-disk-usage-gb 10 --max-single-iteration-hours 2 `
  --no-improvement-patience 2 --minimum-effective-improvement 0.01 `
  --allowed-adaptation-methods inference --allow-partial-unfreeze no --allow-full-finetuning no `
  --data-scope mock-fixture

# 3. Start (mock runs a deterministic simulated loop; --foreground keeps it synchronous)
python scripts/cli.py start campaign-20260802T120000Z --foreground

# 4. Inspect, evaluate, export, and propose database updates
python scripts/cli.py status  campaign-20260802T120000Z
python scripts/cli.py watch   campaign-20260802T120000Z --interval-minutes 1
python scripts/cli.py evaluate campaign-20260802T120000Z
python scripts/cli.py export  campaign-20260802T120000Z
python scripts/cli.py update-db campaign-20260802T120000Z
```

> The `mock` model is a built-in deterministic simulator for exercising orchestration end-to-end. Use `--campaign-id` on `plan` to choose your own id; a PowerShell wrapper (`scripts/campaign_control.ps1`) covers start/status/watch/unwatch/pause/resume/stop.

### Dependencies

- **Python 3.10+** — everything else is the standard library
- **PyYAML** — required to read/write campaign and database YAML
- **jsonschema** — needed for database schema validation (`validate_database.py`)
- **pdfplumber** — needed for PDF → Markdown extraction (`extract_pdf_markdown.py`)
- **pypdf** — needed for PDF page-count verification (`build_verification.py`)

### Pre-delivery checks

```powershell
python scripts/self_test.py          # 5/5 deterministic safety checks
python scripts/validate_database.py  # requires a populated database
python scripts/validate_campaign.py <campaign_id>
python scripts/cli.py --help
```

## Repository layout

```
ai-model-adapter/
├── SKILL.md                  # skill contract: behavior + fixed command interface
├── agents/openai.yaml        # UI metadata; implicit invocation disabled
├── references/               # 9 on-demand knowledge docs (layout, qualification,
│                             #   strategies, acceptance, governance, Windows, lifecycle, security, NExT-GPT)
├── scripts/
│   ├── cli.py                # fixed command interface (the lifecycle commands)
│   ├── campaign_supervisor.py # isolated iteration loop (budget, CI, heartbeats)
│   ├── campaign_monitor.py   # independent monitor (status/monitor.json)
│   ├── monitor_campaign.py   # poll the authoritative local state
│   ├── evaluate_campaign.py  # automatic evaluation + blind human review
│   ├── validate_campaign.py  # campaign validator
│   ├── validate_database.py  # database validator (schemas, secrets, weights)
│   ├── build_verification.py # end-to-end build verification
│   ├── build_catalog.py      # rebuilds catalog.jsonl from model records
│   ├── chunk_documents.py    # semantic Markdown chunking (code-fence aware)
│   ├── extract_pdf_markdown.py / extract_notebook_markdown.py
│   ├── cleanup_campaign.py   # reversible cleanup plan
│   ├── self_test.py          # 5/5 deterministic safety checks
│   ├── campaign_control.ps1  # PowerShell wrapper
│   └── adapters/             # base / mock / next_gpt adapters
└── assets/campaign-template/ # campaign.yaml template
```

## Current status — honest limits
This is a **demonstrable framework**; real training is deliberately not enabled yet.

- **NExT-GPT adapter is dry-run-only by design.** `start` always writes `reports/next-gpt-dry-run.json` and moves the campaign to `blocked` — even when every resource path is present. Real training must not start until a verified real-training executor exists (guarded by `self_test`).
- **Confidence intervals are simulated.** The supervisor emits a `metric ± 0.02` band for the simulated loop; intervals are not yet computed from real evaluation runs.
- **The `mock` adapter emits deterministic simulated metrics** — useful for exercising orchestration, never for real quality claims.
- **Exports contain orchestration metadata only** (`base_model_unchanged: true`, no weights bundled) with a `checksums.sha256` manifest.
- **The knowledge database is external.** Point `AI_MODEL_ADAPTER_DB` at your populated database; this repo ships the skill contract, scripts, references, and templates.

## Roadmap

- **Real training executor** behind the `Adapter` interface (e.g., LoRA/DeepSpeed) so `start` can genuinely train; keep the NExT-GPT dry-run guard until it is verified.
- **Real confidence intervals** computed from held-out evaluation runs, replacing the simulated band.
- **More model adapters** and knowledge records driven by `catalog.jsonl`.
- **Optional Linux/container execution** beyond the Windows-first boundary, always behind explicit approval.

## License

BSD-3-Clause · Copyright (c) 2026, uers123

## 中文简介

`ai-model-adapter` 是一个 Codex Skill：在严格授权门禁下管理开源 AI 模型适配的全生命周期（plan → authorize → start → status/watch → pause/resume → stop → evaluate → export → update-db）。核心理念是「验证写在代码里，不写在提示词里」——资格检查、预算字段、置信区间门禁、盲审与哈希完整性校验均由 Python 脚本强制执行；不隐式触发，AI 只规划不擅动。当前 NExT-GPT 适配器为 dry-run 演示框架（即使资源齐全也强制阻止真实训练），置信区间为模拟值，真实训练执行器与真实置信区间在路线图中。完整中文文档见 [README.zh.md](README.zh.md)。
