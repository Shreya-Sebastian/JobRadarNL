"""Rule-based extractor v1. Cheap, deterministic, and the baseline the LLM extractor must beat on the golden set."""

from __future__ import annotations

import re

from radar.extract.schema import Extraction
from radar.taxonomy import find_skills

RULES_VERSION = "rules-v11"  # bump whenever the taxonomy or the rules change, so `radar extract` re-runs

_NL_WORDS = re.compile(
    r"\b(de|het|een|en|van|voor|met|je|jij|wij|bij|niet|zijn|werken|ervaring|functie|wat|jouw|onze|ook|"
    r"als|dat|naar|over|kunnen|wordt|vacature|collega|team|bieden|sollicit\w*)\b",
    re.I,
)
_EN_WORDS = re.compile(
    r"\b(the|and|you|with|for|our|we|experience|will|are|is|to|of|in|that|this|your|team|role|skills|"
    r"working|have|as|be|on|or|about|who)\b",
    re.I,
)
_DUTCH_REQ = re.compile(
    r"(fluent(?:ly)?|fluency|proficien\w*|native|excellent|good|strong|professional|business)\W{0,20}(in\s+)?"
    r"(dutch|nederlands)|(dutch|nederlands)\W{0,25}(is\s+)?(required|mandatory|a must|must|essential|"
    r"necessary|needed|vereist|verplicht|noodzakelijk)|"
    r"(speak|spreek|beheers\w*)\W{0,30}(dutch|nederlands)|(dutch|nederlands)\s+(and|en)\s+(english|engels)|"
    r"(dutch|nederlands)[- ]speaking|(?:read|write|speak)\W{0,40}fluently in (dutch|nederlands)",
    re.I,
)
_DUTCH_NOT_REQ = re.compile(
    r"dutch\W{0,20}(is\s+)?(not|isn't|is not)\s+(required|necessary|needed|a must)|no dutch (required|needed)|"
    r"english[- ]speaking (environment|company|team)|english is (our|the) (working|company|official) language|"
    r"(nice[- ]to[- ]have|bonus|preferred|a plus|advantage|pre\b)\W{0,40}(fluen\w*\W{0,10})?(in\s+)?(dutch|nederlands)|"
    r"(dutch|nederlands)\W{0,15}(is|would be)\s+(a|an)\s+(plus|bonus|advantage|pre\b)",
    re.I,
)
_ENGLISH_REQ = re.compile(
    r"(fluent(?:ly)?|fluency|proficien\w*|native|excellent|good|strong|professional|business|vloeiend\w*|"
    r"uitstekend\w*|goede?)\W{0,20}(in\s+|kennis van\s+|beheersing van\s+)?(the\s+|de\s+)?(english|engels\w*)|"
    r"(english|engels)\W{0,25}(is\s+)?(required|mandatory|a must|must|essential|necessary|needed|vereist|"
    r"verplicht|noodzakelijk)|"
    r"(speak|spreek|beheers\w*)\W{0,30}(english|engels)|"
    r"(dutch|nederlands)\s+(and|en)\s+(english|engels)|(english|engels)\s+(and|en)\s+(dutch|nederlands)|"
    r"engelse taal|english[- ]speaking|working language is english|voertaal is engels|"
    r"(communicat\w*|communiceren|schrijven|writing)\W{0,30}(in\s+)?(het\s+)?(english|engels)",
    re.I,
)
_ENGLISH_NOT_REQ = re.compile(
    r"(nice[- ]to[- ]have|bonus|preferred|a plus|advantage|\bpre\b|pluspunt)\W{0,40}(in\s+)?(english|engels)|"
    r"(english|engels)\W{0,15}(is|would be|is een)\s+(a|an|een)?\s*(plus|bonus|advantage|pre\b|pluspunt)",
    re.I,
)
_VISA = re.compile(
    r"visa sponsorship|sponsor(?:ship)? (?:a |your )?(?:work )?visa|"
    r"relocation (?:package|support|assistance|budget|team|help|bonus|allowance)|"
    r"help(?:s|ing)? you (?:to )?relocate|assist\w* (?:you )?(?:with|in) (?:your )?(?:relocation|moving)|"
    r"30% ruling|30%-ruling|highly skilled migrant|kennismigrant|we (?:can )?sponsor|sponsor(?:ing)? work permits?|"
    r"immigration support|verhuisvergoeding|verhuiskosten",
    re.I,
)
_NO_VISA = re.compile(
    r"(no|not|unable to|cannot|can't|do not|don't|will not|won't)\W{0,25}(offer\w*|provid\w*|sponsor\w*)\W{0,25}"
    r"(visa|sponsorship|relocation)|"
    # object-first phrasing: "relocation support is not offered", "visa sponsorship is not available"
    r"(visa|sponsorship|relocation)(?:\s+\w+){0,2}\s+(?:is|are|will be)\s+(?:not|un)\w*\s*(?:offered|provided|"
    r"available|possible|supported|included)|"
    r"must (?:already )?(?:have|hold|be) (?:the )?(?:right|eligib|authoris|authoriz)\w* to work|"
    r"(?:eu|european union) (?:citizen|passport|work permit) (?:is )?(?:required|only)|"
    r"without\W{0,25}(?:requiring\s+|needing\s+)?(?:a\s+)?(?:visa\s+)?(?:sponsorship|work permit)|"
    r"(?:do not|don't|does not|doesn't) (?:require|need) (?:a )?(?:visa|sponsorship|work permit)|"
    r"already (?:based|living|located) in the netherlands|"
    # Dutch: "wij bieden geen visa sponsorship", "geen relocatie"
    r"geen\W{0,15}(?:visa|sponsorship|relocat\w*|verhuis\w*)|(?:visa|sponsorship)\W{0,15}(?:is|wordt) niet",
    re.I,
)
_YEARS = re.compile(
    r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|een|één|twee|drie|vier|vijf|zes|"
    r"zeven|acht|negen|tien)\s*(?:\+|[-–—]\s*\d{1,2}|to \d{1,2}|tot \d{1,2}|or more)?\s*(?:years?|yrs?|jaar)\b", re.I
)
_YEARS_CONTEXT = re.compile(
    r"experience|ervaring|track record|professional|working|relevant|hands[- ]on|in a similar|"
    r"background|expertise|werkervaring|"
    # "5+ years in AML", "3+ years as a Sales Engineer", "4+ years leading teams"
    r"^\s*(?:of|in|as|with|leading|building|developing|managing|designing|delivering|running|als|met|in de)\b",
    re.I,
)
_YEARS_NOT = re.compile(
    r"contract|overeenkomst|dienstverband|fixed[- ]term|duur|warranty|after|na |every|elke|per |"
    r"old|oud|guarantee|program|programme|traineeship|founded|opgericht|ago|geleden|history|"
    r"vacation|holiday|verlof|bonus|salary|salaris|budget|lease|tenure at",
    re.I,
)


def find_years(text: str) -> int | None:
    """Minimum years of experience asked for, or None. Requires experience wording nearby and rejects
    contract durations, benefits ("after 2 years"), company history and the like."""
    for m in _YEARS.finditer(text or ""):
        before = text[max(0, m.start() - 40) : m.start()]
        after = text[m.end() : m.end() + 60]
        if _YEARS_NOT.search(before[-25:]) or _YEARS_NOT.search(after[:25]):
            continue
        if _YEARS_CONTEXT.search(after) or _YEARS_CONTEXT.search(before):
            raw = m.group(1).lower()
            years = int(raw) if raw.isdigit() else _NUMBER_WORDS.get(raw, 0)
            if 0 < years <= 20:
                return years
    return None


_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                 "ten": 10, "twelve": 12, "fifteen": 15, "een": 1, "één": 1, "twee": 2, "drie": 3, "vier": 4,
                 "vijf": 5, "zes": 6, "zeven": 7, "acht": 8, "negen": 9, "tien": 10}


_SALARY = re.compile(
    r"(?:€|eur|euro)\s?(\d{1,3}(?:[.,]\d{3})+|\d{2,3}k|\d{4,6})(?:\s?(?:-|–|to|tot|and)\s?(?:€|eur)?\s?"
    r"(\d{1,3}(?:[.,]\d{3})+|\d{2,3}k|\d{4,6}))?",
    re.I,
)
_NICE_SPLIT = re.compile(
    r"(nice[- ]to[- ]have|bonus points?|preferred qualifications|it'?s a plus|would be a plus|pluspunt|"
    r"pre\b|is een pre|extra points|good to have|desirable|ideally you|we'?d love it if)",
    re.I,
)
_BENEFITS_SPLIT = re.compile(
    r"\n\s*(what we offer|we offer|benefits|what'?s in it for you|wat wij bieden|wij bieden|our offer|"
    r"perks|compensation|about us|who we are(?! looking)|over ons)\b",
    re.I,
)

_ENROL_REQ = re.compile(
    r"\benrol{1,2}(?:ed|ment|ing)?\b[^.\n]{0,60}?(?:universit|hogeschool|hbo|\bwo\b|mbo|educational|education system|"
    r"study program|studie|opleiding|bachelor|master|programme|program\b|institution|school)|"
    r"(?:mandatory|required|must be|need to be|have to be)[^.\n]{0,20}enrol|"
    r"ingeschreven[^.\n]{0,40}(?:opleiding|onderwijsinstelling|universiteit|hogeschool|hbo|\bwo\b|mbo|studie)|"
    r"inschrijving bij een (?:erkende )?(?:opleiding|onderwijsinstelling|universiteit|hogeschool)|"
    r"je (?:volgt|doet) (?:momenteel )?een (?:hbo|wo|mbo|master|bachelor|universitaire|relevante)[- ]?"
    r"(?:opleiding|studie)?|"
    r"je studeert\b|je bent (?:een )?(?:hbo|wo|mbo|master|bachelor|universitair)[- ]?student|"
    r"(?:you are|you're|currently|must be|need to be|are) (?:a |an )?(?:currently )?(?:full[- ]time )?"
    r"(?:bachelor|master|hbo|wo|mbo|phd|university|graduate)?['\u2019]?s? ?student\b|"
    r"student (?:at|of|in) (?:a |an )?(?:dutch |eu |recognised |accredited )?(?:university|hogeschool|hbo|"
    r"bachelor|master|educational)|"
    r"(?:pursuing|following|completing) (?:a|an|your) (?:bachelor|master|degree|studies|hbo|wo)|"
    r"(?:bachelor|master)['\u2019]?s? student|working student|werkstudent|"
    r"afstudeer\w*|graduation (?:internship|project|assignment)|thesis (?:internship|project)|"
    r"(?:only|solely) (?:open )?(?:for|to) students|alleen (?:voor )?studenten",
    re.I,
)
_ENROL_NOT = re.compile(
    r"(?:no|not|without)\W{0,20}(?:need to be |required to be |have to be |necessary to be )?enrol|"
    r"enrol\w*\W{0,10}(?:is |are )?not (?:required|necessary|needed|mandatory)|"
    r"(?:recent |new |fresh )?graduates? (?:are |is )?(?:also |equally |very )?welcome|"
    r"(?:also |equally )?open (?:to|for) (?:recent |new )?graduates|"
    r"also (?:suitable |possible )?for (?:recent )?graduates|"
    r"(?:ook |ook geschikt )?voor (?:pas |recent )?afgestudeerden|afgestudeerd\w* (?:zijn |is )?(?:ook )?welkom|"
    r"geen inschrijving (?:vereist|nodig|noodzakelijk)|hoef\w* (?:je )?niet (?:meer )?ingeschreven|"
    r"not (?:required|necessary) to be a student|non-students?|niet[- ]studenten|"
    r"(?<!geen )(?<!no )(?:werkervaringsplek|work experience placement)",  # not "geen werkervaringsplek"
    re.I,
)


def detect_enrollment(text: str) -> bool | None:
    """Does an internship require being enrolled as a student? None when the posting does not say."""
    if _ENROL_NOT.search(text or ""):
        return False
    if _ENROL_REQ.search(text or ""):
        return True
    return None


_SENIORITY = [
    ("intern", r"\bintern(ship)?\b|\bstage\b|\bstagiair|working student|werkstudent|afstudeer"),
    ("trainee", r"\btrainee(ship)?s?\b|traineeprogramma|graduate (programme|program|scheme)|young professional|"
                r"talent ?programm?a?\b|development program(me)?\b|starters?functie|starters?programma|"
                r"\bstarter\b(?! kit)"),
    ("junior", r"\bjunior\b|\bgraduate\b|entry[- ]level|\bstarter\b|early career|\bassociate\b(?!\s*director)"),
    ("staff", r"\bstaff\b|\bprincipal\b|\bdistinguished\b|\bfellow\b"),
    (
        "manager",
        r"(?<!product )(?<!project )(?<!account )(?<!program )\bmanager\b|\bhead of\b|\bdirector\b|\bvp\b|"
        r"\bchief\b|\bcto\b",
    ),
    ("lead", r"\blead\b|\btech ?lead\b|\bteam ?lead\b|\bteamleider\b|\barchitect\b"),
    ("senior", r"\bsenior\b|\bsr\.?\b"),
    ("medior", r"\bmedior\b|\bmid[- ]level\b|\bintermediate\b"),
]
_ROLE = [
    ("product", r"product (owner|manager)|scrum master|agile coach|project manager|delivery manager"),
    (
        "it_support",
        r"support (engineer|specialist|analyst)|technical support|helpdesk|service desk|"
        r"system administrator|systeembeheer|werkplek|\bict\b|it (engineer|support|specialist)",
    ),
    (
        "ml",
        r"machine learning|\bml\b|\bai\b|deep learning|computer vision|\bnlp\b|llm|data scientist|"
        r"research (scientist|engineer)|applied scientist",
    ),
    (
        "simulation",
        r"simulat|\bcfd\b|computational|numerical model|finite[- ]element|\bfea\b|multiphysics|digital twin|"
        r"modell?ing (?:engineer|scientist|specialist)",
    ),
    ("data", r"\bdata\b|analytics|\bbi\b|business intelligence|analist|analyst"),
    ("security", r"security|cyber|\bsoc\b|penetration|\biam\b|\bgrc\b"),
    (
        "platform",
        r"devops|\bsre\b|site reliability|platform|infrastructure|\bcloud\b|kubernetes|"
        r"systems? engineer|network engineer|linux|\bdba\b|database administrator",
    ),
    ("embedded", r"embedded|firmware|\bfpga\b|hardware|electronics|\basic\b|\brtl\b|\bsoc design\b|"
                 r"\bic design|\brf\b|microwave|photonic|analog design"),
    ("mobile", r"\bios\b|android|mobile|flutter|react native"),
    ("qa", r"\bqa\b|\btest\b|tester|quality assurance|test automation"),
    ("frontend", r"front[- ]?end|\bui\b engineer|react|angular|vue|web developer"),
    ("fullstack", r"full[- ]?stack"),
    (
        "backend",
        r"back[- ]?end|software (engineer|developer)|developer|engineer|ontwikkelaar|programm|"
        r"python|java|\.net|golang|scala|kotlin|c\+\+|\bapi\b",
    ),
    ("design", r"\bux\b|\bui\b|designer|user experience"),
]
_SENIORITY_RX = [(k, re.compile(rx, re.I)) for k, rx in _SENIORITY]
_ROLE_RX = [(k, re.compile(rx, re.I)) for k, rx in _ROLE]
_REMOTE = re.compile(r"\bfully remote\b|\bremote[- ]first\b|\b100% remote\b|work from anywhere", re.I)
_HYBRID = re.compile(
    r"\bhybrid\b|days? (?:a|per) week (?:in|at) the office|\d\s*days? (?:in the )?office|"
    r"from home|thuiswerk",
    re.I,
)
_ONSITE = re.compile(
    r"\bon[- ]site\b|\bonsite\b|in the office 5|fully in[- ]office|office[- ]first|"
    r"(?:do not|don't|no) (?:offer )?remote(?:-only)?|remote(?:-only)? (?:work )?is not (?:possible|an option)",
    re.I,
)
_DEGREE = [
    ("phd", r"\bph\.?d\b|doctorate|doctoral"),
    ("msc", r"\bmsc\b|\bm\.sc\b|master(?:'s|s)? (?:degree|in |of science)|\bwo\b|university degree|universitair"),
    ("bsc", r"\bbsc\b|\bb\.sc\b|bachelor|\bbs\b (?:\(or higher\) )?in"),
    ("hbo", r"\bhbo\b"),
    ("mbo", r"\bmbo\b"),
]
_DEGREE_RX = [(k, re.compile(rx, re.I)) for k, rx in _DEGREE]
_DEGREE_LEVEL = {"mbo": 0, "hbo": 1, "bsc": 1, "msc": 2, "phd": 3}  # hbo is a bachelor's level
_NO_DEGREE = re.compile(
    r"(no|without a?|regardless of) (?:formal )?(?:degree|diploma)|degree (?:is )?not required", re.I
)


def detect_language(text: str) -> str:
    nl = len(_NL_WORDS.findall(text))
    en = len(_EN_WORDS.findall(text))
    if nl == 0 and en == 0:
        return "other"
    return "nl" if nl > en * 1.2 else "en"


def detect_seniority(title: str, text: str = "") -> str:
    for key, rx in _SENIORITY_RX:
        if rx.search(title):
            return key
    years = find_years(text)
    if years is not None:
        if years >= 5:
            return "senior"
        if years >= 3:
            return "medior"
        return "junior"
    return "unknown"


def detect_role(title: str) -> str:
    for key, rx in _ROLE_RX:
        if rx.search(title):
            return key
    return "other"


def parse_salary(text: str) -> tuple[int | None, int | None]:
    best: tuple[int | None, int | None] = (None, None)
    for m in _SALARY.finditer(text):
        lo = _to_int(m.group(1))
        hi = _to_int(m.group(2)) if m.group(2) else None
        if lo is None:
            continue
        # monthly salaries: scale to yearly if clearly monthly
        window = text[max(0, m.start() - 60) : m.end() + 60].lower()
        monthly = "month" in window or "maand" in window or "p/m" in window or "per mnd" in window
        if monthly:
            lo *= 12
            hi = hi * 12 if hi else None
        if lo < 20_000 or lo > 400_000:
            continue
        if hi is not None and (hi < lo or hi > 500_000):
            hi = None
        if best[0] is None or (hi is not None and best[1] is None):
            best = (lo, hi)
    return best


def _to_int(s: str | None) -> int | None:
    if not s:
        return None
    s = s.lower().replace(".", "").replace(",", "")
    if s.endswith("k"):
        return int(s[:-1]) * 1000
    try:
        return int(s)
    except ValueError:
        return None


def extract_rules(title: str, description: str) -> Extraction:
    text = description or ""
    lang = detect_language(text) if text else "en"
    core = _BENEFITS_SPLIT.split(text, maxsplit=1)[0] if text else ""
    parts = _NICE_SPLIT.split(core, maxsplit=1)
    required_part = parts[0]
    nice_part = parts[-1] if len(parts) > 1 else ""
    skills_req = find_skills(title + "\n" + required_part)
    skills_nice = [s for s in find_skills(nice_part) if s not in skills_req]

    dutch_required = bool(_DUTCH_REQ.search(text)) and not _DUTCH_NOT_REQ.search(text)
    if lang == "nl" and not _DUTCH_NOT_REQ.search(text):
        dutch_required = True
    visa: bool | None = None
    if _NO_VISA.search(text):
        visa = False
    elif _VISA.search(text):
        visa = True

    # requirements usually sit before the benefits section, but not always: fall back to the whole text
    years = find_years(core)
    if years is None:
        years = find_years(text)
    seniority = detect_seniority(title, text if years is None else f"{years} years of experience")
    if seniority == "unknown":
        # "We are looking for a Senior Information Security Officer ..." in the first lines
        m = re.search(r"\b(senior|junior|medior)\b", text[:300], re.I)
        if m:
            seniority = m.group(1).lower()

    if _REMOTE.search(text):
        remote = "remote"
    elif _HYBRID.search(text):
        remote = "hybrid"
    elif _ONSITE.search(text):
        remote = "onsite"
    else:
        remote = "unknown"

    degree = "unknown"
    if _NO_DEGREE.search(text):
        degree = "none"
    else:
        # the requirement is the lowest level named: "Bachelor's or Master's" asks for a bachelor, and the Dutch
        # "hbo/wo-niveau" (applied or research university) for hbo, not for a master's
        found = [key for key, rx in _DEGREE_RX if rx.search(core)] or [key for key, rx in _DEGREE_RX if rx.search(text)]
        if found:
            low = min(_DEGREE_LEVEL[k] for k in found)
            lowest = [k for k in found if _DEGREE_LEVEL[k] == low]
            degree = "bsc" if "bsc" in lowest else lowest[0]

    lo, hi = parse_salary(text)
    return Extraction(
        role_family=detect_role(title),
        seniority=seniority,
        skills_required=skills_req,
        skills_nice=skills_nice,
        posting_language=lang,
        dutch_required=dutch_required,
        english_only=not dutch_required,
        # written in English means you work in English; a Dutch posting needs English only when it asks for it
        english_required=(lang == "en") or (bool(_ENGLISH_REQ.search(text)) and not _ENGLISH_NOT_REQ.search(text)),
        years_experience=years,
        salary_min_eur=lo,
        salary_max_eur=hi,
        visa_sponsorship=visa,
        remote_policy=remote,
        degree_required=degree,
        enrollment_required=detect_enrollment(text),
    )
