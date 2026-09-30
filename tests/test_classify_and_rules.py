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
    ]
    no = [
        "This internship is also open to recent graduates; enrolment is not required.",
        "Recent graduates are welcome to apply.",
        "Ook voor pas afgestudeerden: je hoeft niet ingeschreven te staan bij een opleiding.",
        "Werkervaringsplek voor starters in de ICT.",
    ]
    assert detect_enrollment("Het betreft een stageopdracht en geen werkervaringsplek. Bedoeld voor studenten.") is not False
    _tail = [
    ]
    unknown = ["Internship Data Engineering. You will work with Python and SQL in Utrecht."]
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
