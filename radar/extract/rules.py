"""Rule-based extractor v1. Cheap, deterministic, and the baseline the LLM extractor must beat on the golden set."""

from __future__ import annotations

import math
import re

from radar.extract.schema import Extraction
from radar.extract.sections import job_text
from radar.taxonomy import find_skills

RULES_VERSION = "rules-v16"  # bump whenever the taxonomy or the rules change, so `radar extract` re-runs

# words only one of the languages uses: "in", "is", "we", "team", "over" and "of" are both Dutch and English,
# "die" and "er" are also German
_NL_WORDS = re.compile(
    r"\b(de|het|een|en|van|voor|met|je|jij|wij|bij|niet|zijn|werken|ervaring|functie|wat|jouw|onze|ook|"
    r"als|dat|naar|kunnen|wordt|vacature|collega|bieden|sollicit\w*|ben|heb|hebt|deze|dit|waar|"
    r"om|te|op|aan|uit|ons|zij|jullie|binnen|werkzaamheden|kennis|vaardigheden)\b",
    re.I,
)
_EN_WORDS = re.compile(
    r"\b(the|and|you|with|for|our|experience|will|are|to|of|that|this|your|role|skills|"
    r"working|have|as|be|on|or|about|who|an|at|from|what|us|can|join|work|their|which|within|strong)\b",
    re.I,
)
_DE_WORDS = re.compile(
    r"\b(und|der|das|mit|für|wir|sie|ist|nicht|auf|eine?|zu|du|dich|dein\w*|unser\w*|oder|bei|sind)\b", re.I)
_DUTCH = r"(?:dutch|nederlands|flemish|vlaams)"
_OTHER_LANG = (r"(?:english|engels|german|duits|french|frans|spanish|spaans|italian|polish|portuguese|mandarin|"
               r"chinese|arabic|turkish|russian|japanese|swedish|danish|norwegian|finnish)")
# what follows "Dutch" when it names the language, not a Dutch company, market, law or university
_LANG_AFTER = (
    r"(?=\s*(?:\(|[,.;:!/|\n•\-–<]|$|and\b|&|en\b|is\b|are\b|as\b|at\b|on\b|op\b|in\b|language|taal|speak|"
    r"skills?|proficien|fluen|native|written|spoken|verbal|both|required|mandatory|essential|a must|must|"
    r"would|preferred|c1\b|c2\b|b1\b|b2\b|level|niveau|communication|vaardig|mondeling|schriftelijk|zowel|"
    r"goed|vloeiend|well\b|to\b|too\b|also\b|oral|for\b))"
)
_BOTH = r"(?:both\s+)?(?:the\s+)?(?:" + _OTHER_LANG + r"(?:\s+language)?\s*(?:and|&|,|/|as well as|en)\s*(?:the\s+)?)?"
_DUTCH_REQ = re.compile(
    # "fluent in Dutch", "fluency in both English and Dutch", "full professional fluency in both Dutch"
    r"(?:fluent(?:ly)?|fluency|proficien\w*|native|mother tongue|vloeiend\w*)\W{0,25}(?:level\s+)?(?:in\s+|of\s+)?"
    + _BOTH + _DUTCH + r"|"
    # "excellent Dutch and English", "good command of the Dutch language", "goede beheersing van het Nederlands"
    r"(?:excellent|good|very good|strong|professional|business|full|perfect|solid|working|written|spoken|"
    r"verbal|advanced|uitstekend\w*|goede?|zeer goede?|prima|perfect\w*|sterke?)\W{0,20}"
    r"(?:(?:command|knowledge|mastery|understanding|proficiency|skills?|beheersing|kennis)\s+(?:of|in|van)\s+)?"
    r"(?:in\s+)?(?:het\s+)?" + _BOTH + r"(?:de\s+)?" + _DUTCH + _LANG_AFTER + r"|"
    # "ability in Dutch is essential", "communication skills in English and Dutch"
    r"(?:command|knowledge|mastery|understanding|abilit(?:y|ies)|skills?|beheersing|kennis)\s+(?:of|in|van)\s+"
    + _BOTH + r"(?:de\s+)?" + _DUTCH + _LANG_AFTER + r"|"
    # "Dutch is required", "Dutch (must)", "Dutch <-must have", "Dutch: fluent", "Dutch (C1)", "Nederlands op C1-niveau"
    + _DUTCH + r"(?:\s+language)?(?:\s+skills)?\W{0,25}(?:is\s+|are\s+)?(?:a\s+)?"
    r"(?:required|mandatory|a must|must|essential|necessary|needed|"
    r"vereist|verplicht|noodzakelijk|requirement|obligatory|een must|een vereiste)|"
    + _DUTCH + r"\s*(?:language\s*)?[:(\-–]\s*(?:fluent|native|c1|c2|b2|mother tongue|vloeiend|moedertaal|"
    r"business|professional|excellent|full|good|goed|uitstekend|minimum|min\.)|"
    + _DUTCH + r"[^.\n]{0,20}?\b(?:c1|c2|b2)\b|\b(?:c1|c2|b2)\b[^.\n]{0,12}?(?:level\s+)?(?:in\s+)?" + _DUTCH + r"|"
    # "you speak Dutch", "je spreekt en schrijft goed Nederlands", "speak, write, and read fluently in Dutch"
    r"(?:speak|spreek\w*|schrijf\w*|beheers\w*|write|read|communicat\w*|communiceer\w*|converse|praat)"
    r"(?:[\s,]+(?:and|en|&|write|read|schrijft|spreekt|fluently|fluent|goed|vloeiend|uitstekend|perfect|"
    r"well|also|both|zowel|in|het|the|english|engels|and/or|native|mondeling|schriftelijk|good|excellent|helder|"
    r"duidelijk|clearly|effectively|effectief|vlot|at|least|minimaal)){0,6}"
    r"\s+" + _DUTCH + _LANG_AFTER + r"|"
    r"(?:conversation|correspondence|documentation|reports?|presentations?|communication)(?:\s+skills)?\s+in\s+"
    + _BOTH + _DUTCH + r"|"
    # "Dutch and English", "English and Dutch", "NL/EN"
    + _DUTCH + r"\s*(?:and|en|&|/|\+)\s*(?:the\s+)?(?:english|engels)|"
    r"(?:english|engels)\s*(?:and|en|&|/|\+|as well as)\s*(?:also\s+)?" + _DUTCH + _LANG_AFTER + r"|"
    r"(?-i:\bNL\s*(?:/|&|\+|and|en)\s*EN\b|\bEN\s*(?:/|&|\+|and|en)\s*NL\b)|"
    # "Dutch-speaking", "Dutch speaker", "Nederlandstalig", "Nederlands is je moedertaal"
    + _DUTCH + r"[- ]speak\w*|nederlandstalig\w*|"
    + _DUTCH + r"(?:\s+[\w-]+){0,2}?\s+(?:proficiency|fluency|skills?)\b|"
    # a sentence that ends in "is (also) required", unless it is about nationality, a degree or a permit
    + _DUTCH + r"(?:(?!(?:or|and/or)\s+" + _OTHER_LANG
    + r"|nationalit|citizen|passport|universit|degree|diploma|residen|bank|security|screening|clearance|"
    r"driv|licen|permit|bsn)[^.;\n]){0,40}?\b(?:is|are)\s+(?:also\s+)?(?:required|mandatory|a must|essential|"
    r"necessary)|"
    + _DUTCH + r"\s+(?:fluent|native)\b|" + _DUTCH + r"[^.\n]{0,25}(?:moedertaal|mother tongue)|"
    r"(?:moedertaal|mother tongue)\W{0,20}(?:is\s+)?" + _DUTCH + r"|"
    r"nederlandse\s+(?:en\s+(?:de\s+)?engelse\s+)?taal|engelse\s+en\s+(?:de\s+)?nederlandse\s+taal|"
    r"nederlands\s+(?:in\s+woord\s+en\s+geschrift|op\s+\w+[- ]?niveau)",
    re.I,
)
# a Dutch requirement is void when its own clause calls it optional: "Dutch is a plus", "fluent Dutch preferred"
_OPTIONAL = re.compile(
    r"nice[- ]to[- ]have|bonus|prefer\w*|\ba plus\b|\bplus\b|pluspunt|advantage\w*|\basset\b|"
    r"beneficial|helpful|desir\w*|welcome|appreciated|\bpre\b|\bpré\b|optional|ideal(?:ly)?|"
    r"not (?:required|mandatory|necessary|needed|a must|a requirement|essential)|useful|"
    r"\b(?:or|of)\s+(?:are\s+|be\s+|you'?re\s+|a\s+)?willing(?:ness)?\s+to\s+learn|"
    r"willing(?:ness)? to learn (?:it|dutch)|"
    r"(?:wilt|bereid)\w*[^.\n]{0,30}(?:te )?leren|would be nice|meerwaarde|valuable|priorit[iy]\w*|"
    r"\bgood to have|optimal",
    re.I,
)
# qualifiers that come before what they qualify: "Nice to have: fluent Dutch", "Preferably Dutch-speaking"
_OPT_BEFORE = re.compile(
    r"nice[- ]to[- ]have|bonus|prefer\w*|ideal(?:ly)?|optional\w*|desir\w*|a plus if|\bplus\s*:|pluspunt|"
    r"pr[eé]\s*(?:als|if|:)|not (?:required|mandatory)|advantage\w*\s*(?:if|:)|would be (?:nice|great)|"
    r"asset\s*:",
    re.I,
)
# a clause that says it is required is not undone by a "nice to have" header further up
_STRONG = re.compile(
    r"required|mandatory|\bmust\b|essential|essentieel|vereist\w*|verplicht|noodzakelijk|necessary|needed|\bnodig\b|"
    r"\beis\b|will not be accepted|only\b",
    re.I,
)
# "Dutch or English", "German or Dutch", "Nederlands of Engels": either language will do
# ("of" is Dutch for "or" only before a Dutch language name: "command of English and Dutch" is not a choice)
_OR_LANG = (r"(?:(?:or|and/or|and/of|/\s*or|en/of)\s+(?:the\s+)?" + _OTHER_LANG
            + r"|of\s+(?:het\s+)?(?:engels|duits|frans|spaans)\b"
            # "Dutch or another European language"
            + r"|(?:or|and/or)\s+(?:any\s+)?(?:an)?other\s+(?:\w+\s+)?languages?\b)")
_ALT_AFTER = re.compile(r"\s*(?:\)\s*)?" + _OR_LANG, re.I)
_ALT_INSIDE = re.compile(r"\b" + _OR_LANG, re.I)
_ALT_BEFORE = re.compile(_OTHER_LANG + r"(?:[- ]speak\w*)?\s*(?:or|of|and/or|en/of)\s+(?:the\s+)?(?:de\s+)?$", re.I)
# list headers: "Nice to have", "Plusses", "Not mandatory, but valuable", "Het is een pré als je:"
_OPT_HEADER = re.compile(
    r"nice[- ]to[- ]have|bonus|plus(?:ses|sen|punten)?\b|prefer\w*|desir\w*|not (?:mandatory|required)|"
    r"\bpr[eé]\b|pluspunt|\bextra\b|good to have|would be great|ideally|advantage|we'?d love|niet verplicht|"
    r"optional|valuable|also nice",
    re.I,
)
_SECTION_HEADER = re.compile(
    r"requirement|qualification|must|what you bring|you bring|you have|about you|who you are|your profile|profile|"
    r"we offer|what we|we ask|looking for|skills|eisen|vereist|wat breng|wie ben|wat vragen|wat wij|jouw profiel|"
    r"functie|responsibil|what you|you will|je gaat|taken|offer|language|talen|taal",
    re.I,
)
_DUTCH_NOT_REQ = re.compile(
    _DUTCH + r"(?:\s+language)?(?:\s+skills)?\W{0,30}(?:is\s+|are\s+)?(?:not|isn'?t|aren'?t|niet|geen)\s+"
    r"(?:a\s+|een\s+)?(?:strict\s+)?(?:required|necessary|needed|a must|mandatory|requirement|essential|vereist|"
    r"nodig|noodzakelijk|verplicht|vereiste|must|eis)|"
    r"no dutch (?:is )?(?:required|needed|necessary)|" + _DUTCH + r"[^.\n]{0,40}\bbut not (?:required|necessary|"
    r"mandatory|a must)|(?:no need|not necessary|not required) to (?:speak|know) "
    + _DUTCH + r"|"
    r"(?:don'?t|do not|doesn'?t|does not|without)\s+(?:need\s+to\s+|having\s+to\s+)?(?:speak|speaking|know|knowing)\s+"
    r"(?:any\s+)?" + _DUTCH + r"|geen nederlands (?:nodig|vereist)|"
    r"(?:not|niet)\s+(?:required|necessary|needed|nodig|vereist)\s+(?:to\s+)?(?:speak\s+|spreken\s+)?" + _DUTCH,
    re.I,
)
# "Dutch is a plus", "Nederlands is een pré": says outright that Dutch is optional
_DUTCH_PLUS = re.compile(
    _DUTCH + r"(?:\s+language)?(?:\s+(?:skills?|proficiency|knowledge))?\W{0,30}(?:is|would be|are|zijn|is een|zou)\s+"
    r"(?:a|an|een)?\s*(?:strong\s+|big\s+|grote?\s+|real\s+)?"
    r"(?:plus|bonus|advantage|pre\b|pr\u00e9|pluspunt|asset|nice to have|useful|helpful|beneficial)|"
    r"(?:nice[- ]to[- ]have|bonus|preferred|preferably|a plus|advantage|\bpre\b|pluspunt)\W{0,40}"
    r"(?:fluen\w*\W{0,10})?(?:in\s+)?" + _DUTCH,
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
_CLAUSE_END = re.compile(r"[.;!?\n•|]|\s-\s|\s–\s")
# a qualifier after another language belongs to that language: "Fluent Dutch and English, German is a plus"
_LANG_NAME = re.compile(r"\b(?:" + _OTHER_LANG[3:-1] + r"|engelse|duitse|franse|spaanse|italiaanse|poolse|"
                        r"other|additional|language|languages|taal|talen)\b", re.I)
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
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                 "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "een": 1, "één": 1, "twee": 2, "drie": 3,
                 "vier": 4, "vijf": 5, "zes": 6, "zeven": 7, "acht": 8, "negen": 9, "tien": 10, "elf": 11,
                 "twaalf": 12, "vijftien": 15, "half": 1, "een half": 1, "a half": 1, "half a": 1, "anderhalf": 2}
_NUM_WORDS = sorted((k for k in _NUMBER_WORDS if " " not in k), key=len, reverse=True)
_NUM = r"(?:\d{1,2}(?:[.,]5)?|" + "|".join(_NUM_WORDS) + ")"
_YEARS = re.compile(
    # optional "6 months to" lead-in (the minimum is then under a year), the number, an optional "(3)" echo,
    # then an optional upper bound or "+": "3-5", "drie tot vijf", "tussen de 3 en 6", "1 or 2", "3 à 4", "5+",
    # "3+ (typically 5+)", and the unit, hyphenated or not ("3-year", "3 jaren")
    # (a digit may follow a letter: "Your profile3-6 years", which the source glued together)
    r"(?<![\d.,])(?:(?=\d)|\b)(\d{1,2}\s*(?:months?|maanden)\s*(?:to|tot|[-–—])\s*)?"
    r"((?:een |a )?half(?: a)?|" + _NUM + r")(?:\s*\(\d{1,2}\+?\))?"
    r"\s*(?:\+|plus|or more|of meer|(?:[-–—]|to|till|until|tot|t/m|à|and|en|or|of)\s*" + _NUM + r"\+?)?"
    r"(?:\s*\([^()]{0,25}\))?[\s-]*(?:years?|yrs?|jaren|jaar)\b",
    re.I,
)
_YEARS_CONTEXT = re.compile(
    r"experience|ervaring|track record|professional|working|relevant|hands[- ]on|in a similar|"
    r"background|expertise|werkervaring|"
    # "5+ years in AML", "3+ years as a Sales Engineer", "4+ years leading teams"
    r"^\s*(?:of|in|as|with|leading|building|developing|managing|designing|delivering|running|als|met|in de)\b",
    re.I,
)
# experience wording: a "not experience" word only counts when no experience wording sits between it and the number,
# so "5 jaar ervaring met contractmanagement" and "program management experience of 3 years" still count
_YEARS_EXP = re.compile(r"experience|ervaring|expertise|track record|background|hands[- ]on|relevant", re.I)
# whole words only: substrings used to reject "Cloud" (oud), "developer " (per), "programming", "duurzaam", "welke"
_YEARS_NOT_AFTER = re.compile(
    r"\b(?:contract(?!\s*manag|beheer)\w*|\w*overeenkomst|dienstverband|fixed[- ]term|looptijd|duration|warranty|"
    r"garantie|guarantee|old(?:er)?|oud(?:er)?|leeftijd|of age|ago|geleden|history|bonus|salary|salaris|vacation|"
    r"verlof|lease|pension|pensioen)\b|"
    # right after the number: "4-year bachelor's degree", "2-year traineeship", "a 4-year position"
    r"^[\s'’-]*(?:\w+[\s'’-]+)?(?:degree|bachelor|master|phd|study|studie|opleiding|programme|program(?!\s*manag)|"
    r"traineeship|trainee|traject|position|positie|aanstelling|appointment|in dienst|in service)\b",
    re.I,
)
_YEARS_NOT_BEFORE = re.compile(
    r"\b(?:contract\w*|\w*overeenkomst|dienstverband|fixed[- ]term|duur|duration|looptijd|warranty|guarantee|after|"
    r"na|every|elke|per|founded|opgericht|since|sinds|history|traineeship|programme|traject|bonus|salary|salaris|"
    r"budget|tenure at|period of|periode van|aanstelling|"
    # company age: "Conclusion is al meer dan twaalf jaar actief", "we have over 20 years of experience"
    r"(?:is|zijn) al|(?:we|wij) (?:have|hebben)|we've)\b|"
    # right before the number: "within three years", "de eerste 2 jaar", "in de afgelopen 3 jaar", "up to 4 years"
    r"(?:\b(?:within|binnen|the first|de eerste|het eerste|next|komende|last|past|afgelopen|laatste|less than|"
    r"fewer than|minder dan|up to|no more than|maximaal|maximum|max|hooguit|aged?)\b|<)\W*$",
    re.I,
)


def _years_value(m: re.Match) -> int:
    if m.group(1):  # "6 months to 3 years": the minimum is under a year
        return 1
    raw = m.group(2).lower()
    if raw[0].isdigit():
        return math.ceil(float(raw.replace(",", ".")))  # "1,5 jaar" counts as more than one year
    return _NUMBER_WORDS.get(raw, 0)


def find_years(text: str) -> int | None:
    """Minimum years of experience asked for, or None. Requires experience wording nearby and rejects
    contract durations, benefits ("after 2 years"), company history, ages, "less than 2 years" and the like."""
    for m in _YEARS.finditer(text or ""):
        before = text[max(0, m.start() - 40) : m.start()]
        after = text[m.end() : m.end() + 60]
        near_before = before[-25:]
        cut = list(_YEARS_EXP.finditer(near_before))
        if cut:
            near_before = near_before[cut[-1].end() :]
        near_after = after[:25]
        cut_a = _YEARS_EXP.search(near_after)
        if cut_a:
            near_after = near_after[: cut_a.start()]
        if _YEARS_NOT_BEFORE.search(near_before) or _YEARS_NOT_AFTER.search(near_after):
            continue
        if _YEARS_CONTEXT.search(after) or _YEARS_CONTEXT.search(before):
            years = _years_value(m)
            if 0 < years < 20:  # "20 years" is nearly always company history, not a requirement
                return years
    return None


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
    r"(?:only|solely) (?:open )?(?:for|to) students|alleen (?:voor )?studenten|"
    # "currently enrolled as a student", "remain enrolled for the duration"
    r"enrol{1,2}ed as (?:a |an )?student|(?:currently|remain|still) enrol{1,2}ed|"
    # "final stage of your master's", "penultimate year of study", "last year of your bachelor"
    r"(?:final|last|penultimate|second|third|fourth) (?:stage|phase|year)s? of (?:your |a |an |the )?"
    r"(?:bachelor|master|msc|bsc|degree|studies|study|studie|program)|"
    r"(?:currently |actively )?studying (?:towards|toward|for) (?:a |an |your )|(?:are|is) currently studying|"
    r"(?:ongoing|current) (?:bachelor|master|msc|bsc|degree|studies|study)|"
    r"(?:msc|bsc|master|bachelor|phd|hbo|wo|mbo)(?:[- ]?\d)?(?:/(?:hbo|wo|mbo))?['\u2019]?s?[- ]stud(?:ents?|enten)\b|"
    r"looking for (?:a |an )?(?:motivated |enthusiastic |talented |curious )?students?\b|\bis a student\b|"
    # Dutch: "je volgt minimaal een MBO-4 opleiding", "laatste jaar van je opleiding", school days during the stage
    r"je volgt (?:minimaal |momenteel |nu |op dit moment )?een [\w/-]*\s?(?:opleiding|studie)|"
    r"(?:laatste|tweede|derde|vierde) jaar van (?:je|jouw) (?:opleiding|studie|bachelor|master)|"
    r"je zit in (?:het )?(?:laatste|tweede|derde|vierde) jaar|naast je [\w/ -]{0,12}studie|"
    r"stageovereenkomst|internship agreement with your (?:university|school)|terugkomdag|schoolopdracht",
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
    r"(?:or|and) (?:have |are )?(?:recently|just|newly) graduated|or (?:a )?recent graduate|\(near-?\)\s?graduates|"
    r"studenten of (?:pas )?afgestudeerden|"
    r"(?<!geen )(?<!no )(?:werkervaringsplek|work experience placement)",  # not "geen werkervaringsplek"
    re.I,
)


# more phrasings found by reading live internships that the patterns above missed
_ENROL_REQ = re.compile(_ENROL_REQ.pattern + "|" + "|".join([
    # "you need to be registered as a student during the entire internship", "be registered at a Dutch university"
    r"registered as (?:a |an )?(?:[\w-]+ )?student|(?:be|are|remain|stay|being|is) registered (?:at|with) (?:a |"
    r"an |the |your )?"
    r"(?:dutch |eu |recogni[sz]ed |accredited )?(?:universit|educational|school|hogeschool|institution|onderwijs)",
    # "Master Thesis student"
    r"thesis students?\b",
    # "We are looking for a highly motivated student" (replaces the fixed adjective list)
    r"looking for (?:a |an )?(?:[\w-]+ ){0,3}students?\b",
    # "Ben je momenteel bezig met een opleiding op HBO/WO niveau", "bezig met de afronding van een HBO- of WO-studie"
    r"bezig met (?:een |je |jouw |de afronding van )[^.\n]{0,40}?(?:opleiding|studie)|je volgt onderwijs",
    # "graduating between September 2027 - July 2028"
    r"graduating (?:between|in|by) (?:[a-z]+ )?20\d\d",
    # "Je volgt momenteel in Nederland een wo-opleiding", "Je volgt op dit moment een relevante voltijd opleiding"
    r"je volgt\b[^.;\n]{0,50}?(?:opleiding|studie)\b",
    # inverted order: "Volg je een mbo-, hbo- of wo-opleiding", "Volg jij een MBO, HBO of WO opleiding", "volg je
    # de Master"
    r"volg (?:je|jij) (?:momenteel |nu |op dit moment |bijvoorbeeld )?(?:een|de) [^.;?\n]{0,40}?(?:opleiding|"
    r"studie|master|bachelor)\b",
    # bullet order: "een mbo-, hbo- of wo-opleiding volgt", "Een hbo- of wo-studie volgt"; "welke opleiding je volgt"
    r"(?:opleiding|studie) volgt\b|(?:welke|wat voor) (?:opleiding|studie) je (?:volgt|doet)",
    # "Ben jij een gedreven (master) student", "Je bent student Bedrijfskunde", "Ben jij derdejaars bachelor- of
    # masterstudent"
    r"(?:je bent|jij bent|ben je|ben jij|bent u) (?:[\w()/-]+ ){0,4}?\w*student(?:e)?\b",
    # "we zoeken een creatieve student", "op zoek naar een gemotiveerde student in het derde jaar"
    r"(?:zoeken|zoekt|op zoek naar) (?:we |wij )?(?:een )?(?:[\w-]+ ){0,4}?student(?:e|en)?\b",
    # compounds: "masterstudent", "derdejaars", "student-stage", "student in het vierde jaar"
    r"\b(?:master|bachelor|rechten|universitaire?)-?student(?:e|en)?\b|\b(?:eerste|tweede|derde|vierde|laatste)jaars\b|"
    r"student-?stag(?:e|iair)|student(?:e|en)? in het (?:eerste|tweede|derde|vierde|laatste) jaar",
    # "Je zit in de laatste fase van je Bachelor", "in de eindfase van een bachelor- of masteropleiding",
    # "in het laatste jaar van een masteropleiding"
    r"(?:laatste|afrondende|eind) ?(?:fase|jaar) van (?:je|jouw|een|de|het|uw) [^.;\n]{0,40}?(?:opleiding|"
    r"studie|bachelor|master|\bwo\b|hbo|mbo)",
    # "Studeert aan HBO Orthopedisch Technologie"
    r"studeert aan\b",
    # thesis: "scriptiestagiair", "schrijven van je master scriptie", "write your master's thesis"
    r"scriptie-?stag\w*|scriptie-?onder(?:zoek|werp)|schrijven van (?:je|jouw) (?:master ?|bachelor ?)?scriptie|"
    r"(?:je|jouw) (?:master ?|bachelor ?)?scriptie (?:te )?schrijven|leidt tot (?:je|jouw) scriptie|"
    r"(?:write|writing|complete|completing) (?:your|a|the) (?:master['\u2019]?s? |bachelor['\u2019]?s? |msc |"
    r"bsc )?thesis",
    # EN "You: Are studying Marketing", "You… are studying at HBO or WO", "Studying at HBO or WO level",
    # "Currently studying a Master's degree"
    r"\byou\W{0,4}(?:are|'re|\u2019re) (?:currently |still )?studying\b|(?:^|\n)\W*(?:are )?(?:currently )?studying\b|"
    r"\bcurrently studying\b|\bstudying (?:at |a |an )(?:dutch |relevant |recogni[sz]ed )?(?:hbo|wo|mbo|"
    r"universit|master|bachelor|"
    r"msc|bsc|degree|hogeschool|college|school)",
    # "You are a 3rd or 4th-year student", "final-year student"
    r"\b(?:1st|2nd|3rd|4th|first|second|third|fourth|final|last)(?:[- ]year)?(?: (?:or|and|/) (?:1st|2nd|3rd|"
    r"4th|first|second|"
    r"third|fourth|final|last))?[- ]year (?:[\w-]+ )?students?\b",
    # "You are currently following a (Dutch) legal/financial MBO/HBO education"
    r"(?:currently|are|you're) following an? [^.\n]{0,40}?(?:education|programme|program|studies|study|degree)\b",
    # "Pursuing a PhD", "pursuing an MSc"
    r"pursuing (?:a |an |your )?(?:phd|msc|bsc|university|master|bachelor)",
    # "The project needs to be part of your MSc program", "a mandatory part of your curriculum"
    r"part of your (?:[\w'\u2019-]+ ){0,3}?(?:curriculum|study|studies|program|programme|degree|education|opleiding)\b",
    # "University education (last year Bachelor or Master degree)"
    r"(?:final|last|penultimate) (?:stage|phase|year)s? (?:of )?(?:your |a |an |the )?(?:bachelor|master|msc|"
    r"bsc|degree)",
    # "while balancing your studies", "alongside your studies"
    r"(?:alongside|next to|besides|while|balanc\w*|combin\w* (?:it )?with) (?:it with )?your stud(?:ies|y)\b",
    # "TNO will arrange an appropriate internship agreement"
    r"internship agreement",
    # German postings: "Du absolvierst derzeit ein Studium", "immatrikuliert", "eingeschrieben"
    r"absolvierst (?:derzeit |aktuell )?ein\w* \w*studium|immatrikuliert|eingeschrieben",
    # an allowance paid per school level: "De stagevergoeding bedraagt voor een mbo-, hbo- of wo stage € 750"
    r"stagevergoeding\b[^.]{0,40}?\b(?:mbo|hbo|wo)\b[^.]{0,25}?\bstage\b",
]), re.I)
_ENROL_NOT = re.compile(_ENROL_NOT.pattern + "|" + "|".join([
    # "If you have recently graduated in Computer Science"
    r"(?:have|having|who|you|you've) (?:recently|just|newly) graduated",
    # "You're a recent graduate", "You are a student or starter", "student of pas afgestudeerde"
    r"(?:are|re|\u2019re|is) (?:a )?(?:recent|new|fresh) graduate|"
    r"(?<![:|] )\bstudent(?:e|en|s)? (?:of|or|en|and|/) (?:een |a )?(?:pas |recent(?:e|ly)? |net |"
    r"new )?(?:afgestudeerde?n?|graduates?|starters?|young professionals?)",
    # "Ben je (bijna) afgestudeerd", "net afgestudeerd"
    r"\((?:bijna|net)\) afgestudeerd|\b(?:net|pas|recent|onlangs) afgestudeerd",
    # "currently in the final stages of a master's, or already holding a master's"
    r"\b(?:or|and/or)\s+(?:you\s+)?(?:are\s+|have\s+)?already\s+(?:hold(?:ing)?|ha(?:ve|ving)|completed|"
    r"obtained|finished|in possession of)\s+(?:a\s+|an\s+|your\s+)?(?:master|bachelor|msc|bsc|degree|diploma)",
]), re.I)
# a title that says thesis, afstudeer or werkstudent is evidence even when the text is empty
_TITLE_REQ = re.compile(
    r"afstudeer|graduation (?:internship|project|assignment)|(?<!non-)(?<!non )thesis|scriptie|werkstudent|"
    r"working student|"
    r"student[- ]?stag|\b(?:mbo|hbo|wo)\b(?:[- ]?\d)?[^\n]{0,40}?stag|stag\w*[^\n]{0,40}?\b(?:mbo|hbo|wo)\b|"
    # a "meewerkstage" or "meeloopstage" is by definition part of a study programme
    r"\bmee(?:werk|loop)stage", re.I)


# titles of student jobs whose level is not "intern": "Onderzoeksstage", "Bijbaan IT", "Internships / Graduation"
_STUDENT_TITLE = re.compile(r"stage|stagiair|intern|bijbaan|werkstudent|working student|student|afstudeer|"
                            r"graduation (?:internship|project|assignment)|thesis", re.I)


def detect_enrollment(text: str, title: str = "") -> bool | None:
    """Does an internship require being enrolled as a student? None when the posting does not say."""
    text = _ODD_SPACES.sub(" ", text or "")
    if _ENROL_NOT.search(text):
        return False
    if _ENROL_REQ.search(text) or _TITLE_REQ.search(title or ""):
        return True
    return None


# functional titles that are individual-contributor jobs, not people management: "Product Manager", "Change Manager"
_IC_MANAGER = ["product", "project", "account", "program", "programme", "marketing", "contract", "vendor", "category",
               "partnership", "community", "relations", "change", "release", "incident", "problem", "configuration",
               "asset", "escalation", "risk", "application", "success", "sales", "development", "growth", "bid", "cost",
               "delivery"]
_NO_LEVEL_WORD = r"^(?!.*\b(?:junior|jr|medior|senior|sr|lead|staff|principal|manager|director|head|chief)\b)"
_LADDER_END = r"(?=\s*(?:$|[,(\-–|/:\[]))"
_SENIORITY = [
    ("intern", r"\binterns?(?:hips?)?\b|\w*(?<!back)(?<!early-)(?<!early )stage(?:s|opdracht\w*|plaats\w*|plek\w*)?\b|"
               # an "advocaat-stagiair" is a trainee lawyer in a three-year training, not an intern
               r"(?<!advocaat-)(?<!advocaat )stagiai?re?|working student|werkstudent|afstudeer|\bthesis\b|scriptie|"
               r"\bgraduation\b|^student\b"),
    ("trainee", r"\btrainee(ship)?s?\b|traineeprogramma|graduate (programme|program|scheme)|young professional|"
                r"advocaat[- ]stagiai?re?|"
                r"talent ?programm?a?\b|development program(me)?\b|starters?functie|starters?programma|"
                r"\bstarter\b(?! kit)|\bbbl\b|apprentice\w*|\bleerling\b|leerwerk\w*|\bin opleiding\b|"
                r"betaalde opleiding|opleiding tot\b"),
    # US-style ladder numbers when no level word is given: "Software Engineer II", "Clinical Research Associate I - ..."
    ("junior", _NO_LEVEL_WORD + r".*[a-z]\s+i" + _LADDER_END),
    ("medior", _NO_LEVEL_WORD + r".*[a-z]\s+ii" + _LADDER_END),
    ("senior", _NO_LEVEL_WORD + r".*[a-z]\s+(?:iii|iv)" + _LADDER_END),
    # "associate" is junior unless the title names another level ("Senior Associate", "Associate Director")
    ("junior", r"\bjunior\b|\bjr\b\.?|\bgraduate\b|entry[- ]level|\bstarter\b|early career|"
               r"^(?!.*\b(?:senior|sr|staff|principal|manager|director|head|lead|chief|vp)\b).*\bassociate\b"),
    ("medior", r"\bmedior\b|\bmid[- ]level\b|\bintermediate\b|\bmiddle\b(?! east)"),
    ("staff", r"\bstaff\b|\bprincipal\b|\bdistinguished\b|\b(?:technical|engineering) fellow\b"),
    (
        "manager",
        "".join(f"(?<!{w} )(?<!{w}-)" for w in _IC_MANAGER) + r"\bmanager\b|\bhead\b(?!\s*line)|\bdirector\b|"
        r"\bdirecteur\b|\bhoofd\b|\bvp\b|\bchief\b|\bcto\b|\bcio\b|\bciso\b|bedrijfsleider|afdelingshoofd|"
        r"vestigingsleider|groepsleider|\bgroup leader\b",
    ),
    ("lead", r"\blead\b|\btech ?lead\b|\bteam ?lead(?:er)?\b|\bteamleider\b|(?<!project )(?<!project-)\bleader\b|"
             # a naval or landscape architect is a design discipline, not a lead level
             r"\bsupervisor\b|(?<!naval )(?<!landscape )\barchitect\b"),
    ("senior", r"\bsenior\b|\bsr\.?\b"),
]
_ROLE = [
    ("security", r"\bciso\b|chief information security"),
    ("product", r"product (owner|manager|lead)|projectmanager|scrum master|agile coach|project manager|"
                r"delivery manager|"
                r"release train engineer|program(?:me|ma)? ?manager|programmamanager|projects? director|"
                r"\bit[- ]project\w*|digital solution lead"),
    # analysts of the business, the process or the requirements: "other" unless the title says data
    ("other", r"^(?!.*\b(?:data|bi|analytics)\b).*\b(?:business|it[- ]business|functioneel|functional|"
              r"requirements|process|proces) ?(?:analy(?:st|sts)|analist(?:en)?)\b|"
              # ERP consultants, commercial IT advisers, business consultants and "Business IT" studies
              r"\bsap\b(?!.*\b(?:developer|ontwikkelaar|abap|engineer|security|authori[sz]ations?)\b)|"
              r"commerci(?:eel|ële) (?:ict[- ])?advis\w*|"
              r"business consultant|business[- ]it\b"),
    ("data", r"spotfire|\bqlik|power ?bi|tableau|looker\b"),
    ("platform", r"\b(?:azure|aws|gcp) integrati\w*"),
    ("backend", r"\b(?:cloud|azure|aws) (?:developer|ontwikkelaar)|uipath|\brpa\b"),
    ("it_support", r"devices? (?:and|&) peripherals|end[- ]user|eindgebruiker|device management|"
                   r"\bit[- ](?:diensten|afdeling|dienstverlening|servicedesk)"),
    # sales and pre-sales engineering is a sales job whatever the product: "Sales Engineer", "Solutions Engineer"
    ("other", r"\bsales\b(?! data| analy)|pre-?sales|business ?develop\w*|product develop\w*|"
          r"(?<!deployed )\bsolutions? engineer\w*|"
              r"\bvalue engineer|\bmarketing (?:manager|lead|director|specialist|executive|intern\w*)|marketeer|"
              r"account executive|\bfield applications? engineer|"
              # machine programmers (CNC, CAM, welding robots, laser cutters) and procurement are not software jobs
              r"\bcnc\b|\bcam[- ]?programm|cad/cam|lasrobot|lasersnij|meetprogramm|operator ?/ ?programm|"
              r"\bav[- ]technicus|audio ?visual|\binkoop(?:adviseur|professional|er|specialist|manager|"
              r"consultant|medewerker)?\b|"
              r"procurement|\bbuyer\b"),
    ("fullstack", r"full[- ]?stack"),
    (
        "it_support",
        r"support (engineer|specialist|analyst)|technical support|helpdesk|service ?desk|"
        r"system administrator|systeembeheer|werkplek|applicatiebeheer\w*|functioneel beheer\w*|"
        r"applicatie ?beheer\w*|application (?:manager|management|administrator|support)|"
        r"modern workplace|workplace (?:engineer|services|automation)|microsoft 365|\bm365\b|"
        r"technical services engineer|"
        r"service management|\bitsm\b|\bitil\b|major incident|incident (?:&|and) problem|\b(?:incident|"
        r"problem) manager",
    ),
    # Microsoft Power Platform is low-code app building, like Mendix and OutSystems, not platform engineering
    ("backend", r"power ?(?:platform|apps)\b"),
    (
        "ml",
        r"machine learning|\bml\b|deep learning|computer vision|\bnlp\b|llm|data scien\w*|reinforcement learning|"
        r"research (scientist|engineer)|applied scientist|mlops|prompt engineer|artificial intelligence|"
        r"\bai[- ](?:engineer|developer|specialist|consultant|architect|researcher|scientist|expert|lead)\b|"
        r"\bgen ?ai\b|generative ai|intelligent automation|agentic|\bai agents?\b|^agents\b",
    ),
    (
        "simulation",
        r"simulat|\bcfd\b|computational|numerical model|finite[- ]element|\bfea\b|multiphysics|digital twin|"
        r"modell?ing (?:engineer|scientist|specialist)|multi-?scale model\w*",
    ),
    ("security", r"security|cyber|\bsoc\b|penetration|\biam\b|\bgrc\b|informatiebeveilig\w*|(?<!ship )vulnerabilit\w*|"
                 r"\bit[- ]?(?:audit|assurance)\w*|technology risk|\bpki\b|threat|detection engineer"),
    ("data", r"\bdata\b(?! ?cent(?:er|re))|analytics|\bbi\b|business intelligence|analist|analyst|databricks|"
             r"snowflake"),
    (
        "platform",
        r"devops|devsecops|\bsre\b|site reliability|platform|\bcloud\b|kubernetes|"
        # IT infrastructure, not the civil and energy kind ("Project Leader Underground Infrastructure")
        r"^(?!.*(?:civil|civiel|underground|ondergrond|energ|environment|construct|soil|resources|regional|"
        r"project ?lead|"
        r"projectleid|supervisor|contract|cost|risico|jurist|communicatie|lecturer|phd)).*infrastru|"
        r"systems? engineer|systeem ?engineer|network engineer|linux|\bdba\b|database administrator|"
        r"netwerk ?(?:engineer|beheer\w*|specialist|architect)|"
        r"network (?:administrator|specialist|architect|operations|automation|consultant)|\bnoc\b|\bhpc\b|"
        r"netwerkautomatiser\w*|"
        r"observability",
    ),
    ("embedded", r"embedded|firmware|\bfpga\b|hardware|electronics|\basic\b|\brtl\b|\bsoc design\b|"
                 r"\bic design|\brf\b|microwave|photonic|analog design|\bplc\b|scada|\bdcs\b|pcs7|mechatroni\w*|"
                 r"\bpcb\b|optoelectron\w*|gebouwautomati\w*|building automation|industri\w* automati\w*|"
                 r"procesautomati\w*|(?<!business )process automation|process control|meet[- ]? ?(?:en|"
                 r"&) ?regel\w*|motion control"),
    ("mobile", r"\bios\b|android|mobile|flutter|react native|\bapp\b(?! ?(?:support|beheer))"),
    ("qa", r"\bqa\b|\btest\b|tester|quality assurance|test ?automati\w*|testautomatiseerder|tosca|"
           r"\btest(?:engineer|analist|analyst|coördinator|coordinator|manager|specialist)\b|\btesting engineer|"
           r"software (?:testing|quality)|testing (?:&|and) verification"),
    ("frontend", r"front[- ]?end|\bui\b engineer|react|angular|vue|web developer"),
    (
        "backend",
        # "programm" but not a "Graduate Programme", "Programmamanager" or "SAP Programme Lead"
        r"back[- ]?end|software ?(?:engineer|developer|development|ontwikkel\w*)|developer|ontwikkelaar|"
        r"programm(?!es?\b|as?\b|[ae][- ]?(?:manag|lead|architect|director))|"
        r"python|java|\.net|golang|scala|kotlin|c\+\+|\bapi\b|\bphp\b|\bruby\b|\brust\b|elixir|mendix|outsystems|"
        r"sitecore|software architect|\btech lead\b|integrati(?:e|on) ?specialist|\bdevelopment\b|"
        r"(?<!gebieds)(?<!project)(?<!vastgoed)ontwikkeling\b",
    ),
    ("data", r"\bgis\b|geo[- ]?ict|geodata|geo[- ]?informati"),
    ("ai", r"\bai\b(?! infra)"),  # a bare "AI": ML only when nothing more specific is named
    # ICT in general is the IT department once more specific families have had their say ("ICT Traineeship Java")
    (
        "platform",
        r"\binfra (?:engineer|specialist)|infrabeheer|openshift|virtuali[sz]ation|mainframe|z/os|"
        r"storage engineer|firewall|telecom ?engineer|engineer telecom|"
        r"telecommunicatie|glasvezel|\b(?:azure|aws|gcp) (?:engineer|specialist|consultant|architect)|"
        r"database[- ]?(?:engineer|operations)|release engineer|build engineer|ci/cd|\bwindows (?:\w+ )?engineer|"
        # "Azure Integration Architect", "Azure Competence Lead", "IT Architect (Azure)", "Practice Lead: AWS"
        r"\bnetworking\b|\b(?:azure|aws|gcp)\b[\w\s]{0,20}?\b(?:architect|lead)\b|"
        r"\b(?:architect|lead)\b\W{1,4}(?:\w+\W+)?(?:azure|aws|gcp)\b",
    ),
    # "IT" as the whole field ("Traineeship IT Leiden"), in capitals only so the English word "it" never counts
    ("it_support", r"\bict\b|(?-i:\bIT\b)(?!-?\w)|managed services? engineer|\bit[- ]systems?\b|"
                   r"\bit (engineer|support|specialist)|"
                   r"\bit[- ](?:medewerker|technician|coördinator|"
                   r"coordinator)|"
                   r"system technician|technisch beheer\w*|\bbeheerder\b"),
    ("embedded", r"robot\w*|\bros ?2?\b|\biot\b|\bot[- ](?:engineer|specialist)|it/ ?ot\b|signal processing|\bgnss\b|"
                 r"radar|vision engineer|quantum (?:\w+ )*engineer|"
                 r"^(?:(?:junior|medior|senior|lead|zzp)\s+)?automation engineer\s*$"),
    # engineers of other disciplines (electrical, mechanical, civil, process, cost, commissioning) are not software
    (
        "other",
        r"electri|elektr|mechani|werktuig|civil|civiel|structural|construct|geotechn|hydrau|piping|pipeline|"
        r"stress engineer|bouwkund|installati|\bhvac\b|\be&(?:amp;)?i\b|\b[ew]\b(?!-)|instrumentat|commissioning|"
        r"inbedrijf|field service|service engineer|site engineer|project ?engineer|work preparation|werkvoorbereid|"
        r"draftsman|tekenaar|modelleur|\bbim\b|\bcad\b|\bcam engineer|proce(?:ss?|s) ?engineer|procesengineer|"
        r"process (?:development|improvement|safety|technology)|production engineer|manufacturing engineer|"
        r"industriali[sz]ation|factory engineer|packaging|logisti\w*|maintenance|reliability engineer|rotating|"
        r"equipment engineer|scheepsbouw|marine|maritie?m|naval|offshore|subsea|dredg\w*|yacht|jachten|propulsion|"
        r"aerospace|turbojet|thermal|optical engineer|acoustic|homologation|regulatory|safety engineer|"
        r"machineveiligheid|spanning|high voltage|power (?:system|engineer|distribution|electronics)|energie|"
        r"energy|warmte|koude|koeltechniek|refrigerat|sprinkler|brandmeld|\brail\b|spoor|trein|bruggen|tunnels|"
        r"waterbouw|watertechn\w*|kabels|leidingen|infratechniek|ondergrond\w*|cost ?engineer|kostenengineer|"
        r"calculat\w*|tender|proposal|detail engineer|beveiliger\b|orderpicker|controls? engineer|\bbid\b|"
        r"failure analysis|quality control|kwaliteit\w*",
    ),
    ("platform", r"data ?cent(?:er|re)s?"),
    ("design", r"\bux\b|\bui\b|designer|user experience"),
    ("backend", r"engineer|engineering"),
]
_EXPERIENCED = re.compile(r"\bervaren\b|\bexperienced\b", re.I)
_LEVEL_WORDS = r"junior|jr\.?|medior|mid[- ]level|senior|sr\.?|lead|staff|principal|manager"
_LEVEL_RANGE = re.compile(
    rf"\b({_LEVEL_WORDS})\s*(?:/|-|–|\bof\b|\bor\b|\bto\b|\btot\b|&|\ben\b|\bén\b)\s*({_LEVEL_WORDS})(?!\w)", re.I)
_RANGE_LEVEL = {"junior": "junior", "jr": "junior", "medior": "medior", "mid-level": "medior", "mid level": "medior",
                "senior": "senior", "sr": "senior", "lead": "lead", "staff": "staff", "principal": "staff",
                "manager": "manager"}
_RANGE_RANK = {"junior": 0, "medior": 1, "senior": 2, "lead": 3, "staff": 3, "manager": 4}
# the level named in the opening lines, but not the colleagues you work with ("onder begeleiding van senior collega's")
_OPENING_LEVEL = re.compile(
    r"\b(senior|junior|medior)\b(?!\s*(?:collega|colleague|engineers|developers|team ?members|teamleden|management|"
    r"leadership|stakeholders|leaders|managers|experts|staff|consultants|onderzoekers|professionals))", re.I)
_SENIORITY_RX = [(k, re.compile(rx, re.I)) for k, rx in _SENIORITY]
_ROLE_RX = [(k, re.compile(rx, re.I)) for k, rx in _ROLE]


# explicit visa / work-permit sponsorship (wins over relocation-only negatives such as "no relocation support")
_VISA_STRONG = re.compile(
    r"vis(?:a|um)[- ]?sponsor\w*|sponsor(?:ship|ing|s)? (?:of |for )?(?:a |your |the |work |residence |their )*"
    r"(?:visas?|permits?)\b|visa (?:support|assistance|help)|(?:support|assist|help)\w* (?:\w+ ){0,3}?(?:with |"
    r"throughout |"
    r"during |in )(?:the |your |any )?(?:\w+ )?vis(?:a|um)\b|vis(?:a|um)[- ]?(?:application|process|procedure|"
    r"aanvra)\w*|"
    r"highly skilled migrants?|kennismigrant\w*|\bHSM[- ](?:visa|permit|status|scheme|sponsor\w*)|"
    r"erkend referent|recogni[sz]ed (?:sponsor|referent)|"
    r"work permit (?:support|sponsorship|application)|immigration (?:support|sponsorship|assistance|services)|"
    r"sponsorship provided\W{0,3}yes|vis(?:a|um)\s*(?:\+|and|&)\s*housing (?:is )?provided|housing\s*(?:\+|and|&)\s*"
    r"vis(?:a|um) (?:is |are )?provided|(?:or|and) (?:be )?eligible for (?:visa )?sponsorship|"
    r"regelen (?:we|wij) (?:een |je |jouw )?(?:visum|verblijfsvergunning|werkvergunning)|"
    r"we (?:can |will |do |are able to |gladly |happily )?sponsor (?:your |a |the |work |residence |relocation )*"
    r"(?:visas?|permits?|relocation|candidates|you)\b",
    re.I,
)
# relocation help and the 30% ruling: a sign of hiring from abroad, weaker than a visa statement
_VISA_WEAK = re.compile(
    r"relocation (?:package|support|assistance|budget|team|help|bonus|allowance|expenses|services|compensation|"
    r"reimbursement)|relocati(?:e|on)[- ]?pakket\w*|relocatie[- ]?ondersteuning|verhuispakket|"
    r"help(?:s|ing)? you (?:to )?relocate|(?:assist|support|help)\w* (?:you |candidates |employees |people )?(?:\w+ )?"
    r"(?:with|in|throughout) (?:your |the )?(?:relocation|moving|move)\b|assistance with relocation|"
    r"(?:assist\w*|support\w*|help\w*) (?:to |for )?(?:candidates|employees|people|those|anyone) who (?:relocate|move)|"
    r"make your move (?:to \w+ )?(?:as )?smooth|relocation (?:is |are )?(?:offered|provided|covered|reimbursed)|"
    r"30\s?%[- ]?(?:tax )?(?:ruling|regeling|facility)|expat (?:support|services|package|centre|center|desk)",
    re.I,
)
_NEG_BEFORE = re.compile(r"\b(?:no|not(?! only)|geen|niet|cannot|unable|without|never|nor|nooit)\b|n[’']t\b", re.I)
_NEG_AFTER = re.compile(r"^\W{0,4}(?:[\w-]+\W+){0,4}?(?:is |are |will be |wordt |kunnen wij )?(?:not|niet|unavailable|"
                        r"nee|no)\b(?! (?:matter|longer)\b)", re.I)
_FIELD_VALUE = re.compile(r"^\s*[:?]\s*(\S[^\n]*)?")  # "VISA Sponsorship:\n\nTravel Requirements:" form fields
_CLAUSE_END = re.compile(r"[.!?;\n•|]")

_NO_VISA = re.compile(
    # "we cannot provide visa sponsorship", "we are not able to offer relocation", "we will not sponsor applicants"
    r"(?:\bno\b|\bnot\b(?! only)|cannot|unable to|n[’']t\b|\bnever\b)(?:\s+[\w’'-]+){0,3}?\s+(?:offer\w*|"
    r"provid\w*|sponsor\w*|"
    r"support\w*|assist\w*|apply for|help with|facilitat\w*)(?:\s+[\w’'/-]+){0,3}?\s+(?:vis(?:a|um)\w*|sponsor\w*|"
    r"relocat\w*|work permits?|work or residence permits?|residence permits?|work visas?|immigration)|"
    # object first: "relocation support is not offered", "visa sponsorship not available", "relocation is not possible"
    r"(?:vis(?:a|um)\w*|sponsor\w*|relocat\w*)(?:\s+[\w/-]+){0,4}?\s+(?:is |are |will be |wordt |kunnen wij |"
    r"kunnen we )?"
    r"(?:unfortunately |currently |sadly )?(?:not|niet|un)\s*(?:\w+\s)?(?:offered|provided|available|possible|"
    r"supported|"
    r"included|mogelijk|bieden|aangeboden|aanbieden)|"
    r"\bno (?:visa |relocation |immigration |work permit )?(?:sponsorship|relocation)\b|"
    r"sponsorship\W{0,3}[:?]\s*(?:no|nee)\b|"
    # must already be allowed to work here
    r"(?:must|need to|needs to|have to|has to|required to|should|will need to)\s+(?:already\s+|currently\s+|also\s+)?"
    r"(?:have|hold|possess|be|obtain)\s+(?:the\s+|a\s+)?(?:full\s+|legal\s+|permanent\s+|valid\s+|existing\s+)*"
    r"(?:right|eligib\w*|authori[sz]\w*|permitted|allowed|entitled|legally)\s+(?:\w+\s+)?to\s+(?:live\s+and\s+)?work|"
    r"(?:right|eligib\w*|authori[sz]\w*|legally allowed|permitted) to (?:live and )?work (?:permanently )?in (?:the )?"
    r"(?:netherlands|nl|eu|european union|europe|eea|uk or eu|country|job location)|"
    r"\bvalid (?:eu[- ]|dutch |nl |netherlands )?(?:work(?:ing)? (?:permit|visa|authori[sz]ation)|residen(?:ce|cy)"
    r"(?:[/ ]?(?:and )?work)? permit)|"
    r"(?:\beu\b|\beea\b|european|dutch)(?:[/ ](?:eea|eu)|[- ]?member state)?[ -](?:citizen\w*|passport\w*|nationals?|"
    r"nationality|residen\w*)(?: holders?)?\s*(?:is |are )?(?:required|only|mandatory|needed)|"
    r"(?:\beu\b|european|dutch)[- ](?:work(?:ing)? )?(?:permit|rights|authori[sz]ation|work visa) (?:is )?"
    r"(?:required|needed|mandatory)|"
    r"(?:have|need|hold) (?:to have )?an eu[- ]passport|(?:have|hold|possess) an? (?:eu|dutch|valid) work permit|"
    r"(?:already )?hold (?:a |an )?(?:permanent |valid )(?:eu |dutch )?work (?:and residence )?permit|"
    r"\bvalid [\w/ -]{0,16}work (?:authori[sz]ation|permit)|"
    r"already (?:based|living|located|residing|reside|live) in (?:the netherlands|nl|europe|the eu)|"
    r"without (?:the need for |requiring |needing |any )*(?:a |company |employer |visa |company-sponsored |further )*"
    r"(?:sponsorship|work permit|visa)|"
    r"(?:do not|don't|does not|doesn't|won't|will not) (?:currently |now or in the future )?(?:require|"
    r"need) (?:a |any )?"
    r"(?:visa|sponsorship|work permit)|"
    # Dutch
    r"geen\W{0,15}(?:vis(?:a|um)\w*|sponsor\w*|relocat\w*|verhuis\w*)|"
    r"(?:vis(?:a|um)\w*|sponsor\w*|relocat\w*)[^.\n]{0,40}\b(?:niet|geen)\b\W{0,3}(?:mogelijk|bieden|aan)|"
    r"geldige [\w -]{0,20}?(?:werk|verblijfs)[- ]?(?:vergunning|visum)|(?:nederlandse |eu-?)?"
    r"werkvergunning (?:is )?(?:vereist|noodzakelijk|verplicht)|in nederland mag werken|gerechtigd (?:zijn )?(?:om )?"
    r"in nederland te (?:wonen en te )?werken|zonder werkvergunning",
    re.I,
)


# "Candidates with the right to work in NL are preferred", "Do you have a valid work permit (if applicable)?"
_HEDGED = re.compile(r"prefer\w*|a plus|an advantage|\bpr[eé]\b|\?|if applicable", re.I)


def _clause(text: str, m: re.Match) -> str:
    start = max(0, m.start() - 110)
    ends = list(_CLAUSE_END.finditer(text, start, m.start()))
    s = ends[-1].end() if ends else start
    e = _CLAUSE_END.search(text, m.end())
    return text[s : e.end() if e else len(text)]


def _unnegated(rx: re.Pattern, text: str) -> tuple[bool, bool]:
    """(any match that is not negated in its own clause, any negated match)"""
    pos = neg = False
    for m in rx.finditer(text):
        start = max(0, m.start() - 110)
        ends = list(_CLAUSE_END.finditer(text, start, m.start()))
        before = text[ends[-1].end() if ends else start : m.start()]
        if re.match(r"\W*(?:if|als|in case|should|when)\b", before, re.I) and "," in before:
            before = before.rsplit(",", 1)[1]  # "If you don't have an EU passport, we sponsor your visa"
        after = text[m.end() : m.end() + 60]
        e = _CLAUSE_END.search(after)
        after = after[: e.start()] if e else after
        fv = _FIELD_VALUE.match(text[m.end() : m.end() + 40])
        if fv:  # a form field: "VISA Sponsorship: No", or left empty
            val = (fv.group(1) or "").strip().lower()
            if re.match(r"(yes|ja|available|possible|provided)\b", val):
                pos = True
            elif re.match(r"(no|nee|not)\b", val):
                neg = True
            continue
        if _NEG_BEFORE.search(before) or _NEG_AFTER.search(after):
            neg = True
        else:
            pos = True
    return pos, neg


def _windows(text: str, anchor: re.Pattern, pad: int = 250) -> str:
    """Only the text around anchor words, joined by newlines (clause breaks): the long patterns then scan a
    fraction of each posting, and every one of their matches contains an anchor word."""
    spans: list[list[int]] = []
    for m in anchor.finditer(text):
        a, b = max(0, m.start() - pad), min(len(text), m.end() + pad)
        while a > 0 and not text[a - 1].isspace():  # never cut a word in half ("two" -> "wo")
            a -= 1
        while b < len(text) and not text[b].isspace():
            b += 1
        if spans and a <= spans[-1][1]:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    return "\n".join(text[a:b] for a, b in spans)


_VISA_ANCHOR = re.compile(
    r"vis[au]m?|sponsor|relocat|permit|vergunning|migrant|30\s?%|referent|immigration|verhuis|expat|right|eligib|"
    r"authori[sz]|citizen|passport|national|residen|already|gerechtigd|mag werken|\bhsm\b|moving|\bmove\b|"
    r"permitted to|allowed to|entitled to|legally", re.I)


def detect_visa(text: str) -> bool | None:
    text = _windows(text or "", _VISA_ANCHOR)
    strong_pos, strong_neg = _unnegated(_VISA_STRONG, text)
    if strong_pos:
        return True
    if any(not _HEDGED.search(_clause(text, m)) for m in _NO_VISA.finditer(text)):
        return False
    weak_pos, weak_neg = _unnegated(_VISA_WEAK, text)
    if weak_pos:
        return True
    if strong_neg or weak_neg:
        return False
    return None


_PLACE = r"(?:office|kantoor|site|on[- ]?site|location|locatie|hq|headquarters|campus|lab|client|klant)"
# "Senior Security Engineer (Remote, EU/CET)", "... - Remote", "Remote Data Engineer"; not "Coupling remote resonators"
_REMOTE_TITLE = re.compile(r"(?:^|[-–|(\[,/:]\s*)remote\b(?![- ](?:sens\w*|control\w*|monitor\w*|support|operat\w*|"
                           r"pilot\w*|access|infra\w*|service\w*|diagnos\w*))|\bremote\s*(?:$|[)\]\-–|,/])", re.I)
_POLICY_LABEL = (r"\b(?:location|locatie|work model|workplace(?: type)?|werklocatie|type werk|work location|werkplek|"
                 r"werkregeling|work arrangements?|flexible work arrangements?|working policy|working environment|"
                 r"where is the work|work setup|work type|arbeidsplaats)(?:\s*[:\-–]\s*|\s*\n\s*)")
_REMOTE = re.compile(
    r"\bfully[- ]remote\w*|\b100\s?% remote|\bremote[- ](?:first|only|native|based)\b|\bfull[- ]time remote|"
    r"\b(?:role|position|job|vacancy|opportunity|functie) is (?:a |an )?(?:fully |100% |entirely |"
    r"completely )?remote\b|"
    r"\b(?:is|as) a (?:fully )?remote (?:role|position|job)|"
    # not "Werkplek: Remote & Utrecht en klant locatie", which is remote next to an office
    + _POLICY_LABEL + r"(?:fully |100% )?remote\b(?!\s*(?:or|/|\+|&|,|-|–|of)\s*(?:hybri|office|on|kantoor|in[- ])|"
    r"\s*(?:&|\+|\ben\b|\band\b)\s*(?-i:[A-Z]))|"
    r"\bremote(?:ly)?(?: working| work)? (?:within|across|from anywhere in|anywhere in) (?:the )?(?:netherlands|"
    r"nl|europe|"
    r"eu|emea|cet|any)|\bwork (?:fully |100% )?remotely from (?:anywhere|home|any)|\bwork from anywhere\b|"
    r"(?:^|\n)\s*remote\s*[-–]\s*(?:emea|europe|eu|global|nl|netherlands)\b|\bremote-global\b|"
    # not the idiom "volledig thuis zijn in de techniek" (fully at home in, an expert in)
    r"\bvolledig (?:remote|op afstand|thuis(?! (?:is|in|zijn|bent|op)\b)|vanuit huis)|\b100\s?% (?:thuis|vanuit huis)|"
    r"\bremote (?:role|position|job)\b(?! (?:is )?not)|"
    # remote is one of the options: "Hybrid or remote working setup", "remote, hybrid or from the Rotterdam office"
    r"\bhybri(?:d|de)(?: working| work| werken)?,? (?:or|of|and|en|/) (?:fully |volledig )?remote\b|"
    r"\bremote(?:ly)?,? (?:or|of|/) hybri(?:d|de)\b|\bremote, hybrid\b|\bin overleg (?:zelfs |ook )?volledig remote",
    re.I,
)
_HYBRID = re.compile(
    r"(?<!cloud )(?<!cloud and )(?<!cloud, )(?<!on-prem and )(?<!on-premise and )(?<!multi- and )(?<!public, )"
    r"\bhybri(?:d|de)\b(?![ -]?(?:cloud|multi|omgevingen|infra|it\b|environments|architect|oplossing|solution|"
    r"ai\b|power|"
    r"system|quantum|vloot|fleet|hospitality|leadership|profiel|ervaring\b|delivery|approach|nano|energ|food|"
    r"zzp|landschap|"
    r"landscape|search|retrieval|technical|techniek|radar|kubernetes|netwerk|network|vehicle|electric|engine|method|"
    r"machine|bond|integrat|mobile|app|data\b|database|workload|platform|simulat|model(?:s|l\w*)? (?:for|of|"
    r"to) (?!work)|"
    r"comput|storage|identit|deploy|rag\b|learning|genetic|physics|modelling|models\b|"
    # technology and business senses: "hybride omgeving (on-premises en cloud)", "hybrid connectivity", "hybrid
    # attackers", "hybrid bare-metal", "hybrid games", "een hybride rol waarin", "hybrid office and cloud environments"
    r"omgeving\b|connectiv|attack|secur|threat|dreiging|positioning|casual|games?\b|publisher|solar|material|"
    r"magnet|klanten|professional|rol\b|focus|agentic|bare|on[- ]?prem|office and cloud|setups|workloads|"
    r"and (?:cloud|multi|on[- ]?prem)|of private))|"
    r"\b(?:[1-4]|one|two|three|four|een|één|twee|drie|vier)(?:\s*(?:[-–/]|to|or|tot|of)\s*(?:[1-5]|two|three|"
    r"four|five|twee|drie|vier|vijf))?\s*"
    r"(?:\(\d\)\s*)?(?:days?|dagen)\s*(?:a|per|p/|in the|/)\s*(?:week|wk)\s*(?:\w+\s+){0,4}?(?:in|at|from|on|op|vanuit|"
    r"naar)?\s*(?:the |our |het |ons |onze )?(?:" + _PLACE + r"|home|thuis|remote|remotely|in[- ]person)|"
    r"\b(?:[1-4]|one|two|three|four|een|één|twee|drie|vier)(?:\s*(?:[-–/]|to|or|tot|of)\s*(?:[1-5]|two|three|"
    r"four|five|twee|drie|vier|vijf))?\s*"
    r"(?:days?|dagen)\s*(?:\w+\s+){0,2}?(?:in|at|from|on|op|vanuit|naar) (?:the |our |het |ons |"
    r"onze )?(?:office|kantoor|"
    r"home|thuis|on[- ]?site)|"
    r"\b(?:office|kantoor|remote|home|thuiswerk)[- ]?(?:days?|dag(?:en)?)\b|\bremote days|"
    r"\bfrom home\b|\bvanuit huis\b|\bthuis\s?werk\w*|\bthuis (?:te )?werken|\bhome[- ]?office|"
    r"\bwork(?:ing)? remotely\b|"
    r"\b(?:deels|gedeeltelijk|partly|partially|part)\)? (?:werken |working |work )?(?:remote|op kantoor|in the office|"
    r"on[- ]?site|thuis|vanuit huis|from home)|"
    r"\b(?:on[- ]?site|onsite|in[- ]office|in the office|at the office|op kantoor|in[- ]person)(?: presence|"
    r" attendance)?"
    r"\W{0,3}(?:\w+\W+){0,2}?(?:[1-4]|one|two|three|four|twee|drie|vier)(?:\s*(?:[-–/]|to|or|tot|of)\s*(?:[1-5]|"
    r"two|three|four|five|twee|drie|vier|vijf))?\s*"
    r"(?:days?|dagen)|"
    r"\b(?:mix|combination|combinatie|balance|blend) (?:of|between|van|tussen) (?:\w+ ){0,3}?(?:office|home|"
    r"remote|kantoor|"
    r"thuis|on[- ]?site)|"
    r"\bremote (?:work(?:ing)?|werken) (?:is )?(?:possible|mogelijk|options?|allowed|available|policy|opportunit)|"
    r"\b(?:flexible|flexibel) (?:remote|home|thuis)[- ]?werk\w*|\bflexible (?:remote|home) work|"
    r"\bwork (?:from|in) the office (?:at least|minimum|min\.?) |\bremote[- ]friendly\b|"
    r"\b(?:grotendeels|largely|mostly|mainly|voornamelijk) (?:remote|thuis|vanuit huis|from home)|"
    # "able to work from our Amsterdam office at least 2 to 3 days per week"
    r"\b(?:office|kantoor|hq|headquarters|campus|hub)\W+(?:\w+\W+){0,5}?(?:[1-4]|one|two|three|four|twee|drie|vier)"
    r"(?:\s*(?:[-–/]|to|or|tot|of)\s*(?:[1-5]|two|three|four|five|twee|drie|vier|vijf))?\s*(?:days?|"
    r"dagen)\s*(?:a|per|in the|/)\s*(?:week|wk)|"
    r"\b[1-9]0\s?% (?:on[- ]?site|in (?:the )?office|remote|from home|thuis|op kantoor)|"
    # "Werkplek: Remote & Utrecht en klant locatie"
    + _POLICY_LABEL + r"remote\s*(?:&|\+|\ben\b|\band\b)\s*(?-i:[A-Z])|"
    # "travelling to the office twice per week", "once a week in the office"
    r"\b(?:office|kantoor|on[- ]?site)\b[^.;\n]{0,50}?\b(?:twice|once|three times)\s+(?:a|per|every|in the)\s+week|"
    r"\b(?:twice|once|three times)\s+(?:a|per|every|in the)\s+week\b[^.;\n]{0,40}?\b(?:office|kantoor|on[- ]?site|"
    r"in[- ]person)",
    re.I,
)
# office attendance in the same clause makes a "remote" statement hybrid: "The role is remote in the Netherlands, but
# you commit to travelling to the office twice per week"
_OFFICE_WEEKLY = re.compile(
    r"\b(?:office|kantoor|on[- ]?site|hq|headquarters|hub)\b[^.;\n]{0,50}?\b(?:twice|once|three times|[1-4]|one|two|"
    r"three|four|een|één|twee|drie|vier)(?:\s*(?:[-–/]|to|or|tot|of)\s*[1-5])?\s*(?:times?\s*|days?\s*|dagen\s*|x\s*)?"
    r"(?:a|per|in the|every|/|p/)\s*(?:week|wk)\b", re.I)
_ONSITE = re.compile(
    r"\b(?:fully|100\s?%|entirely|volledig|always|completely) (?:on[- ]?site|in[- ]office|office[- ]based|op kantoor|"
    r"op locatie|in the office|from the office|at the office|at our office|in[- ]person)|"
    r"\b(?:5|five|vijf) (?:full )?(?:days?|dagen)\s*(?:a|per|in the|/)\s*(?:week|wk)\s*(?:\w+\s+){0,3}?(?:in|at|"
    r"from|on|op|"
    r"vanuit)?\s*(?:the |our |het |ons )?" + _PLACE + r"|"
    r"\b(?:on[- ]?site|onsite|in[- ]office|office[- ]based|op kantoor|in the office|at the office) (?:5|five|"
    r"vijf) days|"
    r"\b(?:on[- ]?site|onsite|in[- ]office|office[- ]based|in[- ]person) (?:role|position|job|functie|only|"
    r"working|work\b|"
    r"presence (?:is )?(?:required|essential|expected|mandatory))|"
    r"\b(?:role|position|job|functie|vacancy) is (?:an? )?(?:fully )?(?:on[- ]?site|onsite|in[- ]office|"
    r"office[- ]based|"
    r"in[- ]person|based (?:in|at) (?:the|our) office)|"
    r"\ban? (?:fully )?(?:on[- ]?site|onsite|in[- ]office|office[- ]based) (?:role|position|job)|"
    r"\((?:on[- ]?site|onsite|in[- ]office|office[- ]based)\)|"
    + _POLICY_LABEL + r"(?:on[- ]?site|onsite|office|kantoor|op locatie|in[- ]office)\b|"
    r"#LI-On-?site\b|\bon[- ]?site \((?:5|five|vijf|full)|\b(?:role|position|job) is based on[- ]?site\b|"
    r"\bbased on[- ]?site (?:at|in)\b|"
    r"\bwork on[- ]?site (?:in|at) (?:our|the) (?:\w+ )?office|(?:^|\n)[ \t]*on[- ]?site[ \t]*(?:\n|$)|"
    r"\bnot (?:a |an )?(?:fully )?remote\b|\bno (?:fully )?remote\b|\bnon[- ]remote\b|\bgeen (?:remote|thuiswerk\w*)|"
    r"\bremote(?:-only)? (?:work(?:ing)? )?(?:is )?not (?:possible|an option|available|supported)|"
    r"(?:thuiswerk\w*|remote werken|op afstand werken|vanuit huis werken) (?:is )?niet mogelijk|"
    r"\boffice[- ]first\b|\bfully in[- ]office\b|\bin the office 5|"
    r"\b(?:do not|don't|doesn't|does not|cannot|can't|no) (?:offer |support |allow )?remote(?:-only)?|"
    r"\bom on[- ]?site (?:in \w+ )?te werken|\bwe (?:work|are) (?:fully |always )?on[- ]?site\b|"
    r"\b(?:not|don't|do not) hire for (?:strictly |fully |purely )?remote",
    re.I,
)
_REMOTE_NEG = re.compile(r"\b(?:no|not(?! only)|geen|niet|cannot|never|isn't|aren't|nor|zonder|unless|tenzij)\b|"
                         r"n[’']t\b", re.I)
# a benefit, not the policy: "1 month per year fully remote", "work from anywhere for up to 4 weeks a year"
_REMOTE_PERIOD = re.compile(
    r"\b(?:\d+|one|two|three|four|six|eight|a|een|één|twee|drie|vier|zes|acht)\s*(?:full |paid |working |work |"
    r"calendar )?(?:weeks?|months?|days?|maand(?:en)?|weken|dagen|werkdagen)\b[^.\n]{0,30}?(?:per|a|each|every|in a|/|"
    r"of the|in het|per kalender)\s*(?:calendar )?(?:year|jaar)|\bper jaar\b|/\s?year|\babroad\b|\bbuitenland\b", re.I)
# company-wide boilerplate: "from in-office to fully remote, depending on the requirements of their role"
_REMOTE_HEDGE = re.compile(r"depending on|afhankelijk van|some (?:roles|positions|of these)|certain roles", re.I)
_AFTER_NEG = re.compile(
    r"\W{0,3}(?:is |are |zijn )?(?:not|niet|geen) (?:possible|mogelijk|an option|allowed|available)", re.I)
_CLAUSE_END_R = re.compile(r"[.!?;\n•|]")
# the employer or team, not the role: "Remote first digital team, based across Europe", "a remote-first company"
_REMOTE_COMPANY = re.compile(r"\bremote[- ](?:first|native|based)\s+(?:[\w-]+\s+)?(?:teams?|company|companies|"
                             r"organi[sz]ations?|culture|business|workforce|employer|start-?up|scale-?up)\b", re.I)


def _clause_parts(text: str, m: re.Match, back: int = 60) -> tuple[str, str]:
    start = max(0, m.start() - back)
    ends = list(_CLAUSE_END_R.finditer(text, start, m.start()))
    before = text[ends[-1].end() if ends else start : m.start()]
    e = _CLAUSE_END_R.search(text, m.end(), m.end() + 120)
    after = text[m.end() : e.start() if e else m.end() + 120]
    return before, after


def _policy_hit(rx: re.Pattern, text: str, period_ok: bool = True) -> bool:
    for m in rx.finditer(text):
        before, after = _clause_parts(text, m)
        if _REMOTE_NEG.search(before[-40:]) or _AFTER_NEG.match(after):
            continue
        if not period_ok and (_REMOTE_PERIOD.search(before) or _REMOTE_PERIOD.search(after[:60])
                              or _REMOTE_HEDGE.search(before + after) or _OFFICE_WEEKLY.search(after)):
            continue
        return True
    return False


_REMOTE_ANCHOR = re.compile(
    r"remote|hybri|home|thuis|huis|office|kantoor|on[- ]?site|in[- ]person|locati|anywhere|afstand|\bsite\b|\bhq\b|"
    r"headquarters|campus|\blab\b|client|klant|\bhub\b", re.I)


def detect_remote(title: str, text: str) -> str:
    text = _windows(text or "", _REMOTE_ANCHOR)
    # the title wins when it names the policy: "Product Engineer (Hybrid Amsterdam)"
    if re.search(r"\bhybri(?:d|de)\b(?![ -]?(?:cloud|power|network|dynamic|infra|it\b|system|quantum|solution|"
                 r"architect|data|integrat|platform|app|mobile|vehicle|electric|engine|search|ai\b|ml\b|simulat|"
                 r"model))",
                 title or "", re.I):
        return "hybrid"
    if re.search(r"\b(?:on[- ]?site|in[- ]office)\b", title or "", re.I):
        return "onsite"
    remote = _policy_hit(_REMOTE, text, period_ok=False)
    if remote and _ONSITE.search(text) and not _policy_hit(_REMOTE, _REMOTE_COMPANY.sub(" ", text), period_ok=False):
        remote = False  # only the company or team is remote-first; the role itself is on-site
    if remote or (
        _REMOTE_TITLE.search(title or "") and not _ONSITE.search(text) and not _policy_hit(_HYBRID, text)
    ):
        return "remote"
    if _policy_hit(_HYBRID, text):
        return "hybrid"
    if _ONSITE.search(text):
        return "onsite"
    if _REMOTE_TITLE.search(title or ""):
        return "remote"
    return "unknown"


_DEGREE = [
    # a PhD as a requirement, not the PhD position itself ("this PhD project", "PhD candidate", "four other PhDs")
    ("phd", r"(?<!your )(?<!this )(?<!the )(?<!our )(?<!during )(?<!funded )(?<!year )(?<!other )(?<!doing a )"
            r"(?<!start a )(?<!starting a )(?<!towards a )(?<!for a )(?<!pursue a )(?<!her )(?<!his )(?<!their )"
            r"(?<!my )(?<!possession of a )"
            r"\bph\.?\s?d\.?(?:['’]s)?\b(?!['’]s\b)(?![\s-]*(?:\d|,?\s*(?:and|or|&|/)\s*post-?doc|position|"
            r"project|candidate|student|researcher|"
            r"vacanc|programme|"
            r"program|track|thesis|research|defen[cs]e|trajector|supervis|fellow|scholarship|journey|stud|"
            r"level position|"
            r"opportunit|network|intern|salary|allowance|contract|traineeship|school|course|life|period|phase))|"
            r"\bdoctorate\b|(?<!possession of a )\bdoctoral degree|\bgepromoveerd|"
            r"\bpromotieonderzoek (?:afgerond|voltooid)"),
    ("msc", r"\bm\.?\s?sc\b(?![\s-]*(?:(?:and|en|or|of|/)\s*ph\.?d\s*)?(?:students|studenten|theses|projects|"
            r"interns?))|(?-i:\bMS)\s*(?:degree|in\b|or PhD|/\s?PhD)|\bmasters? of (?:een )?ph\.?d\b|"
            r"(?<!scrum )(?<!certified )(?<!quiz)\bmasters?(?:['’]s?)?(?:\s+(?:degree|diploma|"
            r"in\b(?! (?:excel|het|de|the|multitask|problem|communic|organi|plannen|verbind|sales))|level|or\b|"
            r"opleiding|programme|program|student|graduate|of (?:science|engineering|arts|business|laws|philosophy|"
            r"computer|information|applied|data))|\s*/\s*(?:phd|ph\.d|doctor))|"
            r"\bmaster(?:diploma|opleiding|niveau|titel|degree|studie|student|s?graad)\w*|\bwo\b|"
            r"\buniversity master|\b(?:afgeronde|completed|finished|behaalde) (?:\w+ )?masters?\b|"
            r"\buniversitair\w* (?:opleiding|niveau|diploma|master|denkniveau|werk|achtergrond|studie)|"
            r"\bacademisch\w* (?:werk[- ] en )?(?:denk)?(?:niveau|opleiding|achtergrond|diploma|master)|"
            r"\buniversity degree"),
    # a degree without a level ("a degree in Computer Science") stays unknown: only an explicit level counts
    ("bsc", r"\bb\.?\s?sc\b|\bbachelor\w*|\bbs\b (?:\(or higher\) )?(?:degree|in)\b|\bb\.?tech\b|\bb\.?eng\b"),
    ("hbo", r"\bhbo\w*(?!['’]s\b)|\bhogeschool(?:opleiding|diploma|niveau)|\bhts\b|\bheao\b|\bhlo\b|"
            r"\buniversity of applied sciences (?:degree|diploma|level|education)|\bhigher professional education|"
            r"\b(?:degree|diploma|education|opleiding) (?:from|at) (?:a |an )?university of applied sciences"),
    ("mbo", r"\bmbo\w*(?!['’]s\b)"),
]
_DEGREE_RX = [(k, re.compile(rx, re.I)) for k, rx in _DEGREE]
_DEGREE_LEVEL = {"mbo": 0, "hbo": 1, "bsc": 1, "msc": 2, "phd": 3}  # hbo is a bachelor's level
_NO_DEGREE = re.compile(
    r"(no|without a?|regardless of) (?:formal )?(?:degree|diploma)|degree (?:is )?not (?:required|necessary|"
    r"needed|a must)|"
    r"(?:don't|do not|doesn't|does not) (?:need|require) (?:a |any )?(?:formal )?(?:[\w-]+,? ){0,4}(?:or )?(?:degrees?|"
    r"diplomas?)\b|"
    r"geen (?:specifiek |formeel )?diploma (?:vereist|nodig|noodzakelijk)|diploma (?:is )?niet (?:vereist|nodig|"
    r"noodzakelijk)",
    re.I,
)
# a degree that is only a plus is not the minimum asked
_DEGREE_PLUS = re.compile(r"a plus|is a bonus|\bbonus\b|nice[- ]to[- ]have|an advantage|\bpluspunt|\bpr[eé]\b|"
                          r"\bvoordeel\b|\bextra\b", re.I)
# "HBO diploma (of MBO-4 met ruime ervaring)", "or an MBO 4 background combined with substantial practical experience":
# an alternative route next to the level asked, not the level itself
_MBO_ALT_BEFORE = re.compile(r"(?:\bof|\bor)\s+\(?(?:een |an |a )?(?:\w+\s)?$", re.I)
_MBO_ALT_AFTER = re.compile(r"^[^.;\n]{0,70}?(?:experience|ervaring|who has reached|heeft bereikt)", re.I)
_ANY_DEGREE = re.compile(r"\b(?:ph\.?d|m\.?sc|b\.?sc|master|bachelor|hbo|mbo|wo\b|universit|academisch|doctora)", re.I)
_OTHER_ITEM = re.compile(r"\b(?:en|and|or|of)\b[^,]*?(?:opleiding|diploma|certific\w*|degree|course|cursus)", re.I)
# "at least 4 years relevant working experience (or PhD)": the PhD replaces experience, it is not the level asked
_INSTEAD_OF_EXPERIENCE = re.compile(r"(?:experience|ervaring)[^.;\n]{0,15}\(?\s*(?:or|of)\s*(?:a\s+)?$", re.I)
_DEG_CLAUSE_END = re.compile(r"[.!?;\n•|]")
# degrees that are not asked of the applicant: the students you supervise or teach, the transcripts to upload, the
# programmes the university runs ("supervising Bachelor's and Master's students", "transcripts of your BSc and MSc")
_DEG_NOT_ASKED_BEFORE = re.compile(
    r"supervis\w*|mentor\w*|teach\w*|lectur\w*|tutor\w*|begeleid\w*|transcripts?|grades?\b|cijferlijst\w*|"
    r"courses followed|list of courses|\bwe educate\b|\bmixed\b|students?\s*\(\s*$", re.I)
_DEG_NOT_ASKED_AFTER = re.compile(
    r"^(?:['’]s?)?\s*(?:(?:and|or|/|&|,)\s*(?:\w+\s)?(?:master|msc|m\.sc|bachelor|bsc|b\.sc)\w*(?:['’]s?)?\s*)?"
    r"(?:teaching|onderwijs|lectures)\b", re.I)
_POSTDOC_TITLE = re.compile(r"\bpost[- ]?doc\w*|\bpostdoctoral", re.I)


def _degree_levels(text: str) -> list[str]:
    found = []
    for key, rx in _DEGREE_RX:
        for m in rx.finditer(text):
            s, e = m.start(), m.end()
            ends = list(_DEG_CLAUSE_END.finditer(text, max(0, s - 60), s))
            before = text[ends[-1].end() if ends else max(0, s - 60) : s]
            after = text[e : e + 90]
            cut = _DEG_CLAUSE_END.search(after)
            after = after[: cut.start()] if cut else after
            # "Master's degree is a plus", "Nice to have: a PhD"; not "mbo 4, hbo is een pre" (the plus is hbo's)
            plus = _DEGREE_PLUS.search(after)
            if plus and not _ANY_DEGREE.search(after[: plus.start()]) and not _OTHER_ITEM.search(after[: plus.start()]):
                continue
            plus = list(_DEGREE_PLUS.finditer(before))
            if plus and not _ANY_DEGREE.search(before[plus[-1].end() :]):
                continue
            if _DEG_NOT_ASKED_BEFORE.search(before) or _DEG_NOT_ASKED_AFTER.match(text[e : e + 60]):
                continue
            if key == "phd" and _INSTEAD_OF_EXPERIENCE.search(text[max(0, s - 60) : s]):
                continue
            if key == "mbo" and _MBO_ALT_BEFORE.search(text[max(0, s - 25) : s]) and _MBO_ALT_AFTER.match(text[e:]):
                continue
            found.append(key)
            break
    return found


_DEGREE_ANCHOR = re.compile(
    r"ph\.?\s?d|doctora|gepromoveerd|promotie|m\.?\s?sc|\bms\b|master|\bwo\b|universit|academisch|b\.?\s?sc|bachelor|"
    r"\bbs\b|b\.?tech|b\.?eng|hbo|hogeschool|\bhts\b|heao|\bhlo\b|applied sciences|higher professional|mbo|degree|"
    r"diploma", re.I)


def detect_degree(title: str, core: str, text: str) -> str:
    core, text = _windows(core, _DEGREE_ANCHOR), _windows(text, _DEGREE_ANCHOR)
    if _NO_DEGREE.search(text):
        return "none"
    # the requirement is the lowest level named: "Bachelor's or Master's" asks for a bachelor, and the Dutch
    # "hbo/wo-niveau" (applied or research university) for hbo, not for a master's
    if _POSTDOC_TITLE.search(title or ""):
        return "phd"
    found = _degree_levels(core) or _degree_levels(text)
    if not found:
        return "unknown"
    low = min(_DEGREE_LEVEL[k] for k in found)
    lowest = [k for k in found if _DEGREE_LEVEL[k] == low]
    return "bsc" if "bsc" in lowest else lowest[0]


def detect_language(text: str) -> str:
    nl = len(_NL_WORDS.findall(text))
    en = len(_EN_WORDS.findall(text))
    de = len(_DE_WORDS.findall(text))
    if nl == 0 and en == 0 or de > max(nl, en):
        return "other"
    return "nl" if nl > en else "en"


def _is_opt_header(line: str) -> bool | None:
    """True for a "nice to have" list header, False for another section header, None for an ordinary line."""
    s = line.strip(" \t|•-*[]")
    if not s or len(s) > 70 or s[-1] in ".;,":
        return None
    if s.endswith(":") and len(s.split()) <= 10:
        return bool(_OPT_HEADER.search(s))
    if ":" in s or len(s.split()) > 6:
        return None
    if _OPT_HEADER.search(s) and not re.search(r"\b(?:is|are|zijn|is een)\b", s, re.I):
        return True
    return False if _SECTION_HEADER.search(s) else None


def _optional(text: str, m: re.Match, headers: bool = True) -> bool:
    """Whether the clause around a Dutch-requirement match, or the list header above it, marks it optional."""
    a = max(0, m.start() - 120)
    cut = [x.end() for x in _CLAUSE_END.finditer(text, a, m.start())]
    start = cut[-1] if cut else a
    e = _CLAUSE_END.search(text, m.end(), m.end() + 120)
    tail = text[m.end():e.start() if e else m.end() + 120]
    n = _LANG_NAME.search(tail)
    own_tail = tail[:n.start()] if n else tail
    # "(preferably native)" qualifies the level, not the requirement
    own_tail = re.sub(r"\((?:preferably|ideally|bij voorkeur)\s+(?:native|c1|c2|mother tongue|moedertaal)\)", "",
                      own_tail, flags=re.I)
    head = text[start:m.start()]
    near = head.rsplit(",", 1)[-1]
    if _OPTIONAL.search(own_tail) or _OPT_BEFORE.search(near) or \
            re.match(r"\W*(?:ideally|preferably|optionally|bonus|nice to have|a plus)\b", head, re.I):
        return True
    if _ALT_AFTER.match(tail) or _ALT_BEFORE.search(head) or _ALT_INSIDE.search(m.group(0)):
        return True
    # "Dutch is an advantage, as we work with Dutch-speaking clients"
    if any(start <= x.start() < m.end() + len(tail) for x in _DUTCH_PLUS.finditer(text, start, m.end() + len(tail))):
        return True
    if _STRONG.search(own_tail) or _STRONG.search(near):
        return False
    if not headers:
        return False
    # the nearest header line above: "Nice to have", "Pluspunten"
    for line in reversed(text[:start].splitlines()[-12:]):
        h = _is_opt_header(line)
        if h is not None:
            return h
    return False


def dutch_requirement(text: str, lang: str = "en") -> bool | None:
    """True/False when the text says whether Dutch is required, None when it does not say."""
    if _DUTCH_NOT_REQ.search(text):
        return False
    found = False
    for m in _DUTCH_REQ.finditer(text):
        found = True
        if not _optional(text, m, headers=lang != "nl"):
            return True
    return False if found or _DUTCH_PLUS.search(text) else None


def language_fields(title: str, text: str) -> tuple[str, bool, bool, bool]:
    """(posting_language, dutch_required, english_only, english_required)."""
    lang = detect_language(text) if text else "en"
    said = dutch_requirement(title + "\n" + text, lang)
    # written in Dutch means you work in Dutch, unless the posting says Dutch is not needed or only a plus
    dutch_required = said if said is not None else lang == "nl"
    # a posting with no readable text (empty, a bare link, "x", a salary line) does not tell whether Dutch is needed
    words = len(_NL_WORDS.findall(text)) + len(_EN_WORDS.findall(text)) + len(_DE_WORDS.findall(text))
    known = said is not None or words >= 3 or len(re.findall(r"[^\W\d_]{3,}", text)) >= 6
    # a German posting, or one whose only text is a link or a salary line, is not an English job, unless it says
    # outright that Dutch is not needed
    german = len(_DE_WORDS.findall(text)) > max(len(_NL_WORDS.findall(text)), len(_EN_WORDS.findall(text)))
    english_only = not dutch_required and known and not german and (lang != "other" or said is False)
    english_required = (lang == "en") or (bool(_ENGLISH_REQ.search(text)) and not _ENGLISH_NOT_REQ.search(text))
    return lang, dutch_required, english_only, english_required


def detect_seniority(title: str, text: str = "") -> str:
    m = _LEVEL_RANGE.search(title)
    if m and not _SENIORITY_RX[0][1].search(title) and not _SENIORITY_RX[1][1].search(title):
        a, b = (_RANGE_LEVEL[g.lower().rstrip(".")] for g in m.groups())
        if a != b and _RANGE_RANK[a] != _RANGE_RANK[b]:
            return min((a, b), key=_RANGE_RANK.get)
    for key, rx in _SENIORITY_RX:
        if rx.search(title):
            return key
    years = find_years(text)
    if _EXPERIENCED.search(title):
        # "Ervaren Data Engineer", "Experienced Quant": not junior, and senior only when the years say so
        return "senior" if years is not None and years >= 5 else "medior"
    if years is not None:
        if years >= 5:
            return "senior"
        if years >= 3:
            return "medior"
        return "junior"
    return "unknown"


# the role is named before qualifiers ("Software Test Engineer met AI-focus", "Data Engineer (Python)"); after a
# dash or bar comes either noise ("IT Business Analist | Amsterdam") or the specialism ("Software Architect - Mobile")
_QUALIFIER = re.compile(r"\s*\([^)]*\)|\s+(?:met|with|voor|for)\s+.*$", re.I)
_SEPARATOR = re.compile(r"\s+[-–|]\s+|,\s+")
_BROAD = (None, "backend", "other", "it_support", "ai")  # families a title falls into when it names no specialism
# the catch-all rules at the end of _ROLE: a title that only says "engineer" or "developer" names no family
_GENERIC_ROLE_TITLE = re.compile(
    r"^\W*(?:(?:junior|medior|senior|sr\.?|lead|staff|principal|zzp|freelance|young professional|starter|"
    r"stagiair|stage|internship|intern|traineeship|trainee|afstudeer\w*|graduation|graduate|an?|at|in|bij|"
    r"\w+ ?(?:track|programme|program)|hbo|wo|mbo|automation|solutions?)\W+){0,4}?"
    r"(?:developer|ontwikkelaar|engineer|internship|stage|traineeship|trainee|"
    r"afstudeer\w*|consultant)\b",
    re.I)
# the families a job's own text points to, by the tools and work it names
_ROLE_TEXT = [(k, re.compile(rx, re.I)) for k, rx in [
    ("frontend", r"\breact\b(?! native)|angular|\bvue\b|typescript|javascript|\bcss\b|front[- ]?end|next\.js"),
    ("mobile", r"\bios\b|android|\bswift\b|flutter|react native|mobile app"),
    ("backend", r"\bjava\b|\.net\b|\bc#|\bgolang\b|node\.?js|spring boot|django|\bphp\b|microservices|back[- ]?end|"
                r"\brest(?:ful)? api|power ?(?:platform|apps|automate)|uipath|\brpa\b"),
    ("data", r"\bsql\b|power ?bi|tableau|data ?warehouse|\betl\b|\bdbt\b|data engineer\w*|databricks|\bspark\b|"
             r"dashboards?"),
    ("ml", r"machine learning|deep learning|pytorch|tensorflow|\bllms?\b|\bnlp\b|computer vision|data scien\w*|"
           r"reinforcement learning|neural"),
    ("platform", r"kubernetes|\bdocker\b|terraform|devops|ci/cd|ansible|\blinux\b|netwerk|network(?:ing)?|"
                 r"cloud infrastruct\w*|\bazure\b|\baws\b"),
    ("embedded", r"embedded|firmware|microcontroller|\bfpga\b|\bplc\b|electronics|hardware|sensor|scada"),
    ("simulation", r"simulat\w*|\bcfd\b|finite[- ]element|\bfea\b|multiphysics|numerical model\w*|"
                   r"computational model\w*|digital twin"),
    ("security", r"\bsecurity\b|\bsiem\b|\bsoc\b|pentest\w*|\biam\b|vulnerabilit\w*|threat"),
    ("qa", r"test ?automati\w*|selenium|cypress|playwright|testing|testcases?"),
    ("it_support", r"helpdesk|service ?desk|werkplek|active directory|intune|\bm365\b|microsoft 365|\bitil\b|"
                   r"eindgebruikers|end users|systeembeheer|applicatiebeheer"),
]]
_SIMULATION_WORK = re.compile(r"simulat\w*|\bcfd\b|finite[- ]element|\bfea\b|multiphysics|numerical model\w*|"
                              r"computational\w*|digital twin|\bmodell?ing\b", re.I)


_LOW_CODE = re.compile(r"uipath|\brpa\b|blue ?prism|power ?(?:platform|automate|apps)", re.I)


# "Software Engineer", "Senior Developer", "Stage Software Developer": software work of an unnamed kind
_GENERAL_SOFTWARE = re.compile(
    r"^\W*(?:(?:junior|medior|senior|sr\.?|lead|staff|principal|stage|stagiair|intern|young professional|"
    r"graduate|zzp|freelance)\W+){0,3}(?:software\W+)?(?:engineer|developer|ontwikkelaar|programmeur)\W*$", re.I)


def _software_kind(text: str) -> str | None:
    """For a general software title: full-stack when the role text names both front- and back-end work clearly,
    otherwise the family it clearly points to (embedded, mobile, ML, data, front-end), else None."""
    focus = job_text(text) or text[:4000]
    score = {k: len({m.group(0).lower() for m in rx.finditer(focus)}) for k, rx in _ROLE_TEXT}
    if score["frontend"] >= 2 and score["backend"] >= 2:
        return "fullstack"
    kind = _text_role(text)
    return kind if kind in ("embedded", "mobile", "ml", "data", "frontend") else None


def _title_role(title: str) -> str | None:
    for key, rx in _ROLE_RX:
        if rx.search(title):
            return key
    return None


def _text_role(text: str) -> str | None:
    """The family the job's own text clearly points to (distinct tools and work named), or None when unclear."""
    if not text:
        return None
    focus = job_text(text) or text[:4000]
    scores = sorted(((len({m.group(0).lower() for m in rx.finditer(focus)}), k) for k, rx in _ROLE_TEXT),
                    reverse=True)
    (best, family), (second, _) = scores[0], scores[1]
    return family if best >= 3 and best >= 2 * second else None


def detect_role(title: str, text: str = "") -> str:
    head, *rest = _SEPARATOR.split(_QUALIFIER.sub("", title or "").strip()) or [""]
    rest += re.findall(r"\(([^)]*)\)", title or "")
    role = _title_role(head)
    if role == "backend":
        # a general software title: the rule order over the whole title decides, so "Software Architect - Mobile"
        # is mobile and "Staff Software Developer (IAM)" security, but "Software Engineer (Networking)" stays backend
        role = _title_role(re.sub(r"\s+(?:met|with|voor|for)\s+.*$", "", title or "", flags=re.I)) or role
    elif role in _BROAD:
        # the specialism after the dash: "IT Internship - Cloud Engineer", "Software Architect - Mobile"
        role = next((r for r in map(_title_role, rest) if r not in _BROAD), None) or role
    if role is None:
        role = _title_role(title or "")
    if role == "backend" and _GENERAL_SOFTWARE.fullmatch(head.strip(" -,.")) and text:
        role = _software_kind(text) or role
    if role in (None, "backend", "other") and _GENERIC_ROLE_TITLE.fullmatch(head.strip(" -,.")):
        # "Lead Developer", "An Internship at Xsens", "Automation Engineer": the title names no family
        role = _text_role(text) or role
    if role == "embedded" and _LOW_CODE.search((title or "") + " " + focus_text(text)):
        # an automation engineer building RPA or Power Platform flows writes software, not machine control
        role = "backend"
    if role in (None, "other") and len(_SIMULATION_WORK.findall(focus_text(text))) >= 4:
        # naval, structural or materials research whose work is modelling and simulation
        role = "simulation"
    return "ml" if role == "ai" else role or "other"


def focus_text(text: str) -> str:
    return (job_text(text) or (text or "")[:4000]) if text else ""


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


# non-breaking and thin spaces are common in pasted posting text and would break every " " in the patterns
_ODD_SPACES = re.compile(r"[     ]")


def extract_rules(title: str, description: str) -> Extraction:
    text = _ODD_SPACES.sub(" ", description or "")
    title = _ODD_SPACES.sub(" ", title or "")
    lang, dutch_required, english_only, english_required = language_fields(title, text)
    core = _BENEFITS_SPLIT.split(text, maxsplit=1)[0] if text else ""
    # skills come from the role and requirement sections when the posting has headers, so the company intro and
    # "about us" (which often name the employer's own products) do not read as requirements
    focus = job_text(text)
    parts = _NICE_SPLIT.split(focus if focus is not None else core, maxsplit=1)
    required_part = parts[0]
    nice_part = parts[-1] if len(parts) > 1 else ""
    skills_req = find_skills(title + "\n" + required_part)
    skills_nice = [s for s in find_skills(nice_part) if s not in skills_req]

    visa = detect_visa(text)

    # requirements usually sit before the benefits section, but not always: fall back to the whole text
    years = find_years(core)
    if years is None:
        years = find_years(text)
    seniority = detect_seniority(title, text if years is None else f"{years} years of experience")
    if seniority == "unknown":
        # "We are looking for a Senior Information Security Officer ..." in the first lines
        m = _OPENING_LEVEL.search(text[:300])
        if m:
            seniority = m.group(1).lower()

    remote = detect_remote(title, text)

    degree = detect_degree(title, core, text)

    lo, hi = parse_salary(text)
    return Extraction(
        role_family=detect_role(title, text),
        seniority=seniority,
        skills_required=skills_req,
        skills_nice=skills_nice,
        posting_language=lang,
        dutch_required=dutch_required,
        english_only=english_only,
        english_required=english_required,
        years_experience=years,
        salary_min_eur=lo,
        salary_max_eur=hi,
        visa_sponsorship=visa,
        remote_policy=remote,
        degree_required=degree,
        # only asked of internships and student jobs, so a regular posting that mentions students is never hidden
        enrollment_required=(detect_enrollment(text, title)
                             if seniority == "intern" or _STUDENT_TITLE.search(title) else None),
    )
