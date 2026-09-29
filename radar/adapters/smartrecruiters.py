from radar.adapters.base import Adapter, RawPosting, parse_dt


class SmartRecruitersAdapter(Adapter):
    """SmartRecruiters public Posting API: https://api.smartrecruiters.com/v1/companies/{slug}/postings
    Listing is paged (100 per page) and carries the location; the job ad text needs one detail request per
    posting, so details are fetched only for postings located in the Netherlands."""

    ats = "smartrecruiters"
    BASE = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    PAGE = 100
    MAX_DETAILS = 400

    def fetch(self, slug: str) -> list[RawPosting]:
        url = self.BASE.format(slug=slug)
        offset = 0
        listings: list[dict] = []
        while True:
            data = self._get_json(url, limit=self.PAGE, offset=offset)
            content = data.get("content") or []
            listings.extend(content)
            offset += self.PAGE
            if not content or offset >= int(data.get("totalFound") or 0) or offset >= 3000:
                break
        out: list[RawPosting] = []
        details_left = self.MAX_DETAILS
        for job in listings:
            loc = job.get("location") or {}
            country = (loc.get("country") or "").upper() or None
            city = loc.get("city")
            parts = [p for p in (city, loc.get("region"), loc.get("country")) if p]
            description = None
            posting_url = f"https://jobs.smartrecruiters.com/{slug}/{job.get('id')}"
            if country == "NL" and details_left > 0:
                details_left -= 1
                try:
                    detail = self._get_json(f"{url}/{job['id']}")
                    sections = (detail.get("jobAd") or {}).get("sections") or {}
                    description = "\n".join(
                        f"<h2>{s.get('title') or ''}</h2>{s.get('text') or ''}"
                        for s in sections.values() if isinstance(s, dict) and s.get("text")
                    ) or None
                    posting_url = detail.get("postingUrl") or posting_url  # the canonical page with its slug
                except Exception:
                    description = None
            out.append(
                RawPosting(
                    external_id=str(job.get("id")),
                    title=job.get("name") or "",
                    url=posting_url,
                    location=", ".join(parts) or None,
                    city=city,
                    country=country if country and len(country) == 2 else None,
                    remote=True if loc.get("remote") else None,
                    description_html=description,
                    posted_at=parse_dt(job.get("releasedDate")),
                    raw={"department": (job.get("department") or {}).get("label"),
                         "function": (job.get("function") or {}).get("label")},
                )
            )
        return out

    def probe(self, slug: str) -> bool:
        try:
            resp = self.client.get(self.BASE.format(slug=slug), params={"limit": 1})
        except Exception:
            return False
        return resp.status_code == 200 and "totalFound" in resp.text[:200]
