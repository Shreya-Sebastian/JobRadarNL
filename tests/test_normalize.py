from datetime import datetime

from radar.adapters.base import RawPosting, html_to_text, parse_dt
from radar.normalize import dedup_key, detect_city, detect_country, is_remote, norm_title, normalize


def test_detect_city_variants():
    assert detect_city("Amsterdam, Netherlands") == "Amsterdam"
    assert detect_city("Veldhoven") == "Eindhoven"
    assert detect_city("Den Haag") == "The Hague"
    assert detect_city("'s-Hertogenbosch, NL") == "'s-Hertogenbosch"
    assert detect_city("Berlin, Germany") is None


def test_detect_country():
    assert detect_country("Utrecht, the Netherlands", None) == "NL"
    assert detect_country("Remote - Netherlands", None) == "NL"
    assert detect_country("Berlin", None) == "XX"
    assert detect_country("Somewhere", None) is None
    assert detect_country("Berlin", "nl") == "NL"


def test_remote_and_title_normalisation():
    assert is_remote("Remote (NL)", None)
    assert not is_remote("Amsterdam", None)
    assert norm_title("Senior Backend Engineer (m/f/d) - Python") == "senior backend engineer python"
    assert dedup_key("Adyen B.V.", "Backend Engineer", "Amsterdam") == dedup_key("Adyen", "backend engineer",
                                                                                 "amsterdam")


def test_html_to_text_handles_escaped_greenhouse_content():
    escaped = "&lt;p&gt;We use &lt;strong&gt;Python&lt;/strong&gt; and Kubernetes.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;AWS&lt;/li&gt;&lt;/ul&gt;"
    text = html_to_text(escaped)
    assert "Python and Kubernetes." in text
    assert "AWS" in text
    assert "<" not in text


def test_parse_dt_epoch_and_iso():
    assert parse_dt(1700000000000) == datetime(2023, 11, 14, 22, 13, 20)
    assert parse_dt("2026-09-01T10:00:00Z").year == 2026
    assert parse_dt(None) is None
    assert parse_dt("not a date") is None


def test_city_from_text_fallback():
    from radar.normalize import city_from_text

    assert city_from_text("Data Engineer Utrecht", "") == "Utrecht"
    assert city_from_text("Data Engineer", "Standplaats: Eindhoven. Je werkt aan ...") == "Eindhoven"
    assert city_from_text("Data Engineer", "You will be based in our Amsterdam office.") == "Amsterdam"
    assert city_from_text("Data Engineer", "We are a company in Delft building robots.") == "Delft"
    assert city_from_text("Data Engineer", "No place named here.") is None
    raw = RawPosting(external_id="1", title="Developer", url="https://x/1", location="Netherlands",
                     description_text="Werklocatie: Groningen")
    assert normalize(raw, "Acme")["city"] == "Groningen"
    remote = RawPosting(external_id="2", title="Developer", url="https://x/2", location="Remote, Netherlands",
                        description_text="Our HQ is in Amsterdam")
    assert normalize(remote, "Acme")["city"] is None  # remote postings stay remote
    unknown_town = RawPosting(external_id="3", title="Developer", url="https://x/3",
                              location="Heerhugowaard, Noord-Holland, Nederland",
                              description_text="Our other office in Eindhoven is nice too.")
    assert normalize(unknown_town, "Acme")["city"] == "Heerhugowaard"  # the board's own town wins over text
    from radar.normalize import plausible_place

    assert plausible_place("Alphen aan den Rijn, Zuid-Holland, Nederland") == "Alphen aan den Rijn"
    assert plausible_place("2 Locations") is None and plausible_place("Netherlands") is None
    assert plausible_place("Remote - NL") is None and plausible_place("harderwijk") == "Harderwijk"


def test_normalize_builds_fields():
    raw = RawPosting(external_id="1", title=" Data Engineer ", url="https://x/y",
                     location="Rotterdam, NL", description_html="<p>SQL and Spark</p>")
    f = normalize(raw, "Acme BV")
    assert f["company"] == "Acme"
    assert f["city"] == "Rotterdam"
    assert f["country"] == "NL"
    assert f["title"] == "Data Engineer"
    assert "SQL and Spark" in f["description"]
    assert len(f["content_hash"]) == 64


def test_scrub_contact_removes_emails_and_dutch_phones_but_keeps_numbers_we_need():
    from radar.normalize import scrub_contact

    text = ("Questions? Mail jan.de.vries+jobs@example-corp.nl or call +31 (0)6 12 34 56 78, 06-12345678 or "
            "020 123 4567. Salary EUR 4.500 - 6.000 per month, 3-5 years experience, start 01-02-2027, "
            "founded in 2010, 40 hours, postcode 1012 AB, KvK 12345678.")
    out = scrub_contact(text)
    assert "@" not in out and "12 34 56 78" not in out and "06-12345678" not in out and "020 123 4567" not in out
    for keep in ("4.500 - 6.000", "3-5 years", "01-02-2027", "2010", "40 hours", "1012 AB", "KvK 12345678"):
        assert keep in out, keep
    assert out.count("[e-mail]") == 1 and out.count("[telefoon]") == 3
