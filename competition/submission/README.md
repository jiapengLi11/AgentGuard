# 初赛提交材料

2026-10-23 已整理[项目结项与公开索引](../../docs/PROJECT_CLOSEOUT_2026-10-23.md)。公开下载入口为[结项 Release](https://github.com/jiapengLi11/AgentGuard/releases/tag/closeout-2026-10-23)；签名版原创性声明不公开，历史附件已移除。以下保留冻结交付的版本与验收范围。

当前修订入口为 [交付复核（2026-10-22）](交付复核-2026-10-22.md)。旧的 2026-10-18、2026-10-20 清单、Release 和历史报告仅供追溯，不是本次上传入口。

本次程序固定在 `96d591b`，报告绑定提交为 `1b64b1f`，312 份运行时源码按 SHA-256 核验；文稿取当前修订版。最新开发分支新增的 PDF/DOCX 解析不纳入这一基线的测试成绩。程序包为 Python 源码发行包，附预构建 Vue 控制台；安装 Python 3.12 依赖后可运行，不是独立 EXE。

## 提交要求

作品文档资料为 PDF、大小不超过 10M，文件名为“队长姓名+作品名称+资料名称”。报告保留官方填写说明、摘要、五章和参考文献，不出现学校、院系、指导教师或作者身份。原创性声明单独提交，不能混入匿名报告。

官方模板要求 A4、正文宋体小四、1.5 倍行距。报告源文件为 [latex/main.tex](latex/main.tex)；正式字体文件只放本机忽略目录 `latex/.local-fonts/`，不上传或打包。CI 的 FandolSong 编译件只用于构建检查，不能覆盖本机宋体版 PDF。

## 复核与构建

```sh
python3 competition/submission/tools/check_report_latex.py
python3 -m unittest discover -s competition/submission/tools -p test_check_report_latex.py
# 使用固定基线的前端目录完成 npm ci && npm run build 后：
python3 competition/submission/tools/build_frozen_source_package.py \
  --console-dist /path/to/frozen-runtime/sujie/console-vue/dist \
  --out /path/to/可执行程序.zip
```

冻结打包器从 Git 对象读取报告基线，逐一核对 312 份源码，再覆盖当前文稿；它不会把工作区的新运行时代码混入包内。前端源文件和锁文件也须与该基线一致。程序包及证据包各有逐文件哈希清单。

部署与测试 PDF 分别由 [部署说明](部署说明-溯界.md)、[测试样例与流程说明](测试样例与流程说明-溯界.md) 生成。报告 LaTeX 工程、文稿源码、验证记录和打包工具均可由队友修改。生成后必须重新检查 PDF、源码绑定和清单，不沿用旧文件大小与页码。

## 当前验证范围

本机从交付包解压、创建独立环境、安装 71 项锁定依赖后，全量检查为 1107 passed / 1 skipped / 1 xfailed / 1 warning，退出码 0；四业务 16/16 完成，云调用 0，归档核验通过。控制台健康检查、首页、资源及认证查询通过。原始记录与修复前的打包失败一并保留在证据包。

跳过项为未分发的固定分词器资产；预期失败记录“审批后超限返回缺少部分效果审计事件”，是尚未修复的缺口。历史云模型原始记录不随包提交，本次报告不列其数字。完整拓扑隔离、真实模型比较及生产性能仍未验收。
