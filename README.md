# NL Tech Job Radar

Tech jobs in the Netherlands read directly from employers' own career sites, with the skills, language and visa
facts extracted from the postings themselves, so students and new grads can see what the market actually asks for and what is missing
from their own CV.

Status: working prototype (27 September 2026: 22,700 live NL postings, 4,450 tech, 79 of 136 tracked large employers). Crawls public job-board APIs, stores postings in Postgres or
SQLite, extracts structured facts, and serves an interactive dashboard with a CV gap analysis.

## Dutch and English

The interface is available in Dutch and English (switch in the header, remembered per browser; Dutch is the
default for browsers set to Dutch). The language filter is neutral: *Nederlands* keeps postings that require Dutch
or are written in Dutch, *Engels* keeps postings that need no Dutch, and the default shows both. The Language
column shows NL or EN as a plain fact, not as a warning.

## Why

Only 1 in 25 "Software Engineer" postings is explicitly entry-level, and skill demand shifts every quarter.
Existing job boards show one posting at a time. The radar shows the whole market: which skills are asked for
together, which companies hire in English, who mentions visa sponsorship, and where a given CV falls short.

The primary goal is coverage. The radar is only as good as the share of the market it sees, so most of the
engineering effort goes into finding and reading as many boards as possible, automatically.

## What it does

- Reads postings from nine applicant-tracking systems with public APIs (Greenhouse, Lever, Ashby, Workable,
  Recruitee, Teamtailor, Personio, Workday, SmartRecruiters) plus a generic adapter for schema.org
  `JobPosting` structured data on any careers page. One adapter per ATS, one row per company.
- Enumerates every board on those platforms from the Internet Archive's URL index, so coverage does not
  depend on knowing company names.
- Discovers sources automatically: give it a company website, it finds the careers page, detects the ATS and
  registers a working source. When the ATS is embedded by JavaScript and cannot be seen statically, it probes
  the company name as a slug on every ATS.
- Keeps only postings located in the Netherlands, tracks each posting's lifecycle (`first_seen`, `last_seen`,
  `closed_at`) and links duplicates across sources.
- Classifies tech versus non-tech roles and extracts a typed schema per posting: role family, seniority,
  required and nice-to-have skills (from a 100-entry taxonomy with aliases), posting language, whether Dutch
  is required, visa sponsorship, remote policy, years of experience, degree and stated salary.
- Serves a JSON API and a five-tab site: **Overview** (skill demand, co-occurrence graph, new since your
  last visit, best matches), **Jobs** (multi-select filters, match score, save, "new" badges), **Market**
  (cities, seniority, roles, employers, salaries with sample sizes, language, remote policy, weekly trend),
  **My profile** (roles, levels, experience asked, cities, remote, posting language, visa, hidden employers, editable skill list with
  CV extraction, gap analysis, saved jobs, export/import; stored in the browser, or in an optional passwordless account that keeps them on every device) and **Coverage**
  (the tracked-employer list and every source's health).
- Ships an eval harness: a hand-reviewed golden set gates extraction changes in CI.

## Numbers after the first day (26 Sept 2026)

| Metric | Value |
|---|---|
| Boards enumerated and probed | ~50,000 across 9 platforms |
| Sources registered (boards with NL postings) | 1,694, plus AcademicTransfer and werkenvoornederland as multi-employer boards |
| Live NL postings tracked, duplicates removed, aggregators excluded | 22,127 |
| Of which tech | 4,244 across 866 employers |
| Top-employer tracker (`radar top100`) | 64 of 136 covered |
| Full crawl wall time | ~25 min with 8 workers |
| Extraction eval (rules, 34 golden postings) | overall 0.98 (see below) |

How the sources were found: `radar enumerate` asks the Internet Archive's CDX index for every archived
board-root URL on each platform (for example every `{slug}.recruitee.com` or `boards.greenhouse.io/{slug}`),
and `radar probe-boards` fetches each board once and keeps the ones with postings in the Netherlands. Recruitee
alone yielded 888 Dutch boards and 13,000 postings. Company-name guessing and careers-page discovery
(`radar discover`) remain as complements for boards the archive has not seen.

## Architecture

```
archive index ──► enumerate ──► probe ──► sources table ◄── discovery / seed
                                              │
                        scheduler (CronJob, every 15 min): enqueue due sources
                                              │
                                     Redis queue (RQ)  ◄── shared per-host rate limits
                                              │
                     worker pods (N, scale on queue depth): one job = one board
                                              │
                        adapters (one per ATS) ─► RawPosting
                                              │
                        normalise ─ country filter ─ dedup key ─ content hash
                                              │
                        classify (tech?) ─► extract (rules | LLM) ─► Extraction JSON
                                              │
                                        PostgreSQL
                                              │
                   finalizer (CronJob): dedup, gauges, bump data version in Redis
                                              │
                   api pods (HPA) ─ Redis response cache ─► dashboard (Chart.js + D3)
                                              │
                                 Prometheus /metrics on api and workers
```

Locally without Redis the same code runs single-process: `radar crawl` uses a thread pool and a local
rate limiter, and the response cache falls back to memory. `DEPLOY.md` covers compose, a local cluster and
the public k3s deployment; `deploy/helm/radar` is the chart and `deploy/terraform` the server.

Key files:

- `radar/adapters/` one class per ATS; `base.py` holds the `RawPosting` model and HTML-to-text.
- `radar/discovery.py` careers-page detection, ATS pattern matching, slug guessing.
- `radar/crawler.py` fetch, ingest, lifecycle, cross-source duplicates.
- `radar/normalize.py` city and country detection for NL, title normalisation, dedup keys.
- `radar/classify.py` tech relevance rules; `radar/taxonomy.py` skill aliases.
- `radar/extract/` `schema.py` (Pydantic), `rules.py` (deterministic v3), `llm.py` (OpenAI structured
  outputs, cached by content hash, budget-capped).
- `radar/evals.py` golden-set scoring; `data/golden/golden.jsonl` the labelled set.
- `radar/stats.py` aggregations; `radar/api.py` endpoints; `web/` the dashboard.
- `radar/enumerate.py` board enumeration from the archive index and bulk probing.
- `radar/tasks.py` queue jobs (`crawl_source`, `schedule`, `finalize`); `radar/queue.py` RQ on Redis;
  `radar/ratelimit.py` shared per-host limits; `radar/cache.py` response cache and data versioning;
  `radar/metrics.py` Prometheus metrics; `migrations/` Alembic.

## Run it

```bash
python -m venv .venv && .venv/Scripts/activate      # or source .venv/bin/activate
pip install -e ".[dev]"
radar init-db
radar seed --yaml data/sources.yaml                  # hand-maintained boards (universities, government, ...)
radar enumerate --ats recruitee && radar probe-boards --ats recruitee && radar register-probed --ats recruitee
radar crawl
radar serve                                          # http://127.0.0.1:8000
```

`data/seeds/` holds the curated employer lists used by discovery: the 541 largest Dutch employers
(`top500.tsv`), IT recruitment and secondment agencies (`agencies_it.tsv`), traineeship providers, and the IND
public register of recognised sponsors (`ind_sponsors.tsv`, read by `radar sponsors`).

Other commands: `radar enumerate --ats recruitee` then `radar probe-boards --ats recruitee` and
`radar register-probed --ats recruitee` (find every board on a platform), `radar discover <domains.txt>`,
`radar reclassify`, `radar extract --all`, `radar eval --extractor rules|llm`,
`radar run-forever --interval-minutes 360`, `radar stats`.

Not read, on purpose: LinkedIn, Indeed and Glassdoor. All three prohibit automated access and none offers a
public listings API; their tech listings are mostly copies of the employer postings read here at the source.
Adzuna is used only for the recall check, never as a displayed source; see COMPLIANCE.md.

With Docker: `docker compose up --build` starts Postgres, Redis, the API on port 8000, four queue workers and
a scheduler loop. With Redis configured (`RADAR_REDIS_URL`) the crawl runs as `radar schedule`, `radar worker`
and `radar finalize`; without it, `radar crawl` does everything in one process. Schema changes: `alembic
upgrade head`. Configuration is via `RADAR_*` environment variables; see `.env.example`.

## Extraction evals

`radar eval` scores an extractor field by field against `data/golden/golden.jsonl` and CI fails if the
overall score drops below 0.70. Current result for `rules-v5` on 46 postings (overall 0.981):

| Field | Accuracy |
|---|---|
| role_family | 0.93 |
| seniority | 1.00 |
| posting_language | 1.00 |
| dutch_required | 1.00 |
| visa_sponsorship | 1.00 |
| remote_policy | 0.98 |
| degree_required | 0.96 |
| years_experience | 1.00 |
| salary_min_eur | 0.98 |
| skills F1 | 0.97 |

Caveat: the golden set was built by reviewing rule outputs against the posting text and correcting
them, so today it is a regression suite for the rules rather than an independent accuracy measurement. The
scalar fields were checked posting by posting; skills were only checked for obvious false positives. The
150-posting independently labelled set from the plan is still to do, and the LLM extractor comparison could
not run because the OpenAI account had no credit at the time.

## Top-employer coverage tracker

`data/top100.yaml` lists the employers the radar must have, and `radar top100` reports which are covered
(live postings attributed to them), registered without postings, or missing, with the platform each one runs
on. The headline claim of the site is derived from this report, not the other way round. Job boards
that host many employers' own postings (AcademicTransfer for universities and research institutes,
werkenvoornederland for the national government) are `board` sources: their postings are attributed to the
hiring organisation named in each posting.

## Integrity

- **Completeness guard.** A board that returns less than half of last time's postings is treated as a partial
  response: nothing is closed, the source is marked `partial`, and the baseline is kept.
- **Link checker.** `radar linkcheck` re-fetches the oldest live postings at their original URL and closes
  those that answer 404, redirect to a listing page, or say the position is filled. Nightly on Kubernetes.
- **Quality report.** `radar check` prints shares of empty descriptions, unknown cities, missing dates, stale
  postings, unknown seniority, skill-less tech postings and failed or partial sources, and exits non-zero
  when a threshold is exceeded (`--strict`).
- **Filter verification.** `scripts/verify_filters.py` applies filter combinations through the API and checks
  every returned posting against the stored fields and the raw text.
- **Extraction evals.** The golden set gates rule changes in CI (see below).

## Coverage and source health

The dashboard's last section lists every source with its ATS, last status and yield. A source that returns
nothing for 24 hours or fails five crawls in a row is deactivated and shows up there. COMPLIANCE.md documents
each source type and the basis for reading it. No LinkedIn or Indeed scraping.

Recall against an independent sample is `radar recall`: it pulls up to 1,000 of Adzuna's IT postings for the
Netherlands (free API key, 20 calls), keeps the ones the radar's own classifier calls tech, drops agency reposts,
and counts a posting as covered only when a live radar posting has the same employer and a matching title. The
report (three recall figures plus the employers we miss most) is written to `data/recall/`. It stays private by
default: Adzuna's API terms allow personal research with acknowledgement but require written consent before
aggregate figures are published, so `--publish` (which puts the numbers on the Coverage tab) is for after that
consent. See COMPLIANCE.md for the full terms review.

## Employer pages

`/companies` lists every employer with open tech postings and `/company/<slug>` shows one employer's roles, skill
mix and language split as plain server-rendered HTML with a canonical URL and JSON-LD, all listed in
`/sitemap.xml`. The same view exists inside the dashboard at `#company=<name>` with match scores and filters.

## Incremental sitemap crawling

Employers whose career sites publish schema.org JobPosting data (ING, Rabobank, Unilever, Netflix, PVH, Politie
and others) are read through their sitemaps. The first crawl reads every job page; later crawls fetch only pages
that are new, keep postings whose page is still listed in the sitemap without re-reading them, and refresh about
one in twenty known pages so content changes are still picked up. A page that drops out of the sitemap closes
the posting. This is what makes a 10-second crawl delay (AcademicTransfer) and 1,700-page sitemaps (ING)
workable at an hourly cadence.

## Terms, robots and privacy

COMPLIANCE.md reviews every external service the project touches. In short: the ATS adapters call APIs that
exist for public job boards; the generic careers-page crawler honours robots.txt (Disallow and Crawl-delay) and
identifies itself with a contact address; LinkedIn, Indeed and Glassdoor are never touched; posting text is
stored for extraction but only facts, title, employer and the original link are shown; the profile and saved jobs
live in the visitor's browser unless they log in (e-mail link, no password; data export and account deletion on the
profile tab, privacy statement at `/privacy`), and pasted CV text is processed in memory and never stored; recruiters' e-mail addresses and
phone numbers are removed from posting text before it is stored.

## How listings are kept real

Every listing comes from the employer's own careers site or applicant-tracking board, or from a public board
that hosts employers' own postings (Werken voor Nederland, AcademicTransfer). Recruitment agencies are included
but labelled, and can be hidden. No aggregator or reposting site is displayed. On top of that:

1. **Still listed.** A posting stays live only while the employer's own board lists it. Each source is re-read on
   a cadence (hourly for busy boards), and a posting that disappears is closed. A board that suddenly returns far
   fewer postings is treated as a broken response, not a mass closure.
2. **Page still up.** A nightly link check opens posting pages, oldest first, sized so that every live posting is
   opened about every two weeks. It closes pages that return 404/410, redirect to a general careers page, or say
   so in English, Dutch or German ("sollicitatietermijn is verlopen", "applications are closed", "Stelle ist
   besetzt"). If most checked pages of one board look dead, the board is flagged and nothing is closed, because
   that usually means a changed URL format rather than closed jobs.
3. **Not expired.** When the employer's job data carries an expiry date (schema.org `validThrough`) that has
   passed, the posting is closed even if the page is still up. A site where nearly every posting looks expired is
   treated as a broken template and ignored.
4. **An actual vacancy.** Open applications, talent pools, "future opportunities", test vacancies and "do not
   apply" postings are not counted as jobs.
5. **The right employer.** Boards found through a link on the employer's own website are trusted. Boards found by
   guessing a board name are recorded as guesses and reviewed (`radar verify-sources`); namesakes with no Dutch
   postings and vendor demo or test tenants are switched off.
6. **Shown to the visitor.** Each listing shows when it was last seen on the employer's site, when its page was
   last opened and checked, and its closing date if the employer gives one. A filter keeps only postings
   confirmed in the last 7 days. Postings open for more than 90 days carry a "long open" badge, because long-open
   roles are sometimes evergreen or pipeline vacancies.

The nightly quality check (`radar check`) tracks these as numbers: share confirmed in the last 7 days, share whose
page was checked in the last 30 days, share open more than 180 days, agency share, and unverified boards.

## Duplicates

Each job appears once on the dashboard. Within a board, postings are unique by the board's own ID. Across
boards, the same company, title and city collapse to one, preferring the employer's ATS over a copy. Identical
twins on the same board (same title, same text, URL differing only by a repost counter) and postings sharing
an original URL are collapsed too. The same title on the same board with different text, or identical text
under a different URL slug (often a different location), is kept: that is usually a separate requisition.


Bilingual career sites (TNO, Nedap, many universities) publish each vacancy twice, under /nl/ and /en/ with a translated title. Those pairs are matched one-to-one on same employer, day and city plus title and number similarity (`radar/bilingual.py`), and the English copy is shown.
## Known limitations

- Workable rate-limits bulk probing (HTTP 429), so only about 1,400 of its 13,000 boards were probed on day
  one; the probe resumes from its state file with `radar probe-boards --ats workable --workers 4`.
- The tech classifier is title rules. It still lets through some non-engineering roles at tech companies
  (for example partner or procurement managers with technical words in the title) and misses a few odd
  titles. A learned classifier on the growing labelled set is the next step.
- Skills come from alias matching, so a posting that lists a company's product languages (a sales engineer
  at Sentry, say) reads as requiring all of them.
- Postings whose location is just "Netherlands" have no city and appear as "Unknown".
- bol.com's Greenhouse board publishes placeholder content, so those postings have empty descriptions.
- Aggregates are computed in memory per API replica from the live set (reloaded when the finalizer bumps the
  data version) and responses are cached in Redis. Fine to a few hundred thousand postings; precomputed
  stats tables after that.

## Documents

- `DEPLOY.md`: Docker Compose, a local cluster, Kubernetes with Helm, Terraform and CI.
- `COMPLIANCE.md`: every source and service the project touches, its rules, and how the code complies.

## License

MIT, see LICENSE. Posting content belongs to the employers who wrote it; the radar stores it only to extract
facts and always links back to the original page.
