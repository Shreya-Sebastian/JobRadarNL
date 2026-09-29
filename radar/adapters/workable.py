from radar.adapters.base import Adapter, RawPosting, parse_dt


class WorkableAdapter(Adapter):
    """Workable public widget API: https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"""

    ats = "workable"
    BASE = "https://apply.workable.com/api/v1/widget/accounts/{slug}"

    def fetch(self, slug: str) -> list[RawPosting]:
        data = self._get_json(self.BASE.format(slug=slug), details="true")
        out: list[RawPosting] = []
        for job in data.get("jobs", []):
            # The widget API puts the primary location at the top level and every location in `locations`.
            locs = job.get("locations") or []
            primary = locs[0] if locs else {}
            city = job.get("city") or primary.get("city")
            country = primary.get("countryCode") or job.get("country_code")
            country_name = job.get("country") or primary.get("country")
            if not country and country_name:
                country = {"netherlands": "NL", "the netherlands": "NL", "nederland": "NL"}.get(country_name.lower())
            all_locs = "; ".join(
                ", ".join(p for p in (loc_.get("city"), loc_.get("region"), loc_.get("country")) if p)
                for loc_ in locs
            )
            parts = [p for p in (city, job.get("state"), country_name) if p]
            if all_locs and all_locs != ", ".join(parts):
                parts = [all_locs]
            if country is None and any(
                (loc_.get("countryCode") or "").upper() == "NL" for loc_ in locs
            ):
                country = "NL"
            workplace = (job.get("workplace") or "").lower()
            loc = {"telecommuting": str(job.get("telecommuting", "")).lower() == "true"}
            out.append(
                RawPosting(
                    external_id=str(job.get("shortcode") or job.get("id")),
                    title=job.get("title") or "",
                    url=job.get("url") or job.get("shortlink") or "",
                    location=", ".join(parts) or None,
                    city=city,
                    country=country.upper() if country and len(country) == 2 else None,
                    remote=True if workplace == "remote" or loc.get("telecommuting") else None,
                    description_html="\n".join(
                        s for s in (job.get("description"), job.get("requirements"), job.get("benefits")) if s
                    )
                    or None,
                    posted_at=parse_dt(job.get("published_on") or job.get("created_at")),
                    raw={"department": job.get("department"), "employment_type": job.get("employment_type")},
                )
            )
        return out

    def probe(self, slug: str) -> bool:
        resp = self.client.get(self.BASE.format(slug=slug))
        return resp.status_code == 200
