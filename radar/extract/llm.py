"""LLM extractor: OpenAI structured outputs into the same Extraction schema, cached by content hash."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from radar.config import settings
from radar.extract.schema import Extraction
from radar.taxonomy import SKILLS

LLM_VERSION = f"llm-{settings.llm_model}-v1"
_CACHE_PATH = Path(settings.data_dir) / "llm_cache.json"
_lock = threading.Lock()
_cache: dict[str, dict] | None = None
_calls = 0

SYSTEM = (
    "You extract structured facts from job postings for the Dutch tech market. "
    "Only use skills from this canonical list, exactly as written: " + ", ".join(SKILLS) + ". "
    "skills_required are skills the posting demands; skills_nice are explicitly optional or 'nice to have'. "
    "dutch_required is true only if the posting requires Dutch (or is written in Dutch without saying English "
    "is fine). english_only is the negation of dutch_required. visa_sponsorship is true if the company offers "
    "visa/relocation/30% ruling support, false if it says it cannot sponsor, null if not mentioned. "
    "Salaries are yearly EUR (convert monthly x12). years_experience is the minimum years asked for. "
    "seniority comes from the title first, then the years asked. remote_policy: remote if fully remote, "
    "hybrid if some office days, onsite if fully in office, unknown otherwise. degree_required: the minimum "
    "degree explicitly required (phd, msc, bsc, hbo, mbo), none if it says no degree needed, unknown otherwise."
)


def _load_cache() -> dict[str, dict]:
    global _cache
    if _cache is None:
        if _CACHE_PATH.exists():
            _cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        else:
            _cache = {}
    return _cache


def _save_cache() -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(_cache), encoding="utf-8")


def canonicalise(skills: list[str]) -> list[str]:
    from radar.taxonomy import canonicalise as _canon

    return _canon(skills)


def extract_llm(title: str, description: str) -> Extraction:
    global _calls
    text = (description or "")[:7000]
    key = hashlib.sha256((LLM_VERSION + "\n" + title + "\n" + text).encode()).hexdigest()
    with _lock:
        cache = _load_cache()
        if key in cache:
            return Extraction.model_validate(cache[key])
        if _calls >= settings.llm_max_postings_per_run:
            raise RuntimeError("LLM extraction budget for this run exhausted")
        _calls += 1

    from openai import OpenAI

    client = OpenAI()
    completion = client.beta.chat.completions.parse(
        model=settings.llm_model,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Title: {title}\n\nPosting:\n{text}"},
        ],
        response_format=Extraction,
    )
    parsed = completion.choices[0].message.parsed or Extraction()
    parsed.skills_required = canonicalise(parsed.skills_required)
    parsed.skills_nice = [s for s in canonicalise(parsed.skills_nice) if s not in parsed.skills_required]
    parsed.english_only = not parsed.dutch_required
    with _lock:
        cache[key] = parsed.model_dump()
        _save_cache()
    return parsed
