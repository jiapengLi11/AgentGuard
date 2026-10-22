> 2026-10-22 更新：本机最终排版可在 `.local-fonts/simsun.ttc` 放置可使用的宋体文件；该目录被 Git 和打包器排除。CI 未配置字体时仅生成 FandolSong 检查版，不能替换正式宋体 PDF。当前上传清单见上级目录 `交付复核-2026-10-22.md`。

# LaTeX 作品报告（当前绑定快照 `1b64b1f`）

正文入口为 `main.tex`，按官方五章拆分到 `sections/`；两张矢量图由 `figures/` 中的 TikZ 源码生成。后续报告修订以本工程为主，旧 Markdown 报告保留为 M21 材料快照，不自动覆盖。

## 模板与编译

- A4，正文小四（12 pt），1.5 倍行距；封面、保留的“填写说明”、章级自动目录、五章正文、参考文献与页码；PDF书签保留节级导航。
- 使用 XeLaTeX；引用由 `thebibliography` 和 `cite` 编号，不依赖额外 BibTeX/Biber 步骤。
- 在 Codex 中打开此目录使用内置编辑器和 PDF 预览。已有 TeX 环境也可在本目录运行 `xelatex -interaction=nonstopmode -halt-on-error -output-directory=../dist main.tex` 三次，以解析目录、交叉引用与总页数。
- `font-config.tex` 优先使用已安装的 SimSun；否则为 Songti SC 或 FandolSong 草稿替代。正式宋体要求需单独核验，不因预览成功而视为满足。未分发任何系统字体文件。
- 在已有 XeLaTeX 环境严格检查字体：`xelatex -interaction=nonstopmode -halt-on-error -output-directory=../dist '\def\RequireOfficialFont{1}\input{main.tex}'`，并重复编译至引用稳定。

## 当前验证状态

本机没有 XeLaTeX，全部构建走 GitHub Actions。当前基线版本的编译、页数、体积与 SHA-256 记录在上一级 `LATEX_DELIVERY_REVIEW.md`，产物为该次运行的 `sujie-m25-latex-review` 附件；本文件不重复这些数字，避免两处不一致。

CI使用TeX Live 2025预置环境，latex-action固定提交，关闭shell escape，产出 `sujie-m25-latex-review` 附件。该环境使用FandolSong草稿替代，正式SimSun字体验收仍待完成。本机若捆绑Poppler缺少Adobe-GB1语言映射，不能以其漏画中文字判定PDF缺字；字体已嵌入，可用支持该映射的阅读器或MuPDF核查。

源码检查（不代替编译）：在仓库根目录运行 `python3 competition/submission/tools/check_report_latex.py`。它检查输入文件、引用、环境配对、摘要长度、匿名占位和官方说明页；按 `runtime-version.json` 的完整提交 ID 与验证记录摘要，核对该历史 Git 快照中的 312 份源码，而非将最新工作区冒充已验收版本。克隆时需包含该提交的历史，CI 使用 `fetch-depth: 0`。清单本身由 `tools/build_report_binding.py` 按固定规则从 git 对象重算，不手工维护。

输出中的 `current_source_mismatches` 单列当前工作区与报告快照的差异；默认通过只表示报告引用的历史快照一致，不表示当前程序已验收。如要检查当前交付代码与报告完全一致，运行 `python3 competition/submission/tools/check_report_latex.py --require-current-source`，存在差异时会失败。更新报告基线时，应先完成对应代码验证，新增独立验证记录，再更新正文与绑定文件；旧记录不覆盖。

## 内容版本

- 绑定快照 `1b64b1f`，其运行时源码与 CI 验证过的 `96d591b` 逐字节一致；回归结论按 `96d591b` 的三平台运行引用（Ubuntu 1107、Windows 1106、macOS 1107）。
- 规则检测离线评测：`rules-v0.3` 14 条冒烟、`rules-v0.6` 42 条合成矩阵与 140 条公开样本留出；三组数字并列呈现，合成矩阵的 100% 标注为同源自检。
- M25 原冻结版本的 48 格脚本、48 格本地 HTTP 和 14 格来源代表作为历史阶段保留，源版本独立于当前基线。
- M24 六链为有限 Linux 运行性记录，不作为完整隔离或性能验收。
- 文献核对与写作辅助出处见上一级 `LATEX_DELIVERY_REVIEW.md`。
