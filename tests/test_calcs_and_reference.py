"""Pipeline output must match the hand-computed 'approved' values in reference/."""
import pytest

from aapurti import calcs
from aapurti.validation.reference import check_calcs, check_fixture


def test_approved_calculation_cases():
    res = check_calcs()
    assert len(res) >= 13
    bad = [r for r in res if not r["ok"]]
    assert not bad, bad


def test_calc_functions_basic():
    assert calcs.days_of_cover(300, 10) == 30
    assert calcs.days_of_cover(5, 0) is None
    assert calcs.safety_stock(2, 4, 1.65) == pytest.approx(6.6)
    assert calcs.utilization(60, 96) == pytest.approx(0.625)
    assert calcs.utilization(1, 0) is None


def test_pipeline_matches_hand_computed_fixture(fixture_lake):
    res = check_fixture(fixture_lake)
    assert len(res) >= 30
    bad = [r for r in res if not r["ok"]]
    assert not bad, bad
