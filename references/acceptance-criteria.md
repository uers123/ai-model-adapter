# 验收标准与盲审

先把自然语言目标写成可测量标准，再开始任何训练：

| task_type | 自动指标 |
|---|---|
| classification | Accuracy, Precision, Recall, F1 |
| detection | mAP, recall, false_positive_rate |
| ocr | character_accuracy, edit_distance |
| asr | WER |
| image_qa | answer_accuracy, hallucination_rate |
| generation | task_metric, relevance, safety |
| multimodal | endpoint_success_rate, key_case_pass_rate, hallucination_rate |

记录 `baseline_metrics`、`target_metrics`、`minimum_absolute_improvement`、`current_metrics`、`confidence_level`、`confidence_intervals`、`regression_checks`、`regression_results` 和 `human_review_status`。默认置信度为 95%。开放式、生成式和多模态质量必须增加盲审；评估者不能看到模型版本和训练轮次。没有真实人工评分时只能写 `pending`，不能让 AI 代填。

置信区间必须支持目标，而不只是存在：越大越好的指标要求区间下界达到目标；越小越好的指标要求区间上界不超过目标。人工盲审文件必须包含 `scores` 对象和人工给出的布尔值 `accepted`；评分完成但 `accepted: false` 时不得导出。

达标即停。未达标时按失败案例、指标变化和预算重新规划；连续无有效提升、预算达到上限、数据或许可变化、异常阻塞、用户暂停或停止时结束。
