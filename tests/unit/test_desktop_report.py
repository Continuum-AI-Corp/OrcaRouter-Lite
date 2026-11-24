"""The weekly report's CSV is opened in spreadsheets: a cell starting with
=, +, - or @ would run as a formula there, so such text is quoted."""

from datetime import date

from packages.desktop import report


def test_csv_cells_cannot_run_as_formulas():
    line = report.Line(agent="=HYPERLINK(\"http://x\")", model="+cmd", provider="@sum", requests=1,
                       input_tokens=1, output_tokens=1, spend=0)
    week = report.Week(start=date(2026, 11, 16), lines=[line])
    body = report.weekly(week, "csv").splitlines()[1]
    assert "'=HYPERLINK" in body and "'+cmd" in body and "'@sum" in body
