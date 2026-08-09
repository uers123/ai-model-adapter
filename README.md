# AI Model Adapter — Codex Skill

让 Codex 在严格授权门禁下规划、适配、评估、监控、恢复和导出开源 AI 模型。

> 这是一个 [Codex](https://openai.com/codex) Skill。安装后，在 Codex 对话中输入 `/ai-model-adapter` 触发。

## 安装

```powershell
# 复制到 Codex skills 目录（自动发现）
Copy-Item -Recurse "ai-model-adapter" "$env:CODEX_HOME\skills\ai-model-adapter"
```

或使用 Codex 的 skill-installer：

```text
/install-skill uers123/ai-model-adapter
```

## 数据库

默认读取以下知识库（可通过环境变量覆盖）：

| 变量 | 默认路径 | 用途 |
|---|---|---|
| `AI_MODEL_ADAPTER_DB` | `D:\github-neirong\AI训练开源模型` | 模型档案与知识数据库 |
| `AI_MODEL_ADAPTER_TASKS` | `D:\github-neirong\AI模型特调任务` | 训练任务工作区 |
| `AI_MODEL_ADAPTER_CACHE` | `D:\github-neirong\AI模型基础资源` | 只读基础资源缓存 |

> 注意：以上默认路径为作者本机目录，请务必通过环境变量覆盖为你自己的实际路径。

首版随附 NExT-GPT 模型档案（Chapter 8 教程 + 官方当前版本双轨），其他模型按模板扩展。

## 命令

```text
/ai-model-adapter plan        # 需求分析、模型选择、验收标准
/ai-model-adapter authorize   # 预算、数据范围、方法授权
/ai-model-adapter start       # 创建独立工作区并启动
/ai-model-adapter status      # 读取本地权威状态
/ai-model-adapter watch       # 建立独立监控
/ai-model-adapter pause       # 安全检查点暂停
/ai-model-adapter resume      # 验证完整性后恢复
/ai-model-adapter stop        # 停止并保留证据
/ai-model-adapter evaluate    # 自动评估 + 人工盲审
/ai-model-adapter export      # 导出达标版本
/ai-model-adapter update-db   # 提交待审核经验
```

## 关键门禁

- **不隐式触发**：只有显式 `/ai-model-adapter` 前缀才启动
- **不自动下载**：外部模型、权重、数据集默认只保留链接
- **不伪造结果**：AI 不得伪造人工评分；缺少盲审时禁止完成和导出
- **预算必填**：每个训练任务必须填写迭代、GPU、磁盘、耐心值
- **架构单独审批**：修改架构、更换基座、WSL2/云端/上传需独立授权
- **双轨隔离**：NExT-GPT 旧版和当前版命令、依赖、路径不混用
- **置信区间门禁**：95% 置信区间必须实际支持目标，不只检查字段存在

## 文件结构

```
ai-model-adapter/
├── SKILL.md              # Codex Skill 入口
├── agents/openai.yaml    # UI 元数据
├── references/           # 按需加载的参考文档
├── scripts/              # 编排脚本和适配器
│   ├── cli.py            # 固定命令接口
│   ├── campaign_supervisor.py
│   ├── campaign_monitor.py
│   ├── build_verification.py
│   └── adapters/         # mock / next_gpt 适配器
└── assets/               # 模板
```

## 许可

BSD-3-Clause
