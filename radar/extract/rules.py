"""Rule-based extractor v1. Cheap, deterministic, and the baseline the LLM extractor must beat on the golden set."""

from __future__ import annotations

import math
import re

from radar.extract.schema import Extraction
from radar.extract.sections import job_text
from radar.taxonomy import find_skills

RULES_VERSION = "rules-v13"  # bump whenever the taxonomy or the rules change, so `radar extract` re-runs

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
]), re.I)
# a title that says thesis, afstudeer or werkstudent is evidence even when the text is empty
_TITLE_REQ = re.compile(
    r"afstudeer|graduation (?:internship|project|assignment)|(?<!non-)(?<!non )thesis|scriptie|werkstudent|"
    r"working student|"
    r"student[- ]?stag|\b(?:mbo|hbo|wo)\b(?:[- ]?\d)?[^\n]{0,40}?stag|stag\w*[^\n]{0,40}?\b(?:mbo|hbo|wo)\b", re.I)


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


_SENIORITY = [
    ("intern", r"\bintern(ship)?\b|\bstage\b|\bstagiair|working student|werkstudent|afstudeer"),
    ("trainee", r"\btrainee(ship)?s?\b|traineeprogramma|graduate (programme|program|scheme)|young professional|"
                r"talent ?programm?a?\b|development program(me)?\b|starters?functie|starters?programma|"
                r"\bstarter\b(?! kit)"),
    # "associate" is junior unless the title names another level ("Senior Associate", "Associate Director")
    ("junior", r"\bjunior\b|\bgraduate\b|entry[- ]level|\bstarter\b|early career|"
               r"^(?!.*\b(?:senior|sr|staff|principal|manager|director|head|lead|chief|vp)\b).*\bassociate\b"),
    ("staff", r"\bstaff\b|\bprincipal\b|\bdistinguished\b|\b(?:technical|engineering) fellow\b"),
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


# non-breaking and thin spaces are common in pasted posting text and would break every " " in the patterns
_ODD_SPACES = re.compile(r"[     ]")


def extract_rules(title: str, description: str) -> Extraction:
    text = _ODD_SPACES.sub(" ", description or "")
    title = _ODD_SPACES.sub(" ", title or "")
    lang = detect_language(text) if text else "en"
    core = _BENEFITS_SPLIT.split(text, maxsplit=1)[0] if text else ""
    # skills come from the role and requirement sections when the posting has headers, so the company intro and
    # "about us" (which often name the employer's own products) do not read as requirements
    focus = job_text(text)
    parts = _NICE_SPLIT.split(focus if focus is not None else core, maxsplit=1)
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
        # only asked of internships and student jobs, so a regular posting that mentions students is never hidden
        enrollment_required=(detect_enrollment(text, title)
                             if seniority == "intern" or _STUDENT_TITLE.search(title) else None),
    )
