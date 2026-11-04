from pathlib import Path

import pytest

from mdcx.config.enums import MarkType
from mdcx.config.manager import manager
from mdcx.config.models import Config
from mdcx.core.file import get_file_info_v2


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
