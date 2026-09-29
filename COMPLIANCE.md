# Terms, robots and privacy review

This lists every external service the project touches, what its rules say and how the code complies. It is not
legal advice.

## Sources the radar reads

| Service | How it is used | Rule | Status |
|---|---|---|---|
| Greenhouse Job Board API | `boards-api.greenhouse.io/v1/boards/{slug}/jobs` | Public, unauthenticated API that Greenhouse documents for embedding a company's jobs on any site | Fine |
| Lever Postings API | `api.lever.co/v0/postings/{slug}` | Public, documented for career-site embedding | Fine |
| Ashby Job Board API | `api.ashbyhq.com/posting-api/job-board/{slug}` | Public, documented | Fine |
| Workable widget API | `apply.workable.com/api/v1/widget/accounts/{slug}` | Public endpoint behind Workable's own jobs widget; rate-limited to 0.5 req/s here | Fine, unofficial |
| Recruitee careers API | `{slug}.recruitee.com/api/offers/` | Public, documented for career sites | Fine |
| Teamtailor | `{slug}.teamtailor.com/jobs.json` | Public JSON feed of the career site | Fine |
| Personio XML feed | `{slug}.jobs.personio.de/xml` | Public feed Personio provides for job boards | Fine |
| SmartRecruiters Posting API | `api.smartrecruiters.com/v1/companies/{slug}/postings` | Public, documented, no key needed | Fine |
| Workday | `{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/...` | Undocumented endpoint that powers the public career site; no authentication, no robots rule against it. Workday's terms bind its customers, not visitors | Grey but common; keep the rate low and stop if a tenant blocks |
| Amazon.jobs | `www.amazon.jobs/en/search.json?country=NLD` | Unauthenticated JSON behind Amazon's own search page; robots.txt excludes only `/internal` | Grey like Workday; one call per 100 rows, a handful of calls per crawl |
| Microsoft Careers | not used | The Eightfold API behind jobs.careers.microsoft.com answers "Not authorized" without a session; not scraped | Not touched |
| Employer career pages (JSON-LD) | Pages listed in a sitemap or linked from a careers page | Ordinary web pages. The code now fetches `robots.txt` per host, skips disallowed paths and honours `Crawl-delay` / `Request-rate` by lowering the per-host rate limit. Sitemap crawls are incremental: a page is read once and only re-read when it changes position or on a 1-in-20 refresh, so load on an employer's site is a few dozen requests per crawl, not thousands | Fixed in this review (see below) |
| AcademicTransfer | JSON-LD from vacancy pages | `robots.txt`: allow all except `/account/` and `/apply/`, `Crawl-delay: 10` | Was crawled at 2 req/s, now 1 request per 10 s as asked. Their terms page could not be fetched; check it once by hand |
| Werken voor Nederland | JSON-LD from vacancy pages | `robots.txt`: `Request-rate: 10/1`, only `/login` disallowed; publishes a vacancy sitemap | Fine (we use 2 req/s) |
| Wayback Machine CDX | One-off enumeration of board URLs per ATS | Public index API; Internet Archive asks for reasonable use. Not part of the recurring crawl | Fine |
| Adzuna API | Recall check only (`radar recall`) | Free key. Terms: personal research allowed with acknowledgement; a 14-day trial for validating coverage; using data "in aggregation (vacancy counts...)" for ongoing work or publication needs written consent; "Jobs by Adzuna" attribution when adverts are displayed; contacting content providers via API data is forbidden; 25 calls/min, 250/day | Compliant by default: private report, no listings displayed; the headline is published only with `--publish`, which requires Adzuna's written consent |
| Rabobank (rabobank.jobs) | Not read | Its sitemap and pages answer 403 to a request whose User-Agent names this crawler, while a plain browser string gets 200. That is a site saying no to bots; we do not swap the agent to get around it | Source kept inactive with the reason |
| LinkedIn, Indeed, Glassdoor | Never | Terms forbid scraping; no public listings API | Not touched |

## What the site shows

Postings are read in full for extraction, but the public site shows only title, employer, city, extracted facts
(skills, seniority, language, visa, salary when printed) and a link to the employer's original page. No
description text is republished. This is the same shape as Google for Jobs: facts about a public offer, plus the
link. It keeps the project well clear of copying employers' copy, which is where scrapers get into trouble.

## Identifying ourselves

The crawler's User-Agent is browser-shaped, because a few career sites return 403 to anything else, but it ends
with `JobRadarNL/0.2 (+https://github.com/Shreya-Sebastian/JobRadarNL; contact via GitHub issues)`, so a site
owner who looks at their logs can see who is crawling and how to reach the maintainer. Sites that still refuse
an identified crawler (Rabobank, SAP) are left out rather than fetched under a disguise.

## Privacy (GDPR / AVG)

- Without an account, the visitor profile, saved jobs and language choice live in `localStorage` in the visitor's
  browser. Nothing is sent to the server except the filter values in query strings (roles, cities, skills), which are
  not personal data.
- Accounts are optional (`radar/auth.py`, privacy statement at `/privacy` and `/nl/privacy`). An account stores the
  e-mail address, the profile and the saved job IDs; lawful basis is performance of the requested service (art.
  6(1)(b)). Login is a one-time e-mail link: no passwords, and only SHA-256 hashes of login and session tokens are
  stored. The IP address a link was requested from is kept with the link for two days, for abuse limits. Users can
  download their data (`/api/me/export`) and delete the account (`DELETE /api/me`) from the profile tab; accounts
  without a login for two years are removed by the post-crawl cleanup. The login mail provider (e.g. Amazon SES in
  eu-west-1) is a processor and needs a data processing agreement, which AWS includes in its service terms.
- Pasted CV text is posted to `/api/gap`, used in memory to detect skills, and never written to disk or logs, also
  for logged-in users.
- Only functional storage is used: `localStorage` and, for logged-in users, one HttpOnly session cookie. No
  analytics or third-party cookies, so no consent banner is required under the Dutch Telecommunicatiewet's
  functional-cookie exemption. Adding analytics would change that.
- No external fonts, scripts or CDNs: Chart.js and D3 are vendored, so visitor IP addresses are not shared with
  third parties.
- Job descriptions sometimes contain a recruiter's name, email or phone number. E-mail addresses and phone
  numbers are now removed before a posting is stored (`scrub_contact` in `radar/normalize.py`), and `radar scrub`
  cleaned the rows stored before that. Names remain in the text; they are never displayed.

## Licences

- Chart.js 4 is MIT, D3 7 is ISC, both permit vendoring with the header kept (it is).
- Python dependencies (FastAPI, SQLAlchemy, httpx, BeautifulSoup, RQ) are MIT/BSD/Apache.
- Ollama models planned: qwen2.5 (Apache 2.0), bge-m3 (MIT).
- The project itself is MIT licensed (LICENSE file, `license` field in `pyproject.toml`).

## Safeguards in the code

1. `radar/robots.py`: robots.txt fetched once per host; disallowed URLs skipped; `Crawl-delay` and
   `Request-rate` lower the per-host rate limit. Rules are matched the way Google and Bing do it (longest
   matching rule wins, Allow wins a tie), because Python's own parser takes the first match and would read
   Netflix's "Disallow: / then Allow: /careers" as a ban on pages the site's sitemap advertises. Wired into the
   JSON-LD adapter, covered by tests.
2. AcademicTransfer rate limit lowered from 2 req/s to 0.1 req/s to match its `Crawl-delay: 10`.
3. Adzuna recall check built to stay inside the terms by default (private report, opt-in publish).
4. Footer states that pasted CV text is processed once and not stored.
5. MIT licence added; e-mail addresses and phone numbers scrubbed from stored posting text, at ingest and once
   over the existing rows.

## Rate limiting on multi-tenant platforms

Recruitee, Teamtailor, Personio and Workday host every customer on its own subdomain but rate-limit by client
IP across all of them. A crawl that paced itself per subdomain hit Recruitee's 429 on 569 boards in one run.
Boards on these platforms now share one rate-limit bucket (`recruitee.com=2` requests per second and so on in
`RADAR_HOST_RATE_LIMITS`), in both the thread-pool crawler and the queue workers.
