from radar.adapters.base import Adapter, RawPosting, parse_dt


class LeverAdapter(Adapter):
    """Lever public postings API: https://api.lever.co/v0/postings/{slug}?mode=json"""

    ats = "lever"
    BASE = "https://api.lever.co/v0/postings/{slug}"

    def fetch(self, slug: str) -> list[RawPosting]:
        data = self._get_json(self.BASE.format(slug=slug), mode="json")
        if not isinstance(data, list):
            return []
        out: list[RawPosting] = []
        for job in data:
            cats = job.get("categories") or {}
            workplace = (job.get("workplaceType") or "").lower()
            out.append(
                RawPosting(
                    external_id=str(job["id"]),
                    title=job.get("text") or "",
                    url=job.get("hostedUrl") or job.get("applyUrl") or "",
                    location=cats.get("location") or ", ".join(cats.get("allLocations") or []) or None,
                    country=job.get("country"),
                    remote=True if workplace == "remote" else None,
                    description_html=_lever_html(job),
                    description_text=_lever_text(job),
                    posted_at=parse_dt(job.get("createdAt")),
                    raw={"team": cats.get("team"), "commitment": cats.get("commitment"), "workplace": workplace},
                )
            )
        return out

    def probe(self, slug: str) -> bool:
        resp = self.client.get(self.BASE.format(slug=slug), params={"mode": "json", "limit": 1})
        return resp.status_code == 200


def _lever_html(job: dict) -> str | None:
    parts = [job.get("description") or ""]
    for lst in job.get("lists") or []:
        if lst.get("text"):
            parts.append(f"<h3>{lst['text']}</h3>")
        if lst.get("content"):
            parts.append(f"<ul>{lst['content']}</ul>")
    parts.append(job.get("additional") or "")
    html = "\n".join(p for p in parts if p).strip()
    return html or None


def _lever_text(job: dict) -> str | None:
    parts = [job.get("descriptionPlain") or ""]
    for lst in job.get("lists") or []:
        parts.append(lst.get("text") or "")
        from radar.adapters.base import html_to_text

        parts.append(html_to_text(lst.get("content") or ""))
    parts.append(job.get("additionalPlain") or "")
    text = "\n".join(p for p in parts if p).strip()
    return text or None
