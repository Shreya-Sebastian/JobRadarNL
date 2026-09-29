from radar.adapters.base import Adapter, RawPosting, parse_dt


class GreenhouseAdapter(Adapter):
    """Greenhouse public job board API: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"""

    ats = "greenhouse"
    BASE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"

    def fetch(self, slug: str) -> list[RawPosting]:
        data = self._get_json(self.BASE.format(slug=slug), content="true")
        out: list[RawPosting] = []
        for job in data.get("jobs", []):
            loc = (job.get("location") or {}).get("name")
            offices = job.get("offices") or []
            office_loc = ", ".join(o.get("location") or o.get("name") or "" for o in offices if o)
            out.append(
                RawPosting(
                    external_id=str(job["id"]),
                    title=job.get("title") or "",
                    url=job.get("absolute_url") or "",
                    location=loc or office_loc or None,
                    description_html=job.get("content"),
                    posted_at=parse_dt(job.get("first_published") or job.get("updated_at")),
                    raw={"departments": [d.get("name") for d in job.get("departments") or [] if d]},
                )
            )
        return out

    def probe(self, slug: str) -> bool:
        resp = self.client.get(self.BASE.format(slug=slug))
        return resp.status_code == 200
