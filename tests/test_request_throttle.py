"""Exercise source methods with fake transports; no network or application config writes."""
import ast
import asyncio
import math
import time
from email.utils import formatdate, parsedate_to_datetime
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1] / "mdcx"


def load_class(path, name, namespace, methods=None, bases=None):
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    if methods:
        cls.body = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in methods]
    for method in cls.body:
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method.decorator_list = []
    if bases is not None:
        cls.bases = [ast.Name(id=b, ctx=ast.Load()) for b in bases]
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


class Permit:
    def __init__(self):
        self.count = 0

    async def acquire(self):
        self.count += 1


class Transport:
    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self.calls = 0
        self.headers = {"Retry-After": "120"}

    async def request(self, *args, **kwargs):
        self.calls += 1
        return SimpleNamespace(status_code=next(self.statuses), headers=self.headers)


class Tests(unittest.IsolatedAsyncioTestCase):
    def client(self, statuses):
        class RequestError(Exception):
            pass

        async def no_sleep(delay):
            pass

        ns = dict(
            time=time, math=math, parsedate_to_datetime=parsedate_to_datetime,
            asyncio=SimpleNamespace(sleep=no_sleep),
            httpx=SimpleNamespace(URL=lambda u: SimpleNamespace(host=urlparse(u).hostname)),
            not_set=None, Timeout=RequestError, ConnectionError=RequestError, RequestException=RequestError,
        )
        cls = load_class(ROOT / "web_async.py", "AsyncWebClient", ns)
        client = object.__new__(cls)
        self.permit = Permit()
        client.limiters = SimpleNamespace(cooldown_until={}, get=lambda host: self.permit)
        client.retry = 3
        client.proxy = None
        client.log_fn = lambda message: None
        client.curl_session = Transport(statuses)
        return client

    async def test_429_stops_retries_and_blocks_same_host(self):
        client = self.client([429])
        response, error = await client.request("GET", "https://javdb.com/search")
        self.assertIsNone(response)
        self.assertIn("120 秒", error)
        response, error = await client.request("GET", "https://javdb.com/v/test")
        self.assertIn("冷却中", error)
        self.assertEqual(client.curl_session.calls, 1)

    async def test_cooldown_does_not_block_other_host(self):
        client = self.client([429, 200])
        await client.request("GET", "https://javdb.com/search")
        response, error = await client.request("GET", "https://other.example/search")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(error, "")

    async def test_retry_also_acquires_rate_limit(self):
        client = self.client([504, 200])
        response, error = await client.request("GET", "https://javdb.com/search")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.permit.count, 2)

    async def test_invalid_retry_after_uses_finite_default(self):
        for value in ["nan", "inf", "invalid"]:
            client = self.client([429])
            client.curl_session.headers = {"Retry-After": value}
            _, error = await client.request("GET", "https://javdb.com/search")
            self.assertIn("60 秒", error)

    async def test_http_date_retry_after(self):
        client = self.client([429])
        client.curl_session.headers = {"Retry-After": formatdate(time.time() + 300, usegmt=True)}
        await client.request("GET", "https://javdb.com/search")
        remaining = client.limiters.cooldown_until["javdb.com"] - time.monotonic()
        self.assertGreater(remaining, 290)
        self.assertLess(remaining, 301)

    async def test_javdb_fetches_are_serial_and_spaced(self):
        clock = [0.0]
        starts = []

        async def sleep(delay):
            clock[0] += delay
            await asyncio.sleep(0)

        class Base:
            async def _fetch(self, ctx, url, use_browser):
                starts.append(clock[0])
                await asyncio.sleep(0)
                return "html", ""

        ns = dict(Base=Base, time=SimpleNamespace(monotonic=lambda: clock[0]),
                  asyncio=SimpleNamespace(sleep=sleep), manager=SimpleNamespace(config=SimpleNamespace(javdb_time=10)))
        cls = load_class(ROOT / "crawlers/javdb_new.py", "JavdbCrawler", ns, {"_fetch"}, ["Base"])
        crawler = cls()
        crawler.lock = asyncio.Lock()
        await asyncio.gather(*(crawler._fetch(None, str(i), False) for i in range(3)))
        self.assertEqual(starts, [0.0, 10.0, 20.0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
