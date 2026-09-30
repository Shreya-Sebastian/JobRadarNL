# Tech Jobs Radar

Tech, software, data and IT vacancies in the Netherlands, read from employers' own career sites. For each posting
the radar extracts the skills, seniority, experience and degree asked, posting language, whether Dutch is required,
visa sponsorship, remote policy and stated salary. Visitors can filter the market, see which skills are asked for
together and compare their own skills against the jobs that fit them. Every listing links to the employer's page.

Live at **https://techjobsradar.nl** since 30 September 2026, in Dutch and English.

| On 30 September 2026 | |
|---|---|
| Live postings in the Netherlands | 49,828 |
| Of which tech roles | 6,363, from 1,180 employers |
| Sources | 2,811 career sites and job boards, 2,679 healthy on the last crawl |
| Large Dutch employers tracked | 275 of 542 covered |
| Extraction eval (46 postings) | 0.976 overall, skills F1 0.96 |
| Tests | 154 |

## What it does

- Reads postings from ten applicant tracking systems with public job-board APIs (Greenhouse, Lever, Ashby,
  Workable, Recruitee, Teamtailor, Personio, Workday, SmartRecruiters, Amazon), plus schema.org `JobPosting`
  data on any careers site, read through the site's sitemap.
- Finds boards without knowing company names: the Internet Archive's URL index lists every archived board on each
  platform (about 50,000 probed), and `radar sponsors` checks the 12,980 employers on the IND register of
  recognised sponsors. `radar discover` turns a company website into a source by finding its careers page and
  detecting the platform.
- Keeps postings located in the Netherlands, tracks each one's lifecycle (`first_seen`, `last_seen`,
  `closed_at`) and merges duplicates.
- Decides whether a role is tech and extracts a typed schema per posting, using a 100-entry skill taxonomy with
  aliases.
- Serves a JSON API and a site with five tabs: Overview (skill demand and a co-occurrence graph), Jobs (filters,
  match scores, saved jobs), Market (cities, seniority, roles, employers, salaries with sample sizes, language,
  remote policy, weekly trend), My profile (preferences, skills from pasted CV text, gap analysis) and Coverage
  (tracked employers and the health of every source). Employer, city and role pages are server-rendered for
  search engines.
- Optional accounts keep the profile and saved jobs on every device: sign in with Google, a one-time e-mail link
  or a password. Account settings hold e-mail job alerts, data export and account deletion.

## Architecture

```
archive index, IND register, seeds ──► enumerate / probe / discover ──► sources table
                                                                            │
                          worker timetable, every 15 min: enqueue the sources that are due
                                                                            │
                                                  Redis queue (RQ), shared per-host rate limits
                                                                            │
                                   workers: one job = one board ─► adapter (one per platform)
                                                                            │
                                  normalise ─ Netherlands filter ─ dedup key ─ content hash
                                                                            │
                                         classify (tech?) ─► extract (rules) ─► typed JSON
                                                                            │
                                                                        PostgreSQL
                                                                            │
                     finalize, every 30 min: merge duplicates, update gauges, bump the data version
                                                                            │
                      API (FastAPI) ─ Redis response cache ─► site (JavaScript, Chart.js, D3, Tailwind)
```

The same code runs in one process without Redis: `radar crawl` uses a thread pool and a local rate limiter, and
the response cache falls back to memory. Nightly jobs in the same timetable: link check, quality report, visit
statistics and job alerts.

Key files:

- `radar/adapters/`: one class per platform; `base.py` holds the `RawPosting` model and HTML-to-text.
- `radar/crawler.py`: fetch, ingest, lifecycle and duplicates. `radar/normalize.py`: cities, country, titles.
- `radar/classify.py`: tech or not. `radar/taxonomy.py`: skill aliases.
- `radar/extract/`: `schema.py` (Pydantic), `rules.py` (the extractor in use), `llm.py` (see Extraction evals).
- `radar/evals.py` and `data/golden/golden.jsonl`: the golden evaluation set and its scoring.
- `radar/api.py`, `radar/stats.py`, `radar/seo.py`, `radar/pages.py`: API, aggregations and server-rendered pages.
- `radar/auth.py`, `radar/alerts.py`, `radar/analytics.py`: accounts, job alerts and cookieless visit statistics.
- `radar/tasks.py`, `radar/timetable.py`, `radar/queue.py`, `radar/ratelimit.py`, `radar/cache.py`: the queue.
- `web/`: the front end. `web/src/app.css` is the Tailwind source; `python scripts/build_css.py` builds
  `web/app.css`.

## Run it locally

```bash
python -m venv .venv && .venv/Scripts/activate      # or source .venv/bin/activate
pip install -e ".[dev]"
radar init-db
radar seed --yaml data/sources.yaml
radar enumerate --ats recruitee && radar probe-boards --ats recruitee && radar register-probed --ats recruitee
radar crawl
python scripts/build_css.py
radar serve                                          # http://127.0.0.1:8000
```

`docker compose up --build` starts Postgres, Redis, the API and queue workers instead. Configuration is through
`RADAR_*` environment variables (see `.env.example`); schema changes through `alembic upgrade head`.

## Production

One AWS EC2 instance (t3.small, 2 GB, eu-west-1) runs k3s with Postgres and Redis. The app is deployed with the
Helm chart in `deploy/helm/radar`, the AWS resources are in Terraform (`deploy/aws`), and Cloudflare handles DNS
and TLS in front of it. GitHub Actions runs lint, tests, the extraction eval and a Docker build on every push, and
publishes the image to GitHub Packages. Postgres is dumped nightly and copied to S3. Login e-mails go through
Resend. Running cost is about USD 25 a month. `DEPLOY.md` has the steps.

## Extraction evals

`radar eval` scores an extractor field by field against `data/golden/golden.jsonl`: scalar fields by exact match,
skills by precision, recall and F1. CI fails if the overall score drops below 0.70. Result for `rules-v11` on 46
postings:

| Field | Accuracy |
|---|---|
| role_family | 0.93 |
| seniority | 1.00 |
| posting_language | 1.00 |
| dutch_required | 1.00 |
| visa_sponsorship | 1.00 |
| remote_policy | 0.98 |
| degree_required | 0.91 |
| years_experience | 1.00 |
| salary_min_eur | 0.98 |
| skills precision / recall / F1 | 0.95 / 0.96 / 0.96 |
| **overall** | **0.976** |

The golden set was built by checking rule output against the posting text and correcting it, so it works as a
regression suite for the rules rather than an independent accuracy measure. An LLM extractor that writes into the
same schema (OpenAI structured outputs, cached by content hash, capped per run) is implemented but has not been
run against the set yet. Next: a larger, independently checked set, and a per-field comparison of the two.

## How listings are kept real

Every listing comes from the employer's own careers site or tracking system, or from a public board that hosts
employers' own postings (Werken voor Nederland, AcademicTransfer). Recruitment agencies are included, labelled,
and can be hidden. Aggregators are not shown.

1. **Still listed.** A posting stays live only while the employer's board lists it. A board that suddenly returns
   far fewer postings is treated as a broken response: nothing is closed and the source is marked `partial`.
2. **Page still up.** The nightly link check opens posting pages, oldest first, so every live posting is opened
   about every two weeks. It closes pages that return 404 or 410, redirect to a general careers page, or say the
   position is closed in English, Dutch or German. If most checked pages of one board look dead, the board is
   flagged instead, since that usually means a changed URL format.
3. **Not expired.** A posting whose `validThrough` date has passed is closed.
4. **An actual vacancy.** Open applications, talent pools, test vacancies and "do not apply" postings are left out.
5. **The right employer.** Boards linked from the employer's own website are trusted. Boards found by guessing a
   name are recorded as guesses and checked (`radar verify-sources`).
6. **Shown to the visitor.** Each listing shows when it was last seen on the employer's site and when its page was
   last checked. A filter keeps only postings confirmed in the last 7 days, and postings open for more than 90
   days are marked.

## Duplicates

Each job appears once. Postings are merged when they share an original URL, when the same employer and title appear
on a second source, when a board lists the same text under several addresses or one page per city (the other
cities are shown as "+N"), and when a bilingual site publishes a Dutch and an English copy (the English one is
kept, see `radar/bilingual.py`). The same title with different text on one board is kept apart, since that is
usually a separate vacancy.

## Coverage

`data/top100.yaml` lists 542 large Dutch employers, and `radar top100` reports which are covered, registered
without postings, or missing, with the platform each one uses. The Coverage tab shows this list, including the
misses. Some employers are missing because their careers platform has no public data (Radancy, Phenom, iCIMS),
and some because their site blocks the crawler; those stay blocked.

`radar recall` compares the radar against a sample of Adzuna's IT postings. It has not been run yet, and its
figures are only published with Adzuna's written consent (see `COMPLIANCE.md`).

## Terms, robots and privacy

The adapters call APIs that exist for public job boards. The careers-site reader honours robots.txt (Disallow and
Crawl-delay) and identifies itself with a contact address. LinkedIn, Indeed and Glassdoor are not read: they
prohibit automated access and offer no public listings API. Posting text is stored for extraction, with e-mail
addresses and phone numbers removed, but only the extracted facts, title, employer and link are shown. Without an
account, the profile and saved jobs stay in the visitor's browser. Pasted CV text is processed in memory and not
stored. Visit statistics use no cookies and store no IP addresses. The privacy statement is at `/privacy`, and
`COMPLIANCE.md` reviews every source and service.

## Known limitations

- The tech classifier is rules on the title and text. It still admits some non-software roles at engineering
  firms and misses a few unusual titles.
- Skills come from alias matching, so a posting that lists the employer's product languages reads as requiring
  them.
- Postings whose location is only "Netherlands" have no city.
- Aggregates are computed in memory from the live set and cached. That holds to a few hundred thousand postings;
  beyond that they need precomputed tables.

## Documents

- `DEPLOY.md`: Docker Compose, a local cluster, and the production setup on AWS.
- `COMPLIANCE.md`: every source and service the project uses, its terms, and how the code follows them.

## License

MIT, see LICENSE. Posting content belongs to the employers who wrote it; the radar stores it only to extract facts
and always links back to the original page.
