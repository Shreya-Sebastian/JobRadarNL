"""Tech / non-tech relevance classifier (v1: title rules with a score). Replaced by a learned model later."""

from __future__ import annotations

import re

_STRONG = re.compile(
    r"software|developer|ontwikkelaar|programmeur|engineer(?!ing\s+manager)|\bdata\b|machine learning|\bml\b|"
    r"\bai\b|artificial intelligence|devops|\bsre\b|site reliability|backend|back-end|frontend|front-end|"
    r"full[- ]?stack|\bqa\b|test automation|tester|security|cloud|platform|architect|embedded|firmware|"
    r"\bfpga\b|\bios\b|android|mobile|web\b|python|java|\.net|c\+\+|golang|scala|kotlin|typescript|react|"
    r"analytics|analist|analyst|scientist|research|robotics|computer vision|\bnlp\b|database|\bdba\b|"
    r"infrastructure|network|systems?\b|\bit\b|\bict\b|informatica|scrum master|product owner|technical|"
    r"solutions?\b|integration|sap\b|salesforce|mendix|low-code|blockchain|quant|bi\b|business intelligence|"
    r"cyber|penetration|\bsoc\b|support engineer|technolog",
    re.I,
)
_EXCLUDE = re.compile(
    r"\b(sales|account manager|account executive|recruiter|recruitment|talent|hr\b|human resources|marketing|"
    r"finance|accountant|accounting|controller|legal|counsel|lawyer|nurse|verpleeg|arts\b|physician|"
    r"warehouse|magazijn|driver|chauffeur|logistics coordinator|customer service|customer support|"
    r"customer success|office manager|receptionist|cleaner|schoonmaak|barista|chef|cook|kok\b|"
    r"mechanical engineer|civil engineer|electrical engineer|process engineer|maintenance engineer|"
    r"service engineer|field engineer|quality engineer|manufacturing engineer|structural engineer|"
    r"hvac|installation|monteur|technicus|operator|assembly|procurement|inkoop|buyer|planner|"
    r"communications?|content|copywriter|designer(?!\s*\(ux)|graphic|brand|pr\b|events?|community|"
    r"store|retail|shop|cashier|kassa|teacher|docent|coach|trainer|therapist|social worker|"
    r"business development|partnerships?|customer|category manager|capacity manager|supply chain|sourcing|"
    r"commercieel|commercial|credit|fraud|compliance|risk manager|trader|trading|treasury|payroll|procurement|"
    r"partner manager|partnerships? manager|macro|economist|growth marketer|"
    r"bezorg\w*|delivery|rider|courier|fulfil\w*|facility|facilities|housekeeping|security guard|"
    r"(?<!informatie)(?<!cyber)beveilig\w*|"
    r"assistant(?! professor)|assistent|(?<!it[- ])auditor|\bsvp\b|\bcoo\b|\bcfo\b|\bceo\b|chief operating|"
    r"chief financial|"
    r"open (?:application|sollicitatie)|co-?founder|secretar\w*|receptie|\[test\]|re-?integratie|klantenservice|"
    r"recruitment business partner|account executive)\b",
    re.I,
)
# Rescue fragments: a title containing any of these is tech even if it also contains an excluded word.
# WEAK ones (product names, "IT") do not override an exclusion: "ServiceNow Sales Executive" stays non-tech.
_RESCUE_FRAGMENTS = [
    r"software",
    r"developer",
    r"ontwikkelaar",
    r"informatiebeveilig\w*",  # information security, not a security guard
    r"network (?:designer|engineer|architect|specialist|administrator)",
    r"netwerk(?:specialist|architect|engineer|beheerder)",
    r"data (?:engineer|scientist|analyst|analytics|platform|architect|science)",
    r"machine learning",
    r"\bml\b",
    r"devops",
    r"backend",
    r"back-end",
    r"frontend",
    r"front-end",
    r"full[- ]?stack",
    r"programm(?:er|ing|eur)",
    r"security engineer",
    r"cloud engineer",
    r"platform engineer",
    r"\bux\b",
    r"python",
    r"\bjava\b",
    r"analytics engineer",
    r"solutions? (?:engineer|architect)",
    r"sales engineer",
    r"support engineer",
    r"cyber",
    r"scientist",
    r"development team",
    r"software development",
    r"engineering manager",
    r"\bsre\b",
    r"site reliability",
    r"kubernetes",
    r"\.net\b",
    r"golang",
    r"typescript",
    r"embedded",
    r"firmware",
    r"\bqa\b",
    r"test automation",
    # Dutch IT titles
    r"systeembeheer",
    r"werkplekbeheer",
    r"applicatiebeheer",
    r"applicatie ?beheerder",
    r"functioneel beheer",
    r"technisch applicatie",
    r"netwerkbeheer",
    r"databasebeheer",
    r"\bict\b",
    r"softwareontwikkel",
    r"software ?engineer",
    r"programmeur",
    r"informatie-?analist",
    r"data-?analist",
    r"bi-?specialist",
    r"bi-?consultant",
    r"servicedesk",
    r"helpdesk",
    r"it-?specialist",
    r"it-?consultant",
    r"it-?beheer",
    r"devrel",
    r"\brust\b",
    r"\bscala\b",
    r"\bkotlin\b",
    r"\bc\+\+",
    r"\bc#",
    r"salesforce (?:developer|consultant|architect|engineer)",
    r"\bsap\b (?:developer|consultant|architect|abap|specialist)",
    r"low-?code",
    r"mendix",
    r"outsystems",
    r"detection engineer",
    r"data ?steward",
    r"power ?platform",
    r"cloud",
    r"informatica",
    r"tech ?lead",
    r"tech(?:nical)? (?:lead|architect|consultant|engineer)",
    r"devsecops",
    r"(?<![a-z-])integratie ?(?:specialist|architect|consultant|ontwikkelaar|engineer)",  # not "re-integratie"
    r"integration (?:specialist|engineer|consultant|architect|developer)",
    r"vulnerab\w*",
    r"patch management",
    r"testautomat\w*",
    r"it support",
    r"ai assistant",
    r"product owner",
    r"abap",
    # specialist engineering and science fields that are tech even when the title also says "designer",
    # "trading" or "communication" (which the exclusion list uses for graphic design, trading desks and PR)
    r"simulat\w*",
    r"\bcfd\b",
    r"computational",
    r"numerical model\w*",
    r"finite[- ]element",
    r"\bfea\b",
    r"\bfem\b(?! ?-?vrouw)",
    r"multiphysics",
    r"digital twin",
    r"\b(?:rf|microwave|analog|mixed[- ]signal|asic|fpga|ic|chip) ?(?:/ ?microwave )?(?:ic )?design(?:er)?\b",
    r"photonic\w*",
    r"remote sensing",
    r"\bgis\b",
    r"geo-?data",
    r"geospatial",
    r"bioinformati\w*",
    r"quantum",
    r"game (?:developer|designer|programmer|engineer)",
    r"gameplay",
    r"trading systems?",
    r"\bnoc\b",
    r"\bpcb\b",
    r"\brf engineer",
    r"forward[- ]deployed",
    r"(?:it|ict|technical|application) support (?:engineer|specialist|analyst)",
    r"communication systems? engineer",
    r"systems? engineer",
]
_WEAK_RESCUE_FRAGMENTS = [
    r"datacenter",  # "Beveiliger datacenter" is a security guard
    r"\bit\b",
    r"servicenow",
    r"dynatrace",
    r"splunk",
    r"datadog",
    r"observability",
    r"azure",
]
_RESCUE = re.compile("|".join(_RESCUE_FRAGMENTS + _WEAK_RESCUE_FRAGMENTS), re.I)
_RESCUE_STRONG = re.compile("|".join(_RESCUE_FRAGMENTS), re.I)


_EARLY = re.compile(
    r"graduate|trainee|traineeship|internship|\bintern\b|\bstage\b|stagiair|afstudeer|werkstudent|working student|"
    r"young professional|starter|graduation|thesis",
    re.I,
)


_SIMULATION = re.compile(
    r"simulat\w*|\bcfd\b|computational fluid|finite[- ]element|\bfea\b|\bfem\b|multiphysics|\bansys\b|\babaqus\b|"
    r"\bcomsol\b|openfoam|star-?ccm|ls-?dyna|\bnastran\b|simulink|digital twin|numerical model\w*|"
    r"computational (?:model\w*|mechanic\w*|physics)",
    re.I,
)
_ENGINEERING_TITLE = re.compile(
    r"engineer|ingenieur|\bphd\b|promov\w*|postdoc|research\w*|scientist|onderzoeker|analyst|"
    r"intern(?:ship)?\b|\bstage\b|afstudeer\w*|thesis|graduation",
    re.I,
)
_COMMERCIAL_TITLE = re.compile(r"sales|account|business development|marketing|recruit|trader|trading|"
                               r"project manager|projectleider|director|\bhead of\b|\bpmo\b", re.I)


# Title words that say "a professional" but not which field: "Scientist", "Engineer", "Researcher", "Analyst",
# "PhD", plus simulation words (CFD, FEA), which describe the tooling of mechanical, civil and maritime engineers as
# much as of software people. A title made only of these is tech only when the text shows software, IT or data work.
_GENERIC_TITLE = re.compile(
    r"\b(?:senior|junior|starter|medior|lead|principal|staff|chief|expert|young|graduate|trainee|"
    r"research|scientists?|researchers?|onderzoek\w*|engineers?|engineering|ingenieurs?|\bphd\b|postdoc\w*|promov\w*|"
    r"analysts?|analist(?:en)?|specialist|consultant|adviseur|advisor|"
    r"simulat\w*|cfd|computational|numerical|model\w*|finite[- ]element|fea|fem|multiphysics|"
    # words that sound technical but name no field: "Sales Engineer", "System Engineer", "Technical Lead",
    # "Advanced Dispensing Systems", "Project Engineer" are as often mechanical, electrical or civil
    r"sales|systems?|technical|technisch\w*|solutions?|technolog\w*|projects?)\b",
    re.I,
)
_SOFTWARE_TEXT = re.compile(
    # "rust" alone is the Dutch word for rest, so the language needs context
    r"\bpython\b|c\+\+|\bfortran\b|\bjulia\b|\bc#|\brust(?: programming|lang|-lang| developer|, | and |/)|"
    r"\bjava\b|\bmatlab\b|\bprogramm(?:ing|er|eur|eren)\b|javascript|typescript|\breact\b|\.net\b|\bgolang\b|"
    r"kubernetes|\bdocker\b|terraform|ansible|\baws\b|\bazure\b|\bgcp\b|devops|ci/cd|\bmicroservices?\b|"
    r"\bprogrammeer\w*|\bscripting\b|\bcoding\b|\bsoftware\b|softwareontwikkel\w*|"
    r"(?:develop\w*|ontwikkel\w*|implement\w*|writ\w*|maintain\w*) (?:\w+ ){0,3}(?:code|solvers?|algorithms?)\b|"
    r"\bhpc\b|high[- ]performance computing|parallel computing|\bgpu\b|\bcuda\b|\bmpi\b|machine learning|"
    r"deep learning|\bai\b|artificial intelligence|data scien\w*|\bsql\b|\blinux\b|\bgit\b|\bcloud\b|"
    r"(?:computer|it|ict|data|mobile|telecom|5g) ?networks?|network (?:engineer\w*|security|infrastructure|protocols?)|"
    r"netwerk(?:beheer|infrastructuur|engineer)\w*|\bict\b|\bit[- ](?:systems?|infrastructure|security|omgeving)|"
    r"cyber\w*|informati(?:on|e)(?:systemen| systems| security| technology|technologie)|"
    r"\bhris\b|\berp\b|\bsap\b|\bcrm\b|power ?bi|tableau|dashboard\w*|database\w*|\bapi'?s?\b|"
    r"applicati(?:on|e)(?:beheer| management| support| landscape)|"
    r"\bplc\b|\bscada\b|automatiseringssystemen|\bsaas\b|\berp-|digitale? (?:transformatie|transformation)|"
    r"\bpega\b|outsystems|mendix|\bapplicaties\b|user stor(?:y|ies)|\bbacklog\b|\bscrum\b|\bagile\b|"
    r"business (?:and|en|&) it\b|\bdevelopers\b|\bontwikkelaars\b|information flows|informatiestromen",
    re.I,
)


def tech_score(title: str, description: str = "") -> float:
    """Return a score in [0, 1]; >= 0.5 counts as tech."""
    score = _title_score(title, description)
    if score >= 0.5 and _generic_title(title) and len((description or "").strip()) >= 100 and \
            len(software_signals(description)) < 2:
        # "Starter Scientist Military CFD", "Cost Engineer", "Electrical Project Engineer": the title only says
        # "professional", and the text shows at most one software word (often boilerplate such as "our ERP" or
        # "ICT allowance"), so this is another field's engineering or science. A short teaser ("Sales Engineer"
        # with two lines about the client) counts the same way; only a missing text is no evidence either way.
        return 0.3
    return score


def software_signals(description: str) -> set[str]:
    """Distinct software, IT or data terms in a text ("python", "sql", "agile", ...)."""
    return {" ".join(m.group(0).lower().split()) for m in _SOFTWARE_TEXT.finditer(description or "")}


def _generic_title(title: str) -> bool:
    t = title or ""
    if not _GENERIC_TITLE.search(t):
        return False
    # a tech phrase that is more than generic words ("Support Engineer", "Data Scientist") makes the title specific,
    # and so does a product name ("Azure Competence Lead", "ServiceNow Specialist")
    for rx in (_RESCUE, _STRONG):
        for m in rx.finditer(t):
            if _GENERIC_TITLE.sub("", m.group(0)).strip(" -/"):
                return False
    return True


def _title_score(title: str, description: str = "") -> float:
    t = title or ""
    if re.search(r"open (?:application|sollicitatie)|\[test\]|spontan\w* (?:application|sollicitatie)|"
                 r"talent ?pool|talent community|future opportunit\w*|general application|expression of interest|"
                 r"interest list|reservelijst|aanmelden (?:voor )?(?:de |onze )?talent|"
                 r"\btest ?vacature|\btest ?template|\bdummy\b|do not apply|niet (?:op )?reageren", t, re.I):
        return 0.05  # not a vacancy (open application, talent pool), whatever the domain words say
    excluded = bool(_EXCLUDE.search(t))
    if _ENGINEERING_TITLE.search(t) and not _COMMERCIAL_TITLE.search(t) and \
            len(_SIMULATION.findall(description or "")) >= 4:
        # "Mechanical Engineer", "Structural Engineer", "PhD position ..." whose text is about FEA, CFD, Ansys or
        # multiphysics: simulation engineering is tech even though the title alone reads as mechanical/civil
        return 0.85
    if _RESCUE.search(t):
        # Product names and "IT" are weak evidence next to a sales, recruiting or support title
        # ("ServiceNow Sales Executive", "Category Manager Entertainment & IT"); real role words win over exclusions.
        if excluded and not _RESCUE_STRONG.search(t):
            return 0.1
        return 0.95
    if excluded:
        return 0.1
    if _STRONG.search(t):
        return 0.8
    head = (description or "")[:2500]
    hits = len(_STRONG.findall(head))
    if _EARLY.search(t):
        # "Graduate Programme 2027", "Traineeship", "Afstudeerstage": the title says nothing about the domain,
        # so let the description decide. Never exclude early-career roles on the title alone.
        return 0.6 if hits >= 3 else 0.3
    # Title says nothing ("Consultant", "Specialist", "Medewerker"): three or more hard technical skills in the
    # text (languages, cloud, infrastructure tooling) make it a tech role.
    if hard_skill_count(description or "") >= 4:
        return 0.6
    return min(0.45, 0.05 * hits)


_HARD_SKILLS = {
    "Python",
    "Java",
    "JavaScript",
    "TypeScript",
    "C++",
    "C#",
    ".NET",
    "Go",
    "Rust",
    "Kotlin",
    "Scala",
    "SQL",
    "React",
    "Angular",
    "Vue",
    "Node.js",
    "Django",
    "Spring",
    "AWS",
    "Azure",
    "GCP",
    "Docker",
    "Kubernetes",
    "Terraform",
    "CI/CD",
    "Linux",
    "Git",
    "PostgreSQL",
    "MySQL",
    "MongoDB",
    "Kafka",
    "Spark",
    "Databricks",
    "PyTorch",
    "TensorFlow",
    "MLOps",
    "Airflow",
    "dbt",
    "Elasticsearch",
    "Redis",
    "Ansible",
    "Embedded",
    "Simulation/CAE",
    "MATLAB",
}


def hard_skill_count(description: str) -> int:
    from radar.taxonomy import find_skills

    return len(set(find_skills(description[:8000])) & _HARD_SKILLS)


def is_tech(title: str, description: str = "") -> bool:
    return tech_score(title, description) >= 0.5
