"""Split a posting into the part about the job and the part about the company.

Skills belong to the role and requirements sections. The company introduction, "about us", the benefits and the
application process often name the employer's own products and customers' tools ("our SDKs support Python, Ruby
and Go"), which are not requirements. When a posting has recognisable section headers, `job_text` returns only
the role and requirement sections; without headers it returns None and the caller keeps its old behaviour.
"""

from __future__ import annotations

import re

# header lines that start a section about the job itself
_JOB = re.compile(
    r"^(?:responsibilit|key responsibilit|key requirements|the impact you(?:'|’)?ll have|the impact you will have|"
    r"what we look for|what (?:we(?:'|’)?d|we would) love|your (?:core )?responsibilit|"
    r"what you(?:'|’)?ll (?:do|own|work on|bring)|"
    r"what you will (?:do|own|work on)|you will\b|in this role|your role|the role|about the (?:role|job|position)|"
    r"job description|role description|the job|the position|your mission|"
    r"qualifications|requirements|requirement|what you bring|what (?:we(?:'|’)?re|we are) looking for|"
    r"who (?:you are|we(?:'|’)?re looking for|we are looking for)|about you|your profile|profile|"
    r"your (?:skills|experience|background)|skills|you have|you bring|must[- ]haves?|nice[- ]to[- ]haves?|"
    r"(?:the |our )?tech(?:nology)? stack|our stack|technologies|tools (?:we use|you(?:'|’)?ll use)|about the team|"
    r"(?:wat|dit) (?:ga je doen|je gaat doen)|wat je gaat doen|dit ga je doen|jouw rol|de rol|de functie|"
    r"functieomschrijving|vacatureomschrijving|je werkzaamheden|werkzaamheden|taken en verantwoordelijkheden|"
    r"jouw taken|functie-?eisen|(?:wat|dit) (?:breng|neem) (?:je|jij) mee|wat je meebrengt|wie ben jij|dit ben jij|"
    r"(?:wat|dit) heb je nodig|wat vragen wij|wat we vragen|wat wij vragen|wie zoeken (?:wij|we)|ons zoekprofiel|"
    r"jij hebt|jouw profiel|jouw achtergrond|jouw vaardigheden|competenties|kennis en ervaring|daarnaast beschik je|"
    r"verder heb je|jouw team|het team)",
    re.I,
)
# header lines that start a section about the company, the offer or the application
_COMPANY = re.compile(
    r"^(?:about us|about (?!the role|the job|the position|you\b|the team)[\w&.' -]{2,40}$|company description|"
    r"who we are|our (?:mission|story|company|culture)|the company|"
    r"what we offer|we offer|what do we offer|what(?:'|’)?s in it for you|benefits|perks|compensation|salary|"
    r"our offer|why (?:join|us|work)|interview process|application process|how to apply|"
    r"equal (?:employment|opportunit)|"
    r"diversity|additional information|location|language|highlights?|"
    r"bedrijfsomschrijving|over ons|over de (?:opdrachtgever|organisatie|werkgever)|wie zijn (?:wij|we)|"
    r"hier ga je werken|waar ga je werken|onze missie|wat (?:bieden|krijg) (?:wij|we|je)|wat wij bieden|wij bieden|"
    r"dit bieden wij|wat je ervoor terugkrijgt|arbeidsvoorwaarden|salaris|solliciteren|sollicitatie|interesse|"
    r"interested|aanvullende informatie|waarom|jouw toekomst)",
    re.I,
)


# sentences in the introduction that describe the job rather than the company
_ROLE_CUE = re.compile(
    r"\byou(?:'|’)?ll\b|\byou will\b|\b(?:is|are|will be) responsible for\b|\byou(?:'|’)?re\b|\byou are\b|"
    r"\bas an? \w+|\bin this role\b|\bthe role\b|"
    r"(?:we(?:'|’)?re|we are|is) (?:looking for|seeking|hiring)|\bjoin (?:our|the) \w+ team\b|"
    r"\bje gaat\b|\bals \w+ (?:ga|werk|ben) je\b|\bjij gaat\b|(?:wij|we) zoeken\b|(?:zijn|is) (?:wij )?op zoek\b|"
    r"\bin deze (?:rol|functie)\b",
    re.I,
)


# lines that state a requirement wherever they appear (some sites put "you have experience with ..." under an
# odd header such as "What do you get?")
_REQ_CUE = re.compile(
    r"\bexperience (?:with|in|using)\b|\bexperienced (?:with|in)\b|\bproficien\w*|\bfamiliar(?:ity)? with\b|"
    r"\bknowledge of\b|\byou have\b|\bbonus points?\b|\bnice to have\b|\ba plus\b|"
    r"\bervaring (?:met|in)\b|\bkennis (?:van|heeft|hebt)\b|\bje hebt\b|\bjij hebt\b|\bpluspunt\w*|\bbonuspunt\w*|"
    r"\bbekend met\b|\bis een pre\b",
    re.I,
)
_BULLET = re.compile(r"^\s*(?:[-•*·▪●–]|\d+[.)])\s+")


def _task_line(line: str) -> bool:
    """A bullet or a short line without a full stop: a task or skill list, not company prose."""
    t = line.strip()
    return bool(t) and (bool(_BULLET.match(line)) or (len(t) < 100 and not t.endswith((".", "!", "?"))))


def _header(line: str) -> str | None:
    """'job' or 'company' when a line is a section header, else None."""
    t = line.strip().strip("#*•-–:").strip()
    if not t or len(t) > 70 or len(t.split()) > 9 or t.endswith((".", ",", ";")):
        return None
    t = t.rstrip(":?! ").strip()
    if _COMPANY.search(t):
        return "company"
    if _JOB.search(t):
        return "job"
    return None


def job_text(text: str) -> str | None:
    """The role and requirement sections of a posting, or None when it has no recognisable job header."""
    kind, kept, found = "intro", [], False
    for line in (text or "").splitlines():
        h = _header(line)
        if h:
            kind = h
            found = found or h == "job"
            if h == "job":
                kept.append(line)  # keep the header itself: "Nice to have" still marks the optional skills
            continue
        if kind == "job" or _REQ_CUE.search(line) or \
                (kind == "intro" and (_ROLE_CUE.search(line) or _task_line(line))):
            kept.append(line)
    return "\n".join(kept) if found and any(x.strip() for x in kept) else None
