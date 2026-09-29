import pytest
from parsel import Selector

from mdcx.crawlers import dmm_new, javdb_new
from tests.crawlers.parser import ParserTestBase


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name, parser_class",
    [
        ("dmm/mono", dmm_new.MonoParser),
        ("dmm/digital", dmm_new.DigitalParser),
        ("dmm/rental", dmm_new.RentalParser),
        ("javdb", javdb_new.Parser),
    ],
)
async def test_parsers(name, parser_class, overwrite, parser_names):
    if parser_names and name not in parser_names:
        pytest.skip(f"跳过解析器: {name}")
    t = ParserTestBase(name, parser_class, overwrite)
    success = await t.run_all_tests()
    assert success, "所有测试应该通过"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "actor_markup, expected_actors, expected_all_actors",
    [
        (
            '<a class="actor-female" href="/actors/1">女優</a>, '
            '<a href="/actors/2">男優</a>',
            ["女優"],
            ["女優", "男優"],
        ),
        ('<a href="/actors/2">男優</a>', [], ["男優"]),
    ],
)
async def test_javdb_current_actor_markup(actor_markup, expected_actors, expected_all_actors):
    html = Selector(
        '<a class="actor-female" href="/actors/unrelated">別の女優</a>'
        '<div class="panel-block"><strong>演員:</strong>'
        f'<span class="value">{actor_markup}</span></div>'
    )
    parser = javdb_new.Parser()
    assert await parser.actors(None, html) == expected_actors
    assert await parser.all_actors(None, html) == expected_all_actors


@pytest.mark.asyncio
async def test_javdb_legacy_actor_markup():
    html = Selector(
        '<span><a href="/actors/1">女優</a><strong class="female"></strong></span>'
        '<span><a href="/actors/2">男優</a><strong class="male"></strong></span>'
    )
    parser = javdb_new.Parser()
    assert await parser.actors(None, html) == ["女優"]
    assert await parser.all_actors(None, html) == ["女優", "男優"]
