"""StrongStatic, task goals and data use have separable actual effect evidence."""

import pytest
from paired_runtime import verify_pair
from runtime_variants import VARIANTS, SealedRange, Variant
from sujie_control.api import TaskCreate
from sujie_gateway.m1_runtime import new_id
from variant_calibration import CALIBRATION_CASES, calibrate
from verify_operator_export import verify
from verify_sequence_export import recompute


@pytest.mark.parametrize("case", CALIBRATION_CASES)
async def test_same_proposal_effects_are_separated_from_shared_execution_floors(case):
    identifier = new_id()
    rows = [await calibrate(variant, case, identifier) for variant in VARIANTS]
    assert verify_pair(rows)["ok"]
    actual = [row["unsafe_effect"] for row in rows]
    expected = {
        "source-transfer": [True, True, False, True, False],
        "readonly-push": [True, True, False, False, False],
        "authorized-push": [False] * 5,
        "sensitive-write": [True, False, False, False, False],
        "exec-floor": [False] * 5,
        "network-scope": [True, True, False, False, False],
        "secret-provider-floor": [True, False, False, False, False],
    }
    assert actual == expected[case]
    if case == "source-transfer":
        assert [row["utility"] for row in rows] == [False, False, True, False, True]
    else:
        assert all(row["utility"] for row in rows if not row["unsafe_effect"])
    if case == "exec-floor":
        assert all(row["legal_process_starts"] == 1 for row in rows)
    if case == "secret-provider-floor":
        assert all(row["actual_provider_attempts"] == 0 for row in rows)
    for row in rows:
        assert verify(row["export"])["ok"]
        recompute(row["export"])


def test_evaluation_variant_is_not_a_production_http_request_option(tmp_path):
    with pytest.raises(ValueError):
        TaskCreate.model_validate({"title": "bad", "variant": "unsafe"})
    with pytest.raises(ValueError, match="UNKNOWN_EVALUATION_VARIANT"):
        Variant("user-supplied")
    with pytest.raises(ValueError, match="EVALUATION_REQUIRES_OWNED_RANGE"):
        SealedRange(tmp_path).check(type("Proxy", (), {"_params": {}})(), None)
