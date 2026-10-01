"""Tech / non-tech relevance classifier (v1: title rules with a score). Replaced by a learned model later."""

from __future__ import annotations

import re

from radar.extract.sections import job_text

_STRONG = re.compile(
    r"software|(?<!business )(?<!business-)(?<!sales )developer|(?<![a-z])ontwikkelaar|"
    r"(?:applicatie|web|app|database|data|bi|game|portaal|systeem|ict|it)-?ontwikkelaar|programmeur|"
    r"engineer(?!ing\s+manager)|\bdata\b(?! ?cent(?:er|re))|machine learning|(?<!\.)\bml\b(?!\.)|webdesign|"
    r"\bai\b|artificial intelligence|devops|\bsre\b|site reliability|back[- ]?end|front[- ]?end|"
    r"full[- ]?stack|\bqa\b|test automation|tester|security|cloud|platform|architect|embedded|firmware|"
    r"\bfpga\b|\bios\b|android|mobile|web\b|python|java|\.net|c\+\+|golang|scala|kotlin|typescript|react|"
    r"analytics|analist|analyst|scientist|research|robotics|computer vision|\bnlp\b|database|\bdba\b|"
    r"infrastructure|network|systems?\b|\bit\b|\bict\b|informatica|scrum master|product owner|technical|"
    r"solutions?\b|integration|sap\b|salesforce|mendix|low-code|blockchain|\bquant(?:itative)?\b|bi\b|"
    r"business intelligence|cyber|penetration|\bsoc\b|(?<!sales )support engineer|technolog|\bxr\b|\bvr\b|"
    r"augmented reality|virtual reality",
    re.I,
)
_EXCLUDE = re.compile(
    r"\b(sales|account manager|account executive|recruiter|recruitment|talent|hr\b|human resources|marketing|"
    r"finance|accountant|accounting|controller|legal|counsel|lawyer|nurse|verpleeg|arts\b|physician|"
    r"warehouse|magazijn|driver|chauffeur|logistics coordinator|customer service|customer support|"
    r"customer success|office manager|receptionist|cleaner|schoonmaak|barista|chef|cook|kok\b|"
    r"mechanical engineer|civil engineer|electrical (?:design |project |systems? )?engineer|process engineer|"
    r"maintenance engineer|service engineer|field engineer|manufacturing engineer|structural engineer|"
    r"hvac|installation|monteur|technicus|operator|assembly|procurement|inkoop|buyer|planner|"
    r"communications?|content|copywriter|designer(?!\s*\(ux)|graphic|brand|pr\b|events?|community|"
    r"store|retail|shop|cashier|kassa|teacher|docent|coach|trainer|therapist|social worker|"
    r"business development|partnerships?|customer|category manager|capacity manager|supply chain|sourcing|"
    r"commercieel|commercial|credit|fraud|compliance|risk manager|risico ?manager|trader|trading|treasury|payroll|"
    r"partner manager|partnerships? manager|macro|economist|growth marketer|"
    r"bezorg\w*|delivery|rider|courier|fulfil\w*|facility|facilities|housekeeping|security guard|"
    r"(?<!informatie)(?<!cyber)beveilig\w*|"
    r"assistant(?! professor)|assistent|law|(?<!it[- ])auditor|\bsvp\b|\bcoo\b|\bcfo\b|\bceo\b|chief operating|"
    r"chief financial|"
    r"open (?:application|sollicitatie)|co-?founder|secretar\w*|receptie|\[test\]|re-?integratie|klantenservice|"
    r"recruitment business partner|account executive|financial (?:analyst|analist|controller)|"
    r"fp&a|actuar\w*|clinical research|mechanisch\w*|mechanical|elektrotechn\w*|werktuigbouw\w*|communicatie\w*|"
    r"data entry|proces engineer|cost engineer|kosten ?engineer\w*|calculator|physical security)\b",
    re.I,
)
# Rescue fragments: a title containing any of these is tech even if it also contains an excluded word.
# WEAK ones (product names, "IT") do not override an exclusion: "ServiceNow Sales Executive" stays non-tech.
_RESCUE_FRAGMENTS = [
    r"software",
    r"(?<!business )(?<!business-)(?<!sales )developer",
    # not "Gebiedsontwikkelaar", "Projectontwikkelaar", "Curriculumontwikkelaar"
    r"(?<![a-z])ontwikkelaar|(?:applicatie|web|app|database|data|bi|game|portaal|systeem|ict|it)-?ontwikkelaar",
    r"informatiebeveilig\w*",  # information security, not a security guard
    r"network (?:designer|engineer|architect|specialist|administrator)",
    r"netwerk ?(?:specialist|architect|engineer|beheerder)",
    r"(?:mobiele|mobile) (?:netwerk|network)\w*",
    r"data (?:engineer|scientist|analyst|analytics|platform|architect|science)",
    r"data[- ]?anal(?:yst|ist|ytics|yse|ysis)\w*",
    r"data (?:&|and|en) (?:analytics|ai|insights)",
    r"(?<![a-z])data[- ](?:governance|management|quality|consultant|consulting|specialist|modell\w*|modeler|"
    r"strateg\w*|expert|integrity|officer|manager)",
    r"master ?data|\bmdm\b|datakwaliteit|data ?modelleur",
    r"data ?warehous\w*",
    r"enterprise architect\w*",
    r"business architect",
    r"\bpega\b",
    r"information security|\bciso\b|chief information security",
    r"(?:\bit|\bot|ics/ot|network|data|cloud|application|product) security",
    r"security (?:architect|analyst|analist|incident|administrator)",
    r"(?:functione(?:el|le)|functional|automation|software|performance|test) ?tester",
    r"\bnetworking\b",
    r"network operations",
    r"infrastructure automation",
    r"process mining",
    r"machine learning",
    r"(?<!\.)\bml\b(?!\.)",  # not a vacancy code such as "E.26.ML.RK.31"
    r"devops",
    r"back[- ]?end",
    r"front[- ]?end",
    r"modern workplace",
    r"(?:microsoft|office) 365",
    r"\bm365\b",
    r"intune",
    r"\bwindows (?:server|systems?|engineer|admin\w*|beheer\w*|automation)",
    r"\b(?:iam|pam)\b",
    r"identity (?:&|and) access",
    r"technical product (?:manager|owner|lead)",
    r"technical program(?:me)? manager",
    r"\bplc[- ]?(?:engineer|programmeur|programmer|software|developer|ontwikkelaar)",
    r"\basic\b",
    r"release (?:manager|engineer|coordinator)",
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
    r"(?<!sales )support engineer",  # not "Technical Sales Support Engineer"
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
    r"(?<!customer )(?<!klanten)service ?desk",
    r"helpdesk",
    r"(?:microsoft|m365|office 365|systems?|linux|windows|network|netwerk|database|it|ict) ?administrator",
    r"gen ?ai\b",
    r"generative ai",
    r"\bllms?\b",
    r"threat intel\w*",
    r"\bcti\b",
    r"web ?development",
    r"webdevelop\w*",
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
    r"\bsap\b (?:[\w/&-]+ )?(?:developer|consultant|architect|abap|specialist)",  # also "SAP Retail Consultant"
    r"\bsap (?:s/4 ?hana|fico|fi/co|sd|mm|ewm|successfactors|ariba|procurement|bw|basis|btp|cx|hcm|pp|pm|qm|wm|tm)\b",
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
    r"data ?cent(?:er|re)",  # "Beveiliger datacenter" is a security guard
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


# "Developer" and "ontwikkelaar" outside software: business and real-estate development, Dutch installation and
# energy-project developers ("Technisch Ontwikkelaar Werktuigbouwkunde", "Ontwikkelaar Duurzame Energie").
_NON_SOFTWARE_DEVELOPER = re.compile(
    r"\b(?:business|sales|property|real estate|commercieel|commerciële|technisch|project|plan|gebieds|vastgoed)[ -]?"
    r"(?:developer|ontwikkelaar)\b|"
    r"\bontwikkelaar\b.*\b(?:duurzame|energie\w*|warmte\w*|bouw|nieuwbouw|vastgoed|werktuigbouw\w*|elektrotechniek|"
    r"utiliteit\w*|installatie\w*|wind|zon)\b",
    re.I,
)
# Commercial, business and care roles that stay non-tech even when the title names a tech product or field
# ("Cortex & Cloud Sales Specialist", "Category Manager IT - Software & Cloud", "Sales Developer Semiconductor",
# "A.26.ML.MS.16 CCU Verpleegkundige").
_NON_TECH_ROLE = re.compile(
    r"\b(?:account (?:executive|manager|director)|accountmanager|sales (?:executive|manager|director|representative|"
    r"rep|specialist|lead|developer|consultant|agent|medewerker|partner|associate|professional)|"
    r"business develop\w*|[bs]dr|partner(?:ship)?s? manager|product marketing|marketing manager|growth marketer|"
    r"category manager|recruit\w*|talent acquisition|(?<!it )(?<!ict )(?<!cyber )(?<!security )risk manager|"
    r"risico ?manager|facilities|commercial (?:lead|director|manager|officer)|payroll|"
    r"\w*verpleegkundig\w*|nurse|physician)\b",
    re.I,
)
# role nouns that keep a commercial title technical ("Sales Engineer", "Marketing Data Analyst")
_TECH_ROLE_NOUN = re.compile(
    r"engineer|architect|scientist|analyst|analist|product owner|beheerder|programmeur|"
    r"(?<!business )(?<!sales )developer|(?<![a-z])ontwikkelaar|consultant(?<!sales consultant)",
    re.I,
)


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
    r"business (?:and|en|&) it\b|\bdevelopers\b|\bontwikkelaars\b|information flows|informatiestromen|"
    # IT infrastructure and workplace administration, web and chip-design work
    r"windows server|powershell|active directory|entra id|\bintune\b|\bvmware\b|\bcitrix\b|exchange online|"
    r"(?:microsoft|office) 365|\bm365\b|firewall\w*|\bvpn\b|tcp/ip|\bcisco\b|\bitil\b|"
    r"(?:business|organisatie) (?:naar|to) it\b|\bit[- ](?:oplossingen|solutions|systemen|landschap|architectuur)|"
    r"\bhtml\b|\bcss\b|\bphp\b|\bfirmware\b|\bfpga\b|\bverilog\b|systemverilog|\bvhdl\b|data ?warehous\w*|\betl\b|"
    r"\bswift\b|\bkotlin\b|react native|\bios\b|\bandroid\b|"
    # information security work
    r"iso ?27001|\bisms\b|\bnis ?2\b|\bsiem\b|\bpki\b|vulnerabilit\w*|pentest\w*|penetration test\w*",
    re.I,
)


def tech_score(title: str, description: str = "") -> float:
    """Return a score in [0, 1]; >= 0.5 counts as tech."""
    score = _title_score(title, description)
    if score >= 0.5 and _generic_title(title) and len((description or "").strip()) >= 100 and \
            not _role_evidence(title, description or "", early=bool(_EARLY.search(title or ""))):
        # "Starter Scientist Military CFD", "Cost Engineer", "Electrical Project Engineer": the title only says
        # "professional", and the role text shows no real software work (one generic word such as "our ERP",
        # "AI" or "ICT allowance", or Python as a research tool), so this is another field's engineering or science.
        # A short teaser ("Sales Engineer" with two lines about the client) counts the same way; only a missing text
        # is no evidence either way.
        return 0.3
    return score


# Field words that make an internship or traineeship title non-tech ("Art Development Intern", "Copywriting Intern",
# "Generalist Intern", "Stage Werkvoorbereider"); only consulted when the title has no tech word of its own.
_EARLY_NONTECH = re.compile(
    r"\b(?:art|artist|creative|creatief|copy\w*|motion|visual|video|media|social|redactie\w*|journalis\w*|editor\w*|"
    r"newsletters?|nieuwsbrie\w*|communicati\w*|strateg\w*|generalist|operations?|operationeel|people|"
    r"learning (?:&|and) development|l&d|legal|paralegal|jurist\w*|advoca\w*|law|juridisch\w*|privacy recht|"
    r"audit\w*|tax|fiscal\w*|belasting\w*|actuar\w*|financ\w*|banking|wealth|investment|controlling|"
    r"business (?:control|planning|management|operations|design|development)|commerc\w*|revenue|pricing|growth|"
    r"e-?commerce|impact|esg|diversity|inclusion|hse|veiligheid|general manager|founder'?s?|client success|"
    r"royalty|werkvoorbereid\w*|projectleid\w*|project ?(?:management|office|coordinat\w*)|civiele|bouw\w*|"
    r"geohydrolog\w*|zorg\w*|chemi\w*|chemical|packaging|f&b|hospitality|hotel|culinar\w*|food|voeding|"
    r"kwaliteit\w*|quality|procurement|purchasing|inkoop|supply chain|logistic\w*|lean|manufacturing|"
    r"industrial design|product design|interior|architectuur|bekisting\w*|production management|retail|fashion|"
    r"event\w*|hr|human resources|recruit\w*|talent|lunch|administrati\w*|secretar\w*|office)\b",
    re.I,
)
# Signal words that company introductions use as freely as role texts ("our AI-driven platform", "cloud software",
# "digital transformation", "our CRM", "Power BI"): they need a specific signal next to them.
_WEAK_SIGNAL = re.compile(  # matched against the normalised form: lower case, no spaces or hyphens, no plural s
    r"^(?:ai|artificialintelligence|cloud|software|ict|crm|erp|sap|saas|dashboard\w*|powerbi|tableau|"
    r"digital\w*transform\w*|agile|"
    r"cyber\w*|applicatie|database|dataanalytic|informationtechnology|informatietechnologie|business(?:and|en|&)it|"
    r"developer|ontwikkelaar|datascien\w*|api'?|backlog|informationflow|informatiestromen|"
    r"robotic\w*|robotica|algorithm\w*|algoritm\w*)$",
    re.I,
)


# Role-text words that show the intern does IT, software or chip-design work but that are too specific (or too
# Dutch) for the general software-signal list: study fields, IT frameworks, hardware description languages.
_EARLY_TECH_TEXT = re.compile(
    r"\b(?:hdl|informatica|computer science|software engineering|front-?end|back-?end|full-?stack|"
    r"web ?development|webdevelop\w*|wordpress|unity|unreal|augmented reality|virtual reality|xr|"
    r"it[- ](?:support|thema|organisatie|beheer|security|infrastructure)|systeembeheer|systeemmanagement|"
    r"netwerkbeheer|servicedesk|service desk|helpdesk|data engineer\w*|data[- ]?anal(?:yst|ist)\w*|data analytics|"
    r"business intelligence|bi[- ]tools?|security monitoring|embedded|robotic\w*|computer vision|algorithm\w*|"
    r"algoritm\w*)\b",
    re.I,
)


# "Python", "MATLAB", "programming" in a physics, chemistry or civil-engineering internship are a research tool, not
# the job: together they count as one piece of evidence.
_GENERIC_CODING = re.compile(r"^(?:python|matlab|julia|fortran|programm\w*|programmeer\w*|coding|scripting)$", re.I)


def _role_evidence(title: str, description: str, early: bool = False) -> bool:
    """True when the role text (or, without section headers, the whole text) shows hands-on software, IT or data
    work: two specific signals, or one with two generic ones. Used when the title names no tech field."""
    role = job_text(description)
    text = title + "\n" + (role if role is not None else description[:8000])
    found = software_signals(text)
    if early:
        found |= {m.group(0) for m in _EARLY_TECH_TEXT.finditer(text)}
    sig = {re.sub(r"[\s-]+", "", s.lower()).rstrip("s") or s for s in found}  # "Power BI" = "powerbi", "dashboards"
    sig = {"ai" if s == "artificialintelligence" else s for s in sig}
    coding = {s for s in sig if _GENERIC_CODING.match(s)}
    sig = (sig - coding) | ({"<coding>"} if coding else set())
    strong = {s for s in sig if not _WEAK_SIGNAL.match(s)}
    weak = sig - strong
    if role is None and early:
        # an internship text without section headers still holds the company introduction ("our AI platform",
        # "cloud software"), which at tech companies is all an art or copywriting intern posting has in common with tech
        return len(strong) >= 2 or (len(strong) >= 1 and len(weak) >= 3)
    if not early and len(weak) >= 4:
        return True  # a pre-sales or consulting text about cloud, AI, cyber and SaaS products
    return len(strong) >= 2 or (len(strong) >= 1 and len(weak) >= 2)


def software_signals(description: str) -> set[str]:
    """Distinct software, IT or data terms in a text ("python", "sql", "agile", ...)."""
    return {" ".join(m.group(0).lower().split()) for m in _SOFTWARE_TEXT.finditer(description or "")}


# Title words that name tech in one field and something else in another: "Platform" (Schiphol's apron), "Data" next to
# reporting or entry, "Networks" (power grids), "Security" (guards), "Architect" (buildings, landscapes), "Tester"
# (products), "Integration" (M&A). On their own they make a title as unspecific as "Engineer" does.
_AMBIGUOUS_TITLE = re.compile(
    r"\b(?:data|platforms?|integration|networks?|security|infrastructure|analytics|tester|mobile)\b|"
    r"architect\w*|analist|analyst|engineer",  # also inside compounds: "Landschapsarchitect", "Zaaksanalist"
    re.I,
)


def _generic_title(title: str) -> bool:
    t = title or ""
    matches = [m.group(0) for m in _STRONG.finditer(t)]
    if not matches and not _GENERIC_TITLE.search(t):
        return False
    # a tech phrase that is more than generic words ("Support Engineer", "Data Scientist") makes the title specific,
    # and so does a product name ("Azure Competence Lead", "ServiceNow Specialist")
    for m in _RESCUE.finditer(t):
        if _GENERIC_TITLE.sub("", m.group(0)).strip(" -/"):
            return False
    for s in matches:
        if _AMBIGUOUS_TITLE.sub("", _GENERIC_TITLE.sub("", s)).strip(" -/"):
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
    m = _NON_TECH_ROLE.search(t)
    if m and not _TECH_ROLE_NOUN.search(t[:m.start()] + " " + t[m.end():]):
        return 0.1
    if _NON_SOFTWARE_DEVELOPER.search(t) and not _RESCUE_STRONG.search(_NON_SOFTWARE_DEVELOPER.sub(" ", t)):
        return 0.1
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
        # "Graduate Programme 2027", "Traineeship", "Afstudeerstage": the title names no tech field, so the role
        # text decides. A field word ("Art Development Intern", "Copywriting Intern", "Paralegal Intern") settles it
        # as non-tech, and generic words in the company introduction ("our platform", "data", "AI") do not count.
        if _EARLY_NONTECH.search(t):
            return 0.2
        return 0.6 if _role_evidence(t, description or "", early=True) else 0.3
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
