from types import SimpleNamespace

import pytest
from parsel import Selector

from mdcx.crawlers.base import CralwerException
from mdcx.crawlers.javdb_new import JavdbCrawler
from mdcx.config.enums import Website
from mdcx.config.models import Config
from mdcx.core.file_crawler import FileScraper
from mdcx.models.types import CrawlerDebugInfo, CrawlerInput, CrawlerResponse


def context(number):
    return SimpleNamespace(input=SimpleNamespace(number=number), debug=lambda message: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("number", ["ABW-096", "abw096", "ABW_096"])
async def test_search_matches_whole_code_with_multiple_classes(number):
    html = Selector(
        '<a class="box" href="/v/WRONG"><div class="video-title"><strong>ABW-0960</strong></div></a>'
        '<a class="box highlighted" href="/v/A52GO">'
        '<div class="video-title extra"><strong><span>ABW-096</span></strong></div></a>'
    )
    crawler = JavdbCrawler(client=None)
    assert await crawler._parse_search_page(context(number), html, "search") == [
        "https://javdb.com/v/A52GO"
    ]


@pytest.mark.asyncio
async def test_search_does_not_match_code_in_metadata_or_longer_number():
    html = Selector(
        '<a class="box" href="/v/WRONG"><div class="video-title"><strong>ABW-0960</strong></div>'
        '<div class="meta">ABW-096</div></a>'
    )
    with pytest.raises(CralwerException, match="未找到完整匹配番号"):
        await JavdbCrawler(client=None)._parse_search_page(context("ABW-096"), html, "search")


@pytest.mark.asyncio
async def test_cloudflare_is_reported_on_detail_page():
    html = Selector('<html><title>Just a moment...</title><form id="challenge-form"></form></html>')
    with pytest.raises(CralwerException, match="Cloudflare"):
        await JavdbCrawler(client=None)._parse_detail_page(context("ABW-096"), html, "https://javdb.com/v/A52GO")


@pytest.mark.asyncio
async def test_detail_number_mismatch_is_rejected():
    html = Selector('<a data-clipboard-text="ABW-099"></a>')
    with pytest.raises(CralwerException, match="详情页番号不符"):
        await JavdbCrawler(client=None)._parse_detail_page(context("ABW-096"), html, "https://javdb.com/v/WRONG")


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["搜索页", "详情页"])
async def test_request_failure_keeps_stage_and_reason(stage):
    class FailingClient:
        async def get_text(self, url, **kwargs):
            if stage == "详情页" and "/search?" in url:
                return (
                    '<a class="box" href="/v/A52GO"><div class="video-title">'
                    '<strong>ABW-096</strong></div></a>', ""
                )
            return None, "test timeout"

    request = CrawlerInput.empty()
    request.number = "ABW-096"
    response = await JavdbCrawler(client=FailingClient()).run(request)
    assert response.data is None
    assert stage in str(response.debug_info.error)
    assert "test timeout" in str(response.debug_info.error)


@pytest.mark.asyncio
async def test_single_site_failure_is_not_silenced(monkeypatch):
    scraper = FileScraper(Config(), crawler_provider=None)
    response = CrawlerResponse(debug_info=CrawlerDebugInfo())
    response.debug_info.error = CralwerException("搜索页: Cloudflare 验证页面")

    async def failed_request(*args):
        return response

    monkeypatch.setattr(scraper, "_call_crawler", failed_request)
    with pytest.raises(ValueError, match="javdb.*Cloudflare"):
        await scraper._call_specific_crawler(CrawlerInput.empty(), Website.JAVDB)
