# Windows 优先与兼容性边界

执行优先级：

1. 原生 Windows + PowerShell；
2. 原生不兼容时提出 WSL2；
3. 本地资源不足时提出云端；
4. WSL2、云端、数据上传和费用均需单独授权。

`windows-native` 表示已在 PowerShell 语义下验证；`windows-experimental` 表示可尝试但依赖未验证；`wsl2-required` 表示依赖 Bash、Linux 或 CUDA 组合；`linux-only` 表示不提供 Windows 运行承诺；`legacy-only` 表示仅用于历史复现。

不要把 Bash/DeepSpeed 命令机械改写成 PowerShell。官方 NExT-GPT 当前脚本是 Bash/DeepSpeed，首版适配器只做资源、路径和阶段检查的 dry-run，不启动真实训练。

