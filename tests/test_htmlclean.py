from radar.htmlclean import clean_html, text_to_html


def test_keeps_formatting_and_drops_everything_else():
    out = clean_html('<div class="x"><h1 style="color:red">Role</h1><p onclick="x()">We want <b>Python</b> and '
                     '<i>SQL</i>. <a href="https://evil.example">Apply</a> or mail jane@corp.nl</p>'
                     '<ul><li>One<script>alert(1)</script></li><li>Two</li></ul><img src=x onerror="alert(1)">'
                     '<iframe src="https://x"></iframe><style>p{}</style></div>')
    assert out.startswith("<h3>Role</h3>")
    assert "<strong>Python</strong>" in out and "<em>SQL</em>" in out and "<ul><li>One</li><li>Two</li></ul>" in out
    assert "Apply" in out and "href" not in out and "evil.example" not in out  # link text stays, the link goes
    for bad in ("script", "alert", "onclick", "onerror", "style", "iframe", "img", "class=", "jane@corp.nl"):
        assert bad not in out, bad
    assert "[e-mail]" in out


def test_entity_escaped_html_and_plain_text():
    assert clean_html("&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;") == "<p>Hello <strong>world</strong></p>"
    assert clean_html("just text, no markup") == ""
    assert clean_html(None) == ""


def test_plain_text_gets_headings_and_lists():
    html = text_to_html("Wat jij meebrengt:\n- Python\n• SQL\nJe bent nieuwsgierig.\n\nTweede alinea <b>niet</b> vet.")
    assert html == ("<h4>Wat jij meebrengt:</h4><ul><li>Python</li><li>SQL</li></ul><p>Je bent nieuwsgierig.</p>"
                    "<p>Tweede alinea &lt;b&gt;niet&lt;/b&gt; vet.</p>")


def test_lever_lists_become_part_of_the_description():
    from radar.adapters.lever import _lever_html

    job = {"description": "<p>Intro</p>", "lists": [{"text": "What you bring", "content": "<li>Go</li><li>Rust</li>"}],
           "additional": "<p>Benefits</p>"}
    assert clean_html(_lever_html(job)) == "<p>Intro</p><h3>What you bring</h3><ul><li>Go</li><li>Rust</li></ul><p>Benefits</p>"


def test_line_broken_vacancy_gets_headings_and_lists():
    out = clean_html("<p>Share this vacancy<br>About the role<br>You will build robot cells for food and pharma "
                     "customers, from the first concept to commissioning on site, together with our engineers.<br>"
                     "What will you do?<br>Program robots;<br>Integrate PLCs;<br>Test on site.</p>")
    assert out == ("<h4>About the role</h4><p>You will build robot cells for food and pharma customers, from the first "
                   "concept to commissioning on site, together with our engineers.</p><h4>What will you do?</h4>"
                   "<ul><li>Program robots;</li><li>Integrate PLCs;</li><li>Test on site.</li></ul>")


def test_inline_bullets_and_split_lists_become_one_list():
    assert clean_html("<p>● Threat modelling ● Monitoring ● Azure</p>") == (
        "<ul><li>Threat modelling</li><li>Monitoring</li><li>Azure</li></ul>")
    assert clean_html("<ul><li>One</li></ul><ul><li>Two</li></ul>") == "<ul><li>One</li><li>Two</li></ul>"


def test_page_furniture_goes():
    out = clean_html("<div><a href=x>Naar overzicht</a></div><p>Werk aan de systemen van de Luchtmacht.</p>"
                     "<p>Relevante vacatures</p><p>Data Engineer</p>")
    assert out == "<p>Werk aan de systemen van de Luchtmacht.</p>"


def test_wrapped_plain_text_is_joined():
    text = ("Het Rijk hecht waarde aan een diverse en inclusieve organisatie waarin iedereen zich thuis\n"
            "voelt en gewaardeerd wordt.")
    assert text_to_html(text) == ("<p>Het Rijk hecht waarde aan een diverse en inclusieve organisatie waarin iedereen "
                                  "zich thuis voelt en gewaardeerd wordt.</p>")
