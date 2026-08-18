# AI Model Adapter（AI 模型适配器）

**在严格授权门禁下，规划、适配、评估、监控、恢复并导出开源 AI 模型。**

`ai-model-adapter` 是一个 [Codex](https://openai.com/codex) Skill：把自然语言适配目标转化为可度量、有预算、隔离运行的 campaign（任务），并沿固定生命周期推进——`plan → authorize → start → status/watch → pause/resume → stop → evaluate → export → update-db`。所有安全门禁都由 `scripts/` 中的 Python 脚本强制执行，而不是依赖提示词约束。

> **核心设计理念：验证写在代码里，不写在提示词里（Verification in code, not in the prompt）。**
> 模型资格检查、预算字段、置信区间门禁、人工盲审、哈希完整性校验，全部由脚本把关——模型无法靠「说辞」绕过任何一道检查。

[English README](README.md)

## 为什么需要它

适配开源模型风险很高：隐式下载、未批准的架构改动、伪造的评估分数、无人跟踪的状态。本项目把每次适配当作一个隔离的 **campaign**，具备：

- **不隐式触发**——只有显式 `/ai-model-adapter` 前缀才激活（`agents/openai.yaml` 中 `allow_implicit_invocation: false`）。
- **AI 只规划、不擅动**——`plan` 仅做分析，campaign 停留在 `awaiting_authorization`。
- **显式授权**——预算（迭代次数、GPU 时长、磁盘、耐心值）、允许的适配方法、架构/基座更换、WSL2/云端执行、数据范围，各自需要独立批准。
- **本地优先、只留链接**——未经授权不下载任何内容；资源记录必须使用 `link-only` 下载策略。
- **campaign 隔离**——每个 campaign 拥有独立工作区：持久本地状态、事件历史、心跳报告、检查点、失败记忆、可逆清理计划。
- **不伪造结果**——开放式/多模态质量结论必须经过人工盲审；禁止 AI 编造人工评分。

## 生命周期与命令

| 命令 | 作用 |
|---|---|
| `plan` | 仅分析。把目标转换为任务类型、模态、指标、基线、限制与验收标准，创建 `awaiting_authorization` 的 campaign。 |
| `authorize <campaign_id>` | 显式批准预算 + 方法 + 环境（架构、WSL2、Linux、数据范围）。 |
| `start <campaign_id>` | 创建隔离目录并启动 supervisor + monitor。NExT-GPT 适配器始终先出 dry-run 报告并阻止真实训练。 |
| `status <campaign_id>` | 读取 `status/current.json`——本地权威状态。 |
| `watch` / `unwatch <campaign_id>` | 注册/移除独立监控；`monitor_campaign.py` 轮询心跳。 |
| `pause` / `resume <campaign_id>` | 在迭代间安全点暂停；恢复前必须先通过哈希完整性校验。 |
| `stop <campaign_id>` | 停止并保留全部证据。 |
| `evaluate <campaign_id>` | 自动评估 + 可选人工盲审；绝不编造人工评分。 |
| `export <campaign_id>` | 导出达标版本（含 `checksums.sha256`）——仅当 completed 且 `acceptance_met` 时允许。 |
| `update-db <campaign_id>` | 将待审提案写入 `pending-updates`；绝不自动改动正式目录。 |

执行器必须在以下情况下停止：达成验收、预算耗尽、无改进耐心值触顶、阻塞错误、暂停或停止；且不得在最终盲测集上调参。

## 安装

```powershell
# 复制到 Codex skills 目录（自动发现）
Copy-Item -Recurse "ai-model-adapter" "$env:CODEX_HOME\skills\ai-model-adapter"
```

或在 Codex 中使用技能安装器：

```text
/install-skill uers123/ai-model-adapter
```

## 快速开始

先设置你自己的数据路径。内置默认值是作者本机 Windows 路径（定义在 `scripts/common.py`）——**务必用环境变量覆盖**。

```powershell
$env:AI_MODEL_ADAPTER_DB    = "C:\ai-model-adapter\db"      # 知识数据库
$env:AI_MODEL_ADAPTER_TASKS = "C:\ai-model-adapter\tasks"   # campaign 工作区根目录
$env:AI_MODEL_ADAPTER_CACHE = "C:\ai-model-adapter\cache"   # 只读基础资源缓存

# 1. 规划（仅分析；输出 campaign id）
python scripts/cli.py plan --model mock --goal "Improve classification accuracy on the built-in synthetic fixture" `
  --task-type classification --input-modalities text --output-modalities label

# 2. 显式授权预算与方法
python scripts/cli.py authorize campaign-20260802T120000Z `
  --max-iterations 5 --max-total-gpu-hours 4 --max-disk-usage-gb 10 --max-single-iteration-hours 2 `
  --no-improvement-patience 2 --minimum-effective-improvement 0.01 `
  --allowed-adaptation-methods inference --allow-partial-unfreeze no --allow-full-finetuning no `
  --data-scope mock-fixture

# 3. 启动（mock 运行确定性模拟循环；--foreground 表示同步前台执行）
python scripts/cli.py start campaign-20260802T120000Z --foreground

# 4. 查看、评估、导出、提交库更新提案
python scripts/cli.py status   campaign-20260802T120000Z
python scripts/cli.py watch    campaign-20260802T120000Z --interval-minutes 1
python scripts/cli.py evaluate campaign-20260802T120000Z
python scripts/cli.py export   campaign-20260802T120000Z
python scripts/cli.py update-db campaign-20260802T120000Z
```

> `mock` 是内置确定性模拟器，用于端到端演练编排流程。可在 `plan` 用 `--campaign-id` 指定自定义 id；另有 PowerShell 封装 `scripts/campaign_control.ps1`（start/status/watch/unwatch/pause/resume/stop）。

### 依赖

- **Python 3.10+**——其余均用标准库
- **PyYAML**——读写 campaign / 数据库 YAML 所必需
- **jsonschema**——数据库 schema 校验用（`validate_database.py`）
- **pdfplumber**——PDF 转 Markdown 用（`extract_pdf_markdown.py`）
- **pypdf**——PDF 页数核验用（`build_verification.py`）

### 交付前检查

```powershell
python scripts/self_test.py          # 5/5 确定性安全检查
python scripts/validate_database.py  # 需要已填充的数据库
python scripts/validate_campaign.py <campaign_id>
python scripts/cli.py --help
```

## 目录结构

```
ai-model-adapter/
├── SKILL.md                  # 技能契约：行为约定 + 固定命令接口
├── agents/openai.yaml        # UI 元数据；禁用隐式调用
├── references/               # 9 份按需加载的知识文档（数据库布局、模型资格、适配策略、
│                             #   验收标准、数据治理、Windows 兼容、生命周期、安全策略、NExT-GPT）
├── scripts/
│   ├── cli.py                # 固定命令接口（生命周期全部命令）
│   ├── campaign_supervisor.py # 隔离迭代循环（预算、置信区间、心跳）
│   ├── campaign_monitor.py   # 独立监控（status/monitor.json）
│   ├── monitor_campaign.py   # 轮询本地权威状态
│   ├── evaluate_campaign.py  # 自动评估 + 人工盲审
│   ├── validate_campaign.py  # campaign 校验器
│   ├── validate_database.py  # 数据库校验器（schema、密钥、权重）
│   ├── build_verification.py # 端到端构建验证
│   ├── build_catalog.py      # 由模型记录重建 catalog.jsonl
│   ├── chunk_documents.py    # 语义化 Markdown 分块（代码围栏感知）
│   ├── extract_pdf_markdown.py / extract_notebook_markdown.py
│   ├── cleanup_campaign.py   # 可逆清理计划
│   ├── self_test.py          # 5/5 确定性安全检查
│   ├── campaign_control.ps1  # PowerShell 封装
│   └── adapters/             # base / mock / next_gpt 适配器
└── assets/campaign-template/ # campaign.yaml 模板
```

## 当前状态——诚实边界

这是一个**可演示框架**，真实训练目前刻意未开启。

- **NExT-GPT 适配器强制 dry-run。** `start` 始终写入 `reports/next-gpt-dry-run.json` 并把 campaign 置为 `blocked`——即使资源路径齐全也必须阻止。在接入并验证真实训练执行器之前，不允许启动真实训练（由 `self_test` 守护）。
- **置信区间为模拟值。** supervisor 对模拟循环输出 `指标 ± 0.02` 区间；尚未基于真实评估数据计算。
- **`mock` 适配器输出确定性模拟指标**——适合演练编排，不能用于真实质量结论。
- **导出仅含编排元数据**（`base_model_unchanged: true`，不打包权重），并附 `checksums.sha256` 清单。
- **知识数据库在仓库之外。** 请将 `AI_MODEL_ADAPTER_DB` 指向你已填充的数据库；本仓库提供技能契约、脚本、参考文档与模板。

## Roadmap

- **真实训练执行器**：在 `Adapter` 接口之后接入真实训练（如 LoRA/DeepSpeed），使 `start` 真正训练；在验证通过前保留 NExT-GPT 的 dry-run 门禁。
- **真实置信区间**：基于留出集评估计算，替换模拟区间。
- **更多模型适配器**与知识记录，由 `catalog.jsonl` 驱动。
- **可选 Linux/容器执行**路径，超出 Windows 优先边界，始终置于显式批准之后。

## 许可

BSD-3-Clause · Copyright (c) 2026, uers123
