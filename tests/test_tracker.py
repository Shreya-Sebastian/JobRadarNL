from radar.adapters.base import RawPosting
from radar.crawler import ingest
from radar.db import session_scope
from radar.models import Source
from radar.tracker import Entry, evaluate, load_tracker


def test_pretty_company_names():
    from radar.registry import pretty_company

    assert pretty_company("deloittenetherlands") == "Deloitte"
    assert pretty_company("accenture.wd103/AccentureCareers") == "Accenture"
    assert pretty_company("kpmg-nederland") == "KPMG"
    assert pretty_company("xebiacareers") == "Xebia"
    assert pretty_company("schubergphilis") == "Schuberg Philis"
    assert pretty_company("adyen") == "Adyen"
    assert pretty_company("some-startup-jobs") == "Some Startup"
    assert pretty_company("acme", "Acme Consulting B.V.") == "Acme Consulting B.V."
    assert pretty_company("https://careers.capgemini.com/sitemap.xml", "Capgemini") == "Capgemini"
    assert pretty_company("https://www.nedap.com/sitemap.xml") == "Nedap"


def test_tracker_file_is_well_formed():
    entries = load_tracker()
    assert len(entries) >= 100
    assert all(e.name and e.match and e.group for e in entries)


def test_board_postings_are_attributed_and_counted(fresh_db):
    with session_scope() as s:
        board = Source(company="AcademicTransfer", ats="jsonld", slug="https://x/sitemap.xml", kind="board")
        own = Source(company="Adyen", ats="greenhouse", slug="adyen")
        s.add_all([board, own])
        s.flush()
        ingest(s, board, [RawPosting(external_id="1", title="PhD in ML", url="https://x/1", company="TU Delft",
                                     location="Delft", description_text="PyTorch")])
        ingest(s, own, [RawPosting(external_id="2", title="Engineer", url="https://y/2", company="Ignored Corp",
                                   location="Amsterdam", description_text="Java")])
        entries = evaluate(s, [
            Entry("TU Delft", ["tu delft"], "academictransfer", "university"),
            Entry("Adyen", ["adyen"], "greenhouse", "finance"),
            Entry("ASML", ["asml"], "custom", "semicon"),
            Entry("Ignored", ["ignored corp"], "x", "x"),
        ])
    by = {e.name: e for e in entries}
    assert by["TU Delft"].status == "covered" and by["TU Delft"].live_postings == 1
    assert by["Adyen"].status == "covered"           # attributed to the employer, not the raw company
    assert by["ASML"].status == "missing"
    assert by["Ignored"].status == "missing"
