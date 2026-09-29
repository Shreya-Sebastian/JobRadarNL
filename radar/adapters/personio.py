import re
import xml.etree.ElementTree as ET

from radar.adapters.base import Adapter, AdapterError, RawPosting, SourceNotFound, parse_dt


class PersonioAdapter(Adapter):
    """Personio publishes an XML feed of open positions at https://{slug}.jobs.personio.de/xml."""

    ats = "personio"
    BASE = "https://{slug}.jobs.personio.de/xml"

    def fetch(self, slug: str) -> list[RawPosting]:
        url = self.BASE.format(slug=slug)
        resp = self.client.get(url)
        if resp.status_code == 404:
            raise SourceNotFound(url)
        if resp.status_code >= 400:
            raise AdapterError(f"{resp.status_code} for {url}")
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            raise AdapterError(f"bad XML from {url}") from e
        out: list[RawPosting] = []
        for pos in root.iter("position"):
            pid = (pos.findtext("id") or "").strip()
            name = (pos.findtext("name") or "").strip()
            if not pid or not name:
                continue
            office = (pos.findtext("office") or "").strip()
            html_parts = [
                (d.findtext("value") or "") for d in pos.iter("jobDescription")
            ]
            years = (pos.findtext("yearsOfExperience") or "").strip()
            out.append(
                RawPosting(
                    external_id=pid,
                    title=name,
                    url=f"https://{slug}.jobs.personio.de/job/{pid}",
                    location=office or None,
                    description_html="\n".join(p for p in html_parts if p) or None,
                    posted_at=parse_dt(pos.findtext("createdAt")),
                    raw={
                        "department": (pos.findtext("department") or "").strip(),
                        "seniority": (pos.findtext("seniority") or "").strip(),
                        "employment_type": (pos.findtext("employmentType") or "").strip(),
                        "years": years,
                        "occupation": (pos.findtext("occupationCategory") or "").strip(),
                    },
                )
            )
        return out

    def probe(self, slug: str) -> bool:
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            return False
        try:
            resp = self.client.get(self.BASE.format(slug=slug))
        except Exception:
            return False
        return resp.status_code == 200 and b"<workzag-jobs" in resp.content[:300]
