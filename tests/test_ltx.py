from pathlib import Path
from types import SimpleNamespace

import pytest

from mdcx.config.enums import DownloadableFile, MarkType
from mdcx.config.manager import manager
from mdcx.config.models import Config
from mdcx.core.file import get_file_info_v2
from mdcx.core import image as image_module
from mdcx.models.types import FileInfo


@pytest.mark.asyncio
async def test_ltx_filename_is_recognized_and_added_to_name(monkeypatch, tmp_path: Path):
    config = Config()
    monkeypatch.setattr(manager, "config", config)
    video = tmp_path / "ABP-123-LTX.mp4"
    video.touch()

    file_info = await get_file_info_v2(video)

    assert file_info.mosaic == "LTX"
    assert file_info.ltx == "-LTX"
    assert file_info.file_show_name == "ABP-123-LTX"


def test_ltx_is_enabled_as_a_watermark_type_by_default():
    assert Config().ltx_style == "-LTX"
    assert MarkType.LTX in Config().mark_type


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled", "expected"),
    [
        ([MarkType.LTX, MarkType.UMR, MarkType.LEAK, MarkType.UNCENSORED], ["LTX"]),
        ([MarkType.UMR, MarkType.LEAK, MarkType.UNCENSORED], ["破解"]),
        ([MarkType.LEAK, MarkType.UNCENSORED], ["流出"]),
        ([MarkType.UNCENSORED], ["无码"]),
        ([], []),
    ],
)
async def test_ltx_mosaic_watermark_priority(monkeypatch, enabled, expected):
    config = Config()
    config.mark_type = enabled
    config.download_files = [DownloadableFile.THUMB]
    config.thumb_mark = 1
    monkeypatch.setattr(manager, "config", config)
    calls = []

    async def capture(path, marks):
        calls.extend(marks)

    monkeypatch.setattr(image_module, "add_mark_thread", capture)
    images = SimpleNamespace(
        poster_marked=False,
        thumb_marked=False,
        fanart_marked=False,
        poster_path=None,
        thumb_path=Path("thumb.jpg"),
        fanart_path=None,
    )
    await image_module.add_mark(images, FileInfo.empty(), "LTX")
    assert calls == expected
