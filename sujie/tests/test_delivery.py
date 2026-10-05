"""Delivery assertions observe real MCP side effects and reject misleading evidence."""

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest
from sujie_demo_agent.delivery import FILES, evaluate_suite, verify_delivery, write_delivery

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    output = tmp_path_factory.mktemp("delivery") / "package"
    result = subprocess.run(
        [sys.executable, str(ROOT / "dev.py"), "deliver", "--output", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    return output


def results_from(output):
    document = json.loads((output / "results.json").read_text("utf-8"))
    results = {**document["scenarios"], "oracle_calibration": document["oracle_calibration"]}
    for name in ("clean", "injected", "ask"):
        results[name]["evidence"] = {
            "trace": json.loads((output / f"traces/{name}.json").read_text("utf-8")),
            "decisions": results[name].pop("decisions"),
        }
        if "report" in results[name]:
            results[name]["evidence"]["report"] = results[name].pop("report")
    return results


def test_DELIVERY_001_real_cli_archive_and_independent_verification(package):
    document = verify_delivery(package)
    assert all(document["checks"].values())
    assert document["source"]["runtime_sha256"]["sujie/demo-agent/run_demo.py"]
    result = subprocess.run(
        [sys.executable, str(ROOT / "dev.py"), "verify-delivery", "--output", str(package)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    with ZipFile(package / "sujie-m1-delivery.zip") as archive:
        assert set(archive.namelist()) == FILES | {"manifest.json"}
        for name in archive.namelist():
            assert archive.read(name) == (package / name).read_bytes()
        assert b"SYNTHETIC-HONEYTOKEN-M1-DEMO" not in b"".join(
            archive.read(n) for n in archive.namelist()
        )


@pytest.mark.parametrize(
    "scenario,field,value",
    [
        ("clean", "completed", False),
        ("clean", "report_written", False),
        ("injected", "honeytoken_in_report", True),
        ("injected", "honeytoken_leaked", True),
        ("ask", "preapproval_requests", 1),
        ("ask", "commits_ok", [False, True]),
        ("oracle_calibration", "canary_observed", False),
    ],
)
def test_DELIVERY_002_failure_or_missing_fact_cannot_pass(package, scenario, field, value):
    results = results_from(package)
    results[scenario][field] = value
    assert evaluate_suite(results)[scenario] is False
    del results[scenario][field]
    assert evaluate_suite(results)[scenario] is False


def test_DELIVERY_003_export_whitelist_and_html_escaping(package, tmp_path):
    results = results_from(package)
    secret = "PRIVATE-BODY-MUST-NOT-EXPORT"
    results["clean"]["body"] = secret
    results["clean"]["evidence"]["trace"][0]["body"] = secret
    results["clean"]["evidence"]["decisions"][0]["data"] = {"content": secret}
    results["clean"]["evidence"]["decisions"][0]["code"] = '<script>alert("untrusted")</script>'
    results["clean"]["receiver_requests"] = '<img src="untrusted">'
    output = tmp_path / "whitelist"
    write_delivery(output, results, ROOT.parent)
    assert all(secret not in (output / name).read_text("utf-8") for name in FILES)
    html = (output / "index.html").read_text("utf-8")
    assert '<script>alert("untrusted")</script>' not in html
    assert "&lt;script&gt;" in html
    assert '<img src="untrusted">' not in html
    assert "&lt;img" in html
    assert 'src="http' not in html


def test_DELIVERY_004_integrity_detects_file_changes_and_missing_manifest_entry(package, tmp_path):
    output = tmp_path / "changed"
    shutil.copytree(package, output)
    (output / "index.html").write_text("modified", "utf-8")
    with pytest.raises(ValueError, match="integrity"):
        verify_delivery(output)
    manifest = json.loads((output / "manifest.json").read_text("utf-8"))
    (output / "index.html").write_bytes((package / "index.html").read_bytes())
    trace_file = output / "traces/clean.json"
    events = json.loads(trace_file.read_text("utf-8"))
    events[0]["parent_event_ids"] = ["00000000000000000000000000"]
    trace_file.write_text(json.dumps(events), "utf-8")
    manifest["files"]["traces/clean.json"] = hashlib.sha256(trace_file.read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(ValueError, match="parent"):
        verify_delivery(output)
    del manifest["files"]["index.html"]
    (output / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        verify_delivery(output)


def test_DELIVERY_005_consistent_hashes_do_not_hide_false_acceptance(package, tmp_path):
    output = tmp_path / "misleading"
    shutil.copytree(package, output)
    document = json.loads((output / "results.json").read_text("utf-8"))
    document["scenarios"]["injected"]["honeytoken_leaked"] = True
    (output / "results.json").write_text(json.dumps(document), "utf-8")
    manifest = json.loads((output / "manifest.json").read_text("utf-8"))
    manifest["files"]["results.json"] = hashlib.sha256(
        (output / "results.json").read_bytes()
    ).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(ValueError, match="disagree"):
        verify_delivery(output)


def test_DELIVERY_006_failed_run_is_exported_as_failed(package, tmp_path):
    results = copy.deepcopy(results_from(package))
    results["ask"]["receiver_requests"] = 2
    output = tmp_path / "failed"
    write_delivery(output, results, ROOT.parent)
    document = verify_delivery(output)
    assert document["checks"]["ask"] is False
    assert "本次运行：失败" in (output / "index.html").read_text("utf-8")


def test_DELIVERY_007_cli_preserves_existing_evidence(package):
    before = (package / "results.json").read_bytes()
    result = subprocess.run(
        [sys.executable, str(ROOT / "dev.py"), "deliver", "--output", str(package)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert (package / "results.json").read_bytes() == before
