# M0 安全声明及剩余边界

> **2026-10-15 交接说明：** 历史纯Schema/领域边界。“未实现”列表仅指M0；当前已有MCP/来源登记/审批原子提交/模型预算/撤销传播及本地token等后续实现。生产身份/签名、跨崩溃提交恢复、通用OS隔离和完整DLP仍未完成，不能把本页当作当前全部风险表。
> [当前交接手册](PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

已实现的是纯领域校验，不是网关或授权服务。

| 声明 | 测试 ID |
|---|---|
| 子 Grant 效果、资源、期限与单次额度不超过父 Grant | ARCH-GRANT-001—015 |
| DATA_ONLY 不能授权，即使载荷自报 AUTHORIZE | ARCH-PROV-011 |
| 普通派生不提高 authority/integrity 或降低 confidentiality | ARCH-PROV-001—014 |
| 危险证据仍可读取、分析、引用与存档 | ARCH-PROV-012 |
| BLOCK 不被普通审批或语义建议覆盖 | ARCH-APPROVAL-002、ARCH-DECISION-001 |
| 工具/参数/任务/来源摘要变化使旧绑定不匹配 | ARCH-APPROVAL-003—024 |
| 未知字段、伪造格式、非有限数值、重复 JSON 键拒绝 | SCHEMA-* |
| 领域校验不依赖数据库或网络 | Schema 离线测试、SCAFFOLD-003 |

未实现：认证、签名、可信任务编译、完整 Need/Contract 交集、兄弟 Grant 共享预算、
父授权递归撤销、来源/exposure 登记、可靠工具 Hash 采集、审批原子消费及持久幂等、
真实参数物化、OS 隔离、MCP、DLP、token 映射、安全恢复。

approval_is_valid 是无副作用资格检查，重复调用不会消费审批，不可宣称防重放。
输入内容/来源 Hash 在 M0 是测试输入，M1 必须由可信运行时采集。
assert_child_within_parent 只证明父权限上限，不代替完整 Need/Contract 交集。

不抵御同进程恶意 Python 篡改类或内存；进程隔离属于后续部署。
路径检查不证明符号链接、挂载、竞态或实际文件句柄安全。
Schema 不证明文本可信、原文真实性或已脱敏。
SecurityException 当前只有结构定义，不是已实现的恢复/输出过滤器。

fixtures 仅用合成标识与摘要；不读取用户密钥，不访问外传地址。
