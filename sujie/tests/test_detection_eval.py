import runpy
from pathlib import Path


def test_versioned_detection_smoke_set_reports_misses_and_false_positive():
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "eval/run_detection.py"))
    report = module["evaluate"]()
    assert report["evaluation_scope"] == "rule_detector_only_not_agent_asr"
    assert report["case_count"] == 14
    assert report["confusion"] == {"tp": 5, "fn": 2, "fp": 1, "tn": 6}
    assert {case["family"] for case in report["cases"] if case["attack"]} == {
        "MULTILINGUAL_EMOJI",
        "UNICODE_CONFUSABLE",
        "FRAGMENTED_MULTITURN",
        "COMMENT_DELIMITER",
        "CHARACTER_ENCODING",
        "CONTEXT_DILUTION",
        "SEMANTIC_DISGUISE",
    }
