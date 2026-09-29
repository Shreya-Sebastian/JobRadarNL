from datetime import datetime

from radar import sizes
from radar.stats import Filters, Row, posting_dicts


def test_bands():
    assert [sizes.band(n) for n in (None, 12, 49, 50, 249, 250, 4999, 5000, 43520)] == \
        ["unknown", "1-49", "1-49", "50-249", "50-249", "250-4999", "250-4999", "5000+", "5000+"]


def test_lookup_reads_the_table(tmp_path, monkeypatch):
    (tmp_path / "company_sizes.tsv").write_text("# company\temployees\tas_of\tsource\n"
                                                "ASML\t43520\t2026\twikidata:Q297879\n"
                                                "Acme B.V.\t30\t\tnlwiki:Acme\n", encoding="utf-8")
    monkeypatch.setattr(sizes.settings, "data_dir", tmp_path)
    sizes._table.cache_clear()
    try:
        assert sizes.employees("ASML") == 43520 and sizes.employees("Acme") == 30  # B.V. is dropped
        assert sizes.employees("Unknown Co") is None
    finally:
        sizes._table.cache_clear()


def _row(i, company, employees, roles):
    return Row(i, "Dev", company, "Utrecht", False, "u", datetime(2026, 9, i), datetime(2026, 9, i), None, "lever",
               {}, "employer", roles, employees=employees)


def test_filter_and_sort_by_headcount():
    rows = [_row(1, "Big", 43520, 300), _row(2, "Small", 30, 2), _row(3, "Mystery", None, 150), _row(4, "Mid", 120, 5)]
    assert [r.id for r in Filters(employees="5000+,1-49").apply(rows)] == [1, 2]
    assert [r.id for r in Filters(employees="unknown").apply(rows)] == [3]
    small_first = [i["company"] for i in posting_dicts(rows, sort="size_small")["items"]]
    large_first = [i["company"] for i in posting_dicts(rows, sort="size_large")["items"]]
    assert small_first == ["Small", "Mid", "Big", "Mystery"] and large_first == ["Big", "Mid", "Small", "Mystery"]
