from types import SimpleNamespace

import pytest

from mdcx.config.manager import manager
from mdcx.tools.emby_actor_image import _generate_server_url, _get_emby_actor_list, _upload_actor_photo


class FakeClient:
    def __init__(self):
        self.calls = []

    async def get_json(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return {"Items": [{"Name": "Actor"}]}, ""

    async def post_content(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return b"", ""


@pytest.mark.asyncio
async def test_jellyfin_actor_requests_use_mediabrowser_header(monkeypatch, tmp_path):
    client = FakeClient()
    monkeypatch.setattr(
        manager,
        "config",
        SimpleNamespace(server_type="jellyfin", emby_url="http://jellyfin:8096/", api_key="test-token", user_id="u1"),
    )
    monkeypatch.setattr(manager, "computed", SimpleNamespace(async_client=client))

    assert await _get_emby_actor_list() == [{"Name": "Actor"}]
    assert client.calls[0] == (
        "GET",
        "http://jellyfin:8096/Persons?userId=u1",
        {"headers": {"Authorization": 'MediaBrowser Token="test-token"'}, "use_proxy": False},
    )

    urls = _generate_server_url({"Name": "Test Actor", "Id": "p1", "ServerId": "s1"})
    assert urls[1] == "http://jellyfin:8096/Persons/Test%20Actor"
    assert urls[-1] == "http://jellyfin:8096/Items/p1"
    assert all("test-token" not in url for url in urls)

    picture = tmp_path / "actor.jpg"
    picture.write_bytes(b"picture")
    assert await _upload_actor_photo(urls[2], picture) == (True, "")
    assert client.calls[1][0:2] == ("POST", "http://jellyfin:8096/Items/p1/Images/Primary")
    assert client.calls[1][2]["headers"] == {
        "Authorization": 'MediaBrowser Token="test-token"',
        "Content-Type": "image/jpeg",
    }
    assert client.calls[1][2]["use_proxy"] is False
