"""Regressions for batch queueing, browser setup, and exact catalogue matching."""
import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from parsel import Selector
from mdcx.config.models import Config, Website
from mdcx.core.file_crawler import FileScraper
from mdcx.crawlers import javdb_new as javdb
from mdcx.models.types import CrawlerInput


class JavdbQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_ten_files_can_queue_past_outer_deadline(self):
        starts = []
        class Client:
            async def get_text(self, url, **kwargs):
                starts.append(time.monotonic())
                return 'html', ''
        class Crawler(javdb.JavdbCrawler):
            async def run(self, task_input):
                await self._fetch(None, 'search', False)
                await self._fetch(None, 'detail', False)
                return 'ok'
        crawler = Crawler(Client())
        class Provider:
            async def get(self, website): return crawler
        scraper = FileScraper(Config(), Provider())
        async def scaled_sleep(seconds): await asyncio.sleep(seconds * 0.001)
        clock = SimpleNamespace(monotonic=lambda: time.monotonic() / 0.001)
        fake_asyncio = SimpleNamespace(Lock=asyncio.Lock, sleep=scaled_sleep)
        with patch.object(javdb, 'time', clock), patch.object(javdb, 'asyncio', fake_asyncio), patch.object(javdb.manager.config, 'javdb_time', 10):
            results = await asyncio.wait_for(asyncio.gather(*(
                scraper._call_crawler(CrawlerInput.empty(), Website.JAVDB, timeout=0.03)
                for _ in range(10)
            )), timeout=2)
        self.assertEqual(results, ['ok'] * 10)
        self.assertEqual(len(starts), 20)
        self.assertTrue(all(b-a >= 0.009 for a,b in zip(starts, starts[1:])))

    async def test_other_sites_keep_outer_timeout(self):
        class Crawler:
            async def run(self, task_input): await asyncio.sleep(1)
        class Provider:
            async def get(self, website): return Crawler()
        with self.assertRaises(asyncio.TimeoutError):
            await FileScraper(Config(), Provider())._call_crawler(CrawlerInput.empty(), Website.JAVBUS, timeout=0.01)

    async def test_javdb_transport_timeout_is_preserved(self):
        class Client:
            async def get_text(self, *args, **kwargs): raise TimeoutError('transport timeout')
        class Crawler(javdb.JavdbCrawler):
            async def run(self, task_input): return await self._fetch(None, 'search', False)
        crawler = Crawler(Client())
        class Provider:
            async def get(self, website): return crawler
        with self.assertRaisesRegex(TimeoutError, 'transport timeout'):
            await FileScraper(Config(), Provider())._call_crawler(CrawlerInput.empty(), Website.JAVDB)

    async def test_browser_initialization_does_not_deadlock(self):
        class Page:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def goto(self, *args, **kwargs): pass
            async def content(self): return 'browser html'
        class Context:
            async def new_page(self): return Page()
        class Browser:
            async def new_context(self, **kwargs): return Context()
        crawler = javdb.JavdbCrawler(None, browser=Browser())
        result = await asyncio.wait_for(crawler._fetch(SimpleNamespace(debug=lambda *a: None), 'https://example.test', True), 0.1)
        self.assertEqual(result, ('browser html', ''))

    async def test_leading_zero_matches_complete_code_only(self):
        html = Selector('''<a class="box" href="/v/wrong"><div class="video-title"><strong>LUXU-1760</strong></div></a>
        <a class="box" href="/v/correct"><div class="video-title"><strong>LUXU-760</strong></div></a>''')
        crawler = javdb.JavdbCrawler(None)
        ctx = SimpleNamespace(input=SimpleNamespace(number='LUXU-0760'), debug=lambda *a: None)
        self.assertEqual(await crawler._parse_search_page(ctx, html, 'search'), ['https://javdb.com/v/correct'])
        for a,b in [('ABW-096','ABW-0960'), ('LUXU-0760','LUXU-1760'), ('ABC-001','ABD-001'), ('FC2-PPV-001','FC2-PPV-1')]:
            self.assertNotEqual(javdb._normalize_number(a), javdb._normalize_number(b))

    async def test_no_cards_includes_page_title(self):
        crawler = javdb.JavdbCrawler(None)
        with self.assertRaisesRegex(Exception, '页面标题: Sign in'):
            await crawler._parse_search_page(None, Selector('<title>Sign in</title>'), 'https://javdb.com/search?q=TEST-1')


if __name__ == '__main__':
    unittest.main(verbosity=2)
