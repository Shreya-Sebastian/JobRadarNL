from radar.discovery import detect_ats, find_careers_links, guess_slugs


def test_detect_ats_patterns_and_skips_vendor_assets():
    html = """
      <script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>
      <a href="https://jobs.lever.co/acme-inc">Jobs</a>
      <img src="https://cdn.homerun.co/x.png"> <a href="https://acme.homerun.co/">Apply</a>
      <a href="https://careers-analytics.recruitee.com/x">nope</a> <a href="https://acme.recruitee.com/o/1">yes</a>
      <a href="https://www.teamtailor.com/">vendor</a> <a href="https://acme.teamtailor.com/jobs">board</a>
      <a href="https://acme.wd3.myworkdayjobs.com/en-US/External">wd</a>
    """
    found = detect_ats(html)
    assert ("greenhouse", "acme") in found
    assert ("lever", "acme-inc") in found
    assert ("homerun", "acme") in found and ("homerun", "cdn") not in found
    assert ("recruitee", "acme") in found and ("recruitee", "careers-analytics") not in found
    assert ("teamtailor", "acme") in found and ("teamtailor", "www") not in found
    assert ("workday", "acme.wd3/External") in found


def test_find_careers_links_prefers_career_words_and_ats_hosts():
    html = """<a href="/about">About</a><a href="/careers">Careers</a>
              <a href="https://jobs.lever.co/acme">Open roles</a><a href="/blog">Blog</a>"""
    links = find_careers_links(html, "https://www.acme.nl/")
    assert links[0] == "https://jobs.lever.co/acme"
    assert "https://www.acme.nl/careers" in links
    assert all("/blog" not in link for link in links)


def test_guess_slugs():
    assert guess_slugs("www.flow-traders.com") == ["flow-traders", "flowtraders", "flow_traders"]
    assert guess_slugs("https://adyen.com") == ["adyen"]
