"""Employee counts per employer, from data/company_sizes.tsv (made by scripts/company_sizes.py from Wikidata and
Wikipedia; only confident matches are listed). International companies count their worldwide headcount."""

from __future__ import annotations

import csv
from functools import lru_cache

from radar.config import settings
from radar.normalize import norm_company

EMPLOYEE_BANDS = ("1-49", "50-249", "250-4999", "5000+", "unknown")


@lru_cache(maxsize=1)
def _table() -> dict[str, int]:
    path = settings.data_dir / "company_sizes.tsv"
    if not path.exists():
        return {}
    out: dict[str, int] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f, delimiter="\t"):
            if not row or row[0].startswith("#") or len(row) < 2 or not row[1].isdigit():
                continue
            out[norm_company(row[0]).lower()] = int(row[1])
    return out


def employees(company: str) -> int | None:
    return _table().get(norm_company(company or "").lower())


def band(n: int | None) -> str:
    if n is None:
        return "unknown"
    if n < 50:
        return "1-49"
    if n < 250:
        return "50-249"
    if n < 5000:
        return "250-4999"
    return "5000+"
