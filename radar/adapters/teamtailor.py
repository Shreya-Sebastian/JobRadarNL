from radar.adapters.base import Adapter, RawPosting, parse_dt
from radar.adapters.jsonld import _to_raw


class TeamtailorAdapter(Adapter):
    """Teamtailor career sites publish a JSON Feed at https://{slug}.teamtailor.com/jobs.json.
    Each item carries the schema.org JobPosting under `_jobposting`, which gives us locations."""

    ats = "teamtailor"
    BASE = "https://{slug}.teamtailor.com/jobs.json"

    def fetch(self, slug: str) -> list[RawPosting]:
        data = self._get_json(self.BASE.format(slug=slug))
        out: list[RawPosting] = []
        for item in data.get("items", []):
            jp = item.get("_jobposting") or {}
            raw = _to_raw(jp, item.get("url") or "") if jp else None
            if raw is None:
                raw = RawPosting(external_id=str(item.get("id")), title=item.get("title") or "",
                                 url=item.get("url") or "", description_html=item.get("content_html"))
            raw.external_id = str(item.get("id") or raw.external_id)
            raw.title = item.get("title") or raw.title
            raw.url = item.get("url") or raw.url
            if not raw.description_text and item.get("content_html"):
                raw.description_html = item["content_html"]
            raw.posted_at = raw.posted_at or parse_dt(item.get("date_published"))
            out.append(raw)
        return out

    def probe(self, slug: str) -> bool:
        try:
            resp = self.client.get(self.BASE.format(slug=slug))
        except Exception:
            return False
        return resp.status_code == 200 and '"items"' in resp.text[:500]
