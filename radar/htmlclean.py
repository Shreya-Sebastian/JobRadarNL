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
    out = "".join(str(c) for c in root.children if not isinstance(c, Tag) or c.name != "html").strip()
    out = re.sub(r"(?:<br/?>\s*){3,}", "<br/><br/>", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s*(</?(?:p|ul|ol|li|h3|h4)>)\s*", r"\1", out)  # no stray whitespace around blocks
    return out if re.search(r"<(?:p|ul|ol|h3|h4|br|strong)\b", out) else ""


_BULLET = re.compile(r"^\s*(?:[•·▪●◦‣∙\-–—*✓✔→>]|\d{1,2}[.)])\s+")


def text_to_html(text: str) -> str:
    """Formatting for a description that only exists as plain text: paragraphs, bullet lines as lists, and short
    lines ending in a colon ("What you bring:") as headings."""
    out: list[str] = []
    for block in re.split(r"\n\s*\n", text or ""):
        # each line is a heading, a list item or paragraph text; consecutive lines of one kind are grouped
        kinds = []
        for ln in (x.strip() for x in block.splitlines()):
            if not ln:
                continue
            if _BULLET.match(ln):
                kinds.append(("li", _BULLET.sub("", ln)))
            elif len(ln) <= 60 and ln.endswith(":"):
                kinds.append(("h4", ln))
            else:
                kinds.append(("p", ln))
        i = 0
        while i < len(kinds):
            kind = kinds[i][0]
            j = i
            while j < len(kinds) and kinds[j][0] == kind and kind != "h4":
                j += 1
            j = max(j, i + 1)
            group = [_html.escape(x) for _, x in kinds[i:j]]
            if kind == "li":
                out.append("<ul>" + "".join(f"<li>{x}</li>" for x in group) + "</ul>")
            elif kind == "h4":
                out.append(f"<h4>{group[0]}</h4>")
            else:
                out.append("<p>" + "<br>".join(group) + "</p>")
            i = j
    return "".join(out)
