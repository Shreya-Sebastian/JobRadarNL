"""Score an extractor against the hand-labelled golden set.

Golden file: JSON lines with {"id", "title", "description", "expected": {Extraction fields}}.
Scalar fields are scored by exact match; skills by set precision/recall/F1 over all skills.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from radar.extract import get_extractor
from radar.extract.schema import Extraction

SCALAR_FIELDS = [
    "role_family", "seniority", "posting_language", "dutch_required", "visa_sponsorship",
    "remote_policy", "degree_required", "years_experience", "salary_min_eur",
]


@dataclass
class EvalReport:
    extractor: str
    n: int
    field_accuracy: dict[str, float] = field(default_factory=dict)
    skills_precision: float = 0.0
    skills_recall: float = 0.0
    skills_f1: float = 0.0
    overall: float = 0.0
    mistakes: list[dict] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [f"### Extractor `{self.extractor}` on {self.n} golden postings", "",
                 "| Field | Accuracy |", "|---|---|"]
        for k, v in self.field_accuracy.items():
            lines.append(f"| {k} | {v:.2f} |")
        lines += [f"| skills precision | {self.skills_precision:.2f} |",
                  f"| skills recall | {self.skills_recall:.2f} |",
                  f"| skills F1 | {self.skills_f1:.2f} |",
                  f"| **overall** | **{self.overall:.3f}** |"]
        return "\n".join(lines)


def load_golden(path: str | Path) -> list[dict]:
    items = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def run_eval(golden_path: str | Path, extractor_name: str = "rules") -> EvalReport:
    golden = load_golden(golden_path)
    extract, version = get_extractor(extractor_name)
    report = EvalReport(extractor=version, n=len(golden))
    hits = {f: 0 for f in SCALAR_FIELDS}
    tp = fp = fn = 0
    for item in golden:
        expected = Extraction.model_validate(item["expected"])
        got = extract(item["title"], item["description"])
        for f in SCALAR_FIELDS:
            if getattr(got, f) == getattr(expected, f):
                hits[f] += 1
            else:
                report.mistakes.append({"id": item.get("id"), "field": f, "expected": getattr(expected, f),
                                        "got": getattr(got, f)})
        e_sk, g_sk = set(expected.all_skills()), set(got.all_skills())
        tp += len(e_sk & g_sk)
        fp += len(g_sk - e_sk)
        fn += len(e_sk - g_sk)
        if g_sk != e_sk:
            report.mistakes.append({"id": item.get("id"), "field": "skills", "missing": sorted(e_sk - g_sk),
                                    "extra": sorted(g_sk - e_sk)})
    n = max(1, len(golden))
    report.field_accuracy = {f: hits[f] / n for f in SCALAR_FIELDS}
    report.skills_precision = tp / max(1, tp + fp)
    report.skills_recall = tp / max(1, tp + fn)
    report.skills_f1 = 2 * tp / max(1, 2 * tp + fp + fn)
    scores = list(report.field_accuracy.values()) + [report.skills_f1]
    report.overall = sum(scores) / len(scores)
    return report
