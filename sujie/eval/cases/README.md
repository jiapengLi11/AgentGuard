# eval/cases

> **2026-10-15 交接更新：** 原M1及paired-v1清单/命令保留为早期开发样例。当前13profile、M19共同配置、M20引用及M21四业务的协议与运行器在eval父目录，不是全部在此。M21默认four_business_workflows_v2.json，v1恢复512原字节；新运行用新输出目录，不覆盖原失败。profile/变体/重复不等于正式独立任务。
> 完整现状、启动与证据限制见[交接手册](../../docs/PROJECT_HANDOFF.md)。

M1 的 E2E-CLEAN-001、E2E-IPI-001 与 E2E-ASK-001 当前固化在自动化测试中；
M2 后再把成组任务扩展为独立数据文件。Schema 非法 fixture 不计真实任务。

现有 `detection_v1.json` 是 14 条版本化合成规则检测样例，不是端到端任务集；
使用 `python dev.py eval-detection` 复现其逐例结果与分母。

`tool_agent_paired_v1.json` 是另一套真实工具调用小样本：同一个基础告警报告任务，
七个攻击模板族各有一条攻击和一条合法对照，共 14 条。它不等于 14 个独立基础任务，
也不等于比赛数据集。运行方式：

```powershell
$env:SUJIE_BAILIAN_CREDENTIAL_CSV = 'C:\path\outside\repo\credentials.csv'
.\.venv\Scripts\python.exe eval/run_bailian.py --suite paired-v1 --max-cases 14
```

脚本校验每组恰有一攻一控、唯一 ID 和预期事实存在性；每次运行记录数据集哈希。
