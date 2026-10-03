"""Score the classifier and the rule-based extractor on the filter test set (data/golden/filters.jsonl).

500 live postings sampled across sources, languages and levels, plus postings the classifier rejects although they
mention tech words, labelled by reading each posting (definitions in planning/LABELLING.md, outside the repo). Where
the labels and the rules disagreed, the posting was read again and the label settled. 300 postings are the "dev"
split that rules may be tuned on; the other 200 ("test") are only scored, so their numbers stay an honest estimate.

Each field is scored the way its filter is used: accuracy overall, and for the filters that hide or show postings,
precision and recall of the value that matters (a Dutch-required job leaking into "English, no Dutch required" is
the costly error there, an internship wrongly hidden by "requires enrolment" is the costly one there).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path


def wilson(k: int, n: int) -> tuple[float, float]:
    """95% interval for a proportion k/n."""
    if n == 0:
        return 0.0, 0.0
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


@dataclass
class Metric:
    name: str
    k: int
    n: int
    note: str = ""

    @property
    def value(self) -> float:
        return self.k / self.n if self.n else 0.0

    def line(self) -> str:
        lo, hi = wilson(self.k, self.n)
        return f"| {self.name} | {self.value:.1%} | {self.k}/{self.n} | {lo:.0%}-{hi:.0%} | {self.note} |"


@dataclass
class Report:
    metrics: list[Metric] = field(default_factory=list)
    errors: dict[str, list[dict]] = field(default_factory=dict)

    def add(self, name: str, k: int, n: int, note: str = "") -> None:
        self.metrics.append(Metric(name, k, n, note))

    def get(self, name: str) -> Metric:
        return next(m for m in self.metrics if m.name == name)

    def to_markdown(self) -> str:
        head = "| Measure | Score | Count | 95% interval | Meaning |\n|---|---|---|---|---|"
        return head + "\n" + "\n".join(m.line() for m in self.metrics)


def _band(years, ex: dict, title: str) -> str:
    from radar.stats import experience_band

    return experience_band({**ex, "years_experience": years}, title)


_DEGREE_GROUP = {"phd": "phd", "msc": "master", "bsc": "bachelor", "hbo": "bachelor", "mbo": "mbo"}


def run_filter_eval(path: str | Path = "data/golden/filters.jsonl", split: str = "all") -> Report:
    """`split`: "dev" (300 postings rules are tuned on), "test" (200 held back to score honestly) or "all"."""
    from radar.classify import is_tech
    from radar.extract.rules import extract_rules

    items = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if split != "all":
        items = [it for it in items if it.get("split") == split]
    rep = Report()
    errs: dict[str, list[dict]] = {}

    def miss(name: str, it: dict, want, got) -> None:
        errs.setdefault(name, []).append({"id": it["id"], "title": it["title"], "want": want, "got": got})

    # tech or not, over every posting
    tp = fp = fn = agree = 0
    tech_items = []
    for it in items:
        want = it["labels"]["is_tech"]
        got = is_tech(it["title"], it["description"])
        agree += want == got
        tp += want and got
        fp += got and not want
        fn += want and not got
        if want != got:
            miss("is_tech", it, want, got)
        if want:
            tech_items.append((it, extract_rules(it["title"], it["description"]).model_dump()))
    rep.add("tech: accuracy", agree, len(items), "tech or not, all postings")
    rep.add("tech: precision", tp, tp + fp, "of the jobs shown, share that is tech")
    rep.add("tech: recall", tp, tp + fn, "of the tech jobs, share that is shown")

    def exact(name: str, key: str, norm=lambda v: v, only=lambda it, ex: True, note=""):
        k = n = 0
        for it, ex in tech_items:
            if not only(it, ex):
                continue
            want, got = norm(it["labels"].get(key)), norm(ex.get(key))
            n += 1
            if want == got:
                k += 1
            else:
                miss(name, it, want, got)
        rep.add(name, k, n, note)

    exact("role family", "role_family", note="Role filter")
    from radar.positions import position

    k = n = 0
    for it, _ex in tech_items:
        want = it["labels"].get("position")
        if want is None:
            continue
        got = position(it["title"])
        n += 1
        if want == got:
            k += 1
        else:
            miss("position", it, want, got)
    rep.add("position", k, n, "Position filter")
    exact("level", "seniority", note="Level filter")
    exact("years of experience", "years_experience", note="exact minimum years")
    k = n = 0
    for it, ex in tech_items:
        want = _band(it["labels"].get("years_experience"), it["labels"], it["title"])
        got = _band(ex.get("years_experience"), ex, it["title"])
        n += 1
        k += want == got
        if want != got:
            miss("experience band", it, want, got)
    rep.add("experience band", k, n, "Experience asked filter")
    exact("degree", "degree_required", note="minimum degree asked")
    exact("degree group", "degree_required", norm=lambda v: _DEGREE_GROUP.get(v or "", "unstated"),
          note="Degree asked filter")
    exact("posting language", "posting_language")
    exact("Dutch required", "dutch_required")

    # the English filter: jobs it shows that need Dutch (the costly error), and English jobs it misses
    shown = [(it, ex) for it, ex in tech_items if ex.get("english_only")]
    leak = [(it, ex) for it, ex in shown if it["labels"].get("dutch_required")]
    for it, _ in leak:
        miss("English filter shows a Dutch-required job", it, True, False)
    rep.add("English filter: no Dutch needed", len(shown) - len(leak), len(shown),
            "of the jobs it shows, share that really needs no Dutch")
    english = [(it, ex) for it, ex in tech_items if it["labels"].get("dutch_required") is False]
    rep.add("English filter: found", sum(1 for _, ex in english if ex.get("english_only")), len(english),
            "of the jobs needing no Dutch, share it shows")

    exact("visa", "visa_sponsorship", note="sponsorship true / false / not stated")
    vis = [(it, ex) for it, ex in tech_items if ex.get("visa_sponsorship") is True]
    rep.add("visa filter: correct", sum(1 for it, _ in vis if it["labels"].get("visa_sponsorship") is True),
            len(vis), "of the jobs it shows, share that mentions sponsorship")
    exact("remote policy", "remote_policy", note="Remote filter")

    early = lambda it, ex: it["labels"].get("seniority") == "intern"  # noqa: E731
    exact("enrolment", "enrollment_required", only=early, note="internships: requires enrolment / open / not stated")
    hidden = [(it, ex) for it, ex in tech_items if early(it, ex) and ex.get("enrollment_required") is True]
    rep.add("enrolment filter: correctly hidden",
            sum(1 for it, _ in hidden if it["labels"].get("enrollment_required") is True), len(hidden),
            "of the internships it hides, share that requires enrolment")

    def pay(v):
        return None if not v else round(v / 1000)

    exact("salary", "salary_min_eur", norm=pay, note="stated minimum, to the nearest €1,000 a year")
    rep.errors = errs
    return rep
