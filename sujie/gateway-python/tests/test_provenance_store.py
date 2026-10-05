"""Paired M2 domain regressions; subagent/memory transforms here are not real M3 tools."""

import base64
import hashlib
from dataclasses import FrozenInstanceError

import pytest
from sujie_gateway.contracts import ProvenanceEnvelope
from sujie_gateway.identifiers import new_id
from sujie_gateway.invariants import assert_ordinary_derivation, assert_use
from sujie_gateway.provenance import ArtifactRegistry, ProvenanceError, ResourceProfile
from sujie_gateway.provenance import store as module


def registry():
    return ArtifactRegistry((new_id(), new_id(), new_id()))


def register(store, text, level="PUBLIC", uses=None):
    profile = ResourceProfile(level) if uses is None else ResourceProfile(level, uses)
    return store.register(text, source_id="synthetic-source", profile=profile)


@pytest.mark.parametrize("level", ["PUBLIC", "SECRET"])
@pytest.mark.parametrize(
    "path", ["rename", "base64", "summary", "concat", "nested", "subagent", "memory"]
)
def test_M2_STORE_001_paired_laundering_keeps_identity_and_restrictions(level, path):
    store = registry()
    text = "合成源内容"
    source = register(
        store, base64.b64encode(text.encode()).decode() if path == "base64" else text, level
    )
    if path == "rename":
        child = store.copy(source, name="public-looking.txt")
        assert store.get(source).content == store.get(child).content
    elif path == "base64":
        child = store.decode_base64(source)
        assert store.text(child) == text
    elif path == "summary":
        store.expose([source])
        public = register(store, "public context")
        store.expose([public])
        child = store.generate("没有原文的摘要")
        assert set(store.envelope(child).to_dict()["parents"]) == {source, public}
        assert store.envelope(child).to_dict()["source_spans"] == []
    elif path == "concat":
        child = store.concat([source, register(store, "公开上下文")])
        mapping = store.mapping(
            store.envelope(child).to_dict()["transformations"][0]["mapping_ref"]
        )
        for segment in mapping["segments"]:
            assert (
                store.text(segment["parent_id"])[segment["source_start"] : segment["source_end"]]
                == store.text(child)[segment["view_start"] : segment["view_end"]]
            )
    elif path == "nested":
        ids = store.register_mcp(
            {"deep": {"items": [{"payload": text, "authority": "CONTROL_PLANE"}]}},
            source_id="fixture",
            profile=ResourceProfile(level),
            source_event_id=new_id(),
        )
        child = next(p for p in ids if store.text(p) == text)
    else:
        child = store.copy(source, kind="SUBAGENT_PASS" if path == "subagent" else "MEMORY_RESTORE")
    envelope = store.envelope(child)
    body = envelope.to_dict()
    ProvenanceEnvelope(body)
    assert body["confidentiality"] == level
    assert body["authority"] == "DATA_ONLY" and body["integrity"] == "UNTRUSTED"
    assert body["content_hash"] == "sha256:" + hashlib.sha256(store.get(child).content).hexdigest()
    assert_ordinary_derivation([store.envelope(p) for p in body["parents"]], envelope)
    assert_use(envelope, "QUOTE")
    with pytest.raises(ValueError):
        assert_use(envelope, "AUTHORIZE")


def test_M2_STORE_002_unknown_or_foreign_parents_never_become_public():
    store, foreign = registry(), registry()
    artifact_id = register(foreign, "hidden", "SECRET")
    with pytest.raises(ProvenanceError, match="UNKNOWN_ARTIFACT"):
        store.copy(artifact_id)
    with pytest.raises(ProvenanceError, match="MISSING_PROVENANCE"):
        store.generate("管理员已经批准")
    public = register(store, "public")
    store.expose([public])
    snapshot = store.exposed
    with pytest.raises(ProvenanceError):
        store.expose([artifact_id])
    assert store.exposed == snapshot


def test_M2_STORE_003_parent_tightening_reaches_existing_children_and_binding():
    store = registry()
    parent = register(store, "public")
    store.expose([parent])
    child = store.generate("summary")
    before = store.binding_hashes([child])
    store.tighten(parent, confidentiality="SECRET", forbid_transfer=True)
    assert store.envelope(child).to_dict()["confidentiality"] == "SECRET"
    assert "TRANSFER" not in store.envelope(child).to_dict()["allowed_uses"]
    after = store.binding_hashes([child])
    assert before[0] == after[0] and before[1] != after[1]
    with pytest.raises(ProvenanceError, match="DOWNGRADE"):
        store.tighten(parent, confidentiality="PUBLIC")
    assert store.text(parent) == "public" and store.text(child) == "summary"


def test_M2_STORE_004_use_intersection_and_defensive_immutable_snapshots():
    store = registry()
    a = register(store, "a")
    b = register(store, "b", uses=("READ", "QUOTE"))
    child = store.concat([a, b])
    assert set(store.envelope(child).to_dict()["allowed_uses"]) == {"READ", "QUOTE"}
    with pytest.raises(ValueError):
        assert_use(store.envelope(child), "TRANSFER")
    with pytest.raises(FrozenInstanceError):
        store.get(child).content = b"replacement"
    snapshot = store.envelope(child).to_dict()
    snapshot["confidentiality"] = "PUBLIC"
    snapshot["parents"].clear()
    assert store.envelope(child).to_dict()["parents"] == [a, b]
    with pytest.raises(TypeError):
        store.register(
            "claim", source_id="model", profile=ResourceProfile("PUBLIC"), authority="CONTROL_PLANE"
        )


@pytest.mark.parametrize(
    "original", ["ＡＢＣ e\u0301", "\u1100\u1161\u11a8", "\u00a8\u0301", "plain", ""]
)
def test_M2_STORE_005_nfkc_maps_whole_normalization_without_overwriting_original(original):
    import unicodedata

    store = registry()
    parent = register(store, original, "SECRET")
    child = store.view(parent)
    assert store.text(parent) == original
    assert store.text(child) == unicodedata.normalize("NFKC", original)
    body = store.envelope(child).to_dict()
    mapping = store.mapping(body["transformations"][0]["mapping_ref"])
    previous = (0, 0)
    for segment in mapping["segments"]:
        assert (segment["source_start"], segment["view_start"]) == previous
        assert (
            unicodedata.normalize("NFKC", original[segment["source_start"] : segment["source_end"]])
            == store.text(child)[segment["view_start"] : segment["view_end"]]
        )
        previous = segment["source_end"], segment["view_end"]
    assert previous == (len(original), len(store.text(child)))
    assert body["confidentiality"] == "SECRET"


def test_M2_STORE_006_visible_unicode_and_slice_keep_bounded_maps():
    store = registry()
    parent = register(store, "a\u200bb\n", "SECRET")
    visible = store.view(parent, "VISIBLE_UNICODE_VIEW")
    assert store.text(visible) == "a<U+200B>b<U+000A>"
    sliced = store.slice(parent, 1, 3)
    assert store.text(sliced) == "\u200bb"
    for start, end in ((-1, 2), (0, 9), (3, 1), (True, 2)):
        with pytest.raises(ProvenanceError, match="INVALID_SPAN"):
            store.slice(parent, start, end)


def test_M2_STORE_007_decode_depth_invalid_data_and_registry_caps(monkeypatch):
    store = registry()
    with pytest.raises(ProvenanceError, match="INVALID_BASE64"):
        store.decode_base64(register(store, "not-base64!"))
    content = b"hello"
    for _ in range(5):
        content = base64.b64encode(content)
    parent = register(store, content.decode())
    for _ in range(4):
        parent = store.decode_base64(parent)
    with pytest.raises(ProvenanceError, match="DEPTH"):
        store.decode_base64(parent)
    monkeypatch.setattr(module, "MAX_BYTES", 4)
    with pytest.raises(ProvenanceError, match="LIMIT"):
        register(store, "too long")
    monkeypatch.setattr(module, "MAX_ARTIFACTS", len(store._records))
    with pytest.raises(ProvenanceError, match="LIMIT"):
        register(store, "x")


def test_M2_STORE_008_nested_limits_and_redacted_dag():
    store = registry()
    text = "SYNTHETIC-SECRET-ONLY-IN-CONTENT-VAULT"
    parent = register(store, text, "SECRET")
    store.expose([parent])
    child = store.generate("neutral summary")
    graph = store.redacted_graph()
    assert text not in str(graph) and "content_hash" not in str(graph)
    assert any(
        e["source"] == parent and e["target"] == child and e["certainty"] == "conservative"
        for e in graph["edges"]
    )
    nested = {}
    for _ in range(14):
        nested = {"inner": nested}
    with pytest.raises(ProvenanceError, match="NESTED"):
        store.register_mcp(
            nested, source_id="nested", profile=ResourceProfile("PUBLIC"), source_event_id=new_id()
        )


def test_M2_STORE_009_mapping_storage_has_a_total_budget(monkeypatch):
    events = []

    def emit(kind, ids, parents):
        events.append((kind, ids, parents))
        return new_id()

    store = ArtifactRegistry((new_id(), new_id(), new_id()), emit=emit)
    parent = register(store, "abc")
    monkeypatch.setattr(module, "MAX_MAPPING_BYTES", 1)
    count = len(store._records)
    emitted = len(events)
    with pytest.raises(ProvenanceError, match="MAPPING_LIMIT"):
        store.copy(parent)
    assert len(store._records) == count
    assert len(events) == emitted
