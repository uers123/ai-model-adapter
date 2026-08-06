# Campaign 生命周期

允许状态：

```text
planned -> awaiting_authorization -> authorized -> running
running -> pausing -> paused -> running
running -> evaluating -> completed
running -> blocked | failed | stopped
```

每个任务目录必须含 `campaign.yaml`、`status/current.json`、`status/history.jsonl`、`logs/`、`reports/live-progress.md`、`memory/`、`checkpoints/`、`recycle-bin/` 和 `final/`。本地 `current.json` 是权威状态；对话监控只负责通知，不替代状态文件。

每次授权都必须填写最大迭代、GPU 小时、磁盘、单轮时长、无提升耐心值、最小有效提升、允许方法以及部分解冻/全量微调开关。没有预算不得启动。

心跳默认十分钟；测试可使用短间隔。心跳包含迭代、epoch、loss、验证指标、历史最佳、GPU、温度、磁盘、耗时、剩余预算、预计完成时间和异常。

`evaluating` 不是终态，等待真实人工盲审时监控器可以继续记录状态。用户执行 `unwatch` 后必须停止监控；如果监控 PID 已不存在但 `monitor.json` 仍为 `watching`，命令应立即把本地状态对账为 `unwatched` 并清除残留请求。
