# NExT-GPT 适配说明

正式记录两个互不混用的版本轨：

- `legacy-chapter8`：Chapter 8 的旧教程、三阶段 `stage_1/2/3`、`train.sh` 和 `app.sh`。只用于历史复现和小白理解。
- `official-current`：官方仓库当前主分支的新版目录、`scripts/pretrain_enc.sh`、`scripts/pretrain_dec.sh`、`scripts/finetune.sh`、`train.py`、`predict.py` 和 `training_utils.py`。记录核查提交、依赖和许可证。

截至 2026-08-02 的官方核查记录写入数据库：

```yaml
repository: https://github.com/NExT-GPT/NExT-GPT
source_revision: 60d618b067ee4cb0d70e7075ae79852780b34fc2
default_branch: main
license: BSD-3-Clause
training_entrypoints:
  - scripts/pretrain_enc.sh
  - scripts/pretrain_dec.sh
  - scripts/finetune.sh
inference_entrypoint: predict.py
legacy_path: NExT-GPT-Lagacy
```

官方脚本依赖 Linux/Bash、DeepSpeed、CUDA 和外部 checkpoints。首版 `next_gpt.py` 只生成训练计划、资源缺口和 Windows/WSL2 边界；它没有真实训练执行器，因此即使资源路径齐全并传入 `--real-training`，也必须保持 dry-run 并阻止执行。dry-run 不伪造准确率、视觉识别结果或已训练产物。
