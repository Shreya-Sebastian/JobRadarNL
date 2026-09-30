from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="RADAR_", env_file=PROJECT_ROOT / ".env", extra="ignore")

    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'radar.db').as_posix()}"
    redis_url: str | None = None  # e.g. redis://redis:6379/0 ; enables the queue, shared rate limits and caching
    countries: str = "NL"  # comma-separated ISO codes to keep, or ALL for every posting with a known country
    cache_ttl_seconds: int = 300
    # requests per second per host, shared across all workers when Redis is configured
    host_rate_limits: str = ("default=3,apply.workable.com=0.5,boards-api.greenhouse.io=4,api.lever.co=3,"
                             "www.werkenvoornederland.nl=2,www.academictransfer.com=0.1,api.adzuna.com=0.4,"
                             "recruitee.com=2,teamtailor.com=2,myworkdayjobs.com=2")
    cadence_high_minutes: int = 60  # sources with many NL postings
    cadence_normal_minutes: int = 180
    cadence_low_minutes: int = 720  # sources that had no NL postings last time
    metrics_port: int = 9100
    log_json: bool = False
    cors_origins: str = "*"  # comma-separated; set to the public domain in production
    # Branding and search: the site name goes into the title, headings and structured data; the aliases are
    # phrases people may search for ("TechJobsNL"); the URL is the canonical public address.
    site_name: str = "Tech Jobs Radar"
    site_aliases: str = "TechJobsRadar, TechJobsNL, Tech Jobs NL, ICT vacatures, IT vacatures, tech jobs Netherlands"
    site_url: str = "https://techjobsradar.nl"
    # Google Search Console verification token (the content of its <meta name="google-site-verification">)
    google_site_verification: str | None = None
    site_tagline: str = ("Tech jobs from Dutch employers' own career sites, with the skills, language and visa "
                         "details of every listing.")
    # The crawler names itself, with a page explaining it and a contact address; robots.txt rules for
    # "TechJobsRadar" apply to it (radar/robots.py). Sites that refuse it are not crawled.
    user_agent: str = "TechJobsRadar/1.0 (+https://techjobsradar.nl/privacy; contact@techjobsradar.nl)"
    http_timeout: float = 30.0
    max_workers: int = 8
    per_domain_delay: float = 0.5
    only_netherlands: bool = True
    # run the periodic jobs (schedule, finalize, linkcheck, qualitycheck) from the queue worker instead of CronJobs
    worker_timetable: bool = False
    # public source repository; when set, the footer and privacy statement link to it (unset = no link)
    source_url: str | None = None
    # requests per client IP per minute (radar/throttle.py); 0 turns the limit off. The detail limit covers
    # /api/postings and the job and company pages, which a scraper would page through.
    rate_limit_per_minute: int = 240
    rate_limit_detail_per_minute: int = 90
    block_scraper_agents: bool = True  # refuse AI-training crawlers and plain HTTP libraries
    # anonymous page-view statistics for /admin/analytics (radar/analytics.py)
    analytics_enabled: bool = True
    # secret for the admin-only "crawl now" endpoints; unset = the endpoints do not exist
    admin_token: str | None = None
    # Adzuna API (free at https://developer.adzuna.com) for the independent recall check, see radar/recall.py
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    # accounts (radar/auth.py): the login link is e-mailed. "console" logs it instead of sending (local use);
    # "smtp" sends through RADAR_SMTP_HOST, e.g. Amazon SES's SMTP endpoint
    mail_backend: str = "console"
    mail_from: str = "Tech Jobs Radar <login@techjobsradar.nl>"
    # where alerts go (crawling stalled, nightly quality check failed); empty = only logged
    alert_email: str | None = "contact@techjobsradar.nl"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    session_days: int = 90  # with "keep me signed in"; without it the login ends with the browser
    short_session_hours: int = 12
    # "Continue with Google" (OpenID Connect); both unset = the button is hidden
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # local development only: with the console backend, show the login link on the page instead of only in the log.
    # Never set this on a server: anyone could then log in as any e-mail address.
    dev_login_links: bool = False
    extractor: str = "rules"  # "rules" or "llm"
    llm_model: str = "gpt-4o-mini"
    llm_max_postings_per_run: int = 200
    raw_dir: str = str(PROJECT_ROOT / "data" / "raw")
    data_dir: Path = PROJECT_ROOT / "data"


settings = Settings()


def allowed_countries() -> set[str] | None:
    """None means every posting with a known country code; otherwise the set of ISO codes to keep."""
    value = settings.countries.strip().upper()
    if value == "ALL":
        return None
    return {c.strip() for c in value.split(",") if c.strip()}


def host_rate_limits() -> dict[str, float]:
    out: dict[str, float] = {}
    for part in settings.host_rate_limits.split(","):
        if "=" in part:
            host, rate = part.split("=", 1)
            try:
                out[host.strip().lower()] = float(rate)
            except ValueError:
                continue
    out.setdefault("default", 3.0)
    return out
