"""Titles and texts the tech/non-tech classifier must get right (from an audit of live postings)."""

from radar.classify import is_tech

FILLER = " We offer a permanent contract, a pension scheme and 30 days of leave in a friendly team." * 4
CO = ("About us\nWe are the leading online marketplace: our platform, data and technology teams build web and mobile "
      "products with AI, cloud software and machine learning for millions of users.\n")
CASES = [
    ("Art Development Intern", CO + "The role\nYou support the art team: curating lots, writing descriptions and "
     "contacting galleries." + FILLER, False),
    ("Copywriting Intern", CO + "What you'll do\nWrite campaign copy, newsletters and app texts in Dutch and English."
     + FILLER, False),
    ("Generalist Intern", CO + "Your role\nSupport the founders across operations, finance and hiring." + FILLER, False),
    ("Paralegal Intern", CO + "The role\nDraft contracts and support the legal team with GDPR questions." + FILLER, False),
    ("Graduation Internship", CO + "What you'll do\nBuild a Python service with a React front-end, store data in "
     "PostgreSQL and deploy it on Kubernetes." + FILLER, True),
    ("Gebiedsontwikkelaar", "", False),
    ("Projectontwikkelaar woningbouw", "", False),
    ("Technisch Ontwikkelaar Werktuigbouwkunde", "", False),
    ("Business Developer IT - Agri, Food & Retail", "", False),
    ("Category Manager IT - Software & Cloud", "", False),
    ("Cortex & Cloud Sales Specialist - Strategic Accounts", "", False),
    ("Technical Sales Support Engineer - Process Industries", "", False),
    ("A.26.ML.MS.16 CCU Verpleegkundige Hartbewaking", "", False),
    ("Remote Data Entry Clerk", "", False),
    ("Senior Electrical Design Engineer (Data Center)", "", False),
    ("Landschapsarchitect", "Je ontwerpt parken, pleinen en groene woonwijken en begeleidt de aanleg." + FILLER, False),
    ("Senior Medewerker Platform Passenger Services", "Je begeleidt passagiers op het platform van Schiphol en "
     "coördineert het boarden van vliegtuigen." + FILLER, False),
    ("Financial Analyst", "You prepare forecasts in SAP and build dashboards in Power BI and Tableau." + FILLER, False),
    ("Senior Front End Engineer", "", True),
    ("Medior Netwerk Engineer", "", True),
    ("Modern Workplace Engineer", "", True),
    ("IAM Consultant", "", True),
    ("Technical Product Manager", "", True),
    ("SAP Retail Consultant", "", True),
    ("Senior Release Manager", "", True),
    ("Data Analist", "", True),
    ("Quality Engineer", "Je bent eigenaar van de kwaliteit van ons leerlingvolgsysteem: je schrijft testautomatisering "
     "in TypeScript en werkt met de developers in een scrum team." + FILLER, True),
    ("Business Analist", "Je vertaalt de wensen van de business naar IT en schrijft user stories voor de developers "
     "in een agile team." + FILLER, True),
]


def test_tech_classifier_cases():
    for title, text, want in CASES:
        assert is_tech(title, text) is want, title
