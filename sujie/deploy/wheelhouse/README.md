# Offline wheelhouse

> **2026-10-15 交接更新：** 本页服务历史M1离线构建，不是当前完整便携包。wheel/基础镜像/分词器/前端依赖均需按目标平台与锁文件重新核验；旧65wheel聚合记录不证明新Host全栈或供应链完备。文件默认忽略，接手需单独移交。
> 完整现状、启动与证据限制见[交接手册](../../docs/PROJECT_HANDOFF.md)。

此目录默认不提交 wheel。正常联网构建从锁文件安装；VM 无外网时，将与
`requirements.lock` 对应的 Linux/CPython 3.12 wheels 放入此目录，并设置：

```sh
export SUJIE_OFFLINE_BUILD=1
export SUJIE_PYTHON_BASE=sujie/python-base:3.12.13
```

离线 wheel 必须按精确锁定版本下载，并在 VM 内由 `pip --no-index` 校验依赖完整性。
