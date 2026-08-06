# 数据库布局与字段约定

默认路径：

```text
D:\github-neirong\AI训练开源模型
D:\github-neirong\AI模型特调任务
D:\github-neirong\AI模型基础资源
```

数据库保存知识、档案、来源和审核后的摘要；训练任务保存代码、数据清单、检查点、日志、状态和评估；只读缓存保存经用户授权、哈希核验后的外部资源。三者不能互相写入任意内容。

Markdown 是给人和检索系统阅读的中文正文。YAML、JSON、JSONL 使用稳定英文键名。代码、命令、配置键和模型术语保持原文，后面追加中文注释。每条结构化记录必须包含 `record_id`、`model_id`、`source_url`（或 `source_file`）、`source_revision`、`checked_at` 和 `confidence`。

模型家族和模型版本分开记录。任务绑定 `model_id`、`variant_id` 和 `source_revision`，不能把 `legacy` 与 `official-current` 的命令、依赖、路径或评估结果混用。

