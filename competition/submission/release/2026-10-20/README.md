# 交付成品快照（2026-10-20）

本目录存放**可直接上传的成品**，队友 `git pull` 后即可取用，不需要重跑构建。全部文件已按 `队长姓名+溯界+资料名称` 命名（队长：李嘉鹏）。

| 文件 | 大小 | 页数 | 说明 |
| --- | --- | --- | --- |
| `李嘉鹏+溯界+作品报告.pdf` | 447,283 B | 26 | 绑定快照 `1b64b1f`，CI 编译，0 溢出 / 0 缺字 / 0 未定义引用 |
| `李嘉鹏+溯界+部署说明.pdf` | 159,586 B | 4 | 含离线评测与检测器选择、7 条已知限制 |
| `李嘉鹏+溯界+测试样例与流程说明.pdf` | 192,408 B | 5 | 样例、Oracle、基线与复现命令 |
| `李嘉鹏+溯界+证据包.zip` | 984,434 B | — | 53 文件，逐文件 SHA-256，无个人路径 |
| `上传清单-2026-10-20.txt` | 953 B | — | 上传目录 6 个文件的完整 SHA-256 |

## 刻意没有放进来的三项

- **`李嘉鹏+溯界+作品原创性声明.pdf`**：含四份手写签名，属于个人信息。本仓库是公开仓库——push 权限只有团队，但**任何人可读**；签名一旦提交就会永久留在 git 历史里，无法真正撤回。因此该文件不入库，由队长本地保存（`competition/submission/dist/`）并私下发给队员或直接上传。
- **`李嘉鹏+溯界+可执行程序.zip`**：内容就是本仓库源码，队友 `git clone` 即得，无需再存一份 2.30 MB 的压缩包。
- **`李嘉鹏+溯界+演示视频.mp4`**：尚未录制，分镜见 [`../../演示脚本-溯界.md`](../../演示脚本-溯界.md)。

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
# 只校验本目录实际存在的 4 个成品；清单另含声明与可执行程序两行
shasum -a 256 *.pdf *.zip
```

输出与 `上传清单-2026-10-20.txt` 中同名行的第 4 列逐行比对即可。清单覆盖上传目录的完整 6 个文件，本目录刻意少了签名声明与可执行程序（原因见上）。

当前提交口径与逐项状态见 [`../../交付总表-2026-10-20.md`](../../交付总表-2026-10-20.md)。
