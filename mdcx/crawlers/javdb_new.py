import asyncio
import re
import time
from typing import override
from urllib.parse import urljoin

from parsel import Selector

from ..config.manager import manager
from ..config.models import Website
from ..models.types import CrawlerResult
from .base import BaseCrawler, CralwerException, CrawlerData, DetailPageParser, extract_all_texts, extract_text


def _normalize_number(number: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]", "", number.upper())
    # Only normalize the numeric suffix of letter-prefixed catalogue codes.
    # Keep embedded digits (e.g. FC2PPV) and the complete prefix significant.
    if match := re.fullmatch(r"([A-Z]+)([0-9]+)", normalized):
        return match[1] + (match[2].lstrip("0") or "0")
    return normalized


def _check_access_page(html: Selector, stage: str) -> None:
    text = html._text or ""
    if "Due to copyright restrictions" in text:
        raise CralwerException(f"{stage}: JavDB 限制当前出口地区访问")
    if "The owner of this website has banned your access" in text:
        raise CralwerException(f"{stage}: JavDB 暂时限制当前 IP 访问")
    title = html.xpath("string(//title)").get(default="").lower()
    if "just a moment" in title or "cf-chl-" in text or html.xpath('//*[@id="challenge-form"]'):
        raise CralwerException(f"{stage}: 收到 Cloudflare 验证页面，尚未取得影片页面")


class Parser(DetailPageParser):
    async def number(self, ctx, html: Selector) -> str:
        result = extract_text(html, '//a[@class="button is-white copy-to-clipboard"]/@data-clipboard-text')
        return result or ctx.input.number

    async def title(self, ctx, html: Selector) -> str:
        return extract_text(html, 'string(//h2[@class="title is-4"]/strong[@class="current-title"])')

    async def originaltitle(self, ctx, html: Selector) -> str:
        return extract_text(html, 'string(//h2[@class="title is-4"]/span[@class="origin-title"])')

    async def actors(self, ctx, html: Selector) -> list[str]:
        # JavDB now marks the actor link itself, rather than a following strong element.
        actors = html.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' panel-block ')]"
            "[strong[contains(., '演員') or contains(., '演员') or contains(., 'Actor')]]"
            "//a[contains(concat(' ', normalize-space(@class), ' '), ' actor-female ')]/text()"
        ).getall()
        if actors:
            return actors
        return html.xpath(
            "//strong[contains(concat(' ', normalize-space(@class), ' '), ' female ')]/preceding-sibling::a/text()"
        ).getall()

    async def all_actors(self, ctx, html: Selector) -> list[str]:
        actors = html.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' panel-block ')]"
            "[strong[contains(., '演員') or contains(., '演员') or contains(., 'Actor')]]"
            "//a[starts-with(@href, '/actors/')]/text()"
        ).getall()
        if actors:
            return actors
        return html.xpath(
            "//strong[contains(@class, 'female') or contains(@class, 'male')]/preceding-sibling::a/text()"
        ).getall()

    async def studio(self, ctx, html: Selector) -> str:
        return extract_text(
            html,
            '//strong[contains(text(),"片商:")]/../span/a/text()',
            '//strong[contains(text(),"Maker:")]/../span/a/text()',
        )

    async def publisher(self, ctx, html: Selector) -> str:
        return extract_text(
            html,
            '//strong[contains(text(),"發行:")]/../span/a/text()',
            '//strong[contains(text(),"Publisher:")]/../span/a/text()',
        )

    async def runtime(self, ctx, html: Selector) -> str:
        result = extract_text(
            html,
            '//strong[contains(text(),"時長")]/../span/text()',
            '//strong[contains(text(),"Duration:")]/../span/text()',
        )
        return result.replace(" 分鍾", "").replace(" minute(s)", "")

    async def series(self, ctx, html: Selector) -> str:
        return extract_text(
            html,
            '//strong[contains(text(),"系列:")]/../span/a/text()',
            '//strong[contains(text(),"Series:")]/../span/a/text()',
        )

    async def release(self, ctx, html: Selector) -> str:
        return extract_text(
            html,
            '//strong[contains(text(),"日期:")]/../span/text()',
            '//strong[contains(text(),"Released Date:")]/../span/text()',
        )

    async def year(self, ctx, html: Selector) -> str:
        release_date = await self.release(ctx, html)
        try:
            result = re.search(r"\d{4}", release_date)
            return result.group() if result else release_date
        except Exception:
            return release_date

    async def tags(self, ctx, html: Selector) -> list[str]:
        tags = extract_all_texts(
            html,
            '//strong[contains(text(),"類別:")]/../span/a/text()',
            '//strong[contains(text(),"Tags:")]/../span/a/text()',
        )
        tags = [tag.replace("\\xa0", "").replace("'", "").replace(" ", "").strip() for tag in tags if tag.strip()]
        return list(dict.fromkeys(tags))

    async def thumb(self, ctx, html: Selector) -> str:
        return extract_text(html, "//img[@class='video-cover']/@src")

    async def extrafanart(self, ctx, html: Selector) -> list[str]:
        return extract_all_texts(html, "//div[@class='tile-images preview-images']/a[@class='tile-item']/@href")

    async def trailer(self, ctx, html: Selector) -> str:
        return extract_text(html, "//video[@id='preview-video']/source/@src")

    async def directors(self, ctx, html: Selector) -> list[str]:
        return extract_all_texts(
            html,
            '//strong[contains(text(),"導演:")]/../span/a/text()',
            '//strong[contains(text(),"Director:")]/../span/a/text()',
        )

    async def score(self, ctx, html: Selector) -> str:
        result = extract_text(html, "//span[@class='score-stars']/../text()")
        try:
            score_match = re.search(r"(\d{1}\.\d+)(分|,)", result)
            return score_match.group(1) if score_match else ""
        except Exception:
            return ""

    async def wanted(self, ctx, html: Selector) -> str:
        html_text = html.get()
        result = re.search(r"(\d+)(人想看| want to watch it)", html_text)
        return result.group(1) if result else ""

    async def image_cut(self, ctx, html: Selector) -> str:
        return "right"

    async def image_download(self, ctx, html: Selector) -> bool:
        return False


class JavdbCrawler(BaseCrawler):
    parser = Parser()

    @override
    async def _fetch(self, ctx, url: str, use_browser: bool | None):
        # One shared crawler instance serves all files in the batch.
        # The base class uses self.lock to initialize its browser context.
        # A separate lock avoids acquiring that same lock again inside _fetch.
        if not hasattr(self, "_request_lock"):
            self._request_lock = asyncio.Lock()
        async with self._request_lock:
            interval = max(1.0, float(manager.config.javdb_time))
            remaining = getattr(self, "_next_request_at", 0) - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(remaining)
            try:
                return await super()._fetch(ctx, url, use_browser)
            finally:
                self._next_request_at = time.monotonic() + interval

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVDB

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://javdb.com"

    @override
    def _get_headers(self, ctx) -> dict[str, str] | None:
        if manager.config.javdb:
            return {"cookie": manager.config.javdb}

    @override
    async def _generate_search_url(self, ctx) -> list[str]:
        number = ctx.input.number.strip()

        # 处理日期格式的番号
        if "." in number:
            old_date = re.findall(r"\D+(\d{2}\.\d{2}\.\d{2})$", number)
            if old_date:
                old_date = old_date[0]
                new_date = "20" + old_date
                number = number.replace(old_date, new_date)

        search_url = f"{self.base_url}/search?q={number}&locale=zh"
        ctx.debug(f"搜索地址: {search_url}")
        return [search_url]

    @override
    async def _parse_search_page(self, ctx, html: Selector, search_url: str) -> list[str] | None:
        _check_access_page(html, "搜索页")

        # 获取搜索结果
        res_list = html.xpath(
            "//a[contains(concat(' ', normalize-space(@class), ' '), ' box ')]"
        )
        if not res_list:
            title = " ".join(html.xpath("string(//title)").get(default="").split())[:120]
            raise CralwerException(
                f"JavDB 搜索页没有影片卡片：可能无结果、需要登录或页面结构已变化；"
                f"页面标题: {title or '无标题'}；地址: {search_url}"
            )

        info_list = []
        for each in res_list:
            href = extract_text(each, "@href")
            title = extract_text(
                each,
                "string(.//*[contains(concat(' ', normalize-space(@class), ' '), ' video-title ')]/strong)",
            )

            if re.fullmatch(r"/v/[a-zA-Z0-9]+", href):
                info_list.append((href, title.strip()))

        # Match only the dedicated code field, never a substring or release date.
        number = _normalize_number(ctx.input.number)
        for href, title in info_list:
            if number and number == _normalize_number(title):
                ctx.debug(f"JavDB 番号匹配成功: {title} -> {href}")
                return [urljoin(self.base_url, href)]
        candidates = ", ".join(title for _, title in info_list[:10]) or "无法读取番号"
        raise CralwerException(f"JavDB 未找到完整匹配番号 {ctx.input.number}；搜索结果: {candidates}")

    @override
    async def _parse_detail_page(self, ctx, html: Selector, detail_url: str) -> CrawlerData | None:
        _check_access_page(html, "详情页")
        page_number = extract_text(html, '//a[@data-clipboard-text]/@data-clipboard-text')
        if page_number and _normalize_number(page_number) != _normalize_number(ctx.input.number):
            raise CralwerException(
                f"JavDB 详情页番号不符：请求 {ctx.input.number}，实际 {page_number}"
            )
        # 提取 javdbid
        javdbid = ""
        if r := re.search(r"/v/([a-zA-Z0-9]+)", detail_url):
            javdbid = r.group(1)
        return await self.parser.parse(ctx, html, external_id=javdbid)

    @override
    async def post_process(self, ctx, res: CrawlerResult) -> CrawlerResult:
        if not res.originaltitle:
            res.originaltitle = res.title
        res.poster = res.thumb.replace("/covers/", "/thumbs/")
        res.mosaic = "无码" if any(keyword in res.title for keyword in ["無碼", "無修正", "Uncensored"]) else "有码"
        if res.trailer.startswith("//"):
            res.trailer = "https:" + res.trailer
        return res
