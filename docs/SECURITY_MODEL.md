# 当前安全模型

更新：2026-10-15，适用 `sujie/` 比赛主线。更详细的实现/限制见[交接手册](../sujie/docs/PROJECT_HANDOFF.md)和[证据矩阵](../sujie/docs/TOPIC5_EVIDENCE_MATRIX.md)。

## 授权与传播

- 可信模板冻结TaskContract与TaskGrant；模型提出动作，Host从真实参数映射语义效果。
- 工具注册/Schema/版本、授权期限/预算、目的/资源/效果、来源用途、DSL和审批绑定共同限制执行；BLOCK不能被检测器或普通批准覆盖。
- 外部内容、Memory、子Agent和模型派生物保持DATA_ONLY；普通转换不提高权限/完整性、不自动降敏。固定公开IPv4提取为受限例外，仍需合同和ASK。
- ASK等待无副作用；批准不执行，提交复查参数/输入/版本/状态后执行。重放/漂移/UNKNOWN有专门路径。
- 模型API也是出口，当前Host保护请求/回应及Provider凭据，角色共用预算；历史入口与完整有效请求仍未全部统一。

## 结论边界

单进程审批单次提交不是跨崩溃exactly-once；持久预算不是持久任务；来源摘要/引用位置不是事实或语义证明。子Agent同Host，本地token不是云内部token。历史M1容器、分类和开发云实验按各自版本限定，不保证任意远程MCP/Host失陷/任意分片改写DLP。根原型实现与比赛版不可混用。
