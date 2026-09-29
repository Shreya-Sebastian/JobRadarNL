from radar.adapters.amazon import AmazonAdapter
from radar.adapters.ashby import AshbyAdapter
from radar.adapters.base import Adapter, RawPosting
from radar.adapters.greenhouse import GreenhouseAdapter
from radar.adapters.jsonld import JsonLdAdapter
from radar.adapters.lever import LeverAdapter
from radar.adapters.personio import PersonioAdapter
from radar.adapters.recruitee import RecruiteeAdapter
from radar.adapters.smartrecruiters import SmartRecruitersAdapter
from radar.adapters.teamtailor import TeamtailorAdapter
from radar.adapters.workable import WorkableAdapter
from radar.adapters.workday import WorkdayAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    a.ats: a
    for a in (
        GreenhouseAdapter,
        LeverAdapter,
        AshbyAdapter,
        WorkableAdapter,
        RecruiteeAdapter,
        TeamtailorAdapter,
        PersonioAdapter,
        WorkdayAdapter,
        SmartRecruitersAdapter,
        JsonLdAdapter,
        AmazonAdapter,
    )
}


def get_adapter(ats: str) -> Adapter:
    try:
        return ADAPTERS[ats]()
    except KeyError as e:
        raise ValueError(f"unknown ATS '{ats}'; known: {sorted(ADAPTERS)}") from e


__all__ = ["ADAPTERS", "Adapter", "RawPosting", "get_adapter"]
