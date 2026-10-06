"""HTML fixtures cover chapter parsing, source order, bounded discovery, and failures."""

import asyncio
from unittest.mock import AsyncMock

import aiohttp
import pytest
from bs4 import BeautifulSoup

from src import http
from src.scrapers import html_common, manganato, mangapill


@pytest.fixture(params=[mangapill, manganato])
def source(request, monkeypatch):
    module = request.param
    monkeypatch.setattr(module, "stop_signal", False)
    monkeypatch.setattr(module, "CLEAN_OUTPUT", True)
    return module


def source_fixture(module):
    if module is mangapill:
        return (
            "https://mangapill.com/manga/1/title",
            '<h1>Title &amp; Friends</h1><div id="chapters"><div>'
            '<a href="/chapters/1/chapter-2">Chapter 2</a>'
            '<a href="/chapters/1/chapter-1.5">Chapter 1.5</a>'
            '<a href="/chapters/1/chapter-1">Chapter 1</a></div></div>',
            "picture",
            "/chapters/1/chapter-",
        )
    return (
        "https://manganato.com/manga-ab123",
        '<h1 class="manga-info-title">Title &amp; Friends</h1><ul class="row-content-chapter">'
        '<li><a href="/manga-ab123/chapter-2">Chapter 2</a></li>'
        '<li><a href="/manga-ab123/chapter-1.5">Chapter 1.5</a></li>'
        '<li><a href="/manga-ab123/chapter-1">Chapter 1</a></li></ul>',
        'div class="container-chapter-reader"',
        "/manga-ab123/chapter-",
    )


def images_html(module, suffix="page"):
    content = (
        f'<img data-src="//cdn.test/{suffix}-001.jpg">'
        f'<img src="//cdn.test/{suffix}-001.jpg">'
        f'<img src="/images/{suffix}-002.jpg">'
        '<img src="javascript:bad()">'
    )
    return (
        f"<picture>{content}</picture>"
        if module is mangapill
        else f'<div class="container-chapter-reader">{content}</div>'
    )


async def test_series_discovery_filters_and_preserves_chapter_and_page_order(
    source, monkeypatch
):
    url, html, _, chapter_path = source_fixture(source)
    active = peak = 0
    requested = []

    async def read(session, requested_url, **kwargs):
        nonlocal active, peak
        assert kwargs["max_retries"] == 2
        requested.append(requested_url)
        if requested_url == url:
            return html
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return images_html(source, requested_url.rsplit("-", 1)[-1])

    monkeypatch.setattr(source, "_fetch_html", read)
    fetch = getattr(source, f"fetch_{source.__name__.rsplit('.', 1)[-1]}_images")
    pages, title = await fetch(url, workers=1, start_chapter=1, max_retries=2)
    assert title == "Title & Friends"
    assert [folder for _, folder in pages] == [
        "chapter_1",
        "chapter_1",
        "chapter_1.5",
        "chapter_1.5",
        "chapter_2",
        "chapter_2",
    ]
    assert pages[0][0] == "https://cdn.test/1-001.jpg"
    assert peak == 1
    requested.clear()
    pages, _ = await fetch(url, workers=2, start_chapter=2, max_retries=2)
    assert len(pages) == 2
    assert all(folder == "chapter_2" for _, folder in pages)
    assert not any(request.endswith(chapter_path + "1") for request in requested)


async def test_single_chapter_urls_use_relative_and_lazy_images(source, monkeypatch):
    series, _, _, chapter_path = source_fixture(source)
    origin = series.split("/", 3)[:3]
    url = "/".join(origin) + chapter_path + "12.5"
    html = "<h1>Title Chapter 12.5</h1>" + images_html(source)
    monkeypatch.setattr(source, "_fetch_html", AsyncMock(return_value=html))
    fetch = getattr(source, f"fetch_{source.__name__.rsplit('.', 1)[-1]}_images")
    pages, _ = await fetch(url)
    assert len(pages) == 2
    assert pages[0] == ("https://cdn.test/page-001.jpg", "chapter_12.5")
    assert pages[1][0].endswith("/images/page-002.jpg")


async def test_discovery_failure_cancels_other_chapters(source, monkeypatch):
    url, html, _, _ = source_fixture(source)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def read(session, requested_url, **kwargs):
        if requested_url == url:
            return html
        if requested_url.endswith("chapter-1"):
            await started.wait()
            raise RuntimeError("missing chapter")
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(source, "_fetch_html", read)
    fetch = getattr(source, f"fetch_{source.__name__.rsplit('.', 1)[-1]}_images")
    with pytest.raises(RuntimeError, match="missing chapter"):
        await asyncio.wait_for(fetch(url, workers=2), timeout=2)
    assert cancelled.is_set()


async def test_empty_series_is_reported_as_discovery_failure(source, monkeypatch):
    url, _, _, _ = source_fixture(source)
    monkeypatch.setattr(
        source,
        "_fetch_html",
        AsyncMock(return_value="<h1>Blocked or changed page</h1>"),
    )
    fetch = getattr(source, f"fetch_{source.__name__.rsplit('.', 1)[-1]}_images")
    with pytest.raises(RuntimeError, match="No chapter links"):
        await fetch(url)


async def test_html_requests_retry_network_errors_and_use_current_timeout(monkeypatch):
    monkeypatch.setattr(html_common.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(
        http, "get_default_timeout", lambda: aiohttp.ClientTimeout(total=7)
    )
    monkeypatch.setattr(html_common, "get_default_timeout", http.get_default_timeout)

    class Response:
        status = 200
        closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def text(self):
            assert not self.closed
            return "<h1>Works</h1>"

    class Session:
        attempts = 0

        def get(self, url, timeout, **kwargs):
            assert timeout.total == 7
            assert kwargs["allow_redirects"] is False
            self.attempts += 1
            if self.attempts == 1:
                raise aiohttp.ClientConnectionError("connection dropped")
            return Response()

    session = Session()
    assert (
        await html_common.fetch_html(session, "https://example.test", max_retries=2)
        == "<h1>Works</h1>"
    )
    assert session.attempts == 2


def test_manganato_chapter_links_reject_cross_origin_hosts():
    soup = BeautifulSoup(
        '<ul class="row-content-chapter">'
        '<li><a href="https://manganato.com/manga/a/chapter-1">ok</a></li>'
        '<li><a href="http://169.254.169.254/latest/meta-data">bad</a></li>'
        "</ul>",
        "html.parser",
    )
    assert manganato._extract_chapter_links(soup, "https://manganato.com/manga/a") == [
        ("https://manganato.com/manga/a/chapter-1", "ok")
    ]


def test_mangapill_images_reject_private_ip_urls():
    soup = BeautifulSoup(
        '<picture><img src="http://127.0.0.1/admin">'
        '<img src="https://cdn.example/page.jpg"></picture>',
        "html.parser",
    )
    assert mangapill._extract_chapter_images(soup) == ["https://cdn.example/page.jpg"]
