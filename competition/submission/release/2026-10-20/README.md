# 交付成品快照（2026-10-20）

本目录是旧版成品快照，当前应使用 [2026-10-22 复核版](../2026-10-22/README.md)。公开文件于 2026-10-23 改用通用 ASCII 名称，不含队员姓名；正式平台实名命名仅在本地处理。文件内容不因重命名改变。

| 文件 | 大小 | 页数 | 说明 |
| --- | --- | --- | --- |
| `sujie-report.pdf` | 447,283 B | 26 | 绑定快照 `1b64b1f`，CI 编译，0 溢出 / 0 缺字 / 0 未定义引用 |
| `sujie-deployment-guide.pdf` | 159,586 B | 4 | 含离线评测与检测器选择、7 条已知限制 |
| `sujie-test-samples-and-flow.pdf` | 192,408 B | 5 | 样例、Oracle、基线与复现命令 |
| `sujie-evidence-packet.zip` | 984,434 B | — | 53 文件，逐文件 SHA-256，无个人路径 |
| `上传清单-2026-10-20.txt` | — | — | 本目录 4 个公开成品的完整 SHA-256 |

## 刻意没有放进来的三项

- **签名版原创性声明**：只在本地私密保留。历史 Release 的声明 PDF/DOCX 附件已移除，仓库不分发；已下载的外部副本无法召回。
- **`队长姓名+溯界+可执行程序.zip`**：内容就是本仓库源码，队友 `git clone` 即得，无需再存一份 2.30 MB 的压缩包。
- **`队长姓名+溯界+演示视频.mp4`**：尚未录制，分镜见 [`../../演示脚本-溯界.md`](../../演示脚本-溯界.md)。

## 重建方式

```sh
cd competition/submission

# 报告 PDF 由 CI 构建，也可下载最近一次构建产物
gh run download --name sujie-m25-latex-review

# 部署说明 / 测试说明
uv run --no-project --with reportlab --with pillow \
  python tools/build_report_pdf.py 部署说明-溯界.md dist/部署说明-溯界.pdf --plain

# 证据包（只打包评测运行目录与验证记录）
python3 tools/build_evidence_packet.py --out dist/证据包.zip \
  --run ../../sujie/eval/reports/runs/competition_repro_20261018 \
  --run ../../sujie/eval/reports/runs/competition_evidence_20261020 \
  --run ../../docs/validation
```

## 校验

```sh
cd competition/submission/release/2026-10-20
# 只校验本目录实际存在的 4 个公开成品
shasum -a 256 *.pdf *.zip
```

输出与 `上传清单-2026-10-20.txt` 中同名行的第 4 列逐行比对即可。隐私清理后的清单仅覆盖本目录 4 个成品，不再列签名附件。

当前提交口径与逐项状态见 [`../../交付总表-2026-10-20.md`](../../交付总表-2026-10-20.md)。
