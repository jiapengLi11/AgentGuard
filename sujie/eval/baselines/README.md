# 五配置开发评测

更新：2026-10-15。共同框架位于 `eval/runtime_variants.py`、`paired_runtime.py` 与 `run_common_runtime_validation.py`；不是本空目录内的独立实现。支持 `unsafe / strong-static / full / no-source / no-recovery`，语义与结果见[M19](../../docs/M19_COMMON_RUNTIME_AND_BASELINES.md)。

评测专用，操作者HTTP无基线切换。配置共用已注册执行器、封闭资源、Provider凭据保护和预算/审批基础设施；B0不是任意宿主命令执行。StrongStatic为固定工具/路径/参数/目的地与ASK；消融只关闭声明机制，不去掉所有公共保障。公共保障不能算Full独有贡献。

已完成35强制提议单元/45脚本业务及10云单元开发比较（7项完成，失败保留），不是正式独立任务矩阵、35次全阻断或比赛ASR。M21新四业务还未补正式共同矩阵。复现使用新输出目录，云调用前固定新预算和协议，见[手册](../../docs/PROJECT_HANDOFF.md)。
