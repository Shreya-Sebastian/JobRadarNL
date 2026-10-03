"""Position types: the job a title names, in the words people search for ("Data Engineer", "Product Owner").

The list comes from the most common titles on the radar once level words, gender tags, locations and Dutch/English
spellings are set aside (`ontwikkelaar` is a developer, `beheerder` an administrator). The first type whose pattern
matches the title wins, so the specific ones come first: "Test Automation Engineer" is QA, not a software engineer.
A title that matches none is "other".
"""

from __future__ import annotations

import re
from functools import lru_cache

# (key, English label, Dutch label, pattern on the cleaned title)
_TYPES: list[tuple[str, str, str, str]] = [
    ("phd_research", "PhD / research", "PhD / onderzoek",
     r"\bphd\b|\bpostdoc|\bpromov|research (?:scientist|engineer|fellow|associate)|\bresearcher\b|onderzoeker|"
     r"wetenschappelijk|research intern"),
    ("product_manager", "Product manager", "Productmanager",
     r"product ?manager|product lead|head of product|product director|productmanagement"),
    ("product_owner", "Product owner", "Product owner", r"product ?owner"),
    ("scrum_agile", "Scrum master / agile coach", "Scrum master / agile coach",
     r"scrum ?master|agile coach|release train engineer|\brte\b"),
    ("project_manager", "IT project / programme manager", "IT-project- / programmamanager",
     r"project ?manager|projectleider|program(?:me|ma)? ?manager|programmamanager|delivery manager|"
     r"project ?lead|implementatiemanager|implementation manager|projects? director"),
    ("engineering_manager", "Engineering manager", "Engineering manager",
     r"engineering manager|head of (?:engineering|software|development|data|it)|development manager|\bcto\b|"
     r"(?:it|ict) ?manager|manager (?:it|ict|software|development)|teamleider (?:it|ict|ontwikkel)|hoofd (?:it|ict)|"
     r"\bcio\b|director (?:of )?(?:engineering|technology|it)"),
    ("ux_designer", "UX / UI designer", "UX- / UI-designer",
     r"\bux\b|\bui\b|user experience|interaction designer|product designer|service designer"),
    ("security_officer", "Security officer / GRC", "Security officer / GRC",
     r"security officer|\bciso\b|\bgrc\b|privacy officer|\biso\b|risk (?:officer|manager|consultant)|"
     r"compliance (?:officer|specialist)|security (?:governance|awareness)|it audit|\bauditor\b|it control|"
     r"^(?=.*(?:security|cyber|beveilig))(?=.*(?:consultant|adviseur|advisor|toezicht)).*"),
    ("security_engineer", "Security engineer / analyst", "Security engineer / analist",
     r"security|cyber|beveilig|\bsoc\b|pentest\w*|penetration|ethical hack|\biam\b|identity (?:and|&) access|"
     r"threat|vulnerab"),
    ("data_scientist", "Data scientist", "Data scientist", r"data scien"),
    ("ml_engineer", "AI / ML engineer", "AI- / ML-engineer",
     r"\bml\b|mlops|llm|gen ?ai|generative ai|computer vision|\bnlp\b|deep learning|applied scientist|"
     r"prompt engineer|\bai (?:engineer|developer|specialist|scientist|researcher|expert|lead|agent)|"
     r"reinforcement learning"),
    ("data_consultant", "Data / AI consultant", "Data- / AI-consultant",
     r"(?:data|ai|analytics|bi) ?(?:management |strategy |governance )?(?:consultant|adviseur|advisor)|"
     r"data management|data governance|data steward|data quality|\bmdm\b|data manager|data transformation|"
     r"^(?=.*\b(?:data|ai|analytics)\b)(?!.*\b(?:sap|salesforce|dynamics|servicenow)\b|.*engineer)"
     r"(?=.*(?:consultant|adviseur|advisor)).*|(?:data|ai)\b.{0,12}traineeship|traineeship data|"
     r"digital (?:en|and|&) data|master data"),
    ("data_architect", "Data architect", "Data-architect", r"data architect"),
    ("bi_analyst", "BI / data analyst", "BI- / data-analist",
     r"data analy|\bbi\b|business intelligence|power ?bi|tableau|qlik|reporting|analytics (?:analyst|specialist)|"
     r"data specialist|informatie ?analy|insights? analy|process mining|web analy|spotfire|looker|product analy"),
    ("data_engineer", "Data engineer", "Data engineer",
     r"data ?engineer|analytics engineer|data platform|\betl\b|data warehouse|dwh|databricks|data ?ontwikkel"),
    ("business_analyst", "Business / IT analyst", "Business- / IT-analist",
     r"business analy|functioneel analy|functional analy|requirements|it analy|proces ?analy|process analy"),
    ("architect", "Solution / enterprise architect", "Solution- / enterprise-architect",
     r"architect"),
    ("sales_engineer", "Solutions / sales engineer", "Solutions- / sales engineer",
     r"sales engineer|pre-?sales|solutions? engineer|solution consultant|field application|forward deployed|"
     r"customer engineer|technical account manager"),
    ("low_code", "Low-code developer", "Low-code developer",
     r"mendix|outsystems|power ?(?:platform|apps|automate)|low-?code|uipath|\brpa\b"),
    ("embedded", "Embedded / firmware engineer", "Embedded- / firmware-engineer",
     r"embedded|firmware|\bfpga\b|\bvhdl\b|microcontroller"),
    ("plc_automation", "PLC / industrial automation engineer", "PLC- / industriële automatisering",
     r"\bplc\b|scada|\bot\b|industri\w* automati|procesautomati|machine ?besturing|besturingstechni|"
     r"industrial automation"),
    ("hardware", "Hardware / electronics engineer", "Hardware- / elektronica-engineer",
     r"hardware|electronic|elektronic|\brf\b|\bpcb\b|analog|chip design|\basic\b"),
    ("simulation", "Simulation / modelling engineer", "Simulatie- / modelleringsengineer",
     r"simulat|\bcfd\b|\bfea\b|finite element|modell?ing"),
    ("qa_test", "QA / test engineer", "QA- / testengineer",
     r"\btest|\bqa\b|quality assurance|testautomat"),
    ("devops", "DevOps engineer", "DevOps-engineer", r"devops|devsecops|ci/cd|release (?:manager|engineer)"),
    ("platform_sre", "Platform / SRE engineer", "Platform- / SRE-engineer",
     r"platform engineer|site reliability|\bsre\b|platform"),
    ("cloud", "Cloud engineer", "Cloud-engineer", r"cloud|azure|\baws\b|\bgcp\b|kubernetes"),
    ("network", "Network engineer", "Netwerkengineer",
     r"network|netwerk|telecom|firewall|\bnoc\b|routing|switching"),
    ("systems", "Systems / infrastructure engineer", "Systeem- / infrastructuurengineer",
     r"system(?:s)? (?:engineer|administrator|specialist|beheer)|systeem ?(?:beheer|engineer|specialist)|"
     r"infrastructu|infra (?:engineer|specialist)|linux|windows|middleware|storage|database administrator|\bdba\b|"
     r"mainframe|database ?(?:engineer|operations|specialist|beheer)|"
     r"\bi[ct]t? (?:engineer|beheer)\b"),
    ("app_admin", "Application administrator", "Applicatie- / functioneel beheerder",
     r"applicatie ?beheer|functioneel (?:beheer|administrator)|application (?:manager|administrator|specialist|"
     r"management)|technisch applicatie"),
    ("it_support", "IT support / workplace", "IT-support / werkplek",
     r"support|helpdesk|service ?desk|werkplek|workplace|^(?!.*consultant).*(?:microsoft 365|\bm365\b)|intune|"
     r"end ?user|desktop|"
     r"ict medewerker|it medewerker"),
    # a developer on an ERP product builds software: "SAP ABAP Developer", "Senior Oracle Ontwikkelaar"
    ("erp_developer", "Software engineer / developer", "Software engineer / developer",
     r"^(?=.*\b(?:sap|erp|salesforce|dynamics|servicenow|oracle|workday)\b).*\b(?:developer|programmer)\b"),
    ("it_consultant", "IT / ERP consultant", "IT- / ERP-consultant",
     r"\bsap\b|\berp\b|salesforce|dynamics|servicenow|oracle|workday|consultant|adviseur"),
    ("mobile", "Mobile developer", "Mobiele developer",
     r"\bios\b|android|mobile|flutter|react native|swift"),
    ("frontend", "Frontend developer", "Frontend developer",
     r"frontend|front end|react|angular|vue|web developer|webdeveloper|typescript|javascript"),
    ("fullstack", "Full-stack developer", "Full-stack developer", r"fullstack|full stack"),
    ("software_engineer", "Software engineer / developer", "Software engineer / developer",
     r"software|developer|backend|back end|programm|\.net|java|python|golang|\bgo\b|c\+\+|c#|php|ruby|rust|"
     r"scala|integrati|tech(?:nical|nology)? lead|(?:ict|it|web|portaal|portal) ?(?:development|ontwikkeling)"),
    # a bare "AI" when nothing more specific is named: "AI Translator", "Operations & AI Traineeship"
    ("ml_engineer_ai", "AI / ML engineer", "AI- / ML-engineer", r"\bai\b"),
    # "Automation Engineer" alone is most often PLC work; "(PowerPlatform & UiPath)" or "test" says otherwise
    ("plc_automation_any", "PLC / industrial automation engineer", "PLC- / industriële automatisering",
     r"automation engineer"),
    ("software_engineer_any", "Software engineer / developer", "Software engineer / developer",
     r"engineer|engineering"),
]
# extra patterns that report as another type; the weak ones are tried last
_WEAK_KEYS = {"ml_engineer_ai", "software_engineer_any", "plc_automation_any"}
_ALIAS = {"erp_developer": "software_engineer", "ml_engineer_ai": "ml_engineer",
          "software_engineer_any": "software_engineer",
          "plc_automation_any": "plc_automation"}
_MAIN_ONLY = {"ml_engineer_ai"}  # "Creative Director (CGI/AI)" is not an AI engineer
POSITIONS = [k for k, *_ in _TYPES if k not in _ALIAS] + ["other"]
LABELS = {"en": {k: en for k, en, _nl, _rx in _TYPES if k not in _ALIAS} | {"other": "Other"},
          "nl": {k: nl for k, _en, nl, _rx in _TYPES if k not in _ALIAS} | {"other": "Overig"}}
_RX = [(k, re.compile(rx, re.I)) for k, _en, _nl, rx in _TYPES if k not in _WEAK_KEYS]
_WEAK = [(k, re.compile(rx, re.I)) for k, _en, _nl, rx in _TYPES if k in _WEAK_KEYS]

_SPELLING = [(r"ontwikkelaar", "developer"), (r"\bprogrammeur\b", "developer"), (r"\bfront[- ]?end\b", "frontend"),
             (r"\bback[- ]?end\b", "backend"), (r"\bfull[- ]?stack\b", "fullstack"), (r"\bdev[- ]?ops\b", "devops"),
             (r"\bmachine[- ]learning\b", "ml"), (r"\bartificial intelligence\b", "ai"), (r"analist", "analyst"),
             (r"\bbeheerder\b", "beheer"), (r"(?<=\w)-(?=\w)", " ")]  # "Data-analist", "IT-support"


def clean(title: str) -> str:
    """The title without gender tags, brackets and what follows a dash or bar, in one spelling."""
    t = (title or "").lower()
    t = re.sub(r"\b(?:m/v/x|m/v|m/f/x|m/f/d|m/f|f/m/x|v/m|h/f|w/m/d|m/w/d)\b", " ", t)
    for a, b in _SPELLING:
        t = re.sub(a, b, t)
    return " ".join(t.split())


@lru_cache(maxsize=20000)
def position(title: str) -> str:
    """The position type of a title: the main part (brackets dropped, before a dash or "bij") first, then the whole
    title; the weak catch-alls ("engineer", a bare "AI") only when no specific type matched either."""
    full = clean(title)
    main = re.split(r"\s+[-–|]\s+|,\s|\s+(?:bij|at|met|with)\s+", re.sub(r"\([^)]*\)?|\[[^\]]*\]?", " ", full))[0]
    for rules in (_RX, _WEAK):
        for text in (main, full):
            for key, rx in rules:
                if text is full and key in _MAIN_ONLY:
                    continue
                if rx.search(text):
                    return _ALIAS.get(key, key)
    return "other"
