"""Workday adapter. Slug format: "{tenant}.wd{n}/{site}", e.g. "nxp.wd3/careers".

Workday career sites expose an unauthenticated JSON API used by their own front end:
  POST https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs   (listing, paged, faceted)
  GET  https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}   (detail)
We read the country facet from the first page, restrict the listing to the Netherlands, then fetch details
only for those postings, so a 1,000-job corporate board costs a few dozen requests, not a thousand.
"""

from __future__ import annotations

import re

from radar.adapters.base import Adapter, AdapterError, RawPosting, SourceNotFound, parse_dt

_SLUG = re.compile(r"^([a-z0-9-]+)\.(wd\d+)/([A-Za-z0-9_-]+)$", re.I)
_NL = re.compile(r"netherlands|nederland", re.I)


def _find_nl_facet(facets: list, param: str | None = None, label: str = "") -> tuple[str | None, str | None, int]:
    """Return (facetParameter, value id, count) for the Netherlands country value.

    Workday tenants differ: some expose a flat `Location_Country` facet, others nest it as
    locationMainGroup -> "Country/Region" (facetParameter locationHierarchy1) -> values. Walk everything, but
    only accept a match inside a country-like facet (by parameter name or by the parent's label) so
    "Netherlands - Remote Based" under City does not win."""
    best: tuple[str | None, str | None, int] = (None, None, 0)
    for facet in facets or []:
        fp = facet.get("facetParameter") or param
        for v in facet.get("values") or []:
            desc = (v.get("descriptor") or "").strip()
            if v.get("values") or v.get("facetParameter"):
                found = _find_nl_facet([v], v.get("facetParameter") or fp, desc)
                if found[1] and found[2] >= best[2]:
                    best = found
                continue
            country_like = re.search(r"country", f"{fp or ''} {label}", re.I)
            if desc.lower() in ("netherlands", "the netherlands", "nederland") and country_like:
                if int(v.get("count") or 0) >= best[2]:
                    best = (fp, v.get("id"), int(v.get("count") or 0))
    return best


def _is_dutch_place(text: str) -> bool:
    from radar.normalize import detect_city

    return bool(_NL.search(text or "")) or bool(detect_city(text or ""))


def _find_nl_locations(facets: list, param: str | None = None) -> tuple[str | None, list[str]]:
    """Fallback when a tenant has no country facet (ASML): the location facet's values that are Dutch places,
    e.g. "Veldhoven", "Eindhoven", "Delft". Returns (facetParameter, [value ids])."""
    for facet in facets or []:
        fp = facet.get("facetParameter") or param
        values = facet.get("values") or []
        nested = [v for v in values if v.get("values")]
        if nested:
            found = _find_nl_locations(nested, fp)
            if found[1]:
                return found
        if re.search(r"location", fp or "", re.I):
            ids = [v.get("id") for v in values if v.get("id") and _is_dutch_place(v.get("descriptor") or "")]
            if ids:
                return fp, ids
    return None, []


class WorkdayAdapter(Adapter):
    ats = "workday"
    PAGE = 20
    MAX_DETAILS = 400

    def _base(self, slug: str) -> tuple[str, str]:
        m = _SLUG.match(slug)
        if not m:
            raise AdapterError(f"workday slug must look like tenant.wd3/site, got {slug!r}")
        tenant, wd, site = m.group(1), m.group(2), m.group(3)
        host = f"https://{tenant}.{wd}.myworkdayjobs.com"
        return host, f"{host}/wday/cxs/{tenant}/{site}"

    def _list(self, api: str, facets: dict, offset: int, search: str = "") -> dict:
        resp = self.client.post(f"{api}/jobs", json={"appliedFacets": facets, "limit": self.PAGE,
                                                      "offset": offset, "searchText": search},
                                headers={"Accept": "application/json", "Content-Type": "application/json"})
        if resp.status_code == 404:
            raise SourceNotFound(api)
        if resp.status_code >= 400:
            raise AdapterError(f"{resp.status_code} for {api}/jobs")
        return resp.json()

    def fetch(self, slug: str) -> list[RawPosting]:
        host, api = self._base(slug)
        first = self._list(api, {}, 0)
        nl_param, nl_id, _ = _find_nl_facet(first.get("facets", []))
        loc_param, loc_ids = (None, []) if nl_id else _find_nl_locations(first.get("facets", []))
        search = ""
        if nl_id:
            facets = {nl_param: [nl_id]}
            page = self._list(api, facets, 0)
        elif loc_ids:
            # no country facet, but a location facet listing Dutch sites: select those
            facets = {loc_param: loc_ids}
            page = self._list(api, facets, 0)
            nl_id = "locations"
        else:
            # No country facet on this tenant: use the site's own search for "Netherlands" so NL postings deep
            # in a 3,000-job list are found, then keep only those whose location text says so.
            facets, search = {}, "Netherlands"
            page = self._list(api, facets, 0, search)
        total = int(page.get("total") or 0)
        listings = list(page.get("jobPostings") or [])
        offset = self.PAGE
        while offset < total and offset < 2000:
            more = self._list(api, facets, offset, search)
            listings.extend(more.get("jobPostings") or [])
            offset += self.PAGE
        if not nl_id:
            listings = [j for j in listings if _is_dutch_place(j.get("locationsText") or "")]

        out: list[RawPosting] = []
        for job in listings[: self.MAX_DETAILS]:
            path = job.get("externalPath") or ""
            ext_id = (job.get("bulletFields") or [path])[0] or path
            description = None
            country = "NL"
            posted = None
            try:
                detail = self.client.get(f"{api}{path}", headers={"Accept": "application/json"})
                if detail.status_code == 200:
                    info = detail.json().get("jobPostingInfo") or {}
                    description = info.get("jobDescription")
                    posted = parse_dt(info.get("startDate"))
                    c = (info.get("country") or {}).get("descriptor") or ""
                    if c and not _is_dutch_place(c):
                        country = None
            except Exception:
                pass
            out.append(
                RawPosting(
                    external_id=str(ext_id),
                    title=job.get("title") or "",
                    url=f"{host}/{slug.split('/', 1)[1]}{path}",
                    location=job.get("locationsText"),
                    country=country,
                    description_html=description,
                    posted_at=posted,
                    raw={"posted_on": job.get("postedOn")},
                )
            )
        return out

    def count_nl(self, slug: str) -> tuple[int, int]:
        """(nl_postings, total_postings) from the first listing page's country facet: one request per board."""
        _, api = self._base(slug)
        first = self._list(api, {}, 0)
        total = int(first.get("total") or 0)
        param, nl_id, count = _find_nl_facet(first.get("facets", []))
        if param:
            return count, total
        # no country facet: ask the site's search; count the matches whose location text names the Netherlands
        page = self._list(api, {}, 0, "Netherlands")
        hits = list(page.get("jobPostings") or [])
        offset = self.PAGE
        while offset < int(page.get("total") or 0) and offset < 400:
            hits.extend(self._list(api, {}, offset, "Netherlands").get("jobPostings") or [])
            offset += self.PAGE
        nl = sum(1 for j in hits if _NL.search(j.get("locationsText") or ""))
        return nl, total

    def probe(self, slug: str) -> bool:
        try:
            _, api = self._base(slug)
            data = self._list(api, {}, 0)
        except Exception:
            return False
        return "jobPostings" in data
