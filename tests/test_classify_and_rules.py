from radar.classify import is_tech
from radar.extract.rules import detect_language, detect_seniority, extract_rules, parse_salary
from radar.taxonomy import find_skills


def test_is_tech_titles():
    assert is_tech("Senior Backend Engineer")
    assert is_tech("Machine Learning Engineer")
    assert is_tech("Data Analyst")
    assert is_tech("DevOps Engineer")
    assert not is_tech("Account Executive")
    assert not is_tech("Mechanical Engineer")
    assert not is_tech("Warehouse Associate")
    assert not is_tech("Recruiter")
    assert is_tech("Sales Engineer")  # technical pre-sales counts


def test_find_skills_word_boundaries():
    text = "We use Python, Go and Java (not JavaScript). Kubernetes (k8s), AWS, and Postgres."
    skills = find_skills(text)
    assert "Python" in skills and "Java" in skills and "Kubernetes" in skills and "AWS" in skills
    assert "PostgreSQL" in skills and "SQL" in skills
    assert "JavaScript" in skills
    assert "Go" not in find_skills("Let's go build things")
    assert "R" not in find_skills("R&D team")


def test_canonical_skill_names():
    from radar.taxonomy import canonical_skill, canonicalise

    assert canonical_skill("LLM") == "LLMs" and canonical_skill("llms") == "LLMs"
    assert canonical_skill("ML") == "Machine Learning" and canonical_skill("machine learning") == "Machine Learning"
    assert canonical_skill("k8s") == "Kubernetes" and canonical_skill("Postgres") == "PostgreSQL"
    assert canonical_skill("AI") == "Machine Learning" and canonical_skill("pytorch") == "PyTorch"
    assert canonical_skill("underwater basket weaving") is None
    assert canonicalise(["ML", "Machine Learning", "llm", "nope"]) == ["Machine Learning", "LLMs"]
    assert canonicalise(["nope"], keep_unknown=True) == ["nope"]


def test_language_and_dutch_requirement():
    nl = "Wij zoeken een developer met ervaring. Je werkt bij ons in een leuk team en wij bieden een goed salaris."
    en = "We are looking for an engineer with experience. You will work with our team and we offer a good salary."
    assert detect_language(nl) == "nl"
    assert detect_language(en) == "en"
    e = extract_rules("Software Engineer", en + " Fluency in Dutch is required.")
    assert e.dutch_required and not e.english_only
    e = extract_rules("Software Engineer", en + " Dutch is not required, we are an English-speaking company.")
    assert not e.dutch_required and e.english_only
    e = extract_rules("Software Engineer", nl)
    assert e.dutch_required


def test_seniority_and_years():
    assert detect_seniority("Junior Developer") == "junior"
    assert detect_seniority("Senior Data Scientist") == "senior"
    assert detect_seniority("Staff Engineer") == "staff"
    assert detect_seniority("Associate Consultant") == "junior"
    assert detect_seniority("Senior Clinical Research Associate") == "senior"
    assert detect_seniority("Associate Director, Data") == "manager"
    assert detect_seniority("Associate Solutions Architect, Benelux") == "junior"
    assert detect_seniority("(Sr) Clinical Research Associate") == "senior"
    assert detect_seniority("Vulnerability Management (Associate) Manager") == "manager"
    assert detect_seniority("Technical Fellow, Compilers") == "staff"
    assert detect_seniority("Postdoctoral Fellow in Genomics") == "unknown"
    assert detect_seniority("Head of Engineering") == "manager"
    assert detect_seniority("Software Engineer", "At least 5 years of experience") == "senior"
    assert detect_seniority("Software Engineer", "1-2 years of experience") == "junior"
    assert detect_seniority("Software Engineer", "") == "unknown"


def test_salary_parsing():
    assert parse_salary("Salary: €60.000 - €80.000 per year") == (60000, 80000)
    assert parse_salary("We pay EUR 5,000 per month") == (60000, None)
    assert parse_salary("€70k-€90k") == (70000, 90000)
    assert parse_salary("Budget €500 for a laptop") == (None, None)


def test_visa_remote_degree():
    text = ("We offer visa sponsorship and relocation support. Hybrid: 2 days in the office. "
            "MSc in Computer Science required. Nice to have: Kafka.")
    e = extract_rules("Backend Engineer", "Required: Python and AWS. " + text)
    assert e.visa_sponsorship is True
    assert e.remote_policy == "hybrid"
    assert e.degree_required == "msc"
    assert "Python" in e.skills_required and "AWS" in e.skills_required
    assert "Kafka" in e.skills_nice and "Kafka" not in e.skills_required
    e2 = extract_rules("Backend Engineer", "You must already have the right to work in the Netherlands.")
    assert e2.visa_sponsorship is False


def test_classifier_edge_cases_from_real_boards():
    assert not is_tech("Senior Procurement Manager - Data Centers")
    assert not is_tech("Technology Partner Manager")
    assert not is_tech("Credit Risk Manager")
    assert not is_tech("Category Manager Entertainment & IT")
    assert is_tech("Development Team Lead")
    assert is_tech("Medior Systeembeheerder") and is_tech("Technisch Applicatie Beheerder")
    assert is_tech("Senior Rust Engineer - High Frequency Trading (HFT)")
    assert not is_tech("Medewerker Technische Dienst") and not is_tech("Mechanical Engineer Machines")
    assert is_tech("Data Engineer") and is_tech("IT Support Lead")


def test_generic_titles_become_tech_with_hard_skills_in_text():
    assert is_tech("Consultant", "You will build pipelines in Python on AWS, deploy with Docker and Kubernetes.")
    assert is_tech("Specialist", "Java, Spring, PostgreSQL and CI/CD experience required.")
    assert not is_tech("Consultant", "You advise clients on change management and stakeholder alignment.")
    assert not is_tech("Marketing Manager", "Python on AWS with Docker and Kubernetes.")  # title exclusion wins
    assert not is_tech("Executive Assistant to the CEO", "We build MySQL, PostgreSQL and MongoDB tooling in Go.")
    assert is_tech("Tech Lead") and is_tech("Lead Observability Consultant (Dynatrace)")
    assert is_tech("Senior Integratie Specialist") and is_tech("Vulnerability & Patch Management Consultant")
    assert is_tech("IT auditor") and is_tech("Product Owner AI Assistant") and is_tech("IT Support Assistant")
    assert not is_tech("Tech Recruitment Business Partner") and not is_tech("Adviseur Verzuim & Re-integratie")
    assert not is_tech("Enterprise Account Executive - High Tech") and not is_tech("Klantenservice medewerker Tech")
    assert not is_tech("Open sollicitatie SAP Specialist") and not is_tech("[TEST] AGENCYHUB")
    assert not is_tech("ServiceNow Sales Executive") and is_tech("ServiceNow Consultant")
    assert is_tech("Tenure-track Assistant Professor in Information Systems")


def test_early_career_titles_are_never_excluded_on_title_alone():
    tech_desc = "You will write Python, work with our software engineers on the data platform and learn Kubernetes."
    assert is_tech("Graduate Programme 2027", tech_desc)
    assert is_tech("Graduation Internship", tech_desc)
    assert is_tech("Afstudeerstage", tech_desc)
    assert is_tech("Graduate Software Engineer") and is_tech("IT Traineeship") and is_tech("Data Science Intern")
    assert not is_tech("Graduate Programme 2027", "You will support the finance team with month-end closing.")
    assert not is_tech("Marketing Intern", tech_desc)  # domain word in title wins


def test_rules_edge_cases_from_real_boards():
    e = extract_rules("Senior Technical Product Manager - Internal Developer Platform",
                      "We are an office-first company and do not offer remote-only roles. You are a master of change.")
    assert e.seniority == "senior" and e.role_family == "product"
    assert e.remote_policy == "onsite" and e.degree_required == "unknown"
    e = extract_rules("Information Security Officer", "Nice to have: Fluency in Dutch. A bachelor's degree in CS.")
    assert not e.dutch_required and e.degree_required == "bsc"
    e = extract_rules("DevOps Engineer", "At this moment we are not providing relocation sponsorships.")
    assert e.visa_sponsorship is False
    assert extract_rules("Customer Support Engineer", "").role_family == "it_support"
    assert extract_rules("Senior Technical Support Engineer", "").role_family == "it_support"


def test_visa_negations_and_years_context_from_real_postings():
    from radar.extract.rules import find_years

    assert extract_rules("Engineer", "Kindly note that relocation support is not offered for this role.").visa_sponsorship is False
    assert extract_rules("Engineer", "You have the legal right to work here without requiring visa sponsorship.").visa_sponsorship is False
    assert extract_rules("Engineer", "Wij bieden geen visa sponsorship aan.").visa_sponsorship is False
    assert extract_rules("Engineer", "Our relocation team assists you when moving to the Netherlands.").visa_sponsorship is True
    assert find_years("1 jaar contract met uitzicht op vast") is None
    assert find_years("Qualifications: 2–5 years of experience in IT support") == 2
    assert find_years("5–10 jaar ervaring met AI/ML") == 5
    assert find_years("€3k after 2 years and a 30% bonus") is None
    assert find_years("7+ years of professional backend experience") == 7
    assert extract_rules("Manufacturing Support Engineer", "1 jaar contract.").seniority == "unknown"
    assert extract_rules("Tech Support Engineer", "2–5 years of experience in IT support").seniority == "junior"


def test_role_family():
    assert extract_rules("Machine Learning Engineer", "").role_family == "ml"
    assert extract_rules("Data Engineer", "").role_family == "data"
    assert extract_rules("Site Reliability Engineer", "").role_family == "platform"
    assert extract_rules("iOS Developer", "").role_family == "mobile"
    assert extract_rules("Full Stack Developer", "").role_family == "fullstack"
    assert extract_rules("Software Engineer", "").role_family == "backend"
    assert extract_rules("Product Owner", "").role_family == "product"


def test_enrollment_requirement_detection():
    from radar.extract.rules import detect_enrollment

    yes = [
        "You are currently enrolled at a Dutch university for the entire duration of the internship.",
        "Mandatory enrolment to a Dutch Education System & resident of The Netherlands",
        "Je volgt een hbo- of wo-opleiding in de richting van Informatica.",
        "Je bent ingeschreven bij een erkende onderwijsinstelling.",
        "Currently enrolled in an MBO or HBO programme in software engineering.",
        "We are looking for a master's student in Data Science for a 6-month thesis internship.",
        "Afstudeerstage Data Engineering: maak impact met slimme data.",
        "Je studeert Business IT & Management.",
        "You are currently enrolled as a student and will remain enrolled for the duration of the assignment.",
        "You are in the final stage of your master's degree in Econometrics.",
        "In your penultimate year of study in computer science, graduating in 2028.",
        "This assignment is intended for an MSc student in Computer Science.",
        "You are studying towards your University Master's degree in Computer Science.",
        "Ongoing Bachelor's or Master's degree in Materials Science.",
        "Jij bent een mbo-3 student met een sterke interesse in ICT.",
        "Je volgt minimaal een MBO-4 opleiding richting Communicatie.",
        "Je zit in het laatste jaar van jouw opleiding.",
        "Een lucratieve bijbaan naast je HBO/WO studie.",
        'You need to be registered as a student during the entire internship period.',
        'Master Thesis student, preferably in Industrial Engineering.',
        'We are looking for a highly motivated student that will help us.',
        'Ben je momenteel bezig met een opleiding op HBO/WO niveau?',
        'Je volgt momenteel in Nederland een wo-opleiding in Bedrijfskunde.',
        'Volg jij een MBO, HBO of WO opleiding en ben je op zoek naar een stage?',
        'Dit breng jij mee: een mbo-, hbo- of wo-opleiding volgt in marketing',
        'Ben jij derdejaars bachelor- of masterstudent Rechtsgeleerdheid?',
        'Je zit in de laatste fase van je Bachelor of Master.',
        'Je bevindt je in de eindfase van een bachelor- of masteropleiding in Econometrie.',
        'Voor de functie van Actuarial Scriptiestagiair heb je nodig:',
        'You:\nAre studying Marketing, Communication or a related field',
        "Currently studying a Master's degree in Civil Engineering",
        'You are a 3rd or 4th-year student in the EU',
        'You are currently following a (Dutch) legal/financial MBO/HBO education;',
        'Pursuing a PhD in Machine Learning',
        'The project needs to be part of your MSc program at an EU university.',
        'University education (last year Bachelor or Master degree);',
        'Three days a week, allowing you to make an impact while balancing your studies.',
        'Du absolvierst derzeit ein Studium an einer Universität.',
        'We zoeken een gemotiveerde student in het derde jaar van de opleiding.',
        'Iemand die: Studeert aan HBO Orthopedisch Technologie.',
        "Are pursuing a\xa0bachelor's or master's degree\xa0in physics",
    ]
    no = [
        "This internship is also open to recent graduates; enrolment is not required.",
        "Recent graduates are welcome to apply.",
        "Ook voor pas afgestudeerden: je hoeft niet ingeschreven te staan bij een opleiding.",
        "Werkervaringsplek voor starters in de ICT.",
        "You are currently studying or have recently graduated.",
        "Our internship program for (near-)graduates offers meaningful projects.",
        'If you have recently graduated in Computer Science, this is for you.',
        'You’re a recent graduate with a background in tech.',
        'Ben je (bijna) afgestudeerd op een relevant rechtsgebied?',
        'Wij zoeken een student of starter met interesse in data.',
    ]
    assert detect_enrollment("Het betreft een stageopdracht en geen werkervaringsplek. Bedoeld voor studenten.") is not False
    unknown = [
        "Internship Data Engineering. You will work with Python and SQL in Utrecht.",
        'Functiefamilie:\xa0Student en afgestudeerden',
        'Bij ons volg je trainingen en opleidingen via onze academy.',
        'We are studying new ways to deploy models.',
        'Een stagevergoeding van 500 euro per maand.',
        'Graduate with us! Learn Python and SQL.',
        'Internship (non-thesis), 6 months, Amsterdam.',
    ]
    for t in yes:
        assert detect_enrollment(t) is True, t
    for t in no:
        assert detect_enrollment(t) is False, t
    for t in unknown:
        assert detect_enrollment(t) is None, t


def test_traineeships_are_a_paid_level_of_their_own():
    from radar.extract.rules import detect_seniority

    assert detect_seniority("IT Traineeship Data Engineering") == "trainee"
    assert detect_seniority("Shell Graduate Programme 2027 - Netherlands") == "trainee"
    assert detect_seniority("Young Professional Software Development") == "trainee"
    assert detect_seniority("Startersfunctie Java developer") == "trainee"
    assert detect_seniority("Internship Data Engineering") == "intern"
    assert detect_seniority("Afstudeerstage Machine Learning") == "intern"
    assert detect_seniority("Werkstudent Backend") == "intern"
    assert detect_seniority("Junior Developer") == "junior"


def test_specialist_tech_fields_are_kept():
    from radar.classify import is_tech
    from radar.extract.rules import detect_role

    keep = ["Simulation Engineer", "CFD Engineer Aerodynamics", "Computational Designer",
            "PhD on Numerical Modelling of Subsurface Erosion in Dikes", "Mechanical Engineer - Finite Element Analysis",
            "RF/Microwave IC designer", "Multiplayer Game Designer", "Trading Systems Engineer",
            "Optical & Quantum Communication System Engineer", "GIS adviseur", "Adviseur geodata",
            "Assistant Professor Radar Remote Sensing", "Bioinformatician Tumorgenetics", "Digital Twin Developer"]
    drop = ["Graphic Designer", "Digital Designer", "Laser Operator", "Mechanisch Monteur", "Pricing Modelling & Commercial Strategist"]
    for t in keep:
        assert is_tech(t, ""), t
    for t in drop:
        assert not is_tech(t, ""), t
    assert detect_role("Simulation Engineer") == "simulation"
    assert detect_role("Grid Simulation Engineer") == "simulation"
    assert detect_role("RF/Microwave IC designer") == "embedded"



def test_engineering_titles_with_simulation_heavy_text_are_tech_when_they_write_code():
    from radar.classify import is_tech

    filler = " We offer a permanent contract, a pension scheme and 30 days of leave in a friendly team." * 4
    sim = ("You run FEA and CFD studies in Ansys and Abaqus, build multiphysics simulation models and validate "
           "them against tests. You develop our in-house solver in C++ and automate studies in Python." + filler)
    assert is_tech("Mechanical Engineer", sim)
    assert is_tech("Structural Engineer", sim)
    assert is_tech("PhD Position on Impact Analysis of Composite Structures", sim)
    assert not is_tech("Sales Manager", sim)
    assert not is_tech("Senior Project Manager", sim)
    assert not is_tech("Mechanical Engineer", "You design brackets and supervise the workshop.")
    # using FEM and CFD tools to analyse ship structures is mechanical engineering, not a tech job
    applied = ("As a Starter Scientist CFD modeler you analyse maritime structures with high-fidelity numerical tools "
               "(FEM and CFD), model blast waves and fluid-structure interaction, and publish your results. You have "
               "a degree in Maritime or Mechanical Engineering and a specialisation in high-speed CFD." + filler)
    assert not is_tech("Starter Scientist Military CFD", applied)
    assert not is_tech("Structural Engineer", applied)


def test_generic_titles_need_software_or_it_in_the_text():
    from radar.classify import is_tech

    filler = " We offer a permanent contract, a pension scheme and 30 days of leave in a friendly team." * 4
    install = "You design electrical installations for utility buildings and supervise contractors on site." + filler
    lab = "You run ICP-MS analyses on water and soil samples in our accredited laboratory." + filler
    it = "You translate business needs into user stories and work with the developers in an agile team." + filler
    assert not is_tech("Engineer Elektrotechniek", install)
    assert not is_tech("Cost Engineer", install)
    assert not is_tech("Senior Scientist", lab)
    assert is_tech("Business Analyst", it)
    assert is_tech("Senior Engineer", "You maintain our Linux servers and the Kubernetes platform." + filler)
    # a specific tech title stands on its own, whatever the text says
    assert is_tech("Data Scientist", lab)
    assert is_tech("OnSite Support Engineer", install)
    # a short or missing description is not evidence either way
    assert is_tech("Research Scientist", "")



def test_simulation_skill_requires_technical_context():
    from radar.taxonomy import find_skills

    assert "Simulation/CAE" in find_skills("You build CFD and FEA simulation models in Ansys.")
    assert "Simulation/CAE" in find_skills("Experience with numerical simulations of multiphase flow.")
    assert "Simulation/CAE" not in find_skills("You take part in a sales simulation during the assessment day.")


def test_engineering_titles_need_real_software_work_not_one_stray_word():
    from radar.classify import is_tech

    filler = " We offer a permanent contract, a pension scheme and 30 days of leave in a friendly team." * 4
    mech = ("You design hydraulic systems for dredging vessels and visit the yard. Our ERP system handles the "
            "orders." + filler)
    soft = "You build our backend in Python and SQL, run it on Kubernetes in the cloud, and work in an agile team." \
        + filler
    for t in ("Sales Engineer Werktuigbouw", "Electrical Project Engineer", "Project Engineer", "System Engineer",
              "Factory Engineer / Werkvoorbereider", "Mechatronic Engineer - Advanced Dispensing Systems"):
        assert not is_tech(t, mech), t
    assert is_tech("Sales Engineer", soft) and is_tech("System Engineer", soft)
    # product names and specific IT or electronics roles stand on their own
    for t in ("Azure Competence Lead", "NOC Engineer", "PCB Design and Verification Engineer", "Senior RF engineer",
              "Technical Support Specialist"):
        assert is_tech(t, mech), t
    # Dutch "rust" (rest) is not the Rust language
    assert not is_tech("Production Engineer", "Werken in rust en ruimte, met een ERP-pakket." + filler)


def test_degree_is_the_lowest_level_named():
    from radar.extract.rules import extract_rules

    def deg(text):
        return extract_rules("Software Engineer", text).degree_required

    assert deg("Je hebt een afgeronde hbo- of wo-opleiding in informatica.") == "hbo"
    assert deg("You have a Bachelor's or Master's degree in Computer Science.") == "bsc"
    assert deg("You hold a Master's degree; a PhD is a plus.") == "msc"
    assert deg("You have a PhD in physics or a related field.") == "phd"
    assert deg("Mbo- of hbo-werk- en denkniveau.") == "mbo"
    assert deg("A degree is not required, skills matter.") == "none"


def test_degree_filter_groups_hbo_with_bachelors(fresh_db):
    from datetime import datetime

    from radar.stats import Filters, Row

    def row(i, degree):
        return Row(i, "Dev", "Acme", "Utrecht", False, "u", None, datetime(2026, 9, 1), None, "lever",
                   {"degree_required": degree})
    rows = [row(1, "hbo"), row(2, "bsc"), row(3, "msc"), row(4, "phd"), row(5, "unknown"), row(6, "none")]
    assert [r.id for r in Filters(degree="bachelor").apply(rows)] == [1, 2]
    assert [r.id for r in Filters(degree="master,phd").apply(rows)] == [3, 4]
    assert [r.id for r in Filters(degree="unstated").apply(rows)] == [5, 6]


def test_short_teaser_text_does_not_make_a_generic_title_tech():
    from radar.classify import is_tech

    teaser = ("Onze opdrachtgever is een toonaangevende speler in het ontwerp en de bouw van "
              "afvalverwerkingsinstallaties wereldwijd. De organisatie biedt daarnaast diverse services voor "
              "onderhoud en verbetering van deze installaties.")
    assert not is_tech("Sales Engineer", teaser)
    assert not is_tech("Project Engineer", teaser)
    # a specific tech title stands on its own, even next to a teaser
    for title in ("OutSystems consultant", "Senior Detection Engineer", "Technical Data Steward", "Software Engineer"):
        assert is_tech(title, teaser), title


def test_skills_come_from_the_job_sections_not_the_company_blurb():
    from radar.extract.rules import extract_rules
    from radar.extract.sections import job_text

    text = ("About Acme\nAcme is the application monitoring standard; clients include OpenAI and our SDKs support "
            "Ruby and PHP.\n\nWhat you'll do\n- Build backend services in Python and Kotlin\n\nRequirements\n"
            "- Experience with PostgreSQL\n\nNice to have\n- Kubernetes\n\nWhat we offer\n- A Java learning budget")
    ex = extract_rules("Backend Engineer", text)
    assert {"Python", "Kotlin", "PostgreSQL"} <= set(ex.skills_required)
    assert "Kubernetes" in ex.skills_nice
    for wrong in ("Monitoring/Observability", "LLMs", "Ruby", "PHP", "Java"):
        assert wrong not in ex.skills_required + ex.skills_nice, wrong
    # a sentence in the introduction that describes the role still counts
    intro = "As a data engineer you will build pipelines with Spark.\n\nRequirements\n- SQL"
    assert "Spark" in extract_rules("Data Engineer", intro).skills_required
    # without recognisable headers the whole text is used, as before
    assert job_text("We use Python and Go every day.") is None
    assert "Python" in extract_rules("Engineer", "We use Python and Go every day.").skills_required


def test_rust_and_scala_are_not_read_from_dutch_words():
    from radar.taxonomy import find_skills

    for text in ("We use Rust and Go", "Experience with Rust, C++ or Go", "Rust developer", "Spark with Scala",
                 "Scala, Kotlin or Java"):
        assert {"Rust", "Scala"} & set(find_skills(text)), text
    for text in ("rust en ruimte om te groeien", "in alle rust werken", "met rust laten",
                 "een breed scala aan projecten", "een scala van mogelijkheden"):
        assert not {"Rust", "Scala"} & set(find_skills(text)), text


def test_it_operations_skills_are_recognised():
    from radar.taxonomy import find_skills

    text = ("Je werkt in de servicedesk (1e lijns) en beheert Microsoft 365, Active Directory en Intune. "
            "Ervaring met ITIL, TOPdesk, VMware en Cisco firewalls is een pre. Kennis van AFAS en PLC-programmering.")
    found = set(find_skills(text))
    for skill in ("IT Support", "Microsoft 365", "Windows Server/AD", "Endpoint Management", "ITIL/ITSM",
                  "Virtualization", "Networking", "ERP", "PLC/Industrial Automation"):
        assert skill in found, skill
    assert "Application Management" in find_skills("Als functioneel beheerder ben je verantwoordelijk voor ...")
    assert "Application Management" not in find_skills("Je werkt samen met functioneel beheer en de gebruikers.")


def test_years_ranges_written_numbers_and_non_experience_years():
    from radar.extract.rules import find_years

    cases = {
        'Minimaal 5 jaar ervaring met cloudbeheer en migraties': 5,
        'circa 3–6 jaar relevante werkervaring met SAP': 3,
        'Minimaal 3 jaar ervaring in contractmanagement': 3,
        'substantial programming.\n\n1 to 3 years of relevant professional experience.': 1,
        '3 years experience as a Java developer in a scale-up': 3,
        'minimaal drie tot vijf jaar ervaring als product owner': 3,
        'Tussen de 3 en 6 jaar relevante werkervaring': 3,
        'Between 2 and 6 years of professional experience': 2,
        'Minimum 1 or 2 years of experience in servicing': 1,
        'Minimaal 2,5 jaar relevante werkervaring': 3,
        'Minimaal 1.5 jaar ervaring als Scrum Master': 2,
        'Minimaal een half jaar ervaring op een 1e lijns servicedesk': 1,
        'minimaal 2 jaren kennis van en werkervaring met': 2,
        '3+ (typically 5+) years of relevant experience': 3,
        'a minimum of three (3) years of experience': 3,
        '6 months to 3 years’ experience in QA': 1,
        'Je hebt minimaal 3 à 4 jaar werkervaring': 3,
        'a 3-year experience in backend': 3,
        'or willingness to obtain it within the first two years; Ideally, some experience': None,
        'obtain a UTQ within three years if you have less than five years of teaching experience': None,
        'Ervaring: junior (< 1,5 jaar werkervaring)': None,
        'De eerste 2 jaar neem je deel aan het Young Professional Program, ervaring': None,
        '0 tot 2 jaar ervaring met data engineering': None,
        "A 4-year bachelor's degree and relevant experience": None,
        'Contract: 2 years, experience with Python': None,
        'You are 18 years or older and have experience': None,
        'Enkele jaren ervaring in de elektrotechniek': None,
        'Several years of experience in network administration': None,
        'Met ruim 90 jaar ervaring in de technische dienstverlening': None,
        '5 jaar ervaring met IT-contracten': 5,
        '5 years of program management experience': 5,
    }
    for text, want in cases.items():
        assert find_years(text) == want, text


def test_levels_and_role_families_from_titles():
    from radar.extract.rules import detect_role, detect_seniority

    levels = {"Medior/Senior Developer": "medior", "Software Engineer II": "medior", "Onderzoeksstage AI": "intern",
              "Backstage Developer": "unknown", "Hoofd ICT": "manager", "Technical Application Manager": "unknown",
              "Team leader Servicedesk": "lead", "Ervaren Data Engineer": "medior"}
    roles = {"SOC Analist": "security", "Functioneel Beheerder": "it_support", "Mechanical Design Engineer": "other",
             "PLC Software Engineer": "embedded", "Business Developer": "other",
             "AI Full Stack Engineer": "fullstack", "Senior Java Developer": "backend"}
    for title, want in levels.items():
        assert detect_seniority(title) == want, title
    for title, want in roles.items():
        assert detect_role(title) == want, title


def test_dutch_requirement_in_english_and_dutch_postings():
    from radar.extract.rules import extract_rules

    en = "We are looking for a backend engineer to join our team in Amsterdam. You will build services in Python. "
    nl = "Wij zoeken een backend developer voor ons team in Utrecht. Je bouwt services in Python en werkt met data. "
    required = [en + "You have fluency in both Dutch (minimum C1 level) and English.",
                en + "You have a good command of the Dutch language.",
                en + "Dutch language required, minimum B2.",
                en + "You are fluent in English and Dutch.",
                nl + "Je spreekt en schrijft goed Nederlands."]
    optional = [en + "Dutch is a plus.",
                en + "Dutch or French fluency is a must.",
                en + "Nice to have:\n- Dutch\n- Kubernetes",
                nl + "Nederlands is een pré, Engels is onze voertaal."]
    for text in required:
        assert extract_rules("Backend Engineer", text).dutch_required is True, text
    for text in optional:
        e = extract_rules("Backend Engineer", text)
        assert e.dutch_required is False and e.english_only is True, text


def test_visa_sponsorship_statements():
    from radar.extract.rules import detect_visa

    cases = [
        ('We offer visa sponsorship and relocation support. Hybrid: 2 days in the office.', True),
        ('You must already have the right to work in the Netherlands.', False),
        ('At this moment we are not providing relocation sponsorships.', False),
        ('Kindly note that relocation support is not offered for this role.', False),
        ('You have the legal right to work here without requiring visa sponsorship.', False),
        ('Wij bieden geen visa sponsorship aan.', False),
        ('Our relocation team assists you when moving to the Netherlands.', True),
        ('Visa sponsorship available (including transfer of Dutch visa; no relocation support)', True),
        ('Visa sponsorship may be available where applicable. We do not provide relocation support.', True),
        ('Employee Status:\nRegular\nRelocation:\n\nVISA Sponsorship:\n\nTravel Requirements:\n', None),
        ('Relocation:\nNo relocation\nVISA Sponsorship:\nNo\nTravel Requirements:\n', False),
        ('Did you know that we sponsor more than 2,000 children worldwide', None),
        ('Please note no relocation support will be provided.', False),
        ('as we don’t offer any visa sponsorship.', False),
        ('Visa sponsorship not available for this role.', False),
        ('For this position we can not sponsor a visa.', False),
        ('without the need for visa sponsorship by Strada.', False),
        ('verhuizing of visumsponsoring niet mogelijk, ook niet via de regeling voor Kennismigranten (Highly Skilled Migrant – HSM).', False),
        ('We are open to support with relocation efforts.', True),
        ('We offer relocation expenses for employees coming from abroad', True),
        ('Relocatiepakket (inclusief visumsponsoring en ondersteuning)', True),
        ("If you're relocating from abroad, we provide full support throughout the visa process", True),
        ('AMOLF assists any new foreign PhD-student with housing and visa applications', True),
        ('Uitgebreid verhuispakket voor internationale sollicitanten.', True),
        ('Sponsorship Provided: Yes Location: Rotterdam', True),
        ('Is role eligible for Immigration Sponsorship? No. Please note that we will not sponsor applicants for work visas', False),
        ('EU citizenship required.', False),
        ('Wij kunnen echter geen visum sponsorship aanbieden.', False),
        ('Please note, we don’t offer relocation for this position.', False),
        ('Legally authorised to work in the country of hire without company sponsorship', False),
        ('A favourable tax agreement, the ‘30% ruling’, may apply to non-Dutch applicants.', True),
        ('Not only do we offer visa sponsorship, we also pay for your flight.', True),
        ("If you don't have an EU passport, we can sponsor your visa.", True),
        ('you can trade PTO for internet costs, our bicycle plan, company fitness and relocation costs.', None),
        ('Kennismigrant: wij zijn erkend referent bij de IND.', True),
        ('Relocation is not possible.', False),
        ('Relocatie of ondersteuning bij visumaanvragen kunnen wij niet bieden.', False),
        ('Voor deze functie bieden wij geen sponsoring voor een verblijfs- of werkvergunning.', False),
        ('We cannot sponsor visas.', False),
        ('No visa sponsorship.', False),
        ('You must have a valid work permit.', False),
        ('geen sponsoring mogelijk', False),
        ('We are a recognised sponsor with the IND and can apply for your highly skilled migrant permit.', True),
        ('Visa Sponsorship (if applicable)', True),
        ('Did you know that we sponsor the local football club.', None),
    ]
    for text, want in cases:
        assert detect_visa(text) is want, text


def test_remote_policy():
    from radar.extract.rules import extract_rules

    cases = [
        ('Engineer', 'We offer visa sponsorship. Hybrid: 2 days in the office.', 'hybrid'),
        ('Engineer', 'We are an office-first company and do not offer remote-only roles.', 'onsite'),
        ('Engineer', 'Hybrid working (50/50); 1 month per year fully remote;', 'hybrid'),
        ('Engineer', "we're explicitly not a hybrid or remote-first company - you can't build robots from home, so we're onsite five days a week", 'onsite'),
        ('Engineer', 'Most people work in a hybrid setup, minimum two days per week in the office. Work from anywhere for up to 4 weeks a year.', 'hybrid'),
        ('Engineer', 'Organize on-site Tableau training sessions.', 'unknown'),
        ('Engineer', 'Onsite presence: 2 days per week in Utrecht.', 'hybrid'),
        ('Engineer', 'Provide demos both remote and onsite across Europe. This is a remote role, with travel as required.', 'remote'),
        ('Engineer', 'Werkregeling: Onsite | Hybride', 'hybrid'),
        ('Engineer', 'Support commissioning on site.', 'unknown'),
        ('Engineer', 'Location: Remote, preference for Netherlands.', 'remote'),
        ('Engineer', 'Hybride werken: thuis, bij de klant of op kantoor.', 'hybrid'),
        ('Engineer', 'Je ontwerpt beveiliging voor Azure en hybride cloudomgevingen.', 'unknown'),
        ('Engineer', 'Experience with hybrid cloud and on-prem infrastructure.', 'unknown'),
        ('Engineer', 'in verband met (deels) werken op kantoor.', 'hybrid'),
        ('Engineer', 'with up to two remote days per week', 'hybrid'),
        ('Engineer', 'This role is remote, but candidates must be based in Netherlands.', 'remote'),
        ('Engineer', 'Je bent 2 dagen per week op kantoor in Utrecht.', 'hybrid'),
        ('Engineer', 'Thuiswerken is niet mogelijk; je werkt 5 dagen per week op locatie.', 'onsite'),
        ('Engineer', 'We work 4 dagen per week (32 uur).', 'unknown'),
        ('Engineer', 'Fully remote within NL.', 'remote'),
        ('Engineer', 'Remote within the Netherlands.', 'remote'),
        ('Engineer', 'We are a remote-first company.', 'remote'),
        ('Engineer', 'This is an on-site role in Eindhoven.', 'onsite'),
        ('Remote Sensing Scientist', 'Work on radar remote sensing.', 'unknown'),
        ('Senior Security Engineer (Remote, EU/CET)', 'Join us.', 'remote'),
        ('IT Support Engineer', 'Provide remote support and remote monitoring for our clients using remote control tools.', 'unknown'),
        ('Engineer', 'Based in Amsterdam or willing to relocate; this role is on-site and is not remote.', 'onsite'),
        ('Engineer', 'Thuiswerkvergoeding en een goede pensioenregeling.', 'hybrid'),
        ('Engineer', "You'll be in the office 3 days a week.", 'hybrid'),
        ('Engineer', 'Werken op locatie bij de klant.', 'unknown'),
        ('Engineer', 'Flexible Work Arrangements:\nHybrid\nShift:', 'hybrid'),
        ('Engineer', 'Flexible Work Arrangements:\nNot Applicable\nShift:', 'unknown'),
        ('Engineer', 'Hybrid AI models for physics.', 'unknown'),
        ('Engineer', 'Work model: Hybrid', 'hybrid'),
    ]
    for title, text, want in cases:
        assert extract_rules(title, text).remote_policy == want, (title, text)


def test_minimum_degree():
    from radar.extract.rules import extract_rules

    cases = [
        ('Software Engineer', 'Je hebt een afgeronde hbo- of wo-opleiding in informatica.', 'hbo'),
        ('Software Engineer', "You have a Bachelor's or Master's degree in Computer Science.", 'bsc'),
        ('Software Engineer', "You hold a Master's degree; a PhD is a plus.", 'msc'),
        ('Software Engineer', 'You have a PhD in physics or a related field.', 'phd'),
        ('Software Engineer', 'Mbo- of hbo-werk- en denkniveau.', 'mbo'),
        ('Software Engineer', 'A degree is not required, skills matter.', 'none'),
        ('Backend Engineer', 'Required: Python and AWS. MSc in Computer Science required. Nice to have: Kafka.', 'msc'),
        ('PM', 'We are an office-first company. You are a master of change.', 'unknown'),
        ('ISO', "Nice to have: Fluency in Dutch. A bachelor's degree in CS.", 'bsc'),
        ('Engineer', "Master's or PhD degree in Electrical Engineering.", 'msc'),
        ('PhD Position in Micro-Robotics', 'This PhD project focuses on robots. You have an MSc in mechanical engineering.', 'msc'),
        ('PhD in Quantum codes', 'join a doctoral network as a PhD candidate at TU/e.', 'unknown'),
        ('Postdoc in X', "The postdoc will work with four other PhD's.", 'phd'),
        ('DBA', 'BE or Master Degree in Computer Science.', 'msc'),
        ('Senior Manager', 'Master’s degree in Information Security, IT, Business, or a related field', 'msc'),
        ('DevOps', "Daarbij vragen wij minimaal een MBO4-diploma, kennis van API's.", 'mbo'),
        ('Manager', 'een masterdiploma, met een voorkeur voor technologie', 'msc'),
        ('AI Engineer', 'Een afgeronde, relevante academische opleiding als fundament.', 'msc'),
        ('Developer', 'Degree in Computer Science or a related technical field', 'unknown'),
        ('CRA', 'Have a degree in Life Sciences or have equivalent experience', 'unknown'),
        ('Engineer', 'Werken bij het Universitair Medisch Centrum Utrecht.', 'unknown'),
        ('Control Engineer', 'This could also be someone with an MBO education level who has reached an HBO working and thinking level through practical experience. Technical MBO/4 to HBO work and thinking level', 'mbo'),
        ('Test Engineer', 'You bring HBO / Bachelor level of working and thinking, or an MBO 4 background combined with substantial practical experience', 'bsc'),
        ('Sales Engineer', 'BS Degree in Engineering (preferably Computer Science/Engineering) is a plus', 'unknown'),
        ('Support', 'BSc in IT/Computer Science preferred; ITIL a plus', 'bsc'),
        ('Engineer', "An organisation's degree of innovation depends on diversity. A high degree of freedom.", 'unknown'),
        ('Scrum Master', 'As Scrum Master, you coach teams. Certified Scrum Master (PSM).', 'unknown'),
        ('Engineer', 'Master Data Management experience.', 'unknown'),
        ('Engineer', 'Je hebt een WO-niveau.', 'msc'),
        ('Engineer', 'Je beschikt over hbo/wo werk- en denkniveau.', 'hbo'),
        ('Engineer', 'Een afgeronde opleiding in een technische richting.', 'unknown'),
        ('Engineer', 'Currently pursuing a degree in Computer Science.', 'unknown'),
    ]
    for title, text, want in cases:
        assert extract_rules(title, text).degree_required == want, (title, text)


def test_years_text_keeps_the_wording():
    from radar.extract.rules import years_text

    assert years_text("Qualifications: 2–5 years of experience in IT support") == "2-5"
    assert years_text("7+ years of professional backend experience") == "7+"
    assert years_text("minimaal 2 jaar werkervaring") == "2+"
    assert years_text("1,5 jaar ervaring") == "1.5"
    assert years_text("3 years of relevant experience") == "3"
    assert years_text("€3k after 2 years and a 30% bonus") is None
