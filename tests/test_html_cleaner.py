"""
Tests for html_cleaner module: boilerplate stripping and clean markdown generation.
"""

import pytest
from bs4 import BeautifulSoup

from kb_web.html_cleaner import (
    clean_html_to_soup,
    extract_primary_content_container,
    html_to_clean_markdown,
    compare_markdown_cleaning,
    strip_boilerplate_elements,
)


SAMPLE_DIRTY_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <title>Understanding Neural Network Embeddings</title>
    <style>body { font-family: sans-serif; } .ad { display: block; }</style>
    <script>console.log("analytics tracker");</script>
</head>
<body>
    <header>
        <div class="logo">TechPulse</div>
        <nav>
            <ul>
                <li><a href="/home">Home</a></li>
                <li><a href="/pricing">Pricing</a></li>
                <li><a href="/login">Sign In</a></li>
            </ul>
        </nav>
    </header>

    <div class="cookie-consent-banner">
        <p>We use cookies to improve your experience. <button>Accept All</button></p>
    </div>

    <aside class="sidebar-ad">
        <div class="ad-banner">Buy our cloud servers today!</div>
    </aside>

    <main>
        <article>
            <h1>Understanding Neural Network Embeddings</h1>
            <p>
                Neural network embeddings are continuous vector representations of discrete tokens
                or entities that map high-dimensional categorical variables into lower-dimensional space.
                They allow models to compute cosine similarities and perform high-speed nearest-neighbor queries.
            </p>
            <h2>Mathematical Formulation</h2>
            <p>
                Given an embedding space $E \in \mathbb{R}^{d}$, the semantic similarity between two vectors
                is computed using the dot product normalized by the Euclidean norm.
            </p>
            <ul>
                <li>High dimensionality compression</li>
                <li>Preservation of semantic manifolds</li>
            </ul>
        </article>
    </main>

    <aside class="social-share-buttons">
        <button>Share on X</button>
        <button>Share on LinkedIn</button>
    </aside>

    <div id="newsletter-signup-modal">
        <h3>Subscribe to our newsletter!</h3>
        <form><input type="email"><button>Submit</button></form>
    </div>

    <footer>
        <p>&copy; 2026 TechPulse Media. All rights reserved. <a href="/privacy">Privacy Policy</a></p>
    </footer>
</body>
</html>
"""


def test_strip_boilerplate_tags():
    soup = clean_html_to_soup(SAMPLE_DIRTY_HTML)
    assert soup.find("header") is None
    assert soup.find("nav") is None
    assert soup.find("footer") is None
    assert soup.find("aside") is None
    assert soup.find("script") is None
    assert soup.find("style") is None
    assert soup.find("form") is None
    assert soup.find("button") is None


def test_strip_cookie_and_ad_containers():
    soup = clean_html_to_soup(SAMPLE_DIRTY_HTML)
    assert soup.find(class_="cookie-consent-banner") is None
    assert soup.find(class_="sidebar-ad") is None
    assert soup.find(id="newsletter-signup-modal") is None


def test_extract_primary_content_container():
    soup = clean_html_to_soup(SAMPLE_DIRTY_HTML)
    primary = extract_primary_content_container(soup)
    assert primary.name in ("article", "main")
    text = primary.get_text()
    assert "Neural network embeddings are continuous vector representations" in text
    assert "TechPulse" not in text
    assert "Privacy Policy" not in text


def test_html_to_clean_markdown():
    cleaned_md = html_to_clean_markdown(SAMPLE_DIRTY_HTML)

    # Core content must be present
    assert "# Understanding Neural Network Embeddings" in cleaned_md
    assert "Neural network embeddings are continuous vector representations" in cleaned_md
    assert "## Mathematical Formulation" in cleaned_md
    assert "Preservation of semantic manifolds" in cleaned_md

    # Boilerplate and navigation must NOT be present
    assert "Home" not in cleaned_md
    assert "Pricing" not in cleaned_md
    assert "Sign In" not in cleaned_md
    assert "We use cookies" not in cleaned_md
    assert "TechPulse Media" not in cleaned_md
    assert "Subscribe to our newsletter" not in cleaned_md
    assert "Share on LinkedIn" not in cleaned_md


def test_compare_markdown_cleaning_metrics():
    dirty_md = """TechPulse Home Pricing Sign In
We use cookies to improve your experience. Accept All
Buy our cloud servers today!
# Understanding Neural Network Embeddings
Neural network embeddings are continuous vector representations of discrete tokens.
Share on X Share on LinkedIn
Subscribe to our newsletter!
All rights reserved. Privacy Policy"""

    metrics = compare_markdown_cleaning(SAMPLE_DIRTY_HTML, dirty_md)
    assert metrics["cleaned_len"] > 0
    assert metrics["original_len"] > 0
    assert "cleaned_markdown" in metrics
    assert "reduction_pct" in metrics


def test_empty_or_whitespace_html():
    assert html_to_clean_markdown("") == ""
    assert html_to_clean_markdown("   ") == ""
    assert html_to_clean_markdown("<html><body></body></html>") == ""
