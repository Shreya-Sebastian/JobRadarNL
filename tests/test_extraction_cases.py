from radar.extract.rules import detect_degree, detect_remote, detect_role, detect_seniority, extract_rules


def test_seniority_naval_architect_and_trainee_lawyer():
    assert detect_seniority("Senior Naval Architect - Yacht Building") == "senior"
    assert detect_seniority("Naval Architect") == "unknown"
    assert detect_seniority("Solution Architect") == "lead"
    assert detect_seniority("Advocaat-stagiair Privacy Recht") == "trainee"
    assert detect_seniority("Stagiair Business Analyst") == "intern"


def test_role_fixes():
    assert detect_role("CNC Frezer – Programmeur (m/v)") == "other"
    assert detect_role("CAM Programmeur Verspaning") == "other"
    assert detect_role("Kerry Graduate Programme 2027 - Engineering") == "backend"  # via "engineering", not "programme"
    assert detect_role("SAP Programme Lead") == "other"
    assert detect_role("Graphics Programmer") == "backend"
    assert detect_role("Power Platform Consultant") == "backend"
    assert detect_role("M365 Engineer met Power Platform-skills") == "it_support"
    assert detect_role("Technisch Consultant Networking") == "platform"
    assert detect_role("Software Engineer (Networking)") == "backend"
    assert detect_role("Managed Services Engineer") == "it_support"
    assert detect_role("Senior Field Application Engineer") == "other"
    assert detect_role("Inkoopadviseur ICT") == "other"
    assert detect_role("Outsystems Developer (Business Team Inkoopdossier)") == "backend"
    assert detect_role("Databricks Senior Solutions Architect") == "data"
    assert detect_role("Consultant IT Assurance") == "security"
    assert detect_role("Major Incident & Problem Manager IT- Infrastructuur") == "it_support"
    assert detect_role("Azure Integration Architect - NL") == "platform"
    assert detect_role("Engineering Manager - Revenue Management Azure") == "backend"
    assert detect_role("IT-Systems manager") == "it_support"


def test_remote_fixes():
    assert detect_remote("Technisch Consultant", "Als Technisch Consultant ben je volledig thuis is de techniek. "
                         "Hybride werkomgeving, met als standplaats Capelle aan den IJssel.") == "hybrid"
    assert detect_remote("Engineer", "The role is remote in the Netherlands or in Berlin, but you commit to "
                         "travelling to the office (The Hague or Berlin) twice per week.") == "hybrid"
    assert detect_remote("Network Engineer", "Preparing the organization for future hybrid connectivity.") == "unknown"
    assert detect_remote("Security Engineer", "Detect modern hybrid attacks in hybrid and multi-cloud "
                         "enterprises.") == "unknown"
    assert detect_remote("Platform Engineer", "Kubernetes-clusters in een hybride omgeving (on-premises en "
                         "cloud).") == "unknown"
    assert detect_remote("Forward Deployed Engineer", "Remote first digital team, based across Europe.\n"
                         "Based on-site at RDM, you will work out where a tool genuinely helps.") == "onsite"
    assert detect_remote("SAP Consultant", "Uren: 32-40\nWerkplek: Remote & Utrecht en klant locatie\n") == "hybrid"
    assert detect_remote("Engineer", "This is a remote role. We hire globally.") == "remote"
    assert detect_remote("Engineer", "Work model: Remote\nWe are a remote-first company.") == "remote"


def test_degree_not_from_teaching_or_transcripts():
    t = ("Job requirements\nAn MSc degree in systems and control.\nContributing to teaching activities and "
         "supervising Bachelor's and Master's students.\nTranscripts of your BSc and MSc degrees.")
    assert detect_degree("PhD Position Control Theory", t, t) == "msc"
    t = "Read about Maryam, who is currently doing her PhD in the IC Design Group!"
    assert detect_degree("PhD position in IC Design group", t, t) == "unknown"
    t = "The candidate cannot already be in possession of a doctoral degree at the date of recruitment."
    assert detect_degree("PhD in Quantum Error Correction", t, t) == "unknown"
    t = "This position is one of twelve PhD and postdoc positions across the consortium."
    assert detect_degree("PhD position", t, t) == "unknown"
    t = "Educated to a HBO level in Software Engineering, Informatica, or Computer Science."
    assert detect_degree("Backend Developer", t, t) == "hbo"
    t = "You hold a PhD in physics. Ideally, some experience in (co-)supervising BSc, MSc, and/or PhD students."
    assert detect_degree("Assistant Professor", t, t) == "phd"
    t = "Upload your resume with a motivation letter and grade lists (of high school, bachelor and master)."
    assert extract_rules("Consultant", "Master's degree or PhD in a technical field.\n" + t).degree_required == "msc"


def test_second_pass_language_and_enrolment():
    from radar.extract.rules import detect_enrollment, extract_rules

    nl = "Wij zoeken een backend developer voor ons team in Utrecht. Je bouwt services in Python en werkt met data. "
    de = "Wir suchen einen Senior Fullstack Engineer (w/m/d), der uns mit viel Energie unterstützt. Du bist Teil unseres Teams und arbeitest mit unseren Kunden. "
    checks = [
        ("url only", extract_rules("SAP Business consultant", "https://werkenbij.example.nl/vacatures/sap-business-consultant-eam/").english_only, False),
        ("salary line", extract_rules("AI Business Consultant", "AI-First Business Consultant (hybrid • 32—40 hours• Barendrecht/Rotterdam • €5700—€8,000)").english_only, False),
        ("german", extract_rules("Senior Engineer", de).english_only, False),
        ("german+eng", extract_rules("Senior Engineer", de + "Englisch fließend.").english_only, False),
        ("nl en/of", extract_rules("Lead Engineer", nl + "Je communiceert helder in het Nederlands en/of Engels.").dutch_required, False),
        ("nl helder", extract_rules("Lead Engineer", nl + "Je communiceert helder in het Nederlands.").dutch_required, True),
        ("en clearly", extract_rules("Engineer", "We are looking for an engineer to join the team. You communicate clearly in Dutch.").dutch_required, True),
        ("no dutch terse", extract_rules("Python dev", "Python dev. No Dutch required.").english_only, True),
        ("plain en", extract_rules("Engineer", "We are looking for an engineer to join our team. You will build services.").english_only, True),
    ]
    enr = [
        ("grad open", detect_enrollment("Completed BSc and currently in the final stages of a master's, or already holding a master's, in a STEM field."), False),
        ("abn stage", detect_enrollment("De stagevergoeding bedraagt voor een mbo-, hbo- of wo stage €750 per maand."), True),
        ("xsens still req", detect_enrollment("Note that you actually need to be enrolled in a school or university in order to be considered for an internship. Almost or already graduated? Please take a look at our current vacancies."), True),
    ]
    en = "We are looking for a backend engineer to join our team in Amsterdam. You will build services in Python. "
    lang2 = [
        ("comm skills both", extract_rules("Engineer", en + "Excellent communication skills in English and Dutch with the ability to explain risks.").dutch_required, True),
        ("comm skills the lang", extract_rules("Engineer", en + "Strong written and verbal communication skills in the Dutch language.").dutch_required, True),
        ("ability essential", extract_rules("Engineer", en + "Ability to speak and write in English; ability in Dutch is considered essential.").dutch_required, True),
        ("or another language", extract_rules("Engineer", en + "Strong communication skills in Dutch or another European language are a plus.").english_only, True),
        ("skills in dutch law", extract_rules("Engineer", en + "Skills in Dutch tax law are useful.").english_only, True),
    ]
    lang3 = [
        ("at least dutch", extract_rules("Engineer", en + "You speak at least Dutch fluently, as our drawings are in Dutch.").dutch_required, True),
        ("english language and dutch", extract_rules("Engineer", en + "Proficient in English language and Dutch.").dutch_required, True),
    ]
    for name, got, want in checks + enr + lang2 + lang3:
        assert got == want, name
