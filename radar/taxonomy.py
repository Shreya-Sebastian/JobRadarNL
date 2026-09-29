"""Skill taxonomy: canonical skill -> alias regex fragments. Grown from the data over time."""

from __future__ import annotations

import re

# Each value is a list of regex fragments matched case-insensitively with word boundaries where sensible.
SKILLS: dict[str, list[str]] = {
    # languages
    "Python": [r"python"],
    "Java": [r"\bjava\b(?!\s*script)"],
    "JavaScript": [r"javascript", r"\bjs\b"],
    "TypeScript": [r"typescript", r"\bts\b(?=\W)"],
    "C++": [r"c\+\+"],
    "C#": [r"c#", r"c-sharp", r"csharp"],
    ".NET": [r"\.net\b", r"dotnet", r"asp\.net"],
    "Go": [r"\bgolang\b", r"\bgo\b(?=\s*(?:developer|engineer|programming|language|\(golang\)|/|,))"],
    "Rust": [r"\brust\b"],
    "Kotlin": [r"kotlin"],
    "Swift": [r"\bswift\b(?!\s*(?:code|payment|transfer))"],
    "Scala": [r"\bscala\b"],
    "Ruby": [r"\bruby\b", r"\brails\b"],  # not "guardrails"
    "PHP": [r"\bphp\b", r"laravel", r"symfony"],
    "R": [r"\bR\b(?=\s*(?:programming|language|/|,|and|or|\)))"],
    "SQL": [r"\bsql\b", r"postgres", r"mysql", r"t-sql", r"pl/sql"],
    "Bash": [r"\bbash\b", r"shell scripting"],
    "MATLAB": [r"matlab"],
    "Dart": [r"\bflutter\b", r"\bdart\b"],
    "Elixir": [r"elixir"],
    "Haskell": [r"haskell"],
    # web
    "React": [r"\breact(?:\.js|js)?\b(?!\s*native)"],
    "React Native": [r"react\s*native"],
    "Angular": [r"\bangular(?:js)?\b"],
    "Vue": [r"\bvue(?:\.js|js)?\b", r"\bnuxt\b"],
    "Next.js": [r"next\.?js"],
    "Node.js": [r"node\.?js", r"\bnode\b"],
    "HTML/CSS": [r"\bhtml\b", r"\bcss\b", r"tailwind", r"\bsass\b"],
    "GraphQL": [r"graphql"],
    # bare "rest" is excluded: Dutch "de rest van de organisatie" is not an API
    "REST APIs": [r"\brestful\b", r"\brest\W{0,3}(?:api|service|endpoint|interface)", r"\bapi(?:s)?\b"],
    "Django": [r"django"],
    "Flask": [r"\bflask\b"],
    "FastAPI": [r"fastapi"],
    "Spring": [r"spring\s*boot", r"\bspring\b"],
    "iOS": [r"\bios\b", r"swiftui"],
    "Android": [r"android"],
    # data & ML
    "Machine Learning": [r"machine\s*learning", r"\bml\b"],
    "Deep Learning": [r"deep\s*learning", r"neural\s*net"],
    "PyTorch": [r"pytorch", r"\btorch\b"],
    "TensorFlow": [r"tensorflow", r"\bkeras\b"],
    "scikit-learn": [r"scikit", r"sklearn"],
    "pandas": [r"\bpandas\b"],
    "NLP": [r"\bnlp\b", r"natural language processing"],
    "Computer Vision": [r"computer vision", r"\bopencv\b"],
    "LLMs": [r"\bllms?\b", r"large language model", r"generative ai", r"\bgenai\b", r"\bgpt\b", r"openai", r"\brag\b",
             r"retrieval[- ]augmented", r"langchain", r"prompt engineering"],
    "MLOps": [r"mlops", r"mlflow", r"kubeflow", r"model deployment", r"model serving"],
    "Spark": [r"\bspark\b", r"pyspark"],
    "Databricks": [r"databricks"],
    "Airflow": [r"airflow"],
    "dbt": [r"\bdbt\b"],
    "Kafka": [r"\bkafka\b"],
    "Snowflake": [r"snowflake"],
    "BigQuery": [r"bigquery"],
    "Data Engineering": [r"data engineering", r"\betl\b", r"\belt\b", r"data pipelines?"],
    "Statistics": [r"statistic"],
    "Power BI / Tableau": [r"power\s*bi", r"tableau", r"looker"],
    # cloud & infra
    "AWS": [r"\baws\b", r"amazon web services"],
    "Azure": [r"\bazure\b"],
    "GCP": [r"\bgcp\b", r"google cloud"],
    "Docker": [r"\bdocker\b", r"containeri[sz](?:ation|ed)", r"\bpodman\b"],
    "Kubernetes": [r"kubernetes", r"\bk8s\b", r"\bopenshift\b", r"\bhelm\b"],
    "Terraform": [r"terraform", r"infrastructure as code", r"\biac\b", r"pulumi", r"cloudformation"],
    "CI/CD": [r"ci/cd", r"\bci\b", r"continuous integration", r"continuous delivery", r"github actions",
              r"gitlab ci", r"jenkins", r"azure devops"],
    "Linux": [r"\blinux\b", r"\bunix\b"],
    "Git": [r"\bgit\b", r"github", r"gitlab"],
    "Monitoring/Observability": [r"observability", r"prometheus", r"grafana", r"datadog", r"opentelemetry",
                                 r"\belk\s*stack\b", r"splunk",
                                 r"monitoring (?:tools|systems?|stack|solutions?|and alerting|"
                                 r"and logging)", r"(?:application|infrastructure|system) monitoring",
                                 r"logging and monitoring", r"monitoring, logging", r"alerting"],
    "Ansible": [r"ansible", r"puppet", r"\bchef\b"],
    "Networking": [r"\btcp/ip\b", r"networking", r"\bdns\b", r"\bvpn\b"],
    "Serverless": [r"serverless", r"\blambda\b", r"azure functions"],
    # databases & messaging
    "PostgreSQL": [r"postgres"],
    "MySQL": [r"mysql", r"mariadb"],
    "MongoDB": [r"mongodb", r"\bmongo\b"],
    "Redis": [r"\bredis\b"],
    "Elasticsearch": [r"elasticsearch", r"opensearch"],
    "RabbitMQ": [r"rabbitmq"],
    "NoSQL": [r"nosql", r"dynamodb", r"cassandra"],
    # practices & architecture
    "Microservices": [r"microservices?", r"micro-services?"],
    "Testing": [r"unit test", r"test automation", r"\btdd\b", r"pytest", r"\bjest\b", r"cypress", r"playwright",
                r"selenium", r"integration test"],
    "Agile/Scrum": [r"\bagile\b", r"\bscrum\b", r"\bkanban\b"],
    "System Design": [r"system design", r"distributed systems", r"software architecture",
                      r"scalable (?:systems?|architectures?|services?|platforms?)", r"high[- ]availability"],
    "Security": [r"cyber\s*security", r"application security", r"security engineer", r"infosec",
                 r"information security", r"\boauth\b", r"penetration test", r"\biso 27001\b", r"\bowasp\b",
                 r"secure coding", r"security best practices", r"\bsecurity\b(?=.{0,40}(?:vulnerabilit|threat|"
                 r"encryption|authentication|pentest|audit))"],
    "DevOps": [r"devops", r"\bsre\b", r"site reliability"],
    "Embedded": [r"embedded (?:software|systems?|engineer|linux|developer|c\b|c\+\+|development)", r"firmware",
                 r"\brtos\b", r"microcontroller", r"\bfpga\b", r"\bvhdl\b", r"\bverilog\b"],
    "Robotics": [r"\bros\b", r"robotics"],
    # technical simulation only: a bare "simulation" also appears in sales training and business games
    "Simulation/CAE": [r"simulation (?:engineer\w*|model\w*|software|tools?|stud(?:y|ies)|analys[ie]s|environments?|"
                       r"framework|platform|code|results?|techniques?|methods?|experts?)",
                       r"(?:numerical|physics(?:-based)?|finite[- ]element|process|flow|fluid|thermal|structural|"
                       r"multi-?body|monte carlo|discrete[- ]event|dynamic|electromagnetic|optical|traffic|"
                       r"hydraulic|molecular|quantum|circuit|device) simulations?", r"\bsimulators?\b", r"\bcfd\b",
                       r"computational fluid dynamics", r"finite[- ]element",
                       r"\bfea\b", r"\bfem\b", r"multiphysics", r"\bansys\b", r"\babaqus\b", r"\bcomsol\b",
                       r"openfoam", r"star-?ccm", r"ls-?dyna", r"\bnastran\b", r"simulink", r"digital twin",
                       r"numerical model\w*"],
    "Blockchain": [r"blockchain", r"solidity", r"web3", r"crypto"],
    "Product Management": [r"product management"],
    "UX/Design": [r"\bfigma\b", r"ux/ui", r"ui/ux", r"ux design", r"user experience design",
                  r"\bux\b(?=\s*(?:designer|design|research))"],
    "SAP": [r"\bsap\b"],
    "Salesforce": [r"salesforce", r"\bapex\b"],
    "Mendix/Low-code": [r"mendix", r"outsystems", r"low-code", r"low code", r"power apps", r"powerapps"],
    "Data Science": [r"data science", r"data scientist"],
    "Quantitative": [r"quantitative", r"\bquant\b"],
}

COMPILED: dict[str, re.Pattern] = {
    skill: re.compile("|".join(f"(?:{frag})" for frag in frags), re.I) for skill, frags in SKILLS.items()
}


def find_skills(text: str) -> list[str]:
    """Return canonical skills mentioned in text, in taxonomy order."""
    if not text:
        return []
    return [skill for skill, rx in COMPILED.items() if rx.search(text)]


# Extra spellings people type into the profile that are not safe as extraction aliases
# ("ai" or "cv" inside a posting mean too many things; as a typed skill they are unambiguous).
_INPUT_ALIASES: dict[str, str] = {
    "ai": "Machine Learning", "artificial intelligence": "Machine Learning", "genai": "LLMs", "gen ai": "LLMs",
    "generative ai": "LLMs", "llm": "LLMs", "large language models": "LLMs", "ml": "Machine Learning",
    "dl": "Deep Learning", "cv": "Computer Vision", "k8s": "Kubernetes", "js": "JavaScript", "ts": "TypeScript",
    "golang": "Go", "node": "Node.js", "nodejs": "Node.js", "reactjs": "React", "react.js": "React",
    "vuejs": "Vue", "postgres": "PostgreSQL", "postgresql": "PostgreSQL", "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn", "torch": "PyTorch", "tf": "TensorFlow", "gcp": "GCP", "google cloud": "GCP",
    "aws": "AWS", "amazon web services": "AWS", "ci": "CI/CD", "cicd": "CI/CD", "ci cd": "CI/CD",
    "c sharp": "C#", "csharp": "C#", "dotnet": ".NET", "cpp": "C++", "html": "HTML/CSS", "css": "HTML/CSS",
    "rest": "REST APIs", "api": "REST APIs", "apis": "REST APIs", "observability": "Monitoring/Observability",
    "monitoring": "Monitoring/Observability", "prometheus": "Monitoring/Observability",
    "grafana": "Monitoring/Observability", "scrum": "Agile/Scrum", "agile": "Agile/Scrum",
    "tableau": "Power BI / Tableau", "power bi": "Power BI / Tableau", "powerbi": "Power BI / Tableau",
    "mendix": "Mendix/Low-code", "low code": "Mendix/Low-code", "ux": "UX/Design", "figma": "UX/Design",
    "unit testing": "Testing", "tdd": "Testing", "pytest": "Testing",
}
_CANON_LOWER = {s.lower(): s for s in SKILLS}


def canonical_skill(name: str) -> str | None:
    """Map a typed skill ('LLM', 'ml', 'k8s', 'Postgres') to its canonical taxonomy name, or None if unknown."""
    key = (name or "").strip().lower()
    if not key:
        return None
    if key in _CANON_LOWER:
        return _CANON_LOWER[key]
    if key in _INPUT_ALIASES:
        return _INPUT_ALIASES[key]
    for skill, rx in COMPILED.items():
        if rx.fullmatch(key):
            return skill
    for skill, rx in COMPILED.items():
        if rx.search(key):
            return skill
    return None


def canonicalise(names: list[str] | None, keep_unknown: bool = False) -> list[str]:
    """Canonical names in input order without duplicates; unknown names dropped unless keep_unknown."""
    out: list[str] = []
    for n in names or []:
        c = canonical_skill(n)
        if c is None and keep_unknown and n.strip():
            c = n.strip()
        if c and c not in out:
            out.append(c)
    return out
