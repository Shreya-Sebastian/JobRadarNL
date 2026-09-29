"""Turn RawPostings into canonical fields: city, country, remote flag, dedup key, content hash."""

from __future__ import annotations

import hashlib
import re

from radar.adapters.base import RawPosting

NL_CITIES: dict[str, str] = {
    # canonical name -> regex alternatives (lowercase). Order matters for "den haag".
    "Amsterdam": r"amsterdam|amstelveen|schiphol|hoofddorp|haarlemmermeer",
    "Rotterdam": r"rotterdam|schiedam|capelle",
    "The Hague": r"den haag|the hague|'s-gravenhage|s-gravenhage|rijswijk|zoetermeer|voorburg",
    "Utrecht": r"utrecht|nieuwegein|houten|zeist|de meern",
    "Eindhoven": r"eindhoven|veldhoven|best\b|son en breugel|waalre|helmond|nuenen|brainport",
    "Delft": r"\bdelft\b",
    "Leiden": r"\bleiden\b|oegstgeest",
    "Groningen": r"groningen",
    "Nijmegen": r"nijmegen",
    "Tilburg": r"tilburg",
    "Breda": r"\bbreda\b",
    "Arnhem": r"arnhem",
    "Haarlem": r"\bhaarlem\b",
    "Hilversum": r"hilversum",
    "Amersfoort": r"amersfoort",
    "Apeldoorn": r"apeldoorn",
    "Enschede": r"enschede|hengelo",
    "Maastricht": r"maastricht",
    "Zwolle": r"zwolle",
    "'s-Hertogenbosch": r"hertogenbosch|den bosch",
    "Almere": r"almere",
    "Deventer": r"deventer",
    "Wageningen": r"wageningen",
    "Alkmaar": r"alkmaar",
    "Leeuwarden": r"leeuwarden",
    "Venlo": r"\bvenlo\b",
    "Dordrecht": r"dordrecht",
    "Gouda": r"\bgouda\b",
    "Ede": r"\bede\b",
    "Veenendaal": r"veenendaal",
    "Emmen": r"\bemmen\b",
    "Roermond": r"roermond",
    "Heerlen": r"heerlen",
    "Sittard": r"sittard|geleen",
    "Assen": r"\bassen\b",
    "Lelystad": r"lelystad",
    "Middelburg": r"middelburg",
    "Weert": r"\bweert\b",
    "Oss": r"\boss\b",
    "Nieuw-Vennep": r"nieuw-vennep",
    "Woerden": r"woerden",
    "Barneveld": r"barneveld",
    "Culemborg": r"culemborg",
    "Naarden": r"naarden",
    "Bussum": r"bussum",
}
_CITY_RX = {city: re.compile(rx, re.I) for city, rx in NL_CITIES.items()}
_NL_RX = re.compile(r"netherlands|nederland|\bnl\b|holland", re.I)
_REMOTE_RX = re.compile(r"\bremote\b|work from home|thuiswerken|anywhere", re.I)
_OTHER_COUNTRY_RX = re.compile(
    r"\b(germany|deutschland|berlin|munich|münchen|hamburg|france|paris|belgium|belgi[eë]|brussels|bruxelles|"
    r"antwerp|united kingdom|\buk\b|london|manchester|spain|madrid|barcelona|portugal|lisbon|lisboa|poland|warsaw|"
    r"krak[oó]w|italy|milan|ireland|dublin|sweden|stockholm|denmark|copenhagen|norway|oslo|finland|helsinki|"
    r"switzerland|zurich|z[üu]rich|austria|vienna|wien|usa|united states|new york|san francisco|seattle|austin|"
    r"boston|chicago|canada|toronto|vancouver|india|bangalore|bengaluru|hyderabad|pune|singapore|australia|sydney|"
    r"brazil|s[ãa]o paulo|mexico|japan|tokyo|china|shanghai|beijing|hong kong|dubai|israel|tel aviv|romania|"
    r"bucharest|czech|prague|hungary|budapest|greece|athens|turkey|istanbul|ukraine|kyiv|lithuania|vilnius|"
    r"latvia|riga|estonia|tallinn|serbia|belgrade|bulgaria|sofia|croatia|zagreb|slovakia|bratislava|slovenia|"
    r"ljubljana|luxembourg|malta|cyprus|philippines|manila|vietnam|indonesia|jakarta|malaysia|kuala lumpur|"
    r"thailand|bangkok|south africa|nigeria|kenya|egypt|argentina|colombia|chile|peru|new zealand|auckland)\b",
    re.I,
)


def detect_city(location: str | None) -> str | None:
    if not location:
        return None
    for city, rx in _CITY_RX.items():
        if rx.search(location):
            return city
    return None


_CITY_HINT = re.compile(
    r"(?:standplaats|werklocatie|locatie|location|based in|office in|kantoor in|gevestigd in|located in|"
    r"vestiging|onze locatie|our office|werken in|working in|work in)\W{0,25}([A-Z][\w' -]{2,30})",
    re.I,
)


_GENERIC_LOCATION = re.compile(
    r"^[\s,;()-]*(the\s+)?(netherlands|nederland|holland|nl|remote|hybrid|thuis\w*)?[\s,;()-]*$", re.I
)


def is_generic_location(location: str | None) -> bool:
    """True when the board names no specific place ("Netherlands", "NL", empty). A town we do not recognise
    (Heerhugowaard) is still a specific place: guessing a city from the text would be wrong."""
    return not location or bool(_GENERIC_LOCATION.match(location.strip()))


_NOT_A_PLACE = re.compile(
    r"\d|locations?$|remote|hybrid|netherlands|nederland|holland|europe|benelux|^nl$|office|"
    r"kantoor|thuis|home|multiple|various|diverse|flexible|anywhere",
    re.I,
)


def plausible_place(value: str | None) -> str | None:
    """The board's own city text when it looks like a place name we simply do not have in the canonical list
    (Harderwijk, Veghel, Zaandam). Returned title-cased, or None."""
    if not value:
        return None
    v = re.split(r"[,;(/|]", value)[0].strip(" -")
    if not 2 <= len(v) <= 40 or _NOT_A_PLACE.search(v) or not re.fullmatch(r"[A-Za-zÀ-ÿ' .-]+", v):
        return None
    words = v.split()
    return " ".join(
        w if w.lower() in ("aan", "de", "den", "der", "het", "op", "ter", "van", "en") else w[:1].upper() + w[1:]
        for w in words
    )


def city_from_text(title: str | None, description: str | None) -> str | None:
    """Fallback when the board gives no city: the title ("Data Engineer Utrecht"), then an explicit location
    phrase in the text ("standplaats Eindhoven", "based in Amsterdam"), then any Dutch city in the opening."""
    if title:
        found = detect_city(title)
        if found:
            return found
    text = description or ""
    for m in _CITY_HINT.finditer(text[:6000]):
        found = detect_city(m.group(1))
        if found:
            return found
    return detect_city(text[:600])


def detect_country(location: str | None, country: str | None) -> str | None:
    """Return 'NL' if the posting is in the Netherlands, 'XX' for another country, None if unknown."""
    if country:
        return country.upper()
    if not location:
        return None
    if detect_city(location) or _NL_RX.search(location):
        return "NL"
    if _OTHER_COUNTRY_RX.search(location):
        return "XX"
    return None


def is_remote(location: str | None, remote_flag: bool | None) -> bool:
    if remote_flag:
        return True
    return bool(location and _REMOTE_RX.search(location))


_EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Dutch numbers: +31 6 12 34 56 78, +31 (0)20 123 4567, 0031..., 06-12345678, 020 1234567. A leading 0 or +31 and
# 9-10 digits in total with optional spaces, dashes, dots or a "(0)"; dates like 01-02-2024 have too few digits.
_PHONE_RX = re.compile(r"(?:\+31|0031|\b0)[\s\-.]?(?:\(0\)[\s\-.]?)?\d(?:[\s\-.]?\d){7,9}\b")


def scrub_contact(text: str) -> str:
    """Remove recruiters' e-mail addresses and phone numbers from posting text before it is stored.
    They are personal data we never display or use, so we do not keep them (GDPR data minimisation)."""
    if not text:
        return text
    text = _EMAIL_RX.sub("[e-mail]", text)
    return _PHONE_RX.sub("[telefoon]", text)


def norm_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)  # drop parentheticals such as "(m/f/d)" or "(Remote)"
    t = re.sub(r"\b(m/f/d|m/v/x|f/m/x|w/m/d|m/w/d|h/f|m/f|m/v)\b", " ", t)
    t = re.sub(r"[^a-z0-9+#.]+", " ", t)
    return " ".join(t.split())


def norm_company(company: str) -> str:
    c = company.strip()
    c = re.sub(r"\s+(b\.?v\.?|n\.?v\.?|inc\.?|ltd\.?|gmbh|holding)$", "", c, flags=re.I)
    return c.strip()


def dedup_key(company: str, title: str, city: str | None) -> str:
    key = f"{norm_company(company).lower()}|{norm_title(title)}|{(city or '').lower()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def content_hash(title: str, text: str) -> str:
    return hashlib.sha256((title.strip() + "\n" + text.strip()).encode("utf-8")).hexdigest()


def _valid_through(raw: RawPosting):
    """schema.org validThrough as a naive UTC datetime, when the source gives one."""
    value = (raw.raw or {}).get("valid_through")
    if not value:
        return None
    from radar.adapters.base import parse_dt

    try:
        dt = parse_dt(value)
    except Exception:
        return None
    if dt is not None and dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def normalize(raw: RawPosting, company: str) -> dict:
    text = scrub_contact(raw.text())
    city = raw.city if raw.city in NL_CITIES else detect_city(raw.location) or detect_city(raw.city)
    country = detect_country(raw.location, raw.country)
    if city and not country:
        country = "NL"
    remote = is_remote(raw.location, raw.remote)
    if city is None and country == "NL" and not remote:
        # a town outside the canonical list: trust the board's city field, then the first part of the location
        city = plausible_place(raw.city) or plausible_place(raw.location)
    if city is None and country == "NL" and not remote and is_generic_location(raw.location):
        city = city_from_text(raw.title, text)
    if remote and country is None and raw.location and _NL_RX.search(raw.location):
        country = "NL"
    return {
        "external_id": raw.external_id,
        "title": raw.title.strip()[:500],
        "company": norm_company(company)[:200],
        "location_raw": (raw.location or "")[:500] or None,
        "city": city,
        "country": country,
        "remote": remote,
        "url": raw.url[:1000],
        "description": text,
        "posted_at": raw.posted_at,
        "valid_through": _valid_through(raw),
        "content_hash": content_hash(raw.title, text),
        "dedup_key": dedup_key(company, raw.title, city),
    }
