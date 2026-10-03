/* Front end: tabs, profile-driven filters, saved jobs, Dutch/English interface. Plain JS + Chart.js + D3. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  // the first two follow the stylesheet's accent colours (they differ in dark mode)
  const palette = [css("--accent") || "#047857", css("--accent-2") || "#f97316", "#2a6f97", "#8e44ad", "#c0392b", "#16a085", "#f39c12", "#34495e",
    "#7f8c8d", "#27ae60", "#d35400", "#2980b9"];
  const LEVELS = ["intern", "trainee", "junior", "medior", "senior", "lead", "staff", "manager"];
  const REMOTE = ["remote", "hybrid", "onsite"];
  const EXP = ["none", "1", "2-3", "4-5", "6+", "unspecified"];
  const DEGREES = ["bachelor", "master", "phd", "mbo", "unstated"];
  const SIZES = ["small", "medium", "large"];
  const EMPS = ["1-49", "50-249", "250-4999", "5000+", "unknown"];

  // ---------- translations ----------
  const I18N = {
    en: {
      "tab.overview": "Overview", "tab.jobs": "Jobs", "tab.market": "Market", "tab.profile": "Profile",
      
      
      "ov.skills": "Most requested skills",
      "ov.graph": "Skills asked for together",
      "ov.matches": "Best matches for you",
      "ov.matches.empty": 'Add your skills under <a href="#profile">Profile</a> to see matches.',
      "f.search": "Search", "f.search.ph": "title or company", "f.window": "Window", "f.window.all": "All live", "f.window.1": "Last 24 h",
      "f.window.7": "Last 7 days", "f.window.30": "Last 30 days", "f.window.90": "Last 90 days",
      "f.language": "Language", "f.language.any": "Dutch and/or English", "f.language.nl": "Dutch only (no English needed)", "f.language.en": "English (no Dutch required)",
      "f.sort": "Sort", "f.sort.newest": "Newest", "f.sort.match": "Best match", "f.role": "Role", "f.level": "Level", "f.remote": "Remote",
      "f.cities": "Cities", "f.visa": "Visa sponsorship mentioned", "f.agencies": "Hide agencies", 
      "f.saved": "Saved only", "f.skill": "Skill", "f.reset": "Reset filters", "f.profile": "Use my profile",
      "th.age": "Age", "th.title": "Title", "th.company": "Company", "th.city": "City", "th.level": "Level", "th.skills": "Skills",
      "th.match": "Match", "th.lang": "Language", "th.visa": "Visa", "th.employer": "Employer", "th.open": "Open tech roles", "th.share": "Share",
      "th.sector": "Sector", "th.status": "Status", "th.livetech": "Live tech postings", "th.platform": "Platform", "th.kind": "Kind", "th.postings": "Postings",
      "pager.prev": "‹ Prev", "pager.next": "Next ›",
      "mk.trend": "New postings per week", "mk.trend.hint": "and the skills you follow", "mk.cities": "Cities", "mk.seniority": "Seniority",
      "mk.roles": "Role family", "mk.hiring": "Who is hiring", "mk.salary": "Stated salaries", "mk.salary.hint": "per year",
      "mk.lang": "Posting language", "mk.remote": "Remote policy",
      "p.looking": "Job preferences",
      "p.roles": "Roles", "p.levels": "Levels", "p.exclude": "Employers to hide", "p.language": "Posting language",
      "p.visa": "Only jobs that mention visa sponsorship", "p.agencies": "Hide recruitment agencies", "p.save": "Save profile", "p.export": "Export",
      "p.import": "Import", "p.clear": "Clear", "p.skills": "Skills",
      "p.extract": "Extract skills from CV text", "p.cv.ph": "Paste your CV text", "p.extract.btn": "Extract",
      "p.gap": "Gap analysis", "p.gap.btn": "Analyse", "p.saved": "Saved jobs",
     
     
     
     
     
      // dynamic strings
      "kpi.live": "live tech postings", "kpi.employers": "employers", "kpi.crawl": "last crawl",
      "title": "{n} tech jobs in the Netherlands",
     
      
     
      "match.none": "No live posting fits all your profile filters. Loosen a level or city under Profile.",
      "li.match": "match {p}%", "li.have": "you have {s}", "li.missing": "missing {s}", "agency": "agency", "closed": "closed",
      "jobs.match": "{n} jobs match", "jobs.match.one": "1 job matches", "page": "page {p} of {t}", "today": "today", "yesterday": "yesterday", "days.ago": "{d}d ago", "old": "old", 
      "lang.nl": "NL", "lang.en": "EN", "lang.both": "NL + EN", "lang.nl.title": "Dutch required, no English needed", "lang.en.title": "No Dutch required", "lang.both.title": "Dutch and English both required",
      "visa.yes": "yes", "visa.no": "no", "visa.unknown": "?", "save": "save", "remove": "remove",
      "salary.none": "No posting in this selection states a salary.", "salary.n": "postings state a salary", "salary.median": "median", "salary.p25": "lower quarter", "salary.p75": "upper quarter",
      "lang.chart.en": "English", "lang.chart.nl": "Dutch", "lang.chart.other": "Other",
      "remote.remote": "Remote", "remote.hybrid": "Hybrid", "remote.onsite": "On-site", "remote.unknown": "Not stated",
      "trend.all": "all new postings",
      "p.saved.empty": "Star a job in the Jobs tab to keep it here.", "p.saved.status": "Saved. The Jobs tab now opens with these filters.", "p.imported": "Imported.",
      "p.import.fail": "Could not read that file.", "p.more.text": "Paste a bit more text first.", "p.extracting": "Extracting…",
      "p.extracted": "{n} skills found; press Save profile to keep them.", "p.add.skills": "Add some skills first.", "p.analysing": "Analysing…",
      "p.considered": "{n} postings considered", "p.coverage": "Your skills cover {p}% of all skill mentions in these postings. The most demanded skills you do not list:",
      "skill.tracked": "“{v}” is tracked as “{c}”.", "skill.unknown": "“{v}” is not one of the tracked skills, so it will not affect matches.",
      "ph.city": "city…", "ph.employer": "employer name…", "ph.skill": "skill…",
     
     
     
     
      "role.ml": "ML / AI", "role.data": "Data", "role.backend": "Backend", "role.frontend": "Frontend", "role.fullstack": "Full-stack", "role.platform": "Platform / DevOps",
      "role.mobile": "Mobile", "role.embedded": "Embedded / hardware", "role.simulation": "Simulation / computational", "role.security": "Security", "role.qa": "QA / Test", "role.product": "Product", "role.design": "Design", "role.it_support": "IT support", "role.other": "Other",
      "level.intern": "intern", "level.trainee": "trainee / graduate programme", "level.junior": "junior", "level.medior": "medior", "level.senior": "senior", "level.lead": "lead", "level.staff": "staff / principal", "level.manager": "manager", "level.unknown": "unknown",
      "fail": "Failed to load: {e}",
      "f.confirmed": "Only confirmed on the employer's site in the last 7 days",
     
      "trust.seen": "Still listed on the employer's own site on {d}", "trust.checked": "page opened and checked on {d}",
      "trust.expires": "closes on {d}",
      "loading": "Loading the latest jobs…",
      "pw.choose": "Choose your new password.", "pw.label": "Password", "pw.none": "No password yet. You sign in with an e-mail link or Google; add a password to sign in with it too.",
      "pw.has": "You can sign in with your password, an e-mail link or Google.", "pw.set": "Set a password", "pw.change": "Change password",
      "pw.remove": "Remove password", "pw.current": "Current password", "pw.new": "New password (10+ characters)", "pw.repeat": "Repeat the new password",
      "pw.save": "Save password", "pw.cancel": "Cancel", "pw.mismatch": "The two passwords are not the same.", "pw.saved": "Password saved.",
      "pw.removed": "Password removed.", "pw.wrong": "The current password is not right.", "pw.short": "Use at least 10 characters.",
      "pw.confirm": "Remove your password? You can still sign in with an e-mail link or Google.",
      "alerts.label": "Job alerts by e-mail", "alerts.off": "Off", "alerts.daily": "Daily", "alerts.weekly": "Weekly",
      "alerts.saved": "Saved.",
      "alerts.noprofile": "Saved. Set roles, cities or skills in your profile below, or the alert matches every new job.",
      "acct.login": "Log in", "acct.settings": "Account settings", "acct.none.title": "You are not logged in",
      "acct.nudge": 'Your profile and saved jobs are kept in this browser. <a href="/login">Log in</a> to have them on every device.',
      "acct.loggedout": "You are logged out.",
      "acct.fail": "Could not send the link. Try again later.",
      "acct.expired": "That login link has expired or was already used. Request a new one.", "acct.welcome": "You are logged in.",
      "acct.in.as": "Logged in as",
      "acct.synced": "Synced.", "acct.sync.fail": "Not synced; changes are kept in this browser.", "acct.logout": "Log out",
      "acct.export": "Download data", "acct.delete": "Delete account",
      "acct.delete.confirm": "Delete your account? Your e-mail address, profile and saved jobs are removed from the server. This browser keeps its own copy.",
      "acct.deleted": "Your account is deleted.", "privacy": "Privacy", "feedback": "Feedback",
      "also.in": "Also advertised in {c}",
      "fresh.text": "New listings are in", "fresh.none": "No new listings yet", "fresh.reload": "Refresh",
      "adm.title": "Admin: refresh listings", "adm.token": "Admin token", "adm.company": "Employer (for a single-employer crawl)",
      "adm.force": "Ignore the 10-minute cool-down", "adm.due": "Crawl sources that are due", "adm.one": "Crawl this employer", "adm.all": "Crawl everything",
     
      "f.exp": "Experience asked", "p.exp": "Experience asked", "mk.exp": "Experience asked", "yrs": "yrs",
      "f.size": "Hiring activity (open roles)", "f.sort.small": "Smaller organisations first", "f.sort.large": "Larger organisations first",
      "f.emp": "Company size (employees)", "f.sector": "Sector", "mk.sector": "Sectors", "f.position": "Position", "mk.position": "Most common positions", "ph.position": "position, e.g. data engineer…", "pos.unknown": "Pick a position from the list", "pos.phd_research": "PhD / research", "pos.product_manager": "Product manager", "pos.product_owner": "Product owner", "pos.scrum_agile": "Scrum master / agile coach", "pos.project_manager": "IT project / programme manager", "pos.engineering_manager": "Engineering manager", "pos.ux_designer": "UX / UI designer", "pos.security_officer": "Security officer / GRC", "pos.security_engineer": "Security engineer / analyst", "pos.data_scientist": "Data scientist", "pos.ml_engineer": "AI / ML engineer", "pos.data_consultant": "Data / AI consultant", "pos.data_architect": "Data architect", "pos.bi_analyst": "BI / data analyst", "pos.data_engineer": "Data engineer", "pos.business_analyst": "Business / IT analyst", "pos.architect": "Solution / enterprise architect", "pos.sales_engineer": "Solutions / sales engineer", "pos.low_code": "Low-code developer", "pos.embedded": "Embedded / firmware engineer", "pos.plc_automation": "PLC / industrial automation engineer", "pos.hardware": "Hardware / electronics engineer", "pos.simulation": "Simulation / modelling engineer", "pos.qa_test": "QA / test engineer", "pos.devops": "DevOps engineer", "pos.platform_sre": "Platform / SRE engineer", "pos.cloud": "Cloud engineer", "pos.network": "Network engineer", "pos.systems": "Systems / infrastructure engineer", "pos.app_admin": "Application administrator", "pos.it_support": "IT support / workplace", "pos.it_consultant": "IT / ERP consultant", "pos.mobile": "Mobile developer", "pos.frontend": "Frontend developer", "pos.fullstack": "Full-stack developer", "pos.software_engineer": "Software engineer / developer", "pos.other": "Other", "sector.software": "Software & internet", "sector.consultancy": "Consultancy & IT services", "sector.hardware": "Semiconductors & hardware", "sector.finance": "Banking, finance & insurance", "sector.pharma": "Pharma & life sciences", "sector.health": "Healthcare", "sector.government": "Government & public sector", "sector.education": "Education & research", "sector.energy": "Energy & utilities", "sector.transport": "Transport & logistics", "sector.engineering": "Engineering & construction", "sector.industry": "Industry & manufacturing", "sector.retail": "Retail & consumer goods", "sector.telecom_media": "Telecom & media", "sector.staffing": "Recruitment agencies", "sector.other": "Other",
      "emp.1-49": "under 50", "emp.50-249": "50-249", "emp.250-4999": "250-4,999", "emp.5000+": "5,000+", "emp.unknown": "unknown",
     
      "size.small": "a few openings (under 10)", "size.medium": "10-99 openings", "size.large": "100+ openings",
      "f.noenrol": "Exclude internships that require enrolment",
      "enrol.required": "enrolment required", "enrol.open": "open to graduates",
      "f.degree": "Degree asked",
      "deg.bachelor": "Bachelor's (HBO / WO)", "deg.master": "Master's", "deg.phd": "PhD", "deg.mbo": "MBO", "deg.unstated": "not stated",
      "exp.none": "none asked (entry level)", "exp.1": "≤ 1 year", "exp.2-3": "2-3 years", "exp.4-5": "4-5 years", "exp.6+": "6+ years", "exp.unspecified": "not stated",
      "co.back": "← Market", "co.skills": "Skills asked for", "co.level": "Seniority", "co.lang": "Posting language", "co.roles": "Open tech roles",
      "co.kpi.roles": "open tech roles", "co.kpi.cities": "cities", "co.kpi.en": "need no Dutch", "co.kpi.visa": "mention visa sponsorship", "co.kpi.new": "new in 30 days",
      "co.none": "No open tech roles at the moment.", "co.title": "{c}: tech jobs", "co.permalink": "Permanent page", "co.all": "All employers",
     
     
     
    },
    nl: {
      "tab.overview": "Overzicht", "tab.jobs": "Vacatures", "tab.market": "Markt", "tab.profile": "Profiel",
      
      
      "ov.skills": "Meest gevraagde skills",
      "ov.graph": "Skills die samen gevraagd worden",
      "ov.matches": "Beste matches voor jou",
      "ov.matches.empty": 'Voeg je skills toe onder <a href="#profile">Profiel</a> om matches te zien.',
      "f.search": "Zoeken", "f.search.ph": "functietitel of werkgever", "f.window": "Periode", "f.window.all": "Alle open", "f.window.1": "Laatste 24 uur",
      "f.window.7": "Laatste 7 dagen", "f.window.30": "Laatste 30 dagen", "f.window.90": "Laatste 90 dagen",
      "f.language": "Taal", "f.language.any": "Nederlands en/of Engels", "f.language.nl": "Alleen Nederlands (geen Engels nodig)", "f.language.en": "Engels (geen Nederlands vereist)",
      "f.sort": "Sorteren", "f.sort.newest": "Nieuwste", "f.sort.match": "Beste match", "f.role": "Rol", "f.level": "Niveau", "f.remote": "Thuiswerken",
      "f.cities": "Steden", "f.visa": "Visumsponsoring genoemd", "f.agencies": "Bureaus verbergen", 
      "f.saved": "Alleen bewaard", "f.skill": "Skill", "f.reset": "Filters wissen", "f.profile": "Mijn profiel gebruiken",
      "th.age": "Leeftijd", "th.title": "Functie", "th.company": "Werkgever", "th.city": "Plaats", "th.level": "Niveau", "th.skills": "Skills",
      "th.match": "Match", "th.lang": "Taal", "th.visa": "Visum", "th.employer": "Werkgever", "th.open": "Open techvacatures", "th.share": "Aandeel",
      "th.sector": "Sector", "th.status": "Status", "th.livetech": "Open techvacatures", "th.platform": "Platform", "th.kind": "Soort", "th.postings": "Vacatures",
      "pager.prev": "‹ Vorige", "pager.next": "Volgende ›",
      "mk.trend": "Nieuwe vacatures per week", "mk.trend.hint": "en de skills die je volgt", "mk.cities": "Steden", "mk.seniority": "Niveau",
      "mk.roles": "Rolfamilie", "mk.hiring": "Wie neemt aan", "mk.salary": "Vermelde salarissen", "mk.salary.hint": "per jaar",
      "mk.lang": "Taal van de vacature", "mk.remote": "Thuiswerkbeleid",
      "p.looking": "Voorkeuren",
      "p.roles": "Rollen", "p.levels": "Niveaus", "p.exclude": "Werkgevers verbergen", "p.language": "Taal van de vacature",
      "p.visa": "Alleen vacatures die visumsponsoring noemen", "p.agencies": "Wervingsbureaus verbergen", "p.save": "Profiel opslaan", "p.export": "Exporteren",
      "p.import": "Importeren", "p.clear": "Wissen", "p.skills": "Skills",
      "p.extract": "Skills uit cv-tekst halen", "p.cv.ph": "Plak je cv-tekst", "p.extract.btn": "Herkennen",
      "p.gap": "Gap-analyse", "p.gap.btn": "Analyseren", "p.saved": "Bewaarde vacatures",
     
     
     
     
     
      "kpi.live": "open techvacatures", "kpi.employers": "werkgevers", "kpi.crawl": "laatste crawl",
      "title": "{n} ICT en tech vacatures in Nederland",
     
      
     
      "match.none": "Geen open vacature past bij al je profielfilters. Versoepel een niveau of stad onder Profiel.",
      "li.match": "match {p}%", "li.have": "je hebt {s}", "li.missing": "mist {s}", "agency": "bureau", "closed": "gesloten",
      "jobs.match": "{n} vacatures gevonden", "jobs.match.one": "1 vacature gevonden", "page": "pagina {p} van {t}", "today": "vandaag", "yesterday": "gisteren", "days.ago": "{d}d geleden", "old": "oud", 
      "lang.nl": "NL", "lang.en": "EN", "lang.both": "NL + EN", "lang.nl.title": "Nederlands vereist, geen Engels nodig", "lang.en.title": "Geen Nederlands vereist", "lang.both.title": "Nederlands en Engels allebei vereist",
      "visa.yes": "ja", "visa.no": "nee", "visa.unknown": "?", "save": "bewaren", "remove": "verwijderen",
      "salary.none": "Geen vacature in deze selectie noemt een salaris.", "salary.n": "vacatures noemen een salaris", "salary.median": "mediaan", "salary.p25": "onderste kwart", "salary.p75": "bovenste kwart",
      "lang.chart.en": "Engels", "lang.chart.nl": "Nederlands", "lang.chart.other": "Anders",
      "remote.remote": "Volledig thuis", "remote.hybrid": "Hybride", "remote.onsite": "Op kantoor", "remote.unknown": "Niet vermeld",
      "trend.all": "alle nieuwe vacatures",
      "p.saved.empty": "Markeer een vacature met een ster in het tabblad Vacatures om hem hier te bewaren.", "p.saved.status": "Opgeslagen. Persoonlijke weergave staat aan.", "p.imported": "Geïmporteerd.",
      "p.import.fail": "Kon dat bestand niet lezen.", "p.more.text": "Plak eerst wat meer tekst.", "p.extracting": "Bezig met herkennen…",
      "p.extracted": "{n} skills gevonden; klik op Profiel opslaan om ze te bewaren.", "p.add.skills": "Voeg eerst wat skills toe.", "p.analysing": "Bezig met analyseren…",
      "p.considered": "{n} vacatures bekeken", "p.coverage": "Je skills dekken {p}% van alle skillvermeldingen in deze vacatures. De meest gevraagde skills die je niet noemt:",
      "skill.tracked": "“{v}” wordt bijgehouden als “{c}”.", "skill.unknown": "“{v}” is geen bijgehouden skill en telt niet mee voor matches.",
      "ph.city": "stad…", "ph.employer": "naam werkgever…", "ph.skill": "skill…",
     
     
     
     
      "role.ml": "ML / AI", "role.data": "Data", "role.backend": "Backend", "role.frontend": "Frontend", "role.fullstack": "Full-stack", "role.platform": "Platform / DevOps",
      "role.mobile": "Mobiel", "role.embedded": "Embedded / hardware", "role.simulation": "Simulatie / modellering", "role.security": "Security", "role.qa": "QA / Test", "role.product": "Product", "role.design": "Design", "role.it_support": "IT-support", "role.other": "Overig",
      "level.intern": "stage", "level.trainee": "traineeship / starterprogramma", "level.junior": "junior", "level.medior": "medior", "level.senior": "senior", "level.lead": "lead", "level.staff": "staff / principal", "level.manager": "manager", "level.unknown": "onbekend",
      "fail": "Laden mislukt: {e}",
      "f.confirmed": "Alleen bevestigd op de site van de werkgever in de laatste 7 dagen",
     
      "trust.seen": "Nog vermeld op de eigen site van de werkgever op {d}", "trust.checked": "pagina geopend en gecontroleerd op {d}",
      "trust.expires": "sluit op {d}",
      "loading": "De nieuwste vacatures laden…",
      "pw.choose": "Kies je nieuwe wachtwoord.", "pw.label": "Wachtwoord", "pw.none": "Nog geen wachtwoord. Je logt in met een e-maillink of Google; voeg een wachtwoord toe om daar ook mee in te loggen.",
      "pw.has": "Je kunt inloggen met je wachtwoord, een e-maillink of Google.", "pw.set": "Wachtwoord instellen", "pw.change": "Wachtwoord wijzigen",
      "pw.remove": "Wachtwoord verwijderen", "pw.current": "Huidig wachtwoord", "pw.new": "Nieuw wachtwoord (10+ tekens)", "pw.repeat": "Herhaal het nieuwe wachtwoord",
      "pw.save": "Wachtwoord opslaan", "pw.cancel": "Annuleren", "pw.mismatch": "De twee wachtwoorden zijn niet gelijk.", "pw.saved": "Wachtwoord opgeslagen.",
      "pw.removed": "Wachtwoord verwijderd.", "pw.wrong": "Het huidige wachtwoord klopt niet.", "pw.short": "Gebruik minstens 10 tekens.",
      "pw.confirm": "Je wachtwoord verwijderen? Je kunt nog steeds inloggen met een e-maillink of Google.",
      "alerts.label": "Vacature-alerts per e-mail", "alerts.off": "Uit", "alerts.daily": "Dagelijks", "alerts.weekly": "Wekelijks",
      "alerts.saved": "Opgeslagen.",
      "alerts.noprofile": "Opgeslagen. Kies functies, steden of skills in je profiel hieronder, anders past elke nieuwe vacature.",
      "acct.login": "Inloggen", "acct.settings": "Accountinstellingen", "acct.none.title": "Je bent niet ingelogd",
      "acct.nudge": 'Je profiel en bewaarde vacatures staan in deze browser. <a href="/nl/inloggen">Log in</a> om ze op elk apparaat te hebben.',
      "acct.loggedout": "Je bent uitgelogd.",
      "acct.fail": "De link kon niet worden verstuurd. Probeer het later opnieuw.",
      "acct.expired": "Die inloglink is verlopen of al gebruikt. Vraag een nieuwe aan.", "acct.welcome": "Je bent ingelogd.",
      "acct.in.as": "Ingelogd als",
      "acct.synced": "Gesynchroniseerd.", "acct.sync.fail": "Niet gesynchroniseerd; wijzigingen blijven in deze browser.", "acct.logout": "Uitloggen",
      "acct.export": "Gegevens downloaden", "acct.delete": "Account verwijderen",
      "acct.delete.confirm": "Je account verwijderen? Je e-mailadres, profiel en bewaarde vacatures worden van de server verwijderd. Deze browser houdt zijn eigen kopie.",
      "acct.deleted": "Je account is verwijderd.", "privacy": "Privacy", "feedback": "Feedback",
      "also.in": "Ook geadverteerd in {c}",
      "fresh.text": "Er zijn nieuwe vacatures", "fresh.none": "Nog geen nieuwe vacatures", "fresh.reload": "Vernieuwen",
      "adm.title": "Beheer: vacatures verversen", "adm.token": "Beheertoken", "adm.company": "Werkgever (voor één werkgever)",
      "adm.force": "Wachttijd van 10 minuten negeren", "adm.due": "Bronnen verversen die aan de beurt zijn", "adm.one": "Deze werkgever verversen", "adm.all": "Alles verversen",
     
      "f.exp": "Gevraagde ervaring", "p.exp": "Gevraagde ervaring", "mk.exp": "Gevraagde ervaring", "yrs": "jr",
      "f.size": "Wervingsactiviteit (open vacatures)", "f.sort.small": "Kleinere organisaties eerst", "f.sort.large": "Grotere organisaties eerst",
      "f.emp": "Bedrijfsgrootte (medewerkers)", "f.sector": "Sector", "mk.sector": "Sectoren", "f.position": "Functie", "mk.position": "Meest voorkomende functies", "ph.position": "functie, bijv. data engineer…", "pos.unknown": "Kies een functie uit de lijst", "pos.phd_research": "PhD / onderzoek", "pos.product_manager": "Productmanager", "pos.product_owner": "Product owner", "pos.scrum_agile": "Scrum master / agile coach", "pos.project_manager": "IT-project- / programmamanager", "pos.engineering_manager": "Engineering manager", "pos.ux_designer": "UX- / UI-designer", "pos.security_officer": "Security officer / GRC", "pos.security_engineer": "Security engineer / analist", "pos.data_scientist": "Data scientist", "pos.ml_engineer": "AI- / ML-engineer", "pos.data_consultant": "Data- / AI-consultant", "pos.data_architect": "Data-architect", "pos.bi_analyst": "BI- / data-analist", "pos.data_engineer": "Data engineer", "pos.business_analyst": "Business- / IT-analist", "pos.architect": "Solution- / enterprise-architect", "pos.sales_engineer": "Solutions- / sales engineer", "pos.low_code": "Low-code developer", "pos.embedded": "Embedded- / firmware-engineer", "pos.plc_automation": "PLC- / industriële automatisering", "pos.hardware": "Hardware- / elektronica-engineer", "pos.simulation": "Simulatie- / modelleringsengineer", "pos.qa_test": "QA- / testengineer", "pos.devops": "DevOps-engineer", "pos.platform_sre": "Platform- / SRE-engineer", "pos.cloud": "Cloud-engineer", "pos.network": "Netwerkengineer", "pos.systems": "Systeem- / infrastructuurengineer", "pos.app_admin": "Applicatie- / functioneel beheerder", "pos.it_support": "IT-support / werkplek", "pos.it_consultant": "IT- / ERP-consultant", "pos.mobile": "Mobiele developer", "pos.frontend": "Frontend developer", "pos.fullstack": "Full-stack developer", "pos.software_engineer": "Software engineer / developer", "pos.other": "Overig", "sector.software": "Software & internet", "sector.consultancy": "Consultancy & IT-dienstverlening", "sector.hardware": "Halfgeleiders & hardware", "sector.finance": "Bank, financiën & verzekeringen", "sector.pharma": "Farma & life sciences", "sector.health": "Zorg", "sector.government": "Overheid & publieke sector", "sector.education": "Onderwijs & onderzoek", "sector.energy": "Energie & nutsbedrijven", "sector.transport": "Transport & logistiek", "sector.engineering": "Ingenieursdiensten & bouw", "sector.industry": "Industrie & productie", "sector.retail": "Retail & consumentengoederen", "sector.telecom_media": "Telecom & media", "sector.staffing": "Werving & detachering", "sector.other": "Overig",
      "emp.1-49": "minder dan 50", "emp.50-249": "50-249", "emp.250-4999": "250-4.999", "emp.5000+": "5.000+", "emp.unknown": "onbekend",
     
      "size.small": "enkele vacatures (minder dan 10)", "size.medium": "10-99 vacatures", "size.large": "100+ vacatures",
      "f.noenrol": "Stages die inschrijving bij een opleiding eisen verbergen",
      "enrol.required": "inschrijving vereist", "enrol.open": "ook voor afgestudeerden",
      "f.degree": "Gevraagde opleiding",
      "deg.bachelor": "Bachelor (hbo / wo)", "deg.master": "Master", "deg.phd": "PhD", "deg.mbo": "Mbo", "deg.unstated": "niet vermeld",
      "exp.none": "geen ervaring gevraagd (starter)", "exp.1": "≤ 1 jaar", "exp.2-3": "2-3 jaar", "exp.4-5": "4-5 jaar", "exp.6+": "6+ jaar", "exp.unspecified": "niet vermeld",
      "co.back": "← Markt", "co.skills": "Gevraagde skills", "co.level": "Niveau", "co.lang": "Taal van de vacature", "co.roles": "Open techvacatures",
      "co.kpi.roles": "open techvacatures", "co.kpi.cities": "steden", "co.kpi.en": "zonder Nederlands", "co.kpi.visa": "noemen visumsponsoring", "co.kpi.new": "nieuw in 30 dagen",
      "co.none": "Op dit moment geen open techvacatures.", "co.title": "{c}: techvacatures", "co.permalink": "Vaste pagina", "co.all": "Alle werkgevers",
     
     
     
    },
  };
  const store = {
    get(k, d) { try { const v = localStorage.getItem("radar." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) {
      try { localStorage.setItem("radar." + k, JSON.stringify(v)); } catch { /* private mode */ }
      if (k === "profile" || k === "saved") account.push();
    },
  };
  // anonymous usage events for the admin analytics page (radar/analytics.py): no cookie, no personal data
  const beacon = (e, d) => {
    try {
      const body = new Blob([JSON.stringify({ e, d: d == null ? null : String(d), p: location.pathname + location.hash })], { type: "application/json" });
      if (!(navigator.sendBeacon && navigator.sendBeacon("/api/e", body))) fetch("/api/e", { method: "POST", body, keepalive: true }).catch(() => {});
    } catch { /* statistics are optional */ }
  };
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest && ev.target.closest("a[data-pid]");
    if (a) beacon("job_click", a.dataset.pid);
  }, true);
  // ---------- account (optional; see radar/auth.py) ----------
  const account = {
    me: null, timer: null,
    async load() {
      try { const r = await fetch("/api/me", { credentials: "same-origin" }); this.me = r.ok ? await r.json() : null; } catch { this.me = null; }
      if (!this.me || !this.me.signed_in) { this.me = null; return; }
      try {
        const d = await (await fetch("/api/me/data", { credentials: "same-origin" })).json();
        // saved jobs: the union of both sides; profile: the account's copy wins once it has one
        const saved = [...new Set([...(d.saved || []), ...state.saved])];
        state.saved.splice(0, state.saved.length, ...saved);
        if (d.updated_at && d.profile && Object.keys(d.profile).length) state.profile = Object.assign(emptyProfile(), d.profile);
        try { localStorage.setItem("radar.profile", JSON.stringify(state.profile)); localStorage.setItem("radar.saved", JSON.stringify(state.saved)); } catch { /* private mode */ }
        this.push(0);
      } catch { /* offline: keep the local copy */ }
    },
    push(delay = 800) {
      if (!this.me) return;
      clearTimeout(this.timer);
      this.timer = setTimeout(async () => {
        const el = document.getElementById("acct-sync");
        try {
          const r = await fetch("/api/me/data", { method: "PUT", credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-Requested-With": "radar" },
            body: JSON.stringify({ profile: state.profile, saved: state.saved }) });
          if (el) el.textContent = r.ok ? t("acct.synced") : t("acct.sync.fail");
        } catch { if (el) el.textContent = t("acct.sync.fail"); }
      }, delay);
    },
    async post(path, method = "POST", body = null) {
      return fetch(path, { method, credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Requested-With": "radar" }, body: body ? JSON.stringify(body) : null });
    },
  };
  // stored choice first; then the page itself (/nl/ is served in Dutch); then the browser
  const pageLang = location.pathname.startsWith("/nl") ? "nl" : null;
  let LANG = store.get("lang", null) || pageLang || ((navigator.language || "").toLowerCase().startsWith("nl") ? "nl" : "en");
  const t = (key, vars = {}) => {
    let s = (I18N[LANG] && I18N[LANG][key]) || I18N.en[key] || key;
    Object.entries(vars).forEach(([k, v]) => { s = s.replace(new RegExp(`\\{${k}\\}`, "g"), v); });
    return s;
  };
  // Cities are stored under their English names; the Dutch interface shows the Dutch ones.
  const CITY_NL = { "The Hague": "Den Haag", "Flushing": "Vlissingen", "Nijmegen": "Nijmegen" };
  const cityLabel = (c) => (LANG === "nl" && CITY_NL[c]) || c || "";
  const roleLabel = (r) => t("role." + r) === "role." + r ? r : t("role." + r);
  const levelLabel = (l) => t("level." + l) === "level." + l ? l : t("level." + l);
  const remoteLabel = (r) => t("remote." + r);
  const expLabel = (e) => t("exp." + e);
  const degreeLabel = (d) => t("deg." + d);
  const sizeLabel = (z) => t("size." + z);
  const empLabel = (e) => t("emp." + e);
  const sectorLabel = (s) => t("sector." + s);
  const positionLabel = (s) => t("pos." + s);
  // typed text becomes the position whose name it matches; anything else is not added
  const positionPick = (v) => {
    const q = v.trim().toLowerCase();
    const hit = state.options.positions.find((k) => k === v) || state.options.positions.find((k) => positionLabel(k).toLowerCase() === q)
      || state.options.positions.find((k) => positionLabel(k).toLowerCase().includes(q));
    return hit ? { value: hit } : { value: null, note: t("pos.unknown") };
  };
  // NL: Dutch is enough; EN: no Dutch needed; NL + EN: both asked for
  const langKey = (i) => (i.english_only ? "en" : i.english_required === false ? "nl" : "both");
  const langCell = (i) => `<span class="lang-${langKey(i)}" title="${t("lang." + langKey(i) + ".title")}">${t("lang." + langKey(i))}</span>`;
  const levelCell = (i) => {
    const lvl = i.seniority === "unknown" || !i.seniority ? "" : levelLabel(i.seniority);
    const yrs = i.years_text ? `${i.years_text.replace("-", "–")} ${t("yrs")}` : i.years != null ? `${i.years}+ ${t("yrs")}` : "";
    const enrol = i.seniority === "intern" && i.enrollment_required === true ? t("enrol.required")
      : i.seniority === "intern" && i.enrollment_required === false ? t("enrol.open") : "";
    return esc([lvl, yrs, enrol].filter(Boolean).join(" · "));
  };
  function applyI18n() {
    document.documentElement.lang = LANG;
    $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $$("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    $$("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    $$("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    $$("#langswitch button").forEach((b) => b.classList.toggle("on", b.dataset.lang === LANG));
  }

  // ---------- state ----------
  const emptyProfile = () => ({ roles: [], positions: [], levels: [], exp: [], degrees: [], emps: [], sectors: [], sizes: [], remote: [], cities: [], exclude: [], skills: [],
    language: "", visa: false, agencies: false, noenrol: false });
  const state = {
    tab: "overview", page: 1, size: 40, sort: "newest", skill: null,
    profile: Object.assign(emptyProfile(), store.get("profile", {})),
    saved: store.get("saved", []),
    options: { roles: [], positions: [], cities: [], skills: [] },
    charts: {}, overview: null,
  };
  if (state.profile.english && !state.profile.language) state.profile.language = "en";  // older profiles
  if (!Array.isArray(state.profile.exp)) state.profile.exp = [];
  if (!Array.isArray(state.profile.degrees)) state.profile.degrees = [];
  if (!Array.isArray(state.profile.emps)) state.profile.emps = [];
  if (!Array.isArray(state.profile.sizes)) state.profile.sizes = [];
  let jobFilters = null;

  // ---------- helpers ----------
  function fmt(n) { return n == null ? "-" : Number(n).toLocaleString(LANG === "nl" ? "nl-NL" : "en-GB"); }
  function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  async function api(path, params) {
    const url = params ? `${path}?${params.toString()}` : path;
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${r.status} ${url}`);
    return r.json();
  }
  function profileParams(p = state.profile) {
    const q = new URLSearchParams();
    if (p.roles.length) q.set("role", p.roles.join(","));
    if (p.levels.length) q.set("seniority", p.levels.join(","));
    if (p.exp.length) q.set("experience", p.exp.join(","));
    if (p.degrees.length) q.set("degree", p.degrees.join(","));
    if (p.emps.length) q.set("employees", p.emps.join(","));
    if (p.sectors && p.sectors.length) q.set("sector", p.sectors.join(","));
    if (p.positions && p.positions.length) q.set("position", p.positions.join(","));
    if (p.sizes.length) q.set("org_size", p.sizes.join(","));
    if (p.remote.length) q.set("remote", p.remote.join(","));
    if (p.cities.length) q.set("city", p.cities.join(","));
    if (p.exclude.length) q.set("exclude_companies", p.exclude.join(","));
    if (p.language) q.set("language", p.language);
    if (p.visa) q.set("sponsorship", "true");
    if (p.agencies) q.set("exclude_agencies", "true");
    if (p.noenrol) q.set("enrollment", "open");
    return q;
  }
  const hasProfileFilters = () => [...profileParams().keys()].length > 0;

  function withParams(base, extra) { const p = new URLSearchParams(base); Object.entries(extra).forEach(([k, v]) => v != null && v !== "" && p.set(k, v)); return p; }
  function fmtDate(iso) { return new Date(iso).toLocaleString(LANG === "nl" ? "nl-NL" : "en-GB", { dateStyle: "medium", timeStyle: "short" }); }

  // ---------- charts ----------
  // long axis labels ("Simulation / computational") on two lines, so Chart.js does not cut them off
  function wrapLabel(label, max = 26) {
    const s = String(label);
    if (s.length <= max) return s;
    const lines = [""];
    for (const w of s.split(" ")) {
      const cur = lines[lines.length - 1];
      if (cur && (cur + " " + w).length > max) lines.push(w);
      else lines[lines.length - 1] = cur ? cur + " " + w : w;
    }
    return lines;
  }
  function barChart(id, labels, values, { horizontal = true, color = palette[0], onClick, pct = false } = {}) {
    const ctx = document.getElementById(id);
    if (!ctx) return;
    if (state.charts[id]) state.charts[id].destroy();
    state.charts[id] = new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [{ data: values, backgroundColor: color, borderRadius: 4 }] },
      options: {
        indexAxis: horizontal ? "y" : "x", maintainAspectRatio: false,
        onClick: onClick ? (_, els) => { if (els.length) onClick(labels[els[0].index]); } : undefined,
        // a hand cursor over bars that open something, so it is clear they can be clicked
        onHover: onClick ? (e, els) => { e.native.target.style.cursor = els.length ? "pointer" : "default"; } : undefined,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => pct ? `${c.raw}%` : `${c.raw}` } } },
        scales: { x: { grid: { color: css("--line") }, ticks: { color: css("--muted") } },
                  y: { grid: { display: false }, ticks: { color: css("--ink"), autoSkip: false, font: { size: 11 },
                       callback(v) { return horizontal ? wrapLabel(this.getLabelForValue(v)) : this.getLabelForValue(v); } } } },
      },
    });
  }
  function doughnut(id, labels, values) {
    const ctx = document.getElementById(id);
    if (!ctx) return;
    if (state.charts[id]) state.charts[id].destroy();
    state.charts[id] = new Chart(ctx, { type: "doughnut",
      data: { labels, datasets: [{ data: values, backgroundColor: palette, borderWidth: 0 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { position: "right", labels: { color: css("--ink"), boxWidth: 10, font: { size: 11 } } } } } });
  }
  function lineChart(id, labels, series) {
    const ctx = document.getElementById(id);
    if (!ctx) return;
    if (state.charts[id]) state.charts[id].destroy();
    state.charts[id] = new Chart(ctx, { type: "line",
      data: { labels, datasets: series.map((s, i) => ({ label: s.label, data: s.data, borderColor: palette[i % palette.length], backgroundColor: palette[i % palette.length], tension: 0.3, pointRadius: 3 })) },
      options: { maintainAspectRatio: false, plugins: { legend: { labels: { color: css("--ink") } } },
        scales: { x: { ticks: { color: css("--muted") }, grid: { color: css("--line") } }, y: { ticks: { color: css("--muted") }, grid: { color: css("--line") }, beginAtZero: true } } } });
  }
  function graph(el, data, onClick) {
    el.innerHTML = "";
    const w = el.clientWidth, h = el.clientHeight;
    if (!data.nodes.length) { el.innerHTML = `<p class="muted">-</p>`; return; }
    const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${w} ${h}`);
    const max = d3.max(data.nodes, (d) => d.count) || 1;
    const r = d3.scaleSqrt().domain([0, max]).range([4, 26]);
    const wmax = d3.max(data.links, (d) => d.weight) || 1;
    const sw = d3.scaleLinear().domain([0, wmax]).range([0.4, 5]);
    const sim = d3.forceSimulation(data.nodes)
      .force("link", d3.forceLink(data.links).id((d) => d.id).distance((d) => 120 - 60 * (d.weight / wmax)).strength((d) => 0.2 + 0.6 * (d.weight / wmax)))
      .force("charge", d3.forceManyBody().strength(-160)).force("center", d3.forceCenter(w / 2, h / 2))
      .force("collide", d3.forceCollide().radius((d) => r(d.count) + 14));
    const link = svg.append("g").attr("stroke", css("--muted")).attr("stroke-opacity", 0.35).selectAll("line").data(data.links).join("line").attr("stroke-width", (d) => sw(d.weight));
    const node = svg.append("g").selectAll("g").data(data.nodes).join("g").on("click", (_, d) => onClick(d.id))
      .call(d3.drag().on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; }).on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));
    const have = new Set(state.profile.skills);
    node.style("cursor", "pointer");
    // solid dots with an outline in the card colour, so the edges behind them never show through
    node.append("circle").attr("r", (d) => r(d.count)).attr("fill", (d) => have.has(d.id) ? css("--accent-2") : css("--accent"))
      .attr("stroke", css("--card")).attr("stroke-width", 1.5);
    node.append("title").text((d) => `${d.id}: ${d.count}`);
    node.append("text").attr("dy", (d) => r(d.count) + 11).attr("text-anchor", "middle").text((d) => d.id);
    sim.on("tick", () => {
      node.attr("transform", (d) => `translate(${Math.max(20, Math.min(w - 20, d.x))},${Math.max(20, Math.min(h - 20, d.y))})`);
      link.attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y).attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
    });
  }

  // ---------- chip widgets ----------
  function toggles(el, options, selected, labelOf = (x) => x, onChange) {
    el.innerHTML = options.map((o) => `<span class="chip${selected.includes(o) ? " on" : ""}" data-v="${esc(o)}">${esc(labelOf(o))}</span>`).join("");
    el.onclick = (e) => {
      const chip = e.target.closest(".chip"); if (!chip) return;
      const v = chip.dataset.v; const i = selected.indexOf(v);
      if (i >= 0) selected.splice(i, 1); else selected.push(v);
      chip.classList.toggle("on"); onChange && onChange(selected);
    };
  }
  async function canonicalSkills(names) {
    if (!names.length) return {};
    try { return await api("/api/skills/canonical", new URLSearchParams({ names: names.join(",") })); } catch { return {}; }
  }
  function chipInput(el, values, suggestions, onChange, placeholder = "…", transform = null, labelOf = (x) => x) {
    let active = -1;
    const render = () => {
      el.innerHTML = values.map((v) => `<span class="chip">${esc(labelOf(v))}<button data-v="${esc(v)}" title="${t("remove")}">×</button></span>`).join("") +
        `<input type="text" placeholder="${esc(placeholder)}" autocomplete="off"><div class="suggest" hidden></div>`;
      const input = $("input", el), box = $(".suggest", el);
      const matches = () => {
        const q = input.value.trim().toLowerCase();
        const pool = suggestions.filter((s) => !values.includes(s));
        const hits = q ? pool.filter((s) => s.toLowerCase().includes(q) || labelOf(s).toLowerCase().includes(q)).sort((a, b) => a.toLowerCase().startsWith(q) === b.toLowerCase().startsWith(q) ? a.localeCompare(b) : (a.toLowerCase().startsWith(q) ? -1 : 1)) : pool;
        return hits.slice(0, 40);
      };
      const paint = () => {
        const hits = matches();
        if (!hits.length || !suggestions.length) { box.hidden = true; return; }
        box.innerHTML = hits.map((s, i) => `<div class="opt${i === active ? " on" : ""}" data-v="${esc(s)}">${esc(labelOf(s))}</div>`).join("");
        box.hidden = false;
        const on = $(".opt.on", box); if (on) on.scrollIntoView({ block: "nearest" });
      };
      input.addEventListener("focus", () => { active = -1; paint(); });
      input.addEventListener("input", () => { active = -1; paint(); });
      input.addEventListener("blur", () => setTimeout(() => { box.hidden = true; }, 150));
      input.addEventListener("keydown", (e) => {
        const hits = matches();
        if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, hits.length - 1); paint(); return; }
        if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, -1); paint(); return; }
        if (e.key === "Escape") { box.hidden = true; return; }
        if (e.key === "Enter") {
          e.preventDefault();
          const typed = input.value.trim().toLowerCase();
          const pick = active >= 0 ? hits[active] : (typed && hits.find((h) => h.toLowerCase() === typed || labelOf(h).toLowerCase() === typed)) || input.value.trim();
          if (pick) add(pick);
          return;
        }
        if (e.key === "Backspace" && !input.value && values.length) { values.pop(); render(); onChange && onChange(values); }
      });
      box.addEventListener("mousedown", (e) => { const o = e.target.closest(".opt"); if (o) { e.preventDefault(); add(o.dataset.v); } });
    };
    const add = async (v) => {
      if (transform) { const r = await transform(v); if (r.note) showNote(el, r.note); v = r.value; }
      if (!v) return;
      if (!values.includes(v)) values.push(v);
      render(); onChange && onChange(values); $("input", el).focus();
    };
    el.onclick = (e) => { const b = e.target.closest("button"); if (b) { values.splice(values.indexOf(b.dataset.v), 1); render(); onChange && onChange(values); } };
    render();
  }
  function showNote(el, text) {
    let n = el.nextElementSibling;
    if (!n || !n.classList.contains("note")) { n = document.createElement("p"); n.className = "note muted small"; el.after(n); }
    n.textContent = text; clearTimeout(n._t); n._t = setTimeout(() => { n.textContent = ""; }, 4000);
  }
  const skillTransform = async (v) => {
    const m = await canonicalSkills([v]); const c = m[v];
    if (c && c !== v) return { value: c, note: t("skill.tracked", { v, c }) };
    if (!c) return { value: v, note: t("skill.unknown", { v }) };
    return { value: v };
  };

  // ---------- header ----------
  async function loadHeader() {
    const [o, f] = await Promise.all([api("/api/overview"), api("/api/filters")]);
    state.overview = o;
    state.options.roles = [...f.roles.filter((r) => r !== "other"), ...f.roles.filter((r) => r === "other")]; state.options.cities = f.cities.filter((c) => c !== "Unknown"); state.options.skills = f.skills;
    state.options.sectors = [...(f.sectors || []).filter((s) => s !== "other"), ...(f.sectors || []).filter((s) => s === "other")];
    state.options.positions = [...(f.positions || []).filter((s) => s !== "other"), ...(f.positions || []).filter((s) => s === "other")];
    renderHeader();
  }
  function renderHeader() {
    const o = state.overview; if (!o) return;
    const last = o.last_crawl_at ? fmtDate(o.last_crawl_at + "Z") : "-";
    $("#kpis").innerHTML = [
      [fmt(o.live_tech_postings), t("kpi.live")], [fmt(o.companies), t("kpi.employers")],
      [last, t("kpi.crawl")],
    ].map(([v, l]) => `<div class="kpi"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("");
    document.title = `${document.title.split(":")[0]}: ${t("title", { n: fmt(o.live_tech_postings) })}`;
  }

  // ---------- OVERVIEW ----------
  async function renderOverview() {
    const p = new URLSearchParams();
    const [skills, co] = await Promise.all([api("/api/skills", withParams(p, { top: 30 })), api("/api/cooccurrence", withParams(p, { top: 28 }))]);
    const have = new Set(state.profile.skills);
    barChart("ov-skills", skills.skills.map((s) => s.skill), skills.skills.map((s) => Math.round(s.share * 100)),
      { pct: true, onClick: (s) => openJobsWithSkill(s), color: skills.skills.map((s) => have.has(s.skill) ? palette[1] : palette[0]) });
    graph($("#ov-graph"), co, (s) => openJobsWithSkill(s));
    const mine = profileParams();
    const hasProfile = [...mine.keys()].length > 0;
    if (state.profile.skills.length) {
      $("#ov-match-empty").hidden = true;
      const m = await api("/api/postings", withParams(mine, { sort: "match", skills_have: state.profile.skills.join(","), size: 8 }));
      $("#ov-matches").innerHTML = m.items.length ? m.items.map(li).join("") : `<li class="muted">${t("match.none")}</li>`;
    } else { $("#ov-match-empty").hidden = false; $("#ov-matches").innerHTML = ""; }
  }
  function li(i) {
    const m = i.match != null
      ? [t("li.match", { p: Math.round(i.match * 100) }), i.matched.length ? t("li.have", { s: esc(i.matched.join(", ")) }) : "", i.missing.length ? t("li.missing", { s: esc(i.missing.slice(0, 4).join(", ")) }) : ""].filter(Boolean).join(" · ")
      : (i.skills || []).slice(0, 5).join(", ");
    return `<li><a href="${jobPath(i)}" data-pid="${i.id}" target="_blank">${esc(i.title)}</a> · ${companyLink(i.company)}${i.city ? " · " + esc(cityLabel(i.city)) : ""}${i.via_agency ? ` <span class="chip more">${t("agency")}</span>` : ""}<div class="m">${esc(i.posted_at)} · ${m}</div></li>`;
  }
  function openJobsWithSkill(skill) { state.skill = skill; state.page = 1; location.hash = "#jobs"; }
  function openJobsWithPosition(key) { currentJobFilters().positions = [key]; state.page = 1; location.hash = "#jobs"; }
  // the listing's page on this site (/job/<id>/<slug>): the employer's text with what the radar read from it
  const slugify = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "company";
  const jobPath = (i) => (LANG === "nl" ? "/nl/vacature/" : "/job/") + i.id + "/" + slugify(i.title);
  function companyLink(name) { return `<a class="co" href="#company=${encodeURIComponent(name)}">${esc(name)}</a>`; }

  // ---------- COMPANY ----------
  async function renderCompany() {
    const name = state.routeArg || "";
    $("#co-name").textContent = name;
    const p = new URLSearchParams({ company: name });
    const [jobs, skills, sen, lang, cities, en, visa, fresh] = await Promise.all([
      api("/api/postings", withParams(p, { size: 200, skills_have: state.profile.skills.join(",") || null })),
      api("/api/skills", withParams(p, { top: 15 })), api("/api/breakdown/seniority", p), api("/api/breakdown/posting_language", p),
      api("/api/breakdown/city", withParams(p, { top: 100 })), api("/api/skills", withParams(p, { top: 1, language: "en" })),
      api("/api/skills", withParams(p, { top: 1, sponsorship: "true" })), api("/api/skills", withParams(p, { top: 1, days: 30 })),
    ]);
    const items = jobs.items;
    for (let page = 2; items.length < jobs.total && page <= 10; page++) {
      const more = await api("/api/postings", withParams(p, { size: 200, page, skills_have: state.profile.skills.join(",") || null }));
      if (!more.items.length) break;
      items.push(...more.items);
    }
    const nCities = cities.items.filter((i) => i.key !== "Unknown" && i.key !== "Remote").length;
    $("#co-kpis").innerHTML = [[fmt(jobs.total), t("co.kpi.roles")], [fmt(nCities), t("co.kpi.cities")], [fmt(en.n), t("co.kpi.en")], [fmt(visa.n), t("co.kpi.visa")], [fmt(fresh.n), t("co.kpi.new")]]
      .map(([v, l]) => `<div class="kpi"><b>${v}</b><span>${esc(l)}</span></div>`).join("");
    const have = new Set(state.profile.skills);
    barChart("co-skills", skills.skills.map((x) => x.skill), skills.skills.map((x) => Math.round(x.share * 100)),
      { pct: true, onClick: (sk) => openJobsWithSkill(sk), color: skills.skills.map((x) => have.has(x.skill) ? palette[1] : palette[0]) });
    doughnut("co-seniority", sen.items.map((i) => levelLabel(i.key)), sen.items.map((i) => i.count));
    doughnut("co-lang", lang.items.map((i) => t("lang.chart." + i.key) === "lang.chart." + i.key ? i.key : t("lang.chart." + i.key)), lang.items.map((i) => i.count));
    $("#co-count").textContent = fmt(jobs.total);
    $("#co-permalink").href = "/company/" + name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    document.title = `${document.title.split(":")[0]}: ${t("co.title", { c: name })}`;
    $("#co-jobs tbody").innerHTML = items.length ? items.map((i) => `<tr>
      <td class="muted" title="${esc(i.posted_at)}">${age(i)}</td>
      <td><a href="${jobPath(i)}" data-pid="${i.id}" target="_blank">${esc(i.title)}</a></td>
      <td>${esc(i.city ? cityLabel(i.city) : (i.remote ? "Remote" : ""))}${i.also_in && i.also_in.length ? ` <span class="more-cities" title="${esc(t("also.in", { c: i.also_in.map(cityLabel).join(", ") }))}">+${i.also_in.length}</span>` : ""}</td>
      <td>${levelCell(i)}</td>
      <td><div class="chips">${i.skills.slice(0, 6).map((sk) => `<span class="chip${have.has(sk) ? " have" : ""}">${esc(sk)}</span>`).join("")}</div></td>
      <td>${langCell(i)}</td>
      <td>${i.visa === true ? `<span class="ok">${t("visa.yes")}</span>` : i.visa === false ? `<span class="bad">${t("visa.no")}</span>` : `<span class="muted">${t("visa.unknown")}</span>`}</td>
    </tr>`).join("") : `<tr><td colspan="7" class="muted">${t("co.none")}</td></tr>`;
  }

  // ---------- JOBS ----------
  function profileJobFilters() {
    const p = state.profile;
    return { roles: [...p.roles], positions: [...(p.positions || [])], levels: [...p.levels], exp: [...p.exp], degrees: [...p.degrees], emps: [...p.emps], sectors: [...(p.sectors || [])], sizes: [...p.sizes], remote: [...p.remote], cities: [...p.cities], language: p.language, visa: p.visa, agencies: p.agencies, noenrol: !!p.noenrol, confirmed: false, q: "", days: "", savedOnly: false, exclude: [...p.exclude] };
  }
  const emptyJobFilters = () => ({ roles: [], positions: [], levels: [], exp: [], degrees: [], emps: [], sectors: [], sizes: [], remote: [], cities: [], language: "", visa: false, agencies: false, noenrol: false, confirmed: false, q: "", days: "", savedOnly: false, exclude: [] });
  // the Jobs tab opens with the saved profile's filters. "Reset filters" turns that off for this browser (it is
  // remembered, so a reload does not bring them back); "Use my profile" and saving the profile turn it on again.
  function currentJobFilters() {
    if (!jobFilters) jobFilters = hasProfileFilters() && store.get("jobsUseProfile", true) ? profileJobFilters() : emptyJobFilters();
    return jobFilters;
  }
  function filtersFromParams(q) {
    const list = (k) => (q.get(k) || "").split(",").map((s) => s.trim()).filter(Boolean);
    return Object.assign(emptyJobFilters(), {
      roles: list("role"), positions: list("position"), levels: list("seniority"), exp: list("experience"), degrees: list("degree"),
      emps: list("employees"), sectors: list("sector"), sizes: list("org_size"), remote: list("remote"), cities: list("city"),
      exclude: list("exclude_companies"), language: q.get("language") || "", visa: q.get("sponsorship") === "true",
      agencies: q.get("exclude_agencies") === "true", noenrol: q.get("enrollment") === "open", confirmed: !!q.get("confirmed_days"),
      q: q.get("q") || "", days: q.get("days") || "", savedOnly: q.get("saved") === "1",
    });
  }
  // the current search as a link, so it can be bookmarked or shared (saved jobs stay out of it: they are personal)
  function syncJobsUrl() {
    const q = jobParams();
    q.delete("ids");
    if (currentJobFilters().savedOnly) q.set("saved", "1");
    if (state.sort !== "newest") q.set("sort", state.sort);
    const s = q.toString().replace(/%2C/g, ",");
    const want = "#jobs" + (s ? "?" + s : "");
    if (location.hash !== want) history.replaceState(null, "", location.pathname + location.search + want);
  }
  function jobParams() {
    const f = currentJobFilters();
    const q = new URLSearchParams();
    if (f.roles.length) q.set("role", f.roles.join(","));
    if (f.levels.length) q.set("seniority", f.levels.join(","));
    if (f.exp.length) q.set("experience", f.exp.join(","));
    if (f.degrees.length) q.set("degree", f.degrees.join(","));
    if (f.emps.length) q.set("employees", f.emps.join(","));
    if (f.sectors && f.sectors.length) q.set("sector", f.sectors.join(","));
    if (f.positions && f.positions.length) q.set("position", f.positions.join(","));
    if (f.sizes.length) q.set("org_size", f.sizes.join(","));
    if (f.remote.length) q.set("remote", f.remote.join(","));
    if (f.cities.length) q.set("city", f.cities.join(","));
    if (f.exclude && f.exclude.length) q.set("exclude_companies", f.exclude.join(","));
    if (f.language) q.set("language", f.language);
    if (f.visa) q.set("sponsorship", "true");
    if (f.agencies) q.set("exclude_agencies", "true");
    if (f.noenrol) q.set("enrollment", "open");
    if (f.confirmed) q.set("confirmed_days", "7");
    if (f.q) q.set("q", f.q);
    if (f.days) q.set("days", f.days);
    if (f.savedOnly) q.set("ids", state.saved.join(",") || "0");
    if (state.skill) q.set("skill", state.skill);
    return q;
  }
  let jobsBuilt = false;
  function buildJobsFilters() {
    const f = currentJobFilters();
    toggles($("#f-roles"), state.options.roles, f.roles, roleLabel, () => refreshJobs(true));
    if (!f.positions) f.positions = [];
    chipInput($("#f-position"), f.positions, state.options.positions, () => refreshJobs(true), t("ph.position"), positionPick, positionLabel);
    toggles($("#f-levels"), LEVELS, f.levels, levelLabel, () => refreshJobs(true));
    toggles($("#f-exp"), EXP, f.exp, expLabel, () => refreshJobs(true));
    toggles($("#f-degree"), DEGREES, f.degrees, degreeLabel, () => refreshJobs(true));
    toggles($("#f-sector"), state.options.sectors, f.sectors, sectorLabel, () => refreshJobs(true));
    toggles($("#f-emp"), EMPS, f.emps, empLabel, () => refreshJobs(true));
    toggles($("#f-size"), SIZES, f.sizes, sizeLabel, () => refreshJobs(true));
    toggles($("#f-remote"), REMOTE, f.remote, remoteLabel, () => refreshJobs(true));
    chipInput($("#f-cities"), f.cities, [...state.options.cities, "Remote"], () => refreshJobs(true), t("ph.city"), null, cityLabel);
    $("#f-language").value = f.language || ""; $("#f-visa").checked = f.visa; $("#f-agencies").checked = f.agencies; $("#f-noenrol").checked = !!f.noenrol; $("#f-confirmed").checked = !!f.confirmed;
    $("#f-saved").checked = f.savedOnly; $("#f-q").value = f.q; $("#f-days").value = f.days;
    $("#f-sort").value = state.sort;
    if (!jobsBuilt) {
      jobsBuilt = true;
      [["#f-visa", "visa"], ["#f-agencies", "agencies"], ["#f-noenrol", "noenrol"], ["#f-confirmed", "confirmed"], ["#f-saved", "savedOnly"]]
        .forEach(([id, key]) => $(id).addEventListener("change", (e) => { currentJobFilters()[key] = e.target.checked; refreshJobs(true); }));
      $("#f-language").addEventListener("change", (e) => { currentJobFilters().language = e.target.value; refreshJobs(true); });
      $("#f-days").addEventListener("change", (e) => { currentJobFilters().days = e.target.value; refreshJobs(true); });
      $("#f-sort").addEventListener("change", (e) => { state.sort = e.target.value; refreshJobs(true); });
      let tm; $("#f-q").addEventListener("input", (e) => { clearTimeout(tm); tm = setTimeout(() => { currentJobFilters().q = e.target.value.trim(); refreshJobs(true); }, 350); });
      $("#clear-skill").addEventListener("click", () => { state.skill = null; refreshJobs(true); });
      $("#f-reset").addEventListener("click", () => { store.set("jobsUseProfile", false); jobFilters = emptyJobFilters(); state.skill = null; state.sort = "newest"; buildJobsFilters(); refreshJobs(true); });
      $("#f-profile").addEventListener("click", () => { store.set("jobsUseProfile", true); jobFilters = profileJobFilters(); state.skill = null; buildJobsFilters(); refreshJobs(true); });
      $("#prev").addEventListener("click", () => { state.page--; refreshJobs(); });
      $("#next").addEventListener("click", () => { state.page++; refreshJobs(); });
      $("#postings tbody").addEventListener("click", (e) => { const b = e.target.closest(".star"); if (b) toggleSaved(Number(b.dataset.id), b); });
    }
  }
  function trustText(i) {
    const d = (iso) => iso ? new Date(iso + (iso.endsWith("Z") ? "" : "Z")).toLocaleDateString(LANG === "nl" ? "nl-NL" : "en-GB", { day: "numeric", month: "short" }) : "";
    const parts = [];
    if (i.confirmed_at) parts.push(t("trust.seen", { d: d(i.confirmed_at) }));
    if (i.link_status === "ok" && i.link_checked_at) parts.push(t("trust.checked", { d: d(i.link_checked_at) }));
    if (i.valid_through) parts.push(t("trust.expires", { d: d(i.valid_through) }));
    return parts.join("; ");
  }
  function trustBadge(i) {
    const fresh = i.confirmed_at && (Date.now() - new Date(i.confirmed_at + "Z").getTime()) < 7 * 864e5;
    return fresh ? ` <span class="ok small" title="${esc(trustText(i))}">✓</span>` : "";
  }
  function age(i) { return i.age_days === 0 ? t("today") : i.age_days === 1 ? t("yesterday") : t("days.ago", { d: i.age_days }); }
  async function refreshJobs(resetPage = false) {
    if (resetPage) state.page = 1;
    $("#active-skill").hidden = !state.skill; $("#active-skill-name").textContent = state.skill || "";
    const p = jobParams();
    p.set("page", state.page); p.set("size", state.size);
    const have = state.profile.skills;
    if (have.length) p.set("skills_have", have.join(","));
    if (state.sort !== "match" || have.length) p.set("sort", state.sort);
    syncJobsUrl();
    const d = await api("/api/postings", p);
    const pages = Math.max(1, Math.ceil(d.total / d.size));
    $("#count").textContent = d.total === 1 ? t("jobs.match.one") : t("jobs.match", { n: fmt(d.total) });
    $("#page-info").textContent = t("page", { p: d.page, t: pages });
    $("#prev").disabled = d.page <= 1; $("#next").disabled = d.page >= pages;
    $("#postings tbody").innerHTML = d.items.map((i) => `<tr>
      <td><button class="star${state.saved.includes(i.id) ? " on" : ""}" data-id="${i.id}" title="${t("save")}">${state.saved.includes(i.id) ? "★" : "☆"}</button></td>
      <td class="muted" title="${esc(i.posted_at)}">${age(i)}${i.age_days > 90 ? `<span class="badge stale">${t("old")}</span>` : ""}</td>
      <td><a href="${jobPath(i)}" data-pid="${i.id}" target="_blank" title="${esc(trustText(i))}">${esc(i.title)}</a>${trustBadge(i)}</td>
      <td>${companyLink(i.company)}${i.via_agency ? ` <span class="chip more">${t("agency")}</span>` : ""}</td>
      <td>${esc(i.city ? cityLabel(i.city) : (i.remote ? "Remote" : ""))}${i.also_in && i.also_in.length ? ` <span class="more-cities" title="${esc(t("also.in", { c: i.also_in.map(cityLabel).join(", ") }))}">+${i.also_in.length}</span>` : ""}</td>
      <td>${levelCell(i)}</td>
      <td><div class="chips">${i.skills.slice(0, 6).map((s) => `<span class="chip${have.includes(s) ? " have" : ""}">${esc(s)}</span>`).join("")}${i.skills.length > 6 ? `<span class="chip more">+${i.skills.length - 6}</span>` : ""}</div></td>
      <td>${i.match != null ? `<span class="match-bar" title="${Math.round(i.match * 100)}%"><i style="width:${Math.round(i.match * 100)}%"></i></span>` : '<span class="muted">-</span>'}</td>
      <td>${langCell(i)}</td>
      <td>${i.visa === true ? `<span class="ok">${t("visa.yes")}</span>` : i.visa === false ? `<span class="bad">${t("visa.no")}</span>` : `<span class="muted">${t("visa.unknown")}</span>`}</td>
    </tr>`).join("");
  }
  function toggleSaved(id, btn) {
    const i = state.saved.indexOf(id);
    if (i >= 0) state.saved.splice(i, 1); else { state.saved.push(id); beacon("star"); }
    store.set("saved", state.saved);
    if (btn) { btn.classList.toggle("on"); btn.textContent = state.saved.includes(id) ? "★" : "☆"; }
  }

  // ---------- MARKET ----------
  async function renderMarket() {
    const p = new URLSearchParams();
    const [city, sen, role, comp, sal, lang, remote, exp, sector, pos] = await Promise.all([
      api("/api/breakdown/city", withParams(p, { top: 12 })), api("/api/breakdown/seniority", p),
      api("/api/breakdown/role_family", p), api("/api/breakdown/company", withParams(p, { top: 20 })),
      api("/api/salary", p), api("/api/breakdown/posting_language", p), api("/api/breakdown/remote_policy", p),
      api("/api/breakdown/experience", p), api("/api/breakdown/sector", p),
      api("/api/breakdown/position", withParams(p, { top: 21 })),
    ]);
    const order = (k) => EXP.indexOf(k);
    exp.items.sort((a, b) => order(a.key) - order(b.key));
    doughnut("mk-exp", exp.items.map((i) => expLabel(i.key)), exp.items.map((i) => i.count));
    barChart("mk-city", city.items.map((i) => cityLabel(i.key)), city.items.map((i) => i.count), { color: palette[2] });
    doughnut("mk-seniority", sen.items.map((i) => levelLabel(i.key)), sen.items.map((i) => i.count));
    barChart("mk-role", role.items.map((i) => roleLabel(i.key)), role.items.map((i) => i.count), { color: palette[3] });
    barChart("mk-sector", sector.items.map((i) => sectorLabel(i.key)), sector.items.map((i) => i.count), { color: palette[4] });
    const top = pos.items.filter((i) => i.key !== "other").slice(0, 20);
    barChart("mk-position", top.map((i) => positionLabel(i.key)), top.map((i) => i.count), { color: palette[0], onClick: (l) => openJobsWithPosition(top.find((i) => positionLabel(i.key) === l).key) });
    $("#mk-companies tbody").innerHTML = comp.items.map((i) => `<tr><td>${companyLink(i.key)}</td><td>${i.count}</td><td>${Math.round(i.share * 100)}%</td></tr>`).join("");
    $("#mk-salary").innerHTML = sal.n
      ? [[t("salary.n"), fmt(sal.n)], [t("salary.p25"), "€" + fmt(sal.p25)], [t("salary.median"), "€" + fmt(sal.median)], [t("salary.p75"), "€" + fmt(sal.p75)]].map(([l, v]) => `<div class="kpi"><b>${v}</b><span>${esc(l)}</span></div>`).join("")
      : `<p class="muted">${t("salary.none")}</p>`;
    doughnut("mk-lang", lang.items.map((i) => t("lang.chart." + i.key) === "lang.chart." + i.key ? i.key : t("lang.chart." + i.key)), lang.items.map((i) => i.count));
    doughnut("mk-remote", remote.items.map((i) => remoteLabel(i.key)), remote.items.map((i) => i.count));
  }

  // ---------- PROFILE ----------
  let profileBuilt = false;
  function renderProfile() {
    const p = state.profile;
    toggles($("#p-roles"), state.options.roles, p.roles, roleLabel);
    if (!p.positions) p.positions = [];
    chipInput($("#p-position"), p.positions, state.options.positions, null, t("ph.position"), positionPick, positionLabel);
    toggles($("#p-levels"), LEVELS, p.levels, levelLabel);
    toggles($("#p-exp"), EXP, p.exp, expLabel);
    toggles($("#p-degree"), DEGREES, p.degrees, degreeLabel);
    if (!p.sectors) p.sectors = [];
    toggles($("#p-sector"), state.options.sectors, p.sectors, sectorLabel);
    toggles($("#p-emp"), EMPS, p.emps, empLabel);
    toggles($("#p-size"), SIZES, p.sizes, sizeLabel);
    toggles($("#p-remote"), REMOTE, p.remote, remoteLabel);
    chipInput($("#p-cities"), p.cities, [...state.options.cities, "Remote"], null, t("ph.city"), null, cityLabel);
    chipInput($("#p-exclude"), p.exclude, [], null, t("ph.employer"));
    chipInput($("#p-skills"), p.skills, state.options.skills, null, t("ph.skill"), skillTransform);
    $("#p-language").value = p.language || ""; $("#p-visa").checked = p.visa; $("#p-agencies").checked = p.agencies; $("#p-noenrol").checked = !!p.noenrol;
    renderSaved();
    if (profileBuilt) return;
    profileBuilt = true;
    canonicalSkills(p.skills).then((m) => {
      const fixed = []; p.skills.forEach((s) => { const c = m[s] || s; if (!fixed.includes(c)) fixed.push(c); });
      if (JSON.stringify(fixed) !== JSON.stringify(p.skills)) { p.skills.splice(0, p.skills.length, ...fixed); store.set("profile", p); chipInput($("#p-skills"), p.skills, state.options.skills, null, t("ph.skill"), skillTransform); }
    });
    $("#p-save").addEventListener("click", () => {
      p.language = $("#p-language").value; p.visa = $("#p-visa").checked; p.agencies = $("#p-agencies").checked; p.noenrol = $("#p-noenrol").checked;
      delete p.english;
      store.set("profile", p); store.set("jobsUseProfile", true); jobFilters = null; beacon("profile_save");
      $("#p-status").textContent = t("p.saved.status"); setTimeout(() => $("#p-status").textContent = "", 3000);
      loadHeader();
    });
    $("#p-reset").addEventListener("click", () => { state.profile = emptyProfile(); store.set("profile", state.profile); jobFilters = null; renderProfile(); });
    $("#p-export").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify({ profile: state.profile, saved: state.saved }, null, 2)], { type: "application/json" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "radar-profile.json"; a.click();
    });
    $("#p-import").addEventListener("change", async (e) => {
      const file = e.target.files[0]; if (!file) return;
      try { const d = JSON.parse(await file.text()); state.profile = Object.assign(emptyProfile(), d.profile || d); if (Array.isArray(d.saved)) state.saved = d.saved;
        store.set("profile", state.profile); store.set("saved", state.saved); jobFilters = null; renderProfile(); $("#p-status").textContent = t("p.imported"); }
      catch { $("#p-status").textContent = t("p.import.fail"); }
    });
    $("#p-extract").addEventListener("click", async () => {
      const text = $("#p-cv").value.trim();
      if (text.length < 20) { $("#p-extract-status").textContent = t("p.more.text"); return; }
      $("#p-extract-status").textContent = t("p.extracting");
      const r = await fetch("/api/gap", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cv_text: text, days: 30 }) });
      const g = await r.json();
      g.cv_skills.forEach((s) => { if (!p.skills.includes(s)) p.skills.push(s); });
      chipInput($("#p-skills"), p.skills, state.options.skills, null, t("ph.skill"), skillTransform);
      $("#p-extract-status").textContent = t("p.extracted", { n: g.cv_skills.length });
      $("#p-cv").value = "";
    });
    $("#p-gap").addEventListener("click", async () => {
      if (!p.skills.length) { $("#p-gap-status").textContent = t("p.add.skills"); return; }
      $("#p-gap-status").textContent = t("p.analysing");
      const body = { skills: p.skills, role: p.roles.join(",") || null, seniority: p.levels.join(",") || null, city: p.cities.join(",") || null,
        language: p.language || null, exclude_agencies: p.agencies, days: null };
      const r = await fetch("/api/gap", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const g = await r.json();
      $("#p-gap-status").textContent = t("p.considered", { n: fmt(g.postings_considered) });
      $("#p-gap-result").hidden = false;
      $("#p-gap-coverage").textContent = t("p.coverage", { p: Math.round(g.demand_coverage * 100) });
      barChart("p-gap-chart", g.missing.map((m) => m.skill), g.missing.map((m) => Math.round(m.share * 100)), { pct: true, color: palette[1], onClick: (s) => openJobsWithSkill(s) });
    });
    $("#p-saved").addEventListener("click", (e) => { const b = e.target.closest(".star"); if (b) { toggleSaved(Number(b.dataset.id)); renderSaved(); } });
  }
  async function renderSaved() {
    $("#p-saved-count").textContent = `${state.saved.length}`;
    if (!state.saved.length) { $("#p-saved").innerHTML = `<li class="muted">${t("p.saved.empty")}</li>`; return; }
    const d = await api("/api/postings", new URLSearchParams({ ids: state.saved.join(","), size: 200, include_closed: "true", skills_have: state.profile.skills.join(",") }));
    $("#p-saved").innerHTML = d.items.map((i) => `<li><button class="star on" data-id="${i.id}" title="${t("remove")}">★</button> <a href="${jobPath(i)}" data-pid="${i.id}" target="_blank">${esc(i.title)}</a> · ${esc(i.company)}${i.city ? " · " + esc(cityLabel(i.city)) : ""}${i.closed ? ` <span class="chip more">${t("closed")}</span>` : ""}<div class="m">${esc(i.posted_at)} · ${(i.skills || []).slice(0, 6).join(", ")}</div></li>`).join("");
  }

  function renderAccount() {
    const me = account.me;
    // header: "Log in" when signed out; an avatar with the account menu when signed in
    $("#acct-btn").hidden = !!me; $("#acct").hidden = !me;
    if (!me) closeMenu();
    $("#acct-out").hidden = !!me; $("#acct-none").hidden = !!me; $("#acct-in").hidden = !me;
    if (me) {
      $("#acct-avatar").textContent = me.email.slice(0, 1).toUpperCase();
      $("#acct-avatar").title = me.email;
      $("#acct-menu-email").textContent = me.email;
      $("#acct-who").textContent = me.email;
      $("#pw-state").textContent = t(me.has_password ? "pw.has" : "pw.none");
      $("#pw-set").textContent = t(me.has_password ? "pw.change" : "pw.set");
      $("#pw-remove").hidden = !me.has_password;
      $("#pw-current").hidden = !me.has_password || !!me.can_reset_password;
      $("#pw-user").value = me.email;
      fetch("/api/me/alerts", { credentials: "same-origin" }).then((r) => r.ok ? r.json() : null)
        .then((a) => { if (a) $("#acct-alerts").value = a.frequency; }).catch(() => {});
    }
  }
  function closeMenu() { $("#acct-menu").hidden = true; $("#acct-avatar").setAttribute("aria-expanded", "false"); }
  let toastTimer = null;
  function toast(msg) {
    const el = $("#toast"); el.textContent = msg; el.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
  }
  function bindAccount() {
    const loginUrl = () => (LANG === "nl" ? "/nl/inloggen" : "/login");
    $("#acct-btn").addEventListener("click", () => { location.href = loginUrl(); });
    $("#acct-avatar").addEventListener("click", (e) => {
      e.stopPropagation();
      const open = $("#acct-menu").hidden;
      $("#acct-menu").hidden = !open; $("#acct-avatar").setAttribute("aria-expanded", String(open));
    });
    $("#acct-menu").addEventListener("click", (e) => { if (e.target.closest("a, button")) closeMenu(); });
    document.addEventListener("click", (e) => { if (!e.target.closest("#acct")) closeMenu(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#acct-menu").hidden) { closeMenu(); $("#acct-avatar").focus(); } });
    $("#acct-menu-logout").addEventListener("click", () => $("#acct-logout").click());
    $("#pw-set").addEventListener("click", () => { $("#pw-form").hidden = false; $("#pw-actions").hidden = true; $("#pw-msg").textContent = ""; ($("#pw-current").hidden ? $("#pw-new") : $("#pw-current")).focus(); });
    $("#pw-cancel").addEventListener("click", () => { $("#pw-form").reset(); $("#pw-form").hidden = true; $("#pw-actions").hidden = false; });
    $("#pw-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const pw = $("#pw-new").value;
      if (pw.length < 10) { $("#pw-msg").textContent = t("pw.short"); return; }
      if (pw !== $("#pw-repeat").value) { $("#pw-msg").textContent = t("pw.mismatch"); return; }
      const r = await account.post("/api/me/password", "PUT", { password: pw, current: $("#pw-current").value });
      if (r.ok) {
        account.me.has_password = true; $("#pw-form").reset(); $("#pw-form").hidden = true; $("#pw-actions").hidden = false;
        renderAccount(); $("#pw-state").textContent = t("pw.saved") + " " + t("pw.has");
      } else {
        const d = await r.json().catch(() => ({}));
        $("#pw-msg").textContent = r.status === 403 ? t("pw.wrong") : (d.detail || t("acct.fail"));
      }
    });
    $("#pw-remove").addEventListener("click", async () => {
      if (!confirm(t("pw.confirm"))) return;
      const current = prompt(t("pw.current")) || "";
      const r = await account.post("/api/me/password", "DELETE", { current });
      if (r.ok) { account.me.has_password = false; renderAccount(); $("#pw-state").textContent = t("pw.removed") + " " + t("pw.none"); }
      else $("#pw-state").textContent = r.status === 403 ? t("pw.wrong") : t("acct.fail");
    });
    $("#acct-alerts").addEventListener("change", async (e) => {
      const r = await account.post("/api/me/alerts", "PUT", { frequency: e.target.value, lang: LANG });
      const p = state.profile;
      const empty = !p.roles.length && !p.cities.length && !p.skills.length && !p.levels.length;
      $("#acct-alerts-status").textContent = r.ok ? t(e.target.value !== "off" && empty ? "alerts.noprofile" : "alerts.saved") : t("acct.fail");
    });
    $("#acct-logout").addEventListener("click", async () => {
      await account.post("/api/auth/logout"); account.me = null;
      // the profile and saved jobs belong to the account (it keeps them for the next login): forget this browser's copy,
      // so the next person on this computer does not get them, or their filters, on the Jobs tab
      state.profile = emptyProfile(); state.saved.splice(0, state.saved.length);
      try { localStorage.removeItem("radar.profile"); localStorage.removeItem("radar.saved"); } catch { /* private mode */ }
      jobFilters = null; state.skill = null;
      renderAccount(); toast(t("acct.loggedout"));
    });
    $("#acct-delete").addEventListener("click", async () => {
      if (!confirm(t("acct.delete.confirm"))) return;
      const r = await account.post("/api/me", "DELETE");
      if (r.ok) { account.me = null; renderAccount(); toast(t("acct.deleted")); }
    });
    // back from the e-mailed link: /?login=ok#profile, /?login=ok&reset=1#account or /?login=expired#profile
    const q = new URLSearchParams(location.search);
    if (q.get("reset") === "1") {
      // opened from a "forgot password" link: go straight to choosing a new one
      let tries = 0;
      const open = () => {
        if (!account.me) { if (++tries < 40) setTimeout(open, 150); return; }  // wait for the account to load
        $("#acct-card").scrollIntoView({ block: "start" });
        $("#pw-set").click();
        $("#pw-msg").textContent = t("pw.choose");
      };
      open();
    }
    if (q.has("login")) {
      const msg = q.get("login") === "ok" ? "acct.welcome" : "acct.expired";
      history.replaceState(null, "", location.pathname + location.hash);
      setTimeout(() => toast(t(msg)), 300);
    }
  }


  // ---------- refresh button: enabled once newer listings exist ----------
  let loadedVersion = null;
  async function checkFresh() {
    if (document.hidden) return;
    try {
      const v = await api("/api/version");
      if (loadedVersion === null) loadedVersion = v.version;
      else if (v.version !== loadedVersion) {
        const b = $("#fresh-btn");
        b.disabled = false; b.dataset.i18nTitle = "fresh.text"; b.title = t("fresh.text");
      }
    } catch { /* offline: try again next minute */ }
  }
  $("#fresh-btn").addEventListener("click", () => location.reload());
  checkFresh();
  setInterval(checkFresh, 60000);

  // ---------- ADMIN ----------
  let admBuilt = false, admTimer = null;
  function admToken() { try { return sessionStorage.getItem("radar.admin") || ""; } catch { return ""; } }
  async function admCall(method, path, body) {
    const r = await fetch(path, { method, headers: { "Content-Type": "application/json", Authorization: "Bearer " + admToken() }, body: body ? JSON.stringify(body) : undefined });
    let data = {}; try { data = await r.json(); } catch { /* empty */ }
    return { code: r.status, data };
  }
  async function admRefresh() {
    const { code, data } = await admCall("GET", "/api/admin/status");
    $("#adm-status").textContent = code === 200 ? JSON.stringify(data, null, 2) : `${code} ${data.detail || ""}`;
    if (code === 200 && data.running && !admTimer) admTimer = setInterval(admRefresh, 5000);
    if ((code !== 200 || !data.running) && admTimer) { clearInterval(admTimer); admTimer = null; }
  }
  function renderAdmin() {
    $("#adm-token").value = admToken();
    if (!admBuilt) {
      admBuilt = true;
      $("#adm-token").addEventListener("change", (e) => { try { sessionStorage.setItem("radar.admin", e.target.value.trim()); } catch { /* private mode */ } admRefresh(); });
      $$('[data-tab="admin"] button[data-scope]').forEach((b) => b.addEventListener("click", async () => {
        const { code, data } = await admCall("POST", "/api/admin/crawl", { scope: b.dataset.scope, company: $("#adm-company").value.trim() || null, force: $("#adm-force").checked });
        $("#adm-status").textContent = `${code}\n` + JSON.stringify(data, null, 2);
        if (code === 202) setTimeout(admRefresh, 1500);
      }));
    }
    if (admToken()) return admRefresh();
  }

  // ---------- routing ----------
  const renderers = { overview: renderOverview, jobs: () => { buildJobsFilters(); return refreshJobs(); }, market: renderMarket, profile: renderProfile, account: renderAccount, company: renderCompany, admin: renderAdmin };
  let firstRoute = true;
  async function route() {
    if (!firstRoute) beacon("nav");
    firstRoute = false;
    let raw = (location.hash || "#overview").slice(1);
    const qi = raw.indexOf("?");
    if (qi >= 0) {
      const q = new URLSearchParams(raw.slice(qi + 1));
      raw = raw.slice(0, qi);
      if (raw === "jobs") {  // a search from a link: these filters for this visit, the saved preference is untouched
        jobFilters = filtersFromParams(q);
        state.skill = q.get("skill") || null; state.page = 1;
        if (["newest", "match", "size_small", "size_large"].includes(q.get("sort"))) state.sort = q.get("sort");
      }
    }
    const eq = raw.indexOf("=");
    const tab = eq >= 0 ? raw.slice(0, eq) : raw;
    state.routeArg = eq >= 0 ? decodeURIComponent(raw.slice(eq + 1)) : null;
    state.tab = renderers[tab] ? tab : "overview";
    $$("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === state.tab));
    $$(".tab").forEach((s) => s.classList.toggle("on", s.dataset.tab === state.tab));
    $("#f-profile").hidden = !hasProfileFilters();
    $("#kpis").hidden = state.tab !== "overview";  // the market figures belong to the overview
    window.scrollTo(0, 0);
    const bar = $("#progress"), slow = setTimeout(() => { bar.hidden = false; }, 150);  // only when it takes a moment
    try { await renderers[state.tab](); } catch (e) { console.error(e); $("#kpis").hidden = false; $("#kpis").insertAdjacentHTML("beforeend", `<div class="kpi bad"><b>!</b><span>${esc(e.message)}</span></div>`); }
    finally { clearTimeout(slow); bar.hidden = true; $("#boot").hidden = true; }
  }
  window.addEventListener("hashchange", route);
  $("#brand").addEventListener("click", (e) => {
    e.preventDefault();
    const target = LANG === "nl" ? "/nl/" : "/";
    if (location.pathname === target) { location.hash = "#overview"; window.scrollTo(0, 0); } else location.href = target;
  });
  $("#langswitch").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b || b.dataset.lang === LANG) return;
    LANG = b.dataset.lang; store.set("lang", LANG); applyI18n(); renderAccount(); renderHeader(); jobsBuilt = false; profileBuilt = false; route();
  });
  applyI18n();
  $("#kpis").hidden = !["", "#overview"].includes(location.hash);  // no placeholder flash on other tabs
  bindAccount();
  account.load().then(() => { renderAccount(); jobFilters = null; }).then(loadHeader).then(route).catch((e) => { $("#kpis").hidden = false; $("#kpis").innerHTML = `<div class="kpi bad"><b>!</b><span>${esc(t("fail", { e: e.message }))}</span></div>`; });
})();
