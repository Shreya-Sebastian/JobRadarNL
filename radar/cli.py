from __future__ import annotations

import argparse
import logging
import sys

from radar.config import settings


def cmd_init_db(_: argparse.Namespace) -> None:
    from radar.db import init_db

    init_db()
    print(f"database ready at {settings.database_url}")


def cmd_seed(args: argparse.Namespace) -> None:
    from radar.db import init_db, session_scope
    from radar.registry import seed_from_probe, seed_from_yaml

    init_db()
    with session_scope() as s:
        n = 0
        if args.probe:
            n += seed_from_probe(s, args.probe)
        if args.yaml:
            n += seed_from_yaml(s, args.yaml)
    print(f"{n} new sources added")


def cmd_crawl(args: argparse.Namespace) -> None:
    from radar.crawler import crawl
    from radar.db import init_db

    init_db()
    run = crawl(ats=args.ats, limit=args.limit, extractor_name=args.extractor)
    print(
        f"run {run.id}: sources ok={run.sources_ok} failed={run.sources_failed} "
        f"seen={run.postings_seen} new={run.postings_new} closed={run.postings_closed} ({run.notes})"
    )


def cmd_extract(args: argparse.Namespace) -> None:
    """Re-run extraction over tech postings whose content changed or that were never extracted."""
    from sqlalchemy import select

    from radar.db import init_db, session_scope
    from radar.extract import get_extractor
    from radar.models import Posting

    init_db()
    extract, version = get_extractor(args.extractor)
    done = 0
    with session_scope() as s:
        q = select(Posting).where(Posting.is_tech.is_(True))
        if not args.all:
            q = q.where(
                (Posting.extractor_version != version)
                | (Posting.extracted_hash != Posting.content_hash)
                | Posting.extraction.is_(None)
            )
        if args.limit:
            q = q.limit(args.limit)
        for p in s.scalars(q):
            p.extraction = extract(p.title, p.description).model_dump()
            p.extractor_version = version
            p.extracted_hash = p.content_hash
            done += 1
            if done % 200 == 0:
                s.commit()
    print(f"extracted {done} postings with {version}")


def cmd_reclassify(_: argparse.Namespace) -> None:
    """Re-run the tech classifier over every posting (after rule changes) and extract newly-tech ones."""
    from sqlalchemy import select

    from radar.classify import is_tech, tech_score
    from radar.db import init_db, session_scope
    from radar.extract import get_extractor
    from radar.models import Posting

    init_db()
    extract, version = get_extractor(settings.extractor)
    flipped = 0
    with session_scope() as s:
        ids = list(s.scalars(select(Posting.id).order_by(Posting.id)))
    # in batches, each committed on its own: loading every posting at once does not fit on a small server
    for i in range(0, len(ids), 500):
        with session_scope() as s:
            for p in s.scalars(select(Posting).where(Posting.id.in_(ids[i:i + 500]))):
                new = is_tech(p.title, p.description)
                p.tech_score = tech_score(p.title, p.description)
                if new != bool(p.is_tech):
                    flipped += 1
                p.is_tech = new
                if new and (p.extraction is None or p.extractor_version != version):
                    p.extraction = extract(p.title, p.description).model_dump()
                    p.extractor_version = version
                    p.extracted_hash = p.content_hash
    print(f"reclassified {len(ids)} postings; {flipped} changed class")


def cmd_fix_cities(_: argparse.Namespace) -> None:
    """Fill in missing cities from the title and text of live postings (normalize.city_from_text)."""
    from sqlalchemy import select

    from radar.db import init_db, session_scope
    from radar.models import Posting
    from radar.normalize import city_from_text, detect_city, is_generic_location, plausible_place

    init_db()
    from_place = from_text = 0
    with session_scope() as s:
        for p in s.scalars(
            select(Posting).where(Posting.remote.is_(False), Posting.closed_at.is_(None), Posting.city.is_(None))
        ):
            if detect_city(p.location_raw):
                continue
            city = plausible_place(p.location_raw)
            if city:
                p.city = city
                from_place += 1
            elif is_generic_location(p.location_raw):
                city = city_from_text(p.title, p.description)
                if city:
                    p.city = city
                    from_text += 1
    print(f"cities filled: {from_place} from the board's location text, {from_text} from the posting text")


def cmd_linkcheck(args: argparse.Namespace) -> None:
    """Re-fetch original URLs of the oldest live postings; close the ones that are gone."""
    from radar.db import init_db, session_scope
    from radar.integrity import link_check

    init_db()
    with session_scope() as s:
        print(link_check(s, sample=args.sample, older_than_days=args.older_than_days, workers=args.workers))


def cmd_check(args: argparse.Namespace) -> None:
    """Data-quality report with thresholds; exits 1 when a threshold is exceeded (nightly job / CI)."""
    import json

    from radar.db import init_db, session_scope
    from radar.integrity import quality_report, violations

    init_db()
    with session_scope() as s:
        report = quality_report(s)
    print(json.dumps(report, indent=2))
    bad = violations(report)
    for v in bad:
        print("VIOLATION:", v)
    if bad and args.strict:
        sys.exit(1)


def cmd_recall(args: argparse.Namespace) -> None:
    """Independent recall check against a sample of Adzuna's IT postings. Private report by default; --publish
    stores the headline for the Coverage tab and is only appropriate with Adzuna's written consent."""
    from radar.db import init_db, session_scope
    from radar.recall import run

    init_db()
    with session_scope() as s:
        report, path = run(s, pages=args.pages, do_publish=args.publish, max_days_old=args.max_days_old)
    print(f"sample {report.sample} (tech {report.sample_tech}, tech by employers "
          f"{report.sample_tech_employer})")
    print(f"recall all {report.recall:.1%} | tech {report.recall_tech:.1%} | tech by employers "
          f"{report.recall_tech_employer:.1%}")
    print(f"employer known but title missing: {report.employer_known_unmatched}")
    missing = ", ".join(f"{m['company']} ({m['postings']})" for m in report.missing_employers[:15])
    print("top missing employers:", missing)
    print("report:", path)
    if not args.publish:
        print("not published to the site (Adzuna terms: aggregate use needs written consent; "
              "use --publish once granted)")


def cmd_scrub(_: argparse.Namespace) -> None:
    """One-off: remove e-mail addresses and phone numbers from descriptions stored before scrubbing existed."""
    from sqlalchemy import select

    from radar.db import init_db, session_scope
    from radar.models import Posting
    from radar.normalize import content_hash, scrub_contact

    init_db()
    changed = 0
    with session_scope() as s:
        for p in s.scalars(select(Posting).execution_options(yield_per=500)):
            clean = scrub_contact(p.description or "")
            if clean == p.description:
                continue
            old_hash = p.content_hash
            p.description = clean
            p.content_hash = content_hash(p.title, clean)
            if p.extracted_hash == old_hash:
                p.extracted_hash = p.content_hash  # the facts did not change, no re-extraction needed
            changed += 1
    print(f"scrubbed {changed} postings")


def cmd_verify_sources(args: argparse.Namespace) -> None:
    """Flag recently added boards whose postings rarely name their employer (namesake or demo boards)."""
    from radar.db import init_db, session_scope
    from radar.integrity import verify_sources

    init_db()
    with session_scope() as s:
        how = tuple(args.discovered_by.split(","))
        flagged = verify_sources(s, since_days=args.since_days, flag=not args.dry_run, discovered_by=how)
    for f in flagged:
        print(f"  {f['id']:5d} {f['company'][:30]:30s} {f['ats']:15s} {f['postings']:4d} postings, "
              f"{f['mention_share']:.0%} name the employer | {str(f['slug'])[:60]}")
    print(f"{len(flagged)} sources flagged")


def cmd_rename(_: argparse.Namespace) -> None:
    """Recompute employer display names from board slugs (data/registry name rules)."""
    from radar.db import init_db, session_scope
    from radar.registry import rename_employers

    init_db()
    with session_scope() as s:
        print(f"renamed {rename_employers(s)} employer sources")


def cmd_top100(args: argparse.Namespace) -> None:
    """Report coverage of the employers in data/top100.yaml; optionally fail below a covered fraction."""
    from radar.db import init_db, session_scope
    from radar.tracker import evaluate, report

    init_db()
    with session_scope() as s:
        entries = evaluate(s)
    text = report(entries)
    print(text)
    if args.write:
        from pathlib import Path

        Path(args.write).write_text(text, encoding="utf-8")
    covered = sum(1 for e in entries if e.status == "covered") / max(1, len(entries))
    if args.fail_under is not None and covered < args.fail_under:
        print(f"FAIL: covered {covered:.2f} < {args.fail_under}")
        sys.exit(1)


def cmd_source_kinds(_: argparse.Namespace) -> None:
    """Label sources as employer / agency / aggregator from data/source_kinds.yaml; switch aggregators off."""
    from radar.db import init_db, session_scope
    from radar.registry import apply_source_kinds

    init_db()
    with session_scope() as s:
        print(apply_source_kinds(s))


def cmd_copy_db(args: argparse.Namespace) -> None:
    """Copy every table from the current database to another one (e.g. local SQLite -> server Postgres)."""
    from sqlalchemy import create_engine, insert, select

    from radar.db import get_engine
    from radar.models import Base

    src = get_engine()
    dst = create_engine(args.to, future=True)
    Base.metadata.create_all(dst)
    with src.connect() as sc, dst.begin() as dc:
        if args.replace:  # children before parents, so foreign keys never block the delete
            for table in reversed(Base.metadata.sorted_tables):
                dc.execute(table.delete())
        for table in Base.metadata.sorted_tables:
            rows = [dict(r._mapping) for r in sc.execute(select(table))]
            # a column pointing at its own table (postings.duplicate_of) may reference a row inserted later:
            # insert with it empty, then fill it in once every row exists
            self_refs = [c.name for c in table.c if any(fk.column.table is table for fk in c.foreign_keys)]
            later = [{"pk": r["id"], **{c: r[c] for c in self_refs}} for r in rows if any(r[c] for c in self_refs)]
            for i in range(0, len(rows), 1000):
                batch = [{**r, **{c: None for c in self_refs}} for r in rows[i : i + 1000]]
                dc.execute(insert(table), batch)
            for c in self_refs:
                from sqlalchemy import bindparam, update

                stmt = update(table).where(table.c.id == bindparam("pk")).values({c: bindparam(c)})
                todo = [{"pk": r["pk"], c: r[c]} for r in later if r[c] is not None]
                for i in range(0, len(todo), 1000):
                    dc.execute(stmt, todo[i : i + 1000])
            print(f"{table.name}: {len(rows)} rows copied")
        if args.to.startswith("postgresql"):
            from sqlalchemy import text

            for table in Base.metadata.sorted_tables:  # SQLite ids were explicit; move the sequences past them
                if "id" not in table.c:
                    continue
                dc.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table.name}), 1))"
                    )
                )


def cmd_stats(_: argparse.Namespace) -> None:
    from radar.db import init_db, session_scope
    from radar.stats import overview

    init_db()
    with session_scope() as s:
        o = overview(s)
    for k, v in o.items():
        print(f"{k:>24}: {v}")


def cmd_find_sitemaps(args: argparse.Namespace) -> None:
    """For employers without a public ATS board: find a career sitemap (or vacancy overview) whose job pages carry
    JobPosting data and register it as a jsonld source. Input lines: "domain" or "name<TAB>domain"."""
    from concurrent.futures import ThreadPoolExecutor

    from radar.db import init_db, session_scope
    from radar.registry import upsert_source
    from radar.sitemaps import find_job_sitemap

    init_db()
    entries = []
    for line in open(args.file, encoding="utf-8"):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.rstrip("\r\n").split("\t")
        name, domain = (parts[0], parts[2] if len(parts) > 2 else parts[1]) if len(parts) > 1 else (None, parts[0])
        entries.append((name, domain.strip()))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda e: (e, find_job_sitemap(e[1])), entries))
    added = 0
    with session_scope() as s:
        for (name, domain), res in results:
            if not res:
                print(f"  -  {domain}")
                continue
            company = name or domain.split(".")[0].capitalize()
            _, new = upsert_source(s, company, "jsonld", res["sitemap"], res["sample"], discovered_by="sitemap")
            added += int(new)
            print(f"  +  {domain}: {res['sitemap']} ({res['jobs']} job pages){' new' if new else ''}")
    print(f"registered {added} new sitemap sources from {len(entries)} domains")


def cmd_sponsors(args: argparse.Namespace) -> None:
    """Find job boards for employers on the IND register of recognised sponsors (resumable)."""
    from pathlib import Path

    from radar.db import init_db, session_scope
    from radar.sponsors import run

    init_db()
    if args.register_only:
        # replay registrations from the saved state (idempotent), e.g. after database-lock failures
        import json

        from radar.sponsors import register

        added = 0
        state = json.loads(Path(args.state).read_text(encoding="utf-8"))
        with session_scope() as s:
            for entry in state.values():
                if entry.get("ats") or entry.get("jsonld") or entry.get("sitemap"):
                    added += register(s, entry)
        print(f"re-registered from state: {added} new sources")
        return
    with session_scope() as s:
        stats = run(s, Path(args.register), Path(args.state), workers=args.workers, limit=args.limit)
    print(stats)


def cmd_discover(args: argparse.Namespace) -> None:
    from radar.db import init_db, session_scope
    from radar.discovery import discover_many

    init_db()
    domains = [line.strip() for line in open(args.file, encoding="utf-8") if line.strip() and not line.startswith("#")]
    with session_scope() as s:
        found = discover_many(s, domains, workers=args.workers)
    print(f"discovered {found} new sources from {len(domains)} domains")


def cmd_enumerate(args: argparse.Namespace) -> None:
    """List every board slug on an ATS from the Wayback index into data/enumerated/{ats}.txt."""
    from pathlib import Path

    from radar.enumerate import PATTERNS, enumerate_slugs, slugs_from_text

    out_dir = Path(settings.data_dir) / "enumerated"
    out_dir.mkdir(parents=True, exist_ok=True)
    for ats in args.ats or list(PATTERNS):
        raw = out_dir / f"raw_{ats}.txt"
        if args.from_raw and raw.exists():
            slugs = slugs_from_text(ats, raw.read_text(encoding="utf-8", errors="ignore"))
        else:
            slugs = enumerate_slugs(ats)
        (out_dir / f"{ats}.txt").write_text("\n".join(slugs) + "\n", encoding="utf-8")
        print(f"{ats}: {len(slugs)} board slugs")


def cmd_probe_boards(args: argparse.Namespace) -> None:
    """Probe every enumerated board for NL postings (state file only; run `radar register-probed` after)."""
    from pathlib import Path

    from radar.enumerate import PATTERNS, probe_slugs

    for ats in args.ats or list(PATTERNS):
        path = Path(settings.data_dir) / "enumerated" / f"{ats}.txt"
        if not path.exists():
            print(f"{ats}: no slug list, run `radar enumerate --ats {ats}` first")
            continue
        slugs = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if args.limit:
            slugs = slugs[: args.limit]
        summary = probe_slugs(ats, slugs, workers=args.workers)
        print(f"{ats}: {summary}", flush=True)


def cmd_register_probed(args: argparse.Namespace) -> None:
    """Turn probe state files into active sources."""
    from radar.db import init_db, session_scope
    from radar.enumerate import PATTERNS, register_probed, summarize_state

    init_db()
    for ats in args.ats or list(PATTERNS):
        with session_scope() as s:
            added = register_probed(s, ats, min_nl=args.min_nl)
        print(f"{ats}: {summarize_state(ats)} -> {added} new sources")


def cmd_eval(args: argparse.Namespace) -> None:
    from radar.evals import run_eval

    report = run_eval(args.golden, args.extractor)
    print(report.to_markdown())
    if args.fail_under and report.overall < args.fail_under:
        print(f"FAIL: overall {report.overall:.3f} < {args.fail_under}")
        sys.exit(1)


def cmd_analytics_nightly(_: argparse.Namespace) -> None:
    """Keep daily visit totals and drop old raw page views (Kubernetes CronJob)."""
    from radar.tasks import analytics_nightly

    print(analytics_nightly())


def cmd_send_alerts(_: argparse.Namespace) -> None:
    """E-mail due job alerts (Kubernetes CronJob)."""
    from radar.tasks import send_alerts

    print(send_alerts())


def cmd_schedule(_: argparse.Namespace) -> None:
    """Enqueue every due source (Kubernetes CronJob)."""
    from radar.tasks import schedule

    print(schedule())


def cmd_finalize(_: argparse.Namespace) -> None:
    """Dedup, gauges, data-version bump (Kubernetes CronJob)."""
    from radar.tasks import finalize

    print(finalize())


def cmd_worker(args: argparse.Namespace) -> None:
    """Consume crawl jobs from Redis. Exposes Prometheus metrics on --metrics-port."""
    from prometheus_client import start_http_server
    from rq import SimpleWorker, Worker

    from radar.db import init_db
    from radar.queue import CRAWL_QUEUE, MAINT_QUEUE, get_queue, get_redis

    init_db()
    if args.metrics_port:
        start_http_server(args.metrics_port)
    if settings.worker_timetable:  # periodic jobs from this worker instead of CronJobs (radar/timetable.py)
        from radar import timetable

        timetable.start(get_redis())
    # maintenance first: a dedup or link check waits for the running crawl job, not for the whole crawl queue
    queues = [get_queue(MAINT_QUEUE), get_queue(CRAWL_QUEUE)]
    cls = SimpleWorker if (args.simple or sys.platform == "win32") else Worker
    worker = cls(queues, connection=get_redis())
    worker.work(burst=args.burst, with_scheduler=False)


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("radar.api:app", host=args.host, port=args.port, reload=args.reload)


def main(argv: list[str] | None = None) -> None:
    if settings.log_json:
        from pythonjsonlogger import jsonlogger

        handler = logging.StreamHandler()
        handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logging.basicConfig(level=logging.INFO, handlers=[handler])
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(prog="radar", description="NL Tech Job Radar")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)

    p = sub.add_parser("seed", help="add sources from probe results and/or YAML")
    p.add_argument("--probe")
    p.add_argument("--yaml")
    p.set_defaults(fn=cmd_seed)

    p = sub.add_parser("crawl", help="fetch all active sources")
    p.add_argument("--ats")
    p.add_argument("--limit", type=int)
    p.add_argument("--extractor", default=None)
    p.set_defaults(fn=cmd_crawl)

    p = sub.add_parser("extract", help="(re)run extraction on stored postings")
    p.add_argument("--extractor", default=settings.extractor)
    p.add_argument("--all", action="store_true")
    p.add_argument("--limit", type=int)
    p.set_defaults(fn=cmd_extract)

    sub.add_parser("stats").set_defaults(fn=cmd_stats)
    sub.add_parser("source-kinds", help="label employer/agency/aggregator sources").set_defaults(fn=cmd_source_kinds)
    sub.add_parser("rename", help="recompute employer display names from slugs").set_defaults(fn=cmd_rename)
    p = sub.add_parser("verify-sources", help="flag new boards whose postings rarely name their employer")
    p.add_argument("--since-days", type=int, default=3)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--discovered-by", default="discovery-guess", help="comma list of discovery methods to check")
    p.set_defaults(fn=cmd_verify_sources)
    sub.add_parser("scrub", help="remove e-mails and phone numbers from stored descriptions").set_defaults(fn=cmd_scrub)
    sub.add_parser("fix-cities", help="fill missing cities from posting text").set_defaults(fn=cmd_fix_cities)
    p = sub.add_parser("linkcheck", help="re-fetch original URLs of old live postings and close gone ones")
    p.add_argument("--sample", type=int, default=None, help="default: enough to cover every posting every 14 days")
    p.add_argument("--older-than-days", type=int, default=21)
    p.add_argument("--workers", type=int, default=8)
    p.set_defaults(fn=cmd_linkcheck)
    p = sub.add_parser("check", help="data-quality report with thresholds")
    p.add_argument("--strict", action="store_true", help="exit 1 on a violation")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("recall", help="recall check against a sample of Adzuna IT postings (needs API keys)")
    p.add_argument("--pages", type=int, default=20, help="pages of 50 results (20 = 1,000 postings, 20 API calls)")
    p.add_argument("--max-days-old", type=int, default=None)
    p.add_argument("--publish", action="store_true", help="store the headline for the Coverage tab")
    p.set_defaults(fn=cmd_recall)
    p = sub.add_parser("top100", help="coverage of the employers in data/top100.yaml")
    p.add_argument("--fail-under", type=float, default=None)
    p.add_argument("--write", help="also write the report to this file")
    p.set_defaults(fn=cmd_top100)
    p = sub.add_parser("copy-db", help="copy all tables to another database URL")
    p.add_argument("--to", required=True)
    p.add_argument("--replace", action="store_true", help="empty destination tables first")
    p.set_defaults(fn=cmd_copy_db)
    sub.add_parser("reclassify", help="re-run the tech classifier on all postings").set_defaults(fn=cmd_reclassify)

    p = sub.add_parser("sponsors", help="find job boards for employers on the IND sponsor register")
    p.add_argument("--register", default="data/seeds/ind_sponsors.tsv")
    p.add_argument("--state", default="data/enumerated/sponsors_state.json")
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--register-only", action="store_true", help="only (re)create sources from the saved state")
    p.set_defaults(fn=cmd_sponsors)

    p = sub.add_parser("find-sitemaps", help="find career sitemaps with JobPosting pages for domains in a file")
    p.add_argument("file")
    p.add_argument("--workers", type=int, default=6)
    p.set_defaults(fn=cmd_find_sitemaps)

    p = sub.add_parser("discover", help="detect the ATS behind company websites listed in a file")
    p.add_argument("file")
    p.add_argument("--workers", type=int, default=8)
    p.set_defaults(fn=cmd_discover)

    p = sub.add_parser("enumerate", help="list every board on an ATS from the Wayback index")
    p.add_argument("--ats", nargs="*")
    p.add_argument("--from-raw", action="store_true", help="parse an existing data/enumerated/raw_{ats}.txt")
    p.set_defaults(fn=cmd_enumerate)

    p = sub.add_parser("probe-boards", help="probe enumerated boards and register those with NL postings")
    p.add_argument("--ats", nargs="*")
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--limit", type=int)
    p.set_defaults(fn=cmd_probe_boards)

    p = sub.add_parser("register-probed", help="create sources from probe state files")
    p.add_argument("--ats", nargs="*")
    p.add_argument("--min-nl", type=int, default=1)
    p.set_defaults(fn=cmd_register_probed)

    p = sub.add_parser("eval", help="score an extractor against the golden set")
    p.add_argument("--golden", default="data/golden/golden.jsonl")
    p.add_argument("--extractor", default="rules")
    p.add_argument("--fail-under", type=float, default=None)
    p.set_defaults(fn=cmd_eval)

    sub.add_parser("schedule", help="enqueue due sources onto the Redis queue").set_defaults(fn=cmd_schedule)
    sub.add_parser("analytics-nightly", help="roll up visit statistics").set_defaults(fn=cmd_analytics_nightly)
    sub.add_parser("send-alerts", help="e-mail due job alerts").set_defaults(fn=cmd_send_alerts)
    sub.add_parser("finalize", help="dedup + gauges + cache version bump").set_defaults(fn=cmd_finalize)
    p = sub.add_parser("worker", help="run a queue worker")
    p.add_argument("--burst", action="store_true", help="exit when the queue is empty")
    p.add_argument("--simple", action="store_true", help="no forking (Windows / tests)")
    p.add_argument("--metrics-port", type=int, default=settings.metrics_port)
    p.set_defaults(fn=cmd_worker)


    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(fn=cmd_serve)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
