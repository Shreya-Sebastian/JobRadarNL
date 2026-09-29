"""Amazon.jobs: the JSON search endpoint behind amazon.jobs, filtered to one country.

`https://www.amazon.jobs/en/search.json?country=NLD&result_limit=100&offset=0` returns the same data the
public search page renders (title, city, country, posting date, description and qualifications, job path).
Undocumented but unauthenticated, robots.txt only excludes /internal, and we page through a few hundred rows
at most. The slug is the ISO-3 country code, normally NLD. The hiring entity varies (Amazon Web Services EMEA
SARL, Amazon Development Center Netherlands, Annapurna Labs); postings are attributed to the source, "Amazon".
"""

from __future__ import annotations

from datetime import datetime

from radar.adapters.base import Adapter, AdapterError, RawPosting

SEARCH = "https://www.amazon.jobs/en/search.json"
BASE = "https://www.amazon.jobs"


class AmazonAdapter(Adapter):
    ats = "amazon"
    PAGE = 100
    MAX_PAGES = 20

    def fetch(self, slug: str) -> list[RawPosting]:
        country = (slug or "NLD").upper()
        out: list[RawPosting] = []
        seen: set[str] = set()
        for page in range(self.MAX_PAGES):
            # `country=NLD` filters; the array form `country[]=NLD` the site itself uses is ignored by the JSON endpoint
            data = self._get_json(SEARCH, country=country, result_limit=self.PAGE, offset=page * self.PAGE,
                                  sort="recent")
            jobs = data.get("jobs") or []
            if not isinstance(jobs, list):
                raise AdapterError("unexpected amazon.jobs payload")
            for j in jobs:
                ext = str(j.get("id_icims") or j.get("id") or "")
                if not ext or ext in seen:
                    continue
                seen.add(ext)
                html = "<br/>".join(x for x in (j.get("description"), j.get("basic_qualifications"),
                                                j.get("preferred_qualifications")) if x)
                city = j.get("city") or None
                out.append(RawPosting(
                    external_id=ext, title=(j.get("title") or "").strip(),
                    url=BASE + (j.get("job_path") or f"/en/jobs/{ext}"),
                    location=j.get("location") or j.get("normalized_location") or city,
                    city=city, country=_iso2(j.get("country_code")), description_html=html,
                    posted_at=_date(j.get("posted_date")),
                    raw={"company_name": j.get("company_name"), "job_category": j.get("job_category"),
                         "is_intern": j.get("is_intern"), "university_job": j.get("university_job")},
                ))
            if len(jobs) < self.PAGE:
                break
        return out

    def probe(self, slug: str) -> bool:
        try:
            data = self._get_json(SEARCH, country=(slug or "NLD").upper(), result_limit=1)
        except AdapterError:
            return False
        return isinstance(data.get("jobs"), list)


def _iso2(code: str | None) -> str | None:
    return {"NLD": "NL", "DEU": "DE", "BEL": "BE", "GBR": "GB", "USA": "US"}.get((code or "").upper()) or None


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None
