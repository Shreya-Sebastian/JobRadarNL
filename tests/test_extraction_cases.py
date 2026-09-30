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
