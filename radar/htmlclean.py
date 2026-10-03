"""Keep a posting's formatting (paragraphs, headings, lists, bold, italics) and nothing else.

Descriptions arrive as HTML from the employers' platforms. The listing page shows them as the employer wrote them,
so the HTML is reduced to an allowlist before it is stored: every attribute, script, style, image, form, frame and
link goes (link text stays), headings are brought down to two levels, and e-mail addresses and phone numbers are
removed from the text like they are from the plain-text copy. The page escapes nothing it did not build itself, so
this cleaning is what keeps employer markup from running on the site; it runs again when a page is rendered.
"""

from __future__ import annotations

import html as _html
import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

_KEEP = {"p", "br", "ul", "ol", "li", "strong", "em", "h3", "h4"}
_RENAME = {"b": "strong", "i": "em", "h1": "h3", "h2": "h3", "h5": "h4", "h6": "h4"}
_DROP = {"script", "style", "noscript", "iframe", "frame", "object", "embed", "img", "picture", "svg", "video",
         "audio", "source", "form", "input", "button", "select", "textarea", "canvas", "map", "head", "title",
         "meta", "link", "template"}
_BLOCK = {"div", "section", "article", "header", "footer", "aside", "main", "blockquote", "figure", "dl", "dd",
          "dt", "table", "tbody", "thead", "tr", "center", "pre"}


def clean_html(fragment: str | None) -> str:
    """The fragment reduced to safe formatting, or "" when it carries no markup worth keeping."""
    if not fragment:
        return ""
    if "<" not in fragment and "&lt;" in fragment:
        fragment = _html.unescape(fragment)  # Greenhouse sends its HTML entity-escaped
    if "<" not in fragment:
        return ""  # plain text: the page formats it from the text instead
    from radar.normalize import scrub_contact

    soup = BeautifulSoup(fragment, "lxml")
    for el in soup.find_all(string=lambda s: isinstance(s, Comment)):
        el.extract()
    for el in soup.find_all(list(_DROP)):
        el.decompose()
    for el in soup.find_all(True):
        name = el.name.lower()
        name = _RENAME.get(name, name)
        if name in ("td", "th"):
            el.append(" ")
            el.unwrap()
            continue
        if name in _BLOCK:
            # a block of loose text becomes a paragraph; a block that only wraps other blocks just goes
            if any(isinstance(c, NavigableString) and c.strip() for c in el.children):
                el.name, el.attrs = "p", {}
            else:
                el.unwrap()
            continue
        if name not in _KEEP:
            el.unwrap()  # links, spans, fonts and the like: keep the text, lose the tag
            continue
        el.name, el.attrs = name, {}
    for text in soup.find_all(string=True):
        cleaned = scrub_contact(str(text))
        if cleaned != str(text):
            text.replace_with(cleaned)
    root = soup.body or soup
    # a paragraph inside a paragraph (from the block rule) is not valid HTML: flatten it
    for p in root.find_all("p"):
        if p.find_parent("p") is not None or p.find_parent("li") is not None:
            p.unwrap()
    for el in root.find_all(["p", "li", "strong", "em", "h3", "h4", "ul", "ol"]):
        if not el.get_text(strip=True):
            el.decompose()
    _restructure(soup, root)
    out = "".join(str(c) for c in root.children if not isinstance(c, Tag) or c.name != "html").strip()
    out = re.sub(r"(?:<br/?>\s*){3,}", "<br/><br/>", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s*(</?(?:p|ul|ol|li|h3|h4)>)\s*", r"\1", out)  # no stray whitespace around blocks
    return out if re.search(r"<(?:p|ul|ol|h3|h4|br|strong)\b", out) else ""


_BULLET = re.compile(r"^\s*(?:[•·▪●◦‣∙\-–—*✓✔→>]|\d{1,2}[.)])\s+")
_INLINE_BULLET = re.compile(r"\s*[•●▪◦‣]\s+")
# page furniture that comes along when a description is read off the careers page
_CHROME = re.compile(
    r"^\W*(?:share(?: this)?(?: job| vacancy| position)?|deel(?: deze)?(?: vacature)?|"
    r"apply(?: now| here| for this job)?|"
    r"solliciteer(?: direct| nu| hier)?|direct solliciteren|(?:terug )?naar (?:het )?overzicht|"
    r"terug(?: naar (?:alle )?vacatures)?|back(?: to (?:all )?(?:jobs|vacancies|overview|search results))?|"
    r"print(?: this)?(?: vacancy| vacature)?|save(?: job)?|(?:vacature )?opslaan|bewaar(?: vacature)?|"
    r"share on (?:linkedin|facebook|x|twitter)|linkedin|facebook|twitter|whatsapp|kopieer link|copy link|"
    r"(?:bekijk )?(?:bewaarde|opgeslagen) vacatures|saved jobs|vergelijkbare vacatures|similar jobs|"
    # form messages (Webflow) and Cloudflare's stand-in for a hidden e-mail address
    r"thank you! your submission has been received!|oops! something went wrong while submitting the form\.?|"
    r"\[email(?:&#160;|\s)protected\])\W*$",
    re.I,
)
# section titles employers write as a plain paragraph
# where the vacancy ends and the careers site's other content begins
_TAIL = re.compile(
    r"^\W*(?:relevante|vergelijkbare|andere|meer|recente|soortgelijke) vacatures|(?:related|similar|other|more) "
    r"(?:jobs|vacancies|positions|openings)|scroll naar (?:de )?(?:top|boven)|back to top|naar boven\W*$",
    re.I,
)
_SECTION = re.compile(
    r"^(?:about (?:the|this) (?:role|job|position|team)|about (?:us|you)|the role|the job|your role|your profile|"
    r"(?:what|who) (?:you(?:'ll| will)? (?:do|bring|get|need)|we (?:offer|are|ask|expect|look for))|"
    r"(?:key )?responsibilities|requirements|qualifications|nice to haves?|benefits|why join us|our offer|"
    r"over (?:de|deze) (?:functie|rol|baan|vacature)|over ons|de functie|functieomschrijving|functie-?eisen|"
    r"wat (?:ga je doen|breng je mee|vragen wij|bieden wij|wij bieden|we bieden|je gaat doen)|"
    r"wie (?:ben jij|zoeken wij)|"
    r"jouw (?:profiel|rol|functie|taken)|ons aanbod|arbeidsvoorwaarden|wat wij bieden|"
    r"(?:dit|wat) (?:ga je doen|breng je mee|vragen (?:wij|we)|bieden (?:wij|we)|krijg je|ben jij)|"
    r"hier (?:kom|ga) je (?:te )?werken|(?:de )?sollicitatieprocedure|interesse|meer informatie|contact)\b",
    re.I,
)


def _text(el) -> str:
    return " ".join(el.get_text(" ").split())


def _is_heading(el: Tag, nxt: Tag | None) -> bool:
    t = _text(el)
    if nxt is None:
        return False  # a title needs something under it
    if not t or len(t) > 80 or len(t.split()) > 10 or t[-1] in ".,;!" or _BULLET.match(t) or re.search(r"[.!?]\s", t):
        return False  # a sentence, not a title
    if t.endswith(":") or (t.endswith("?") and len(t) <= 70) or _SECTION.match(t):
        return True
    strong = el.find(["strong", "em"])
    if strong is not None and _text(strong) == t:
        return True  # "<p><strong>Meet the job</strong></p>"
    # a short title-like line right before a list or a longer paragraph: "Dit ga je doen", "Responsibilities"
    if len(t) <= 50 and len(t.split()) <= 6 and t[0].isupper():
        return nxt.name in ("ul", "ol") or len(_text(nxt)) > max(100, 2 * len(t))
    return False


def _split_breaks(soup, root) -> None:
    """A paragraph broken into lines with <br> becomes one paragraph per line, so lines can be read as headings
    and list items: many careers sites put the whole vacancy in one <p> that way."""
    for p in list(root.find_all("p")):
        if not p.find("br") or p.find_parent("li") is not None:
            continue
        parts: list[list] = [[]]
        for child in list(p.children):
            if isinstance(child, Tag) and child.name == "br":
                parts.append([])
            else:
                parts[-1].append(child.extract())
        for nodes in parts:
            if not any((n.get_text() if isinstance(n, Tag) else str(n)).strip() for n in nodes):
                continue
            new = soup.new_tag("p")
            for n in nodes:
                new.append(n)
            p.insert_before(new)
        p.decompose()


def _wrap_loose(soup, root) -> None:
    """Text sitting loose between blocks (a link's text once the link is gone) goes into a paragraph of its own."""
    run: list = []

    def flush():
        if any((n.get_text() if isinstance(n, Tag) else str(n)).strip() for n in run):
            p = soup.new_tag("p")
            run[0].insert_before(p)
            for n in run:
                p.append(n.extract())
        run.clear()

    for child in list(root.children):
        if isinstance(child, Tag) and child.name in ("p", "ul", "ol", "li", "h3", "h4"):
            flush()
        else:
            run.append(child)
    flush()


def _restructure(soup, root) -> None:
    """Give a description the shape it was meant to have: lines broken with <br> as paragraphs, page furniture
    ("Share this vacancy", "Apply now") gone, section titles as headings, bullet characters and runs of short
    lines as lists, and neighbouring lists (one <ul> per item on some boards) joined into one."""
    _wrap_loose(soup, root)
    _split_breaks(soup, root)
    for el in list(root.find_all(["p", "li", "h3", "h4"])):
        t = _text(el)
        if _CHROME.match(t) or not re.search(r"\w", t):
            el.decompose()
    blocks = [c for c in root.children if isinstance(c, Tag)]
    for i, el in enumerate(blocks):
        if i >= len(blocks) // 2 and el.name in ("p", "h3", "h4") and _TAIL.match(_text(el)):
            for rest in blocks[i:]:
                rest.decompose()
            break
    blocks = [c for c in root.children if isinstance(c, Tag)]
    for i, el in enumerate(blocks):
        if el.name != "p":
            continue
        t = _text(el)
        items = [x for x in _INLINE_BULLET.split(t) if x.strip()]
        if len(items) >= 3 or (len(items) == 2 and _INLINE_BULLET.match(t)):
            # "● Run threat modelling ● Help build monitoring": one list item per bullet
            ul = soup.new_tag("ul")
            for x in items:
                li = soup.new_tag("li")
                li.string = x.strip()
                ul.append(li)
            el.replace_with(ul)
            blocks[i] = ul
        elif _BULLET.match(t):
            first = el.find(string=True)
            if first is not None:
                first.replace_with(_BULLET.sub("", str(first), count=1))
            el.name = "li"
        elif _is_heading(el, next((b for b in blocks[i + 1:] if b.name != "br"), None)):
            for s in el.find_all(["strong", "em"]):
                s.unwrap()
            el.name = "h4"
    blocks = [c for c in root.children if isinstance(c, Tag)]
    # runs of short lines between headings read as lists: three or more lines that are mostly not sentences,
    # or two or more ending in ";"
    i = 0
    while i < len(blocks):
        j = i
        while j < len(blocks) and blocks[j].name == "p" and len(_text(blocks[j])) <= 200:
            j += 1
        run = blocks[i:j]
        texts = [_text(b) for b in run]
        semi = sum(t.endswith(";") for t in texts)
        loose = sum(not t.endswith((".", "!", ":")) for t in texts)
        if (len(run) >= 3 and loose * 3 >= len(run) * 2) or (len(run) >= 2 and semi >= len(run) - 1):
            for b in run:
                b.name = "li"
        i = max(j, i + 1)
    # loose <li> become lists, and neighbouring lists of one kind become one
    for el in [c for c in root.children if isinstance(c, Tag)]:
        if el.name == "li" and el.parent is root:
            prev = el.find_previous_sibling(True)
            if prev is not None and prev.name == "ul" and prev.next_sibling is el:
                prev.append(el.extract())
            else:
                ul = soup.new_tag("ul")
                el.replace_with(ul)
                ul.append(el)
    for el in [c for c in root.children if isinstance(c, Tag)]:
        if el.name in ("ul", "ol") and el.parent is root:
            prev = el.previous_sibling
            while prev is not None and isinstance(prev, NavigableString) and not prev.strip():
                prev = prev.previous_sibling
            if isinstance(prev, Tag) and prev.name == el.name:
                for li in list(el.children):
                    prev.append(li.extract() if isinstance(li, Tag) else li)
                el.decompose()


def text_to_html(text: str) -> str:
    """Formatting for a description that only exists as plain text: a paragraph per line, then the same shaping
    as employer HTML (bullet lines as lists, section titles as headings)."""
    lines: list[str] = []
    for ln in (x.strip() for x in (text or "").splitlines()):
        if not ln:
            continue
        # a hard-wrapped paragraph: a line going on in lower case after a long unfinished one is the same sentence;
        # punctuation on a line of its own, or a link cut out of its sentence ("KLM", ",", "en") rejoins it too
        if lines and len(lines[-1]) >= 70 and lines[-1][-1] not in ".:;!?" and ln[0].islower():
            lines[-1] += " " + ln
        elif lines and ln[0] in ",.;:)!?":
            lines[-1] += ln
        else:
            lines.append(ln)
    html = "".join(f"<p>{_html.escape(ln)}</p>" for ln in lines)
    return clean_html(html) if html else ""


def drop_leading(html: str, names: tuple[str, ...]) -> str:
    """Without the first lines that only repeat the title or the employer (read off the careers page with it)."""
    if not html:
        return html
    soup = BeautifulSoup(html, "lxml")
    root = soup.body or soup
    wanted = {" ".join(n.lower().split()) for n in names if n}
    for _ in range(4):
        first = next((c for c in root.children if isinstance(c, Tag)), None)
        if first is None or first.name not in ("p", "h3", "h4") or _text(first).lower() not in wanted:
            break
        first.decompose()
    return "".join(str(c) for c in root.children)
