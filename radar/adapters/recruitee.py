from radar.adapters.base import Adapter, RawPosting, parse_dt


class RecruiteeAdapter(Adapter):
    """Recruitee public offers API: https://{slug}.recruitee.com/api/offers/ (Dutch ATS, common in NL)."""

    ats = "recruitee"
    BASE = "https://{slug}.recruitee.com/api/offers/"

    def fetch(self, slug: str) -> list[RawPosting]:
        data = self._get_json(self.BASE.format(slug=slug))
        out: list[RawPosting] = []
        for job in data.get("offers", []):
            if job.get("status") not in (None, "published"):
                continue
            country_code = job.get("country_code")
            out.append(
                RawPosting(
                    external_id=str(job["id"]),
                    title=job.get("title") or "",
                    url=job.get("careers_url") or job.get("url") or "",
                    location=job.get("location") or None,
                    city=job.get("city"),
                    country=country_code.upper() if country_code and len(country_code) == 2 else None,
                    remote=True if job.get("remote") else None,
                    description_html="\n".join(s for s in (job.get("description"), job.get("requirements")) if s)
                    or None,
                    posted_at=parse_dt(job.get("published_at") or job.get("created_at")),
                    raw={"department": job.get("department"), "employment_type": job.get("employment_type_code")},
                )
            )
        return out

    def probe(self, slug: str) -> bool:
        try:
            resp = self.client.get(self.BASE.format(slug=slug))
        except Exception:
            return False
        return resp.status_code == 200 and "offers" in resp.text[:200]
