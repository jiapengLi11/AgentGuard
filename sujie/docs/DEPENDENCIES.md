# M0/M1 依赖与许可证

> **2026-10-15 交接更新：** 本页保留依赖表及M0/M1/M6安装观察；Python锁和前端锁是当前版本来源。本次交接实际解释器为Windows Python3.12.2，原3.12.14/容器3.12.13/Node22.14等属于旧环境，不作为当前补丁版本要求。当前需要Python3.12.x、Node20.19+或22.12+，Git业务另需Git；Java/MySQL非依赖。旧npm审计为当时查询，未重新做安全审计。
> 完整现状、启动与证据限制见[交接手册](PROJECT_HANDOFF.md)。

安装范围：仅 sujie/.venv，不修改 Anaconda 或全局 Python。
版本以 requirements.lock 为准；直接依赖以 requirements.txt / requirements-dev.txt 声明。
当前锁定全部 Python 包版本，但没有声称完成 wheel Hash 校验或供应链审计。
本机 Windows/Python 3.12.14 与 Ubuntu VM 容器/Python 3.12.13 已验证；
Linux CI 配置已写，远端 CI 尚未运行。

## 直接依赖

| 依赖 | 版本 | 用途与许可证 | 可替代方案 | 是否进入安全热路径 |
|---|---|---|---|---|
| jsonschema | 4.26.0 | Draft 2020-12 校验，MIT | fastjsonschema（需重新核对 draft/format 支持）；手写校验不推荐 | 当前领域对象入口校验；未来热路径需实测 |
| referencing | 0.37.0 | 无网络取回器的本地引用注册，MIT | 只使用内联 Schema，但仍需验证嵌套定义 | 与契约解析一起 |
| rfc3986-validator | 0.1.1 | URI 格式断言，MIT | 其他 RFC URI 校验器；urlsplit 本身不等于完整校验 | 校验 URI 字段时 |
| pytest | 8.4.2 | 测试，MIT | 标准库 unittest | 否 |
| ruff | 0.12.12 | 静态检查/格式化，MIT | Black + Flake8/Isort | 否 |
| PyYAML | 6.0.2 | safe_load 解析策略及测试配置，MIT | JSON 策略或其他安全 YAML 解析器 | 是，策略初始化路径 |
| mcp | 2.1.1 | 官方 MCP v2 客户端/Server/stdio，MIT | 固定并维护 v1；自行实现协议不推荐 | 是，协议代理和 Server |
| langgraph | 1.2.11 | Demo Agent 状态图，MIT | 自建显式状态机 | 否，不参与最终授权判断 |
| fastapi | 0.141.1 | Gateway 进程边界 HTTP API，MIT | Starlette/ASGI 手写接口；不利于冻结输入模型 | 是，协议入口但不做最终策略判断 |
| pytest-asyncio | 1.3.0 | 异步 MCP 测试，Apache-2.0 | anyio 测试插件或 asyncio.run | 否 |

JSON Schema 中 format 默认不必执行；本项目显式提供 FormatChecker 并测试每个使用的格式
确实有对应检查器。URI 校验依赖缺失曾在首轮测试中被发现，现已补齐并锁定。
参考：[jsonschema 验证文档](https://python-jsonschema.readthedocs.io/en/stable/validate/)。

许可证由已安装发行包 metadata/classifier 核对；上游：
[jsonschema](https://pypi.org/project/jsonschema/)、[referencing](https://pypi.org/project/referencing/)、
[rfc3986-validator](https://pypi.org/project/rfc3986-validator/)、
[pytest](https://pypi.org/project/pytest/)、[Ruff](https://pypi.org/project/ruff/)、
[PyYAML](https://pypi.org/project/PyYAML/)、
[MCP Python SDK](https://pypi.org/project/mcp/)、
[LangGraph](https://pypi.org/project/langgraph/)、
[FastAPI](https://pypi.org/project/fastapi/)、
[pytest-asyncio](https://pypi.org/project/pytest-asyncio/)。

## 间接依赖

| 依赖 | 用途 | 许可证 | 热路径 |
|---|---|---|---|
| attrs | JSON Schema / 引用库数据结构 | MIT | 契约入口 |
| jsonschema-specifications | 标准元 Schema 注册 | MIT | 契约入口/初始化 |
| rpds-py | 不可变映射 | MIT | 契约入口 |
| typing_extensions | 类型兼容 | PSF-2.0 | 库导入，不做授权判断 |
| colorama | Windows 测试终端颜色 | BSD | 否 |
| iniconfig | 测试配置 | MIT | 否 |
| packaging | 测试依赖版本解析 | Apache-2.0 OR BSD-2-Clause | 否 |
| pluggy | pytest 插件调度 | MIT | 否 |
| Pygments | 测试输出高亮 | BSD-2-Clause | 否 |

MCP/LangGraph 的间接依赖已记录于 requirements.lock，包括 Pydantic、HTTP 栈和加密库；
它们扩大了依赖面，后续需要漏洞扫描和 wheel Hash 锁定。百炼 Provider 使用已有
标准库 HTTP 适配；Java 仍未安装。前端依赖现在由 `console-vue/package-lock.json`
固定，下面单列。
纯 Python 领域模型以 Schema 为唯一字段定义，不另写易漂移的传输模型。

M1 Dockerfile 联网默认仍使用 `python:3.12-slim`。由于 VM 外网不可用，本次验收使用
Astral 官方 GHCR 镜像 `uv:0.12.1-python3.12-trixie-slim` 的 linux/amd64 固定来源摘要
`sha256:c225b0be...d25441c6`，镜像内 Python 为 3.12.13；离线 tar SHA-256 为
`9b6842d7...48bfd9b`。该镜像额外包含 uv，比赛最终交付前应评估是否换回更小的纯 Python
镜像并重新验收。

65 个 Linux/CPython 3.12 wheels 按 requirements.lock 精确版本下载，在 VM 构建时强制
`pip --no-index`。远端按文件名排序后的 SHA-256 清单聚合值为
`4eef9a71...7ad932e`。wheel 未提交仓库，逐文件 Hash 尚未进入锁文件，不能声称已完成
完整供应链验证。官方 `crane` 0.22.1 只用于离线镜像传输，不进入应用运行镜像。

## M6 前端

Vue 3.5.44、Vite 7.3.7、@vitejs/plugin-vue 6.0.10、vue-tsc 3.3.13（MIT）；
TypeScript 5.9.3（Apache-2.0）。Node 本机为 22.14.0；CI 选择 Node 22。
安装范围仅 `console-vue/node_modules`，构建产物在已忽略的 `dist`。
`npm ci` 与 `npm run build` 已本机验证，包含类型检查；本次 npm 审计返回 0 个
已知漏洞，仅代表查询时 npm 数据库结果。CI 新增前端构建任务，远端尚未运行。
不加载远端字体、图标、分析脚本或 CDN 资源。

## M21 源码集成补记

`tokenizers==0.22.2` 已存在于交付锁文件，集成时补列到直接依赖，避免仅安装
`requirements.txt` 时遗漏实际使用的库。它用于按固定本地资产生成文本字段的 token
区间；上游包 metadata 标注 Apache Software License，资产清单标注 Apache-2.0。
可替代方案为只保留字符/字节区间，但不能将该降级描述为已有 token 映射。
它参与模型请求来源审计，不签发权限或覆盖授权拒绝。新增机器应从锁文件安装并校验资产，
不复制其他成员的虚拟环境；首次准备资产需要网络或已有经摘要核验的缓存。
