"""Weekly discovery: only boards and employers never checked before are probed, and the results are remembered."""

from datetime import datetime, timedelta

from radar import timetable, weekly


def test_register_page_rows_are_parsed():
    page = ('<thead><tr><th scope="col">Organisation</th><th scope="col">KVK number</th></tr></thead>'
            '<tr><th scope="row">""Aa-Dee"" Machinefabriek B.V.</th>\n<td>16051874</td></tr>'
            '<tr><th scope="row">Smith &amp; Jones B.V.</th><td> 12345678 </td></tr>')
    assert weekly.parse_register(page) == [('""Aa-Dee"" Machinefabriek B.V.', "16051874"),
                                           ("Smith & Jones B.V.", "12345678")]


def test_three_platforms_a_week_in_turn():
    weeks = [weekly.platforms_this_week(datetime(2026, 10, 5) + timedelta(weeks=i)) for i in range(3)]
    assert all(len(set(w)) == 3 for w in weeks)
    from radar.enumerate import PATTERNS

    assert set(sum(weeks, [])) == set(PATTERNS)  # nine platforms, all covered within three weeks


def test_weekly_slot_only_on_sunday_night():
    entry = next(e for e in timetable.TIMETABLE if e.name == "discover_weekly")
    assert timetable.slot(entry, datetime(2026, 10, 4, 0, 40)) == "discover_weekly:2026-10-04"  # a Sunday
    assert timetable.slot(entry, datetime(2026, 10, 5, 0, 40)) is None  # Monday
    assert timetable.slot(entry, datetime(2026, 10, 4, 0, 41)) is None


def test_run_probes_only_new_boards_and_employers(fresh_db, monkeypatch):
    from sqlalchemy import select

    from radar import enumerate as en
    from radar import sponsors as sp
    from radar.db import session_scope
    from radar.models import DiscoveryCandidate, Source
    from radar.registry import upsert_source

    with session_scope() as s:
        upsert_source(s, "Known", "recruitee", "known")
        s.add(DiscoveryCandidate(kind="recruitee", key="seen", status="ok", nl=0, checked_at=datetime.utcnow()))
        s.add(DiscoveryCandidate(kind="sponsor", key="11111111", status="no_board", checked_at=datetime.utcnow()))

    probed, looked_up = [], []
    monkeypatch.setattr(weekly, "platforms_this_week", lambda today: ["recruitee"])
    monkeypatch.setattr(en, "enumerate_slugs", lambda ats, timeout=0: ["newco", "known", "seen", "abroad"])
    monkeypatch.setattr(en, "_probe_one", lambda ats, slug: probed.append(slug) or
                        {"slug": slug, "status": "ok", "total": 5, "nl": 3 if slug == "newco" else 0})
    monkeypatch.setattr(weekly, "fetch_register", lambda: [("Old Sponsor B.V.", "11111111"),
                                                           ("New Sponsor B.V.", "22222222")])
    monkeypatch.setattr(sp, "process_one", lambda name, client: looked_up.append(name) or
                        {"name": name, "domain": "newsponsor.nl", "ats": [("teamtailor", "newsponsor")]})
    monkeypatch.setattr(sp, "register", lambda session, entry: 1)

    with session_scope() as s:
        out = weekly.run(s)
    assert probed == ["newco", "abroad"]  # the known source and the board checked before are skipped
    assert looked_up == ["New Sponsor B.V."]
    assert out["sources_added"] == 2 and out["boards_probed"] == 2 and out["sponsors_checked"] == 1
    with session_scope() as s:
        assert s.scalar(select(Source).where(Source.ats == "recruitee", Source.slug == "newco")) is not None
        assert s.scalar(select(Source).where(Source.slug == "abroad")) is None  # no Dutch postings: not a source
        kinds = {(c.kind, c.key): c.status for c in s.scalars(select(DiscoveryCandidate))}
    assert kinds[("recruitee", "abroad")] == "ok" and kinds[("sponsor", "22222222")] == "board"

    # the second run finds nothing new to do
    probed.clear(), looked_up.clear()
    with session_scope() as s:
        weekly.run(s)
    assert probed == [] and looked_up == []


def test_boards_without_dutch_postings_are_checked_again_after_three_months(fresh_db, monkeypatch):
    from radar import enumerate as en
    from radar.db import session_scope
    from radar.models import DiscoveryCandidate

    old = datetime.utcnow() - timedelta(days=100)
    with session_scope() as s:
        s.add(DiscoveryCandidate(kind="lever", key="grew", status="ok", nl=0, checked_at=old))
        s.add(DiscoveryCandidate(kind="lever", key="recent", status="ok", nl=0, checked_at=datetime.utcnow()))
    probed = []
    monkeypatch.setattr(weekly, "platforms_this_week", lambda today: [])
    monkeypatch.setattr(weekly, "fetch_register", lambda: [])
    monkeypatch.setattr(en, "_probe_one", lambda ats, slug: probed.append(slug) or
                        {"slug": slug, "status": "ok", "total": 9, "nl": 4})
    with session_scope() as s:
        out = weekly.run(s)
    assert probed == ["grew"] and out["rechecked"] == 1 and out["sources_added"] == 1


def test_import_state_seeds_earlier_results(fresh_db):
    from radar.db import session_scope

    probed = {"recruitee": {"a": {"status": "ok", "nl": 2}, "b": {"status": "not_found"}}}
    sponsors = {"33333333": {"name": "X", "domain": "x.nl"}, "44444444": {"name": "Y", "domain": None}}
    with session_scope() as s:
        assert weekly.import_state(s, probed, sponsors, datetime(2026, 9, 29)) == 4
    with session_scope() as s:
        assert weekly.import_state(s, probed, sponsors, datetime(2026, 9, 29)) == 0  # idempotent
