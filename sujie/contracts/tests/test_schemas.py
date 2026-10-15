import copy
import hashlib
import json
import socket

import pytest
from jsonschema import Draft202012Validator
from sujie_gateway.contracts import (
    CONTRACTS,
    DOCUMENT_TYPES,
    SCHEMA_NAMES,
    ContractError,
    load_json,
    validate_document,
    validator,
)


@pytest.mark.parametrize("name", SCHEMA_NAMES, ids=lambda n: f"SCHEMA-VALID-{n}")
def test_valid_fixture(name, fixture_document):
    validate_document(name, fixture_document(name))
    assert DOCUMENT_TYPES[name](fixture_document(name)).to_dict() == fixture_document(name)


@pytest.mark.parametrize("name", SCHEMA_NAMES, ids=lambda n: f"SCHEMA-INVALID-{n}")
def test_invalid_fixture(name):
    invalid = load_json((CONTRACTS / "fixtures" / "invalid" / f"{name}.json").read_text("utf-8"))
    with pytest.raises(ContractError):
        validate_document(name, invalid)


@pytest.mark.parametrize("name", SCHEMA_NAMES, ids=lambda n: f"SCHEMA-META-{n}")
def test_schema_is_closed_and_self_contained(name):
    schema = validator(name).schema
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert "schema_version" in schema["required"]

    def inspect(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert node.get("required")
            if "$ref" in node:
                assert node["$ref"].startswith("#/$defs/")
                assert node["$ref"][8:] in schema["$defs"]
            if "format" in node:
                assert node["format"] in validator(name).format_checker.checkers
            for value in node.values():
                inspect(value)
        elif isinstance(node, list):
            for value in node:
                inspect(value)

    inspect(schema)


@pytest.mark.parametrize("name", SCHEMA_NAMES, ids=lambda n: f"SCHEMA-REQUIRED-{n}")
def test_each_required_field_is_enforced(name, fixture_document):
    original = fixture_document(name)
    for key in validator(name).schema["required"]:
        value = copy.deepcopy(original)
        del value[key]
        with pytest.raises(ContractError):
            validate_document(name, value)


@pytest.mark.parametrize("name", SCHEMA_NAMES, ids=lambda n: f"SCHEMA-UNKNOWN-{n}")
def test_unknown_fields_rejected_at_every_object(name, fixture_document):
    def paths(node, prefix=()):
        if isinstance(node, dict):
            yield prefix
            for key, value in node.items():
                yield from paths(value, (*prefix, key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield from paths(value, (*prefix, index))

    original = fixture_document(name)
    for path in paths(original):
        modified = copy.deepcopy(original)
        target = modified
        for step in path:
            target = target[step]
        target["untrusted_admin_override"] = True
        with pytest.raises(ContractError):
            validate_document(name, modified)


@pytest.mark.parametrize("name", SCHEMA_NAMES, ids=lambda n: f"SCHEMA-VERSION-{n}")
def test_unknown_version_rejected(name, fixture_document):
    value = fixture_document(name)
    value["schema_version"] = "999"
    with pytest.raises(ContractError):
        validate_document(name, value)


@pytest.mark.parametrize(
    "value",
    [
        "ctr_...",
        "00000000-0000-4000-8000-000000000000",
        "81K4M0AAAAAAAAAAAAAAA00001",
        "01K4M0AAAAAAAAAAAAAAI00001",
    ],
    ids=["ID-PLACEHOLDER", "ID-UUID4", "ID-OVERFLOW", "ID-AMBIGUOUS"],
)
def test_id_formats(value, fixture_document):
    doc = fixture_document("task-contract")
    doc["contract_id"] = value
    with pytest.raises(ContractError):
        validate_document("task-contract", doc)


def test_uuid7_accepted(fixture_document):
    doc = fixture_document("task-contract")
    doc["contract_id"] = "01991ab0-0000-7000-8000-000000000001"
    validate_document("task-contract", doc)


@pytest.mark.parametrize(
    "value",
    [
        "2026-02-30T00:00:00Z",
        "2026-09-05T00:00:00+08:00",
        "2026-09-05T00:00:00",
        "2026-09-05T25:00:00Z",
        "2026-09-05T00:00:00Z\n",
    ],
    ids=["UTC-CALENDAR", "UTC-OFFSET", "UTC-NAIVE", "UTC-HOUR", "UTC-SUFFIX"],
)
def test_dates_are_real_utc(value, fixture_document):
    doc = fixture_document("task-grant")
    doc["expires_at"] = value
    with pytest.raises(ContractError):
        validate_document("task-grant", doc)


@pytest.mark.parametrize(
    "name,path,value",
    [
        ("task-grant", ["budgets", "tool_calls"], True),
        ("task-grant", ["budgets", "tool_calls"], -1),
        ("task-grant", ["effects"], ["fs.magic"]),
        ("task-grant", ["effects"], ["file.read", "file.read"]),
        ("task-contract", ["workspace_roots"], ["/workspace/../secrets"]),
        ("task-contract", ["workspace_roots"], ["/workspace/%2e%2e"]),
        ("task-contract", ["workspace_roots"], ["/workspace\\..\\secret"]),
        ("provenance-envelope", ["content_ref"], "not a uri"),
        ("provenance-envelope", ["authority"], "ADMIN_FROM_PROMPT"),
        ("semantic-action", ["materialized_args_hash"], "sha256:fake"),
        ("decision-record", ["decision"], "HARD_BLOCK"),
        ("decision-record", ["hard_block"], True),
        ("approval-record", ["approved_at"], None),
        ("detection-finding", ["confidence"], float("nan")),
        ("detection-finding", ["confidence"], 1.1),
        ("security-exception", ["raw_secret"], "SYNTHETIC_ONLY"),
    ],
    ids=[f"SCHEMA-NEG-{i:03d}" for i in range(1, 17)],
)
def test_security_fields(name, path, value, fixture_document):
    doc = fixture_document(name)
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ContractError):
        DOCUMENT_TYPES[name](doc)


@pytest.mark.parametrize("text", ['{"status":"ACTIVE","status":"REVOKED"}', '{"v":NaN}'])
def test_duplicate_or_nonfinite_json_rejected(text):
    with pytest.raises(ContractError):
        load_json(text)


def test_schema_access_cannot_traverse():
    with pytest.raises(ContractError):
        validator("../secrets")


@pytest.mark.parametrize(
    "name,path,value",
    [
        ("semantic-action", ["materialized_args_hash"], "sha256:" + "a" * 64 + "\n"),
        ("semantic-action", ["tool_identity", "tool_name"], "write_report\n"),
        ("provenance-envelope", ["content_ref"], "evidence://fixture/report\n"),
    ],
    ids=["FORMAT-HASH-SUFFIX", "FORMAT-TOOL-SUFFIX", "FORMAT-URI-SUFFIX"],
)
def test_identifier_suffix_cannot_bypass_patterns(name, path, value, fixture_document):
    payload = fixture_document(name)
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ContractError):
        validate_document(name, payload)


def test_schema_validation_is_offline(monkeypatch, fixture_document):
    def fail(*args, **kwargs):
        raise AssertionError("SCHEMA-NETWORK-001: network access forbidden")

    monkeypatch.setattr(socket, "create_connection", fail)
    validator.cache_clear()
    for name in SCHEMA_NAMES:
        validate_document(name, fixture_document(name))


def test_shared_enums_do_not_drift():
    enums = json.loads((CONTRACTS / "enums.json").read_text("utf-8"))
    for name in SCHEMA_NAMES:
        for key, definition in validator(name).schema["$defs"].items():
            if key in enums:
                assert definition["enum"] == enums[key]


def test_schema_bundle_freeze():
    manifest = json.loads((CONTRACTS / "manifest.json").read_text("utf-8"))
    assert manifest["bundle_version"] == "0.2"
    assert set(manifest["schemas"]) == {f"{name}.schema.json" for name in SCHEMA_NAMES}
    for file, expected in manifest["schemas"].items():
        # Stable across Git CRLF/LF checkout settings.
        data = (CONTRACTS / "schemas" / file).read_text("utf-8").replace("\r\n", "\n")
        assert hashlib.sha256(data.encode("utf-8")).hexdigest() == expected
