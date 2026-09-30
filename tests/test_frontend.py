"""Every page loads the one Tailwind-built stylesheet, and the build script's pins stay consistent."""

import importlib.util
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def test_every_page_uses_the_built_stylesheet():
    pages = sorted(WEB.glob("*.html"))
    assert pages
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert '/static/app.css?v=' in html, page.name
        assert "style.css" not in html, page.name
    assert not (WEB / "style.css").exists()


def test_tailwind_source_scans_the_templates_and_the_server_rendered_html():
    src = (WEB / "src" / "app.css").read_text(encoding="utf-8")
    assert 'source(none)' in src  # no automatic scanning of the whole repository (data files, vendor bundles)
    for glob in ('"../*.html"', '"../app.js"', '"../../radar/*.py"'):
        assert f"@source {glob}" in src


def test_build_script_pins_a_checksum_for_every_platform_it_runs_on():
    spec = importlib.util.spec_from_file_location("build_css", WEB.parent / "scripts" / "build_css.py")
    build_css = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_css)

    assert re.fullmatch(r"v\d+\.\d+\.\d+", build_css.VERSION)
    for name in ("tailwindcss-linux-x64", "tailwindcss-linux-arm64", "tailwindcss-windows-x64.exe"):
        assert re.fullmatch(r"[0-9a-f]{64}", build_css.SHA256[name])


def test_cached_pages_are_keyed_by_the_code_version(monkeypatch):
    from radar import cache

    monkeypatch.setattr(cache.settings, "redis_url", None)
    monkeypatch.setattr(cache, "_local", {})
    calls = []
    cache.cached("page:x", lambda: calls.append(1) or "old")
    assert cache.cached("page:x", lambda: "unused") == "old"
    monkeypatch.setattr(cache, "CODE_VERSION", "next-release")
    assert cache.cached("page:x", lambda: "new") == "new"


def test_pages_are_revalidated_so_a_deploy_reaches_open_browsers(fresh_db):
    from fastapi.testclient import TestClient

    from radar.api import app

    client = TestClient(app)
    for path in ("/", "/nl/", "/login", "/feedback", "/privacy"):
        assert client.get(path).headers.get("cache-control") == "no-cache", path
