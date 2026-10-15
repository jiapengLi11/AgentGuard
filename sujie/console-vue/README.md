# Vue 操作者控制台

更新：2026-10-15。Vue3/TypeScript页面通过独立Python控制面显示真实任务、审批、来源DAG、序列、效果、子Agent/Memory与业务Oracle；前端不授予权限、不伪造任务数据。

Node20.19+或22.12+，从本目录：

```powershell
npm ci
npm run build
```

构建包含 `vue-tsc --noEmit`，依赖由 `package-lock.json` 固定。交付为同源静态资源和API；不用开发服务器/CORS代理。构建后从 `sujie/` 启动 `python dev.py console`，默认 `http://127.0.0.1:8765`。粘贴 `.control-runtime/operator-token.txt`；页面内存保存，刷新需重新登录。端口/云配置见[交接手册](../docs/PROJECT_HANDOFF.md)。

当前13个profile，M21四业务可选合法原文引用场景，并显示来源读取/报告核验；report可选M20无工具分析，两者不是同一开关。审批先批准再提交，关闭前导出任务。旧8765后端不会随前端构建自动升级。

最近M21类型检查与构建通过；对应JS `index-DPkZ5w2A.js`、CSS `index-punx0FXz.css` 为该次历史产物，重建Hash可能变化。本阶段未完成新页面浏览器布局验收，不能沿用M6/M12旧界面验证冒充本版验收。运行边界与后续项以手册/当前状态为准。
