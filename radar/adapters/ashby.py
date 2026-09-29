from radar.adapters.base import Adapter, RawPosting, parse_dt


class AshbyAdapter(Adapter):
    """Ashby public job board API: https://api.ashbyhq.com/posting-api/job-board/{slug}"""

    ats = "ashby"
    BASE = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

    def fetch(self, slug: str) -> list[RawPosting]:
        data = self._get_json(self.BASE.format(slug=slug), includeCompensation="true")
        out: list[RawPosting] = []
        for job in data.get("jobs", []):
            secondary = [s.get("location") for s in job.get("secondaryLocations") or [] if s.get("location")]
            location = job.get("location") or ""
            if secondary:
                location = "; ".join([location, *secondary]) if location else "; ".join(secondary)
            out.append(
                RawPosting(
                    external_id=str(job["id"]),
                    title=job.get("title") or "",
                    url=job.get("jobUrl") or job.get("applyUrl") or "",
                    location=location or None,
                    remote=bool(job.get("isRemote")) or None,
                    description_html=job.get("descriptionHtml"),
                    description_text=job.get("descriptionPlain"),
                    posted_at=parse_dt(job.get("publishedAt")),
                    raw={
                        "department": job.get("department"),
                        "team": job.get("team"),
                        "employment_type": job.get("employmentType"),
                        "compensation": (job.get("compensation") or {}).get("compensationTierSummary"),
                    },
                )
            )
        return out

    def probe(self, slug: str) -> bool:
        resp = self.client.get(self.BASE.format(slug=slug))
        return resp.status_code == 200
