import httpx
import respx

from radar.sponsors import clean_name, domain_candidates, name_key, tokens, verify


def test_name_cleaning_and_candidates():
    assert clean_name('""AAE"" Advanced Automated Equipment B.V.') == "AAE Advanced Automated Equipment"
    assert clean_name("Adyen N.V.") == "Adyen"
    assert clean_name("Booking.com B.V.") == "Booking com"
    assert name_key("Tata Consultancy Services Netherlands B.V.") == "tataconsultancyservices"
    assert "adyen.nl" in domain_candidates("Adyen N.V.") and "adyen.com" in domain_candidates("Adyen N.V.")
    assert "advanced" not in tokens("10X Genomics B.V.") and "genomics" in tokens("10X Genomics B.V.")


@respx.mock
def test_verify_accepts_matching_title_and_rejects_parked_and_namesakes():
    html = {"content-type": "text/html"}
    respx.get("https://www.acmerobotics.nl").mock(return_value=httpx.Response(
        200, text="<html><title>Acme Robotics | Industrial automation</title></html>", headers=html))
    respx.get("https://www.parked.nl").mock(return_value=httpx.Response(
        200, text="<html><title>parked.nl is for sale</title><p>This domain is for sale</p></html>", headers=html))
    respx.get("https://www.delta.com").mock(return_value=httpx.Response(
        200, text="<html><title>Delta Air Lines | Flights</title></html>", headers=html))
    c = httpx.Client()
    assert verify("Acme Robotics B.V.", "acmerobotics.nl", c) == "www.acmerobotics.nl"
    assert verify("Parked Solutions B.V.", "parked.nl", c) is None
    assert verify("Delta Precision Engineering B.V.", "delta.com", c) is None  # shares no distinctive word
