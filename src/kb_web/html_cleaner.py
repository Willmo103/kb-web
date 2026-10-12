"""
HTML Sanitizer and Clean Markdown Generator for kb-web.

Strips navigational, advertising, structural, and script boilerplate from raw HTML
documents before synthesizing clean, high-density Markdown representations.
"""

from html import unescape
import re
from typing import Optional, Tuple

from bs4 import BeautifulSoup, Comment, Tag
from html2text import HTML2Text


# Unwanted structural, script, and non-content HTML tags to decompose
BOILERPLATE_TAGS = [
    "script",
    "style",
    "noscript",
    "header",
    "nav",
    "footer",
    "aside",
    "svg",
    "form",
    "iframe",
    "button",
    "canvas",
    "dialog",
]

# Patterns in class or id attributes that indicate boilerplate/noise containers
BOILERPLATE_ATTR_PATTERN = re.compile(
    r"(cookie|consent|banner|newsletter|sidebar|social-share|ad-|advertisement|popup|modal|breadcrumb|widget|share-buttons|flyout)",
    re.IGNORECASE,
)

# Minimum text character threshold to treat an <article> or <main> as primary content
PRIMARY_CONTAINER_TEXT_THRESHOLD = 250


def get_configured_html2text() -> HTML2Text:
    """Returns an HTML2Text instance configured for clean readability without word-wrap line breaks."""
    h = HTML2Text()
    h.body_width = 0  # Prevents hard line-wrap at 78 characters
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_emphasis = False
    h.protect_links = True
    h.wrap_links = False
    h.single_line_break = False
    h.skip_internal_links = True
    h.inline_links = True
    return h


def strip_boilerplate_elements(soup: BeautifulSoup) -> None:
    """Decomposes script, style, navigation, footer, and boilerplate elements in place."""
    # 1. Remove comments
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()

    # 2. Remove non-content tags
    for tag_name in BOILERPLATE_TAGS:
        for element in soup.find_all(tag_name):
            element.decompose()

    # 3. Remove common boilerplate containers by class / id
    for element in list(soup.find_all(True)):
        if element.decomposed:
            continue
        classes = " ".join(element.get("class", [])) if isinstance(element.get("class"), list) else str(element.get("class", ""))
        el_id = str(element.get("id", ""))
        combined_attr = f"{classes} {el_id}"
        
        # Avoid decomposing high-level document containers or primary content tags
        if element.name in ("html", "body", "main", "article"):
            continue
            
        if BOILERPLATE_ATTR_PATTERN.search(combined_attr):
            # Only decompose if not containing an article/main tag
            if not element.find(["article", "main"]):
                element.decompose()


def extract_primary_content_container(soup: BeautifulSoup) -> Tag:
    """
    Finds the most specific substantive article container (<article> or <main>).
    Falls back to <body> or the root soup if no dedicated container exists.
    """
    # 1. Check <article> tags
    for article in soup.find_all("article"):
        text_len = len(article.get_text(strip=True))
        if text_len >= PRIMARY_CONTAINER_TEXT_THRESHOLD:
            return article

    # 2. Check <main> tags
    for main in soup.find_all("main"):
        text_len = len(main.get_text(strip=True))
        if text_len >= PRIMARY_CONTAINER_TEXT_THRESHOLD:
            return main

    # 3. Check elements with role="main" or role="article"
    for role_el in soup.find_all(attrs={"role": re.compile(r"^(main|article)$", re.I)}):
        if len(role_el.get_text(strip=True)) >= PRIMARY_CONTAINER_TEXT_THRESHOLD:
            return role_el

    # 4. Fallback to <body> or soup
    return soup.body or soup


def clean_html_to_soup(raw_html: str) -> BeautifulSoup:
    """Parses raw HTML and removes all boilerplate elements."""
    if not raw_html or not raw_html.strip():
        return BeautifulSoup("", "html.parser")

    soup = BeautifulSoup(raw_html, "html5lib")
    strip_boilerplate_elements(soup)
    return soup


def html_to_clean_markdown(raw_html: str) -> str:
    """
    Sanitizes raw HTML by removing non-content boilerplate, prioritizing article
    containers, and converting the cleaned markup into high-density Markdown.
    """
    if not raw_html or not raw_html.strip():
        return ""

    soup = clean_html_to_soup(raw_html)
    primary_container = extract_primary_content_container(soup)
    cleaned_html = str(primary_container)

    h = get_configured_html2text()
    md_content = h.handle(cleaned_html)

    # Post-processing: Collapse excessive blank lines (3+ into 2) and clean trailing whitespace
    md_content = re.sub(r"\n{3,}", "\n\n", md_content)
    md_content = md_content.strip()

    return md_content


def compare_markdown_cleaning(raw_html: str, original_md: str) -> dict:
    """
    Utility returning metrics comparing the original markdown against
    the newly cleaned markdown.
    """
    cleaned_md = html_to_clean_markdown(raw_html)
    orig_len = len(original_md or "")
    clean_len = len(cleaned_md)
    char_diff = orig_len - clean_len
    reduction_pct = round((char_diff / orig_len * 100), 2) if orig_len > 0 else 0.0

    orig_lines = len((original_md or "").splitlines())
    clean_lines = len(cleaned_md.splitlines())

    return {
        "original_len": orig_len,
        "cleaned_len": clean_len,
        "char_diff": char_diff,
        "reduction_pct": reduction_pct,
        "original_lines": orig_lines,
        "cleaned_lines": clean_lines,
        "cleaned_markdown": cleaned_md,
    }
