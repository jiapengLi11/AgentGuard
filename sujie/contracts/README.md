# Schema 包 v0.2

> **2026-10-15 交接更新：** 当前仍是九类对象、契约包0.2/载荷schema_version=1.0。独立Python/FastAPI控制面已经实现，并复用契约校验；Java适配尚未实现。下文“M0不声称/后续里程碑”等为对象冻结时边界，不表示当前没有运行时工具摘要/审批/来源。Hash是本地一致性指纹，不是签名。
> 完整现状、启动与证据限制见[交接手册](../docs/PROJECT_HANDOFF.md)。

架构来源为 ../../competition/docs/SUJIE_FINAL_DESIGN.md，第 4—11 节。
按实施总指令增加所有对象必填 schema_version；保留最终设计载荷示例的 "1.0"。
v0.2 在F2中扩展上下文登记、模型请求/回应检查与出口阻断四种Trace事件。
包版本不替换载荷版本1.0；旧事件仍有效，新事件需要v0.2枚举。
变更记录见 [ADR-002](../docs/adr/ADR-002-context-audit.md)。
ctr_... 等只是示例占位，真实 fixtures 使用 ULID；同样接受 UUIDv7。

## 九类业务对象

TaskContract、TaskGrant、ProvenanceEnvelope、SemanticAction、DecisionRecord、
ApprovalRecord、TraceEvent、SecurityException、DetectionFinding。
文件名采用对应的 kebab-case.schema.json。

Schema 是序列化事实来源。每份文件独立使用本地 $defs，不从网络解析引用。
enums.json 检查跨 Schema 枚举一致性。manifest.json 固定 Schema 文本 Hash（LF 换行），
变更需审阅，不自动更新。

M0 Python 模型是对 Schema 验证后 JSON 的不可变领域封装，不维护第二套字段定义。
当前 FastAPI/Pydantic HTTP 适配已在 Python 控制面接入；领域对象仍不得绕开同一份 Schema 验证。

## 补全规则

设计示例的 TaskContract、TaskGrant、ProvenanceEnvelope、SemanticAction 字段均保留；
Decision/Approval/Detection 的字段按设计叙述补全。
枚举成员明细见 enums.json；它们不是新增授权来源。

Approval binding 包含主体/任务/动作、合同与 Grant 快照、工具、参数、
输入内容与来源状态 Hash。Grant 没有 version 字段，所以使用整个不可变快照摘要，
没有擅自加入 Grant.version。工具聚合 Hash 应在 M1 绑定描述、Schema、身份和实现版本，
M0 不声称已采集这些数据。

M0 Hash 使用 Python 确定性 JSON 编码，只是本地指纹，不是签名或跨语言 JCS。
Java 互操作之前必须冻结并验证统一字节编码，禁止各端自行猜测。

resource-scope 首轮接受规范 POSIX 路径、末尾 /** 范围及精确 HTTP(S) 地址。
父子范围验证只证明保守词法包含，不解析任意 glob，不接触文件系统。
无法证明的收窄拒绝；字符串前缀不等于文件系统授权。

## 测试

每个对象各一份 valid 和 unknown-field invalid fixture。
自动测试另外逐项验证必填字段、每层未知字段、枚举/格式/时间/Hash、
非法数值、重复键、离线引用、Schema 摘要和领域模型一致性。
这些不等于 P0 的 200 条攻击回归或 60 个真实业务任务。
