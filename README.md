# Tech Jobs Radar

A job board for tech, software, data and IT vacancies in the Netherlands, read directly from employers' own career
sites. Each posting is tagged with the skills, seniority, experience and degree it asks for, its language, whether
Dutch is required, visa sponsorship and remote policy. Every listing links to the employer's original page.

Live at [techjobsradar.nl](https://techjobsradar.nl), in Dutch and English.

## How it works

- **Sources.** Adapters for the public job-board APIs of common applicant tracking systems (Greenhouse, Lever,
  Ashby, Workable, Recruitee, Teamtailor, Personio, Workday, SmartRecruiters, Amazon), plus schema.org
  `JobPosting` data read through a careers site's sitemap. Boards are found through the Internet Archive's URL
  index, the IND register of recognised sponsors and `radar discover`, which locates a company's careers page; a
  weekly job looks for new ones.
- **Crawling.** A Redis queue (RQ) with worker processes, one job per board, with shared per-host rate limits and
  robots.txt respected.
- **Processing.** A Netherlands-only filter, duplicate merging, lifecycle tracking and periodic link checks, followed
  by a rule-based classifier and extractor that fill a typed schema.
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

Without Redis everything runs in one process; `docker compose up --build` starts Postgres, Redis, the API and the
workers instead. Configuration is through `RADAR_*` environment variables (see `.env.example`). Tests run with
`pytest`, linting with `ruff check radar tests scripts`.

## Deployment

Production runs on k3s on a single AWS EC2 instance, deployed with the Helm chart in `deploy/helm/radar`. The AWS
resources are defined in Terraform (`deploy/aws`). Every push to main runs the tests and evaluation gates in GitHub
Actions, builds an image tagged with the commit and points `deploy/flux/radar.yaml` at it; Flux in the cluster then
upgrades the release from Git and rolls it back if the new pods do not become ready.

## Evaluation

`radar eval` scores the extractor field by field against a golden set of postings (`data/golden/golden.jsonl`), and
CI fails if the score drops below a threshold.

## Data and terms

Only public job-board APIs and careers pages are read. LinkedIn, Indeed and Glassdoor are not, as their terms
prohibit automated access. Aggregators are left out, and sites that block the crawler are not crawled. Contact
details are removed from posting text before it is stored. The privacy statement is at
[techjobsradar.nl/privacy](https://techjobsradar.nl/privacy).

## License

MIT, see LICENSE. Posting content belongs to the employers who wrote it.
