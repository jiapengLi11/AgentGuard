# M0 文件清单

> **2026-10-15 交接说明：** 历史M0文件清单，不是当前完整交付清单。后续新增模型Host、Python控制面、Vue、多个MCP/执行器及评测；最新源码归档按各阶段manifest解释。完整交接还需移交忽略的原始证据与固定资源。
> [当前交接手册](PROJECT_HANDOFF.md)。下文“当前/未完成/下一步”均按原阶段阅读；原始数字与证据不追溯改写，不构成继续执行授权。

<!-- 原阶段正文开始 -->

所有路径相对于 E:/project11/AgentGuard。

## 新增文件

- .github/workflows/sujie-m0.yml
- sujie/.editorconfig
- sujie/.env.example
- sujie/.gitattributes
- sujie/.gitignore
- sujie/README.md
- sujie/conftest.py
- sujie/console-vue/README.md
- sujie/contracts/README.md
- sujie/contracts/enums.json
- sujie/contracts/fixtures/invalid/approval-record.json
- sujie/contracts/fixtures/invalid/decision-record.json
- sujie/contracts/fixtures/invalid/detection-finding.json
- sujie/contracts/fixtures/invalid/provenance-envelope.json
- sujie/contracts/fixtures/invalid/security-exception.json
- sujie/contracts/fixtures/invalid/semantic-action.json
- sujie/contracts/fixtures/invalid/task-contract.json
- sujie/contracts/fixtures/invalid/task-grant.json
- sujie/contracts/fixtures/invalid/trace-event.json
- sujie/contracts/fixtures/valid/approval-record.json
- sujie/contracts/fixtures/valid/decision-record.json
- sujie/contracts/fixtures/valid/detection-finding.json
- sujie/contracts/fixtures/valid/provenance-envelope.json
- sujie/contracts/fixtures/valid/security-exception.json
- sujie/contracts/fixtures/valid/semantic-action.json
- sujie/contracts/fixtures/valid/task-contract.json
- sujie/contracts/fixtures/valid/task-grant.json
- sujie/contracts/fixtures/valid/trace-event.json
- sujie/contracts/manifest.json
- sujie/contracts/schemas/approval-record.schema.json
- sujie/contracts/schemas/decision-record.schema.json
- sujie/contracts/schemas/detection-finding.schema.json
- sujie/contracts/schemas/provenance-envelope.schema.json
- sujie/contracts/schemas/security-exception.schema.json
- sujie/contracts/schemas/semantic-action.schema.json
- sujie/contracts/schemas/task-contract.schema.json
- sujie/contracts/schemas/task-grant.schema.json
- sujie/contracts/schemas/trace-event.schema.json
- sujie/contracts/tests/test_schemas.py
- sujie/control-plane-java/README.md
- sujie/demo-agent/README.md
- sujie/deploy/compose.yaml
- sujie/dev.py
- sujie/docs/DEPENDENCIES.md
- sujie/docs/M0_ACCEPTANCE.md
- sujie/docs/M0_FILE_MANIFEST.md
- sujie/docs/M0_SECURITY.md
- sujie/docs/adr/ADR-001-dsl-lt.md
- sujie/eval/attacks/README.md
- sujie/eval/baselines/README.md
- sujie/eval/cases/README.md
- sujie/eval/oracles/README.md
- sujie/eval/reports/README.md
- sujie/gateway-python/src/sujie_gateway/__init__.py
- sujie/gateway-python/src/sujie_gateway/contracts.py
- sujie/gateway-python/src/sujie_gateway/invariants.py
- sujie/gateway-python/tests/test_invariants.py
- sujie/mcp-servers/evidence-server/README.md
- sujie/mcp-servers/malicious-variants/README.md
- sujie/mcp-servers/operations-server/README.md
- sujie/pyproject.toml
- sujie/requirements-dev.txt
- sujie/requirements.lock
- sujie/requirements.txt
- sujie/sandbox/README.md
- sujie/tests/test_scaffold.py

## 修改文件

- README.md：将比赛版入口指向 sujie/，保留历史介绍。
- .gitignore：补充密钥、证据、缓存和构建产物排除。

## 本机生成但不提交

- sujie/.venv/：隔离依赖环境。
- Python、pytest、Ruff 缓存：均在忽略列表中。

两份最终设计原文、历史 agentguard/、tests/、benchmark/ 未修改。
