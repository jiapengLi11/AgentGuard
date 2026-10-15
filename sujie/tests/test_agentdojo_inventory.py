"""Upstream source inventory must stay static and fail unsupported task shapes."""

import pytest
from index_agentdojo import SUITES, index


def write_suite_sources(root, source):
    for suite in SUITES:
        directory = root / f"default_suites/v1/{suite}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "user_tasks.py").write_text(source, "utf-8")


def test_inventory_parses_expressions_without_running_upstream(tmp_path):
    marker = tmp_path / "should-not-exist"
    source = f"""
raise RuntimeError("Must never import this source")
class UserTask0:
    PROMPT = open({str(marker)!r}, "w").write("unexpected")
    def ground_truth(self, env):
        return [FunctionCall(function="read_file", args={{}})]
"""
    write_suite_sources(tmp_path, source)
    record = index(tmp_path)
    assert not marker.exists()
    assert record["summary"]["base_task_classes"] == 4
    assert all(row["ground_truth_tool_names"] == ["read_file"] for row in record["rows"])
    assert all(not row["prompt_is_literal"] for row in record["rows"])
    before = record["source_sha256"]
    write_suite_sources(tmp_path, source + "\n# changed\n")
    assert index(tmp_path)["source_sha256"] != before


def test_inventory_refuses_to_silently_drop_inherited_prompts(tmp_path):
    write_suite_sources(tmp_path, "class UserTask0(BaseTask):\n    pass\n")
    with pytest.raises(ValueError, match="UNSUPPORTED_INHERITED_TASK_PROMPT"):
        index(tmp_path)
