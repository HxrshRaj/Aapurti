from aapurti.validation.reconcile import to_markdown


def test_every_check_reconciles_with_zero_unexplained_variance(mini_env):
    rec = mini_env["reconciliation"]
    assert len(rec["checks"]) >= 8
    for c in rec["checks"]:
        assert c["ok"], c
    assert rec["all_ok"]


def test_quarantined_units_are_itemised(mini_env):
    assert "units_out_of_range" in mini_env["reconciliation"]["quarantined_units_by_reason"]


def test_markdown_table(mini_env):
    md = to_markdown(mini_env["reconciliation"])
    assert md.count("\n") >= 8 and "| yes |" in md and "| NO |" not in md
