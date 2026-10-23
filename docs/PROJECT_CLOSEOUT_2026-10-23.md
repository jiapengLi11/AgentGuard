# 项目结项与公开材料索引（2026-10-23）

本次结项是已有研究原型与比赛材料的公开归档，不把未完成能力改写为完成，不关闭后续协作，也未代替队长向比赛平台提交材料。

## 版本边界

| 对象 | 版本与用途 |
|---|---|
| 结项前主线 | `d4141fdac9668e20f03ef88e23cb80562c1c936f`；本轮不改运行时 |
| 当前运行时验收 | 与 `985417a437eec6c7b53ce4f64c52f72369499f6d` 的 `sujie/` 无差异；[跨平台质量门禁成功](https://github.com/jiapengLi11/AgentGuard/actions/runs/39599299709) |
| 正式程序基线 | `96d591b14460a531004ae2b18aa4004a24af78d3`；[冻结质量门禁](https://github.com/jiapengLi11/AgentGuard/actions/runs/39286375609) |
| 报告源码绑定 | `1b64b1fdfbbd108decdede7383adc5cfb297626d`，312 份源码；报告采用 2026-10-22 宋体修订版 |
| M13–M21 旧记录 | 42 个旧运行目录，保留失败和未完成记录，不能代表当前模型比较或正式 ASR |

## 所有材料从哪里取

入口：[结项 Release](https://github.com/jiapengLi11/AgentGuard/releases/tag/closeout-2026-10-23)。Release 页自动提供本次标签的完整 Git 源码 ZIP/TAR；下表的专用包各有明确版本，不是同一份源码的重复命名。

| 材料 | 仓库或附件 |
|---|---|
| 当前完整项目源码、单元/集成测试、合成样例、配置模板、锁文件 | `sujie/`；旧原型 `agentguard/`、`tests/`、`benchmark/`；Git 标签源码下载 |
| 总体设计、架构、安全模型、团队开发与阶段记录 | `competition/docs/`、`docs/`、`sujie/docs/` |
| 正式报告、部署、测试三个 PDF | `competition/submission/release/2026-10-22/`；附件 `sujie-report.pdf`、`sujie-deployment-guide.pdf`、`sujie-test-samples-and-flow.pdf` |
| LaTeX 文稿和原版绘图代码 | `competition/submission/latex/`；附件 `sujie-latex-project.zip`；完整字体不再分发 |
| 已验收的冻结 Python 源码发行包，含预构建 Vue | `sujie-python-distribution.zip`，保持 2026-10-22 字节不变 |
| 正式证据、逐文件清单、失败及通过日志 | `sujie-evidence-packet.zip`，保持 2026-10-22 字节不变 |
| 早期模型/脚本运行的原始文字记录与源码快照 | 新附件 `sujie-historical-evidence-m13-m21.zip`：483 份 JSON/TXT，排除 62 份预算数据库/日志文件；此次零内容脱敏，保留原字节 |
| 历史原型演示和基准输出 | `docs/legacy-v01/`；只说明旧 v0.1，不加入当前验收统计 |
| 公开包重建与审计工具 | `competition/submission/tools/build_public_history.py`；工具测试与文稿源码核验纳入专用 CI |
| 发布完整性 | Release 的 `SHA256SUMS.txt`；历史包自带 `PUBLICATION_MANIFEST.json`（原始/公开 SHA-256） |

历史材料不是新实验。公开包的清单仅证明所收录文件的一致性，不证明模型结果真实、安全有效或签名真实性。旧云记录含当时已暴露的开发输入和版本，仅供追溯；正式报告没有据此补填模型 ASR。

## 隐私处理及不上传范围

- 已从 2026-10-18、2026-10-20 两个 Release 移除共 4 个原创性声明 PDF/DOCX 附件，其中 2026-10-20 PDF 含手写签名。原件仅在本地忽略目录私密备份，未放进新 Release。
- 2026-10-20 的 4 个仓库成品改用 ASCII 通用文件名，正文清单中的队员姓名改为占位；PDF/证据内容未因重命名改变。
- 2026-10-18 旧源码包曾夹带第三方官方附件，其 DOCX 页眉包含作者目录；移除该旧包内的 `artifacts/review-2026-10-05/official/` 非运行时附件，重算**包装**清单并加入隐私处理说明。运行时实验哈希不篡改。
- 不公开 API CSV、云密钥、`.env`、操作者 token、签名图、签名版声明、预算 SQLite、虚拟环境、node_modules、模型缓存及未授权字体。合成秘密、技术摘要/签名字段与公开引用不当作真人隐私删除。
- 本轮检查了 Git 跟踪文本、PDF 文本/作者元数据、公开附件及 ZIP 内层。自动扫描不是“绝无泄露”保证；历史作者信息和旧文件名仍可存在 Git 历史，且不能召回已下载或分叉副本。本轮未强推、改写历史或删除其他协作者提交；如需历史级匿名化，须另行协调。

## 验证与未完成项

当前 `sujie/` 与已成功的跨平台质量门禁版本无差异；结项改动仅为材料、隐私处理和发布工具，重新验证发布工具、文稿绑定、包哈希与公开附件。本轮不冒充重新执行了冻结包全量测试。

冻结包既有解压复验：1107 passed / 1 skipped / 1 xfailed / 1 warning，四业务 16/16、云调用 0，见[原始记录](validation/SUBMISSION_PACKAGE_REVIEW_2026-10-22.json)。不同系统的测试数按各自日志引用，不混成一个成绩。

仍未完成：真实模型独立任务主比较、正式 Execution ASR 与统计、完整工具/角色拓扑隔离、生产延迟与吞吐验收、外部宿主完整接入。已知审批后超限返回部分效果审计 xfail 仍存在；本地 token 区间与来源 DAG 不代表模型内部因果归因。演示视频未录制。现有计划和阶段文档按历史原样保留。

结项后继续开发时从最新 `main` 建分支；不要覆盖冻结交付标签，也不要将本地私密备份批量上传。
