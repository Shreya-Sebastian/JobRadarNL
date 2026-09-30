# Tech Jobs Radar

A job board for tech, software, data and IT vacancies in the Netherlands, read from employers' own career sites.
Each posting is tagged with the skills, seniority, experience and degree asked, posting language, whether Dutch is
required, visa sponsorship and remote policy. Every listing links to the employer's page.

Live at https://techjobsradar.nl, in Dutch and English.

## How it works

- **Sources.** Adapters for the public job-board APIs of common applicant tracking systems (Greenhouse, Lever,
  Ashby, Workable, Recruitee, Teamtailor, Personio, Workday, SmartRecruiters, Amazon), plus schema.org
  `JobPosting` data read through a careers site's sitemap. Boards are found through the Internet Archive's URL
  index, the IND register of recognised sponsors and `radar discover`, which finds a company's careers page.
- **Crawling.** A Redis queue (RQ) with worker processes, one job per board, shared per-host rate limits and
  robots.txt respected.
- **Processing.** Netherlands-only filter, duplicate merging, lifecycle tracking and periodic link checks, then a
  rule-based classifier and extractor that fill a typed schema.
- **Serving.** A FastAPI JSON API with a response cache, and a plain JavaScript front end (Chart.js, D3, Tailwind
  CSS). Optional accounts keep a profile and saved jobs across devices.

```
sources ─► queue ─► workers + adapters ─► normalise, filter, dedup ─► classify, extract ─► Postgres ─► API ─► site
```

## Run it locally

```bash
python -m venv .venv && .venv/Scripts/activate      # or source .venv/bin/activate
pip install -e ".[dev]"
radar init-db
radar seed --yaml data/sources.yaml
radar crawl
python scripts/build_css.py
radar serve                                          # http://127.0.0.1:8000
```

Without Redis everything runs in one process. `docker compose up --build` starts Postgres, Redis, the API and
workers. Configuration is through `RADAR_*` environment variables, see `.env.example`.

## Deployment

k3s on a single AWS EC2 instance, deployed with the Helm chart in `deploy/helm/radar`; the AWS resources are in
Terraform (`deploy/aws`). GitHub Actions runs the checks and builds the image on every push. See `DEPLOY.md`.

## Extraction checks

`radar eval` compares the extractor with a golden set of postings in `data/golden/golden.jsonl`, and CI fails if
the score drops below a threshold. The set was built by correcting rule output, so it catches regressions rather
than measuring accuracy independently. An LLM extractor (`radar/extract/llm.py`) is implemented but not yet
evaluated.

## Data and terms

Only public job-board APIs and careers pages are read. LinkedIn, Indeed and Glassdoor are not, as they prohibit
automated access. Aggregators are left out, and sites that block the crawler stay blocked. Contact details are
removed from posting text before it is stored. `COMPLIANCE.md` covers each source, and the privacy statement is
at `/privacy`.

## Known limitations

- The tech classifier is rule-based and still admits some non-software roles at engineering firms.
- Skills come from alias matching, so product names in a posting can read as requirements.
- Some large employers use careers platforms without public data and are not covered; the Coverage tab lists them.

## License

MIT, see LICENSE. Posting content belongs to the employers who wrote it.
