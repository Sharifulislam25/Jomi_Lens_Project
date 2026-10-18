from src.exporting import safe_cell, to_csv


def test_formula_cells_are_neutralised_but_numbers_kept():
    assert safe_cell("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert safe_cell("+cmd") == "'+cmd" and safe_cell("@SUM(A1)") == "'@SUM(A1)" and safe_cell("-2+3") == "'-2+3"
    assert safe_cell("-12.5") == "-12.5" and safe_cell(7) == "7" and safe_cell(None) == ""
    out = to_csv([{"a": "=1+1", "b": "ok"}]).decode("utf-8-sig")
    assert out.splitlines() == ["a,b", "'=1+1,ok"]
