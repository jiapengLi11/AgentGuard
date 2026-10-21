# Document parsing

`sujie_gateway.doc_parsing.parse_document(bytes, mime=..., filename=...)` extracts
PDF page text, standard metadata, the complete XMP packet, and annotation contents.
DOCX extraction covers body paragraphs, tables, headers/footers, comments, core
properties, and explicit `w:vanish` runs (also retained in their paragraph text).
Every segment has `doc_type`, `part`, `page` (PDF page number, starting at 1), and
`field` labels. `scan_document()` uses `detection_v2` multi-source scanning.

Install `pypdf` and `python-docx` from `requirements.txt`. Without `python-docx`,
DOCX uses a local ZIP/XML fallback. Missing `pypdf` produces
`PDF_PARSER_UNAVAILABLE`. Corrupt/encrypted or oversized documents return explicit
errors; partial extraction is never treated as a clean scan. Extraction is bounded
by input bytes, expanded ZIP bytes, segment count, and detector character limits.
This is text extraction, without OCR or rendering; inherited style-based hiding
and embedded attachments are outside its coverage.

The gateway automatically inspects inline results of existing reading tools
(including `operations.read_file`, `evidence.read_alert`, and `network.fetch`).
PDF/DOCX are recognized by MIME type, filename extension, or magic/package bytes.
Nested MCP blocks with `content`, `data`, `blob`, `bytes`, `base64`, or
`content_base64` accept base64, data URIs, and document bytes (serialized as base64).
No paths or URLs in a result are opened or fetched by the parser.

Each extracted segment becomes an untrusted trace artifact and a provenance graph
`source` node with the original labels, including benign sources. Findings retain
artifact spans across segments; these are advisory injection findings under the
existing authorization policy. An unavailable or failed parser withholds the tool
result with an explicit error code. Returned document data remains in its original
JSON representation (binary values are encoded as base64).

Run only the focused tests and lint:

```sh
cd sujie
.venv/bin/python -m pytest tests/test_doc_parsing.py
.venv/bin/python -m ruff check gateway-python/src/sujie_gateway/doc_parsing.py \
  gateway-python/src/sujie_gateway/tool_result.py \
  gateway-python/src/sujie_gateway/m1_runtime.py \
  gateway-python/src/sujie_gateway/provenance_graph.py tests/test_doc_parsing.py
```
