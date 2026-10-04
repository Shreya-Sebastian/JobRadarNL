import pytest

from radar.positions import LABELS, POSITIONS, position
from radar.stats import Filters, Row, breakdown


@pytest.mark.parametrize("title,kind", [
    ("Senior Software Engineer", "software_engineer"),
    ("Medior .NET ontwikkelaar (m/v)", "software_engineer"),
    ("Data Engineer - Azure", "data_engineer"),
    ("Data-analist de Gelderlander", "bi_analyst"),
    ("Product Owner Payments", "product_owner"),
    ("Senior Product Manager", "product_manager"),
    ("AI Engineer", "ml_engineer"),
    ("Machine Learning Engineer", "ml_engineer"),
    ("Senior AI-Native Java Engineer", "software_engineer"),
    ("AI Solutions Architect", "architect"),
    ("Associate Creative Director (CGI/AI)", "other"),
    ("Data & AI Consultant", "data_consultant"),
    ("Test Automation Engineer", "qa_test"),
    ("DevOps Engineer", "devops"),
    ("Release Manager", "devops"),
    ("IT Auditor (RE)", "security_officer"),
    ("SOC Analyst", "security_engineer"),
    ("Functioneel beheerder", "app_admin"),
    ("Scrum Master", "scrum_agile"),
    ("PhD position in robotics", "phd_research"),
    ("Fullstack Developer", "fullstack"),
    ("Frontend Developer React", "frontend"),
    ("Servicedeskmedewerker", "it_support"),
    ("Senior Oracle Ontwikkelaar", "software_engineer"),
    ("SAP FICO Consultant", "it_consultant"),
    ("Information Security Consultant", "security_officer"),
    ("Data Engineering Consultant", "data_engineer"),
    ("Medior Automation engineer (PowerPlatform & UiPath)", "low_code"),
    ("Automation Engineer", "plc_automation"),
    ("SAP (S4/HANA) Projectmanager", "project_manager"),
    ("Front-end developer met passie voor DevOps", "frontend"),
    ("Technisch Support Engineer bij M2Beveiliging", "it_support"),
    ("Technical Lead", "software_engineer"),
])
def test_position(title, kind):
    assert position(title) == kind


def test_every_position_has_both_labels():
    for lang in ("en", "nl"):
        assert set(LABELS[lang]) == set(POSITIONS)


def _row(i, title):
    from datetime import datetime

    return Row(i, title, "Acme", "Utrecht", False, "https://x", None, datetime.utcnow(), None, "greenhouse")


def test_filter_and_breakdown():
    rows = [_row(1, "Data Engineer"), _row(2, "Data Engineer II"), _row(3, "Product Owner")]
    assert [r.id for r in Filters(position="product_owner").apply(rows)] == [3]
    assert breakdown(rows, "position")[0] == {"key": "data_engineer", "count": 2, "share": 0.6667}


def test_alerts_use_position_and_sector_from_the_profile():
    from datetime import datetime

    from radar.alerts import profile_filters

    f = profile_filters({"positions": ["data_engineer"], "sectors": ["finance"], "cities": ["Utrecht"]},
                        datetime(2026, 10, 1))
    assert (f.position, f.sector, f.city) == ("data_engineer", "finance", "Utrecht")


def test_curated_company_names_join_one_organisation():
    from radar.normalize import dedup_key, norm_company

    assert norm_company("Metyisag") == norm_company("Metyis") == "Metyis"
    assert norm_company("Werkenbijadesso") == "adesso"
    assert dedup_key("Metyisag", "AI Solutions Engineer", "Amsterdam") == dedup_key("Metyis", "AI Solutions Engineer",
                                                                                    "Amsterdam")


def test_same_job_on_one_board():
    from radar.crawler import same_job

    body = "We build data platforms for retail and logistics clients across Europe. " * 20
    ex = {"posting_language": "en", "seniority": "medior", "years_experience": 3, "role_family": "data",
          "skills_required": ["Python", "SQL"]}
    brand_a = ("About Metyis. " + body, ex)
    brand_b = ("About Adaptfy, a Metyis company with its own clients. " + body, ex)
    assert same_job(brand_a, brand_b)
    other_team = ("About Metyis. " + body[: len(body) // 2] + "You lead the Kafka streaming team and mentor Java "
                  "engineers on event-driven services. " * 10, dict(ex, skills_required=["Java", "Kafka"],
                                                                     seniority="senior"))
    assert not same_job(brand_a, other_team)
    # mostly the same template (60-90% of the text) but another level and stack: a different opening
    template = ("About Metyis. " + body[: len(body) * 3 // 4] + "You lead the Kafka streaming team. " * 6,
                dict(ex, skills_required=["Java", "Kafka"], seniority="senior"))
    assert not same_job(brand_a, template)
    assert same_job(brand_a, (template[0], ex))  # the same text with the same facts is the same job
    dutch = ("Wij bouwen dataplatforms voor klanten in retail en logistiek. " * 20, dict(ex, posting_language="nl"))
    assert same_job(brand_a, dutch)
    assert same_job(brand_a, ("https://example.org/apply", {}))
