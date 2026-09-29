from radar.extract.rules import RULES_VERSION, extract_rules
from radar.extract.schema import Extraction


def get_extractor(name: str):
    """Return (callable(title, description) -> Extraction, version)."""
    if name == "rules":
        return extract_rules, RULES_VERSION
    if name == "llm":
        from radar.extract.llm import LLM_VERSION, extract_llm

        return extract_llm, LLM_VERSION
    raise ValueError(f"unknown extractor {name}")


__all__ = ["Extraction", "extract_rules", "get_extractor"]
