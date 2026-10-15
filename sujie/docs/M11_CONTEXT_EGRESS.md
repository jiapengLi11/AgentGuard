# M11：模型输入来源与出口保护

> **2026-10-15 交接说明：** 阶段M11记录，原303测试/报告按该版保留。后续M13加请求/回复前缀绑定，M17/M18/M20将实际子孙/Memory/无工具分析接入当前保护与共享预算。历史入口统一、全转换与完整有效HTTP请求仍未完成；本地token不是供应商内部token。
> [当前交接手册](PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

日期：2026-10-14。实施范围：F2第一轮，后续按F3继续。

## 已实现

- 可信Host登记用户补充消息；文本不修改Contract/Grant，角色伪装按DIRECT检测。
- `model_context.py`构建不可变messages/tools快照，原文字面与JSON转义映射到来源字符区间。
- `tokenizer_mapper.py`使用固定公开Qwen tokenizer JSON，不下载模型权重，不运行远程模型代码。
- `protected_model.py`在报告Host后端调用前检查数据类别/用途，检查回应中的禁发整值与已定义编码。
- `BailianChatModel`在HTTP前保护实际API凭据；回应凭据检查拒绝后仍保留已返回用量。
- 认证contexts接口、脱敏导出及Vue来源表，不返回原始对话、秘密token文本或token ID。
- 契约包0.2增加上下文审计事件；已有结构版本与历史0.1证据分别保留。

tokenizer：`Qwen/Qwen3-0.6B`，revision `c1899de289a04d12100db370d81485cdf75e47ca`，
JSON 11,422,654 bytes，SHA-256 `aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4`。
资产与runtime固定见 `assets/tokenizer/qwen3-local-manifest.json`。许可文件的交付整理仍待完成。

## 验证与边界

第一轮完整回归303 passed、2项平台条件跳过，Vue构建通过。
真实MCP故意Host误读校准：[v1记录](../eval/reports/runs/model_context_calibration_v1.json)。
PUBLIC请求转发一次；MAIN/CLASSIFY/ISOLATED_ANALYSIS/SUBAGENT/RECOVERY五角色各拒绝一次，
误读后的后端调用为0。后端是捕获组件，不是五个真实自主LLM角色实验。
M12之后重新校准的[v2记录](../eval/reports/runs/model_context_calibration_v2.json)仍为五角色拒绝、后端0次。

[真实报告冒烟](../eval/reports/runs/operator_context_model_smoke_v1/summary.json)：
正常和注入各三次固定百炼模型请求，两者完成报告、Receiver零请求，共4,558个返回Token。
注入有检测发现，但没有越权工具提议/BLOCK，不能计作网关拦截成功。

当前快照只绑定messages/tools，完整有效生成配置绑定待补。
字面/JSON转义定位不覆盖所有规范化、拼接和摘要；assistant保守继承全部当前暴露来源仍需改进。
本地字段token映射不等同百炼内部token、聊天模板或思维链。缺资产时明确UNAVAILABLE。
五角色接口可复用，但历史独立评测入口尚未统一业务来源绑定。
整值及已定义编码检查不保证任意分片/改写DLP。

后续：[M12预算与自主审批](M12_AUTONOMOUS_APPROVAL_AND_BUDGET.md)、[F3计划](../../competition/docs/SUJIE_REVIEW_AND_PLAN_F3.md)。
