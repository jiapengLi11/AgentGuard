# 本地输入来源映射资产

`qwen3-local-manifest.json` 固定官方 Qwen/Qwen3-0.6B 的 tokenizer.json 提交与摘要。
仅下载约11.4MB的分词器JSON，不下载模型权重、不执行远端Python代码、不需要GPU。

在 `sujie` 执行：

```powershell
.\.venv\Scripts\python.exe dev.py prepare-tokenizer
```

资产保存在忽略目录 `model-cache/qwen3-local/`；控制台运行时只读本地文件，不联网下载。
缺少资产则记录 `UNAVAILABLE`，不能宣称完成了token来源映射。资产摘要或绑定版本
不匹配时拒绝加载。

区间是逐API文本字段的本地字符、UTF-8字节、token区间；没有记录可还原正文的
token ID或token文本。它不等于百炼 qwen-plus 的内部token序列、聊天模板或思维链。
来源绑定分为字面/JSON转义匹配、保守父来源继承和未绑定区间，未绑定区间不伪装成
可信来源，也不能自动授予工具权限。

上游资产许可为Apache-2.0。正式离线包应保留上游许可与来源清单。
接口依据：[官方Tokenizer文档](https://huggingface.co/docs/tokenizers/v0.20.3/api/tokenizer)、
[固定0.22.2接口源码](https://github.com/huggingface/tokenizers/blob/v0.22.2/bindings/python/py_src/tokenizers/__init__.pyi)。
