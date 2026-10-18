import hashlib
import time
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PASSWORD = "test-admin-password-only"
NAV_PASSWORD = "test-navidrome-password"
MBID = "a74b1b7f-71a5-4011-9441-d0b5e4122711"


class FakeNavidrome:
    """Validate real Subsonic authentication/form encoding, not just endpoint URLs."""
    def __init__(self):
        self.calls = []
        self.playlists = []
        self.fail_album = False
        self.fail_playlist = False
        self.fail_connection = False
        self.songs = [
            {"id": "s1", "title": "Everything in Its Right Place", "artist": "Radiohead", "artistId": "a1",
             "album": "Kid A", "duration": 251, "year": 2000, "genre": "Wrong file genre"},
            {"id": "s2", "title": "Idioteque", "artist": "Radiohead", "artistId": "a1",
             "album": "Kid A", "duration": 309, "year": 2000},
            {"id": "s3", "title": "Teardrop", "artist": "Massive Attack", "artistId": "a2",
             "album": "Mezzanine", "duration": 330, "year": 1998},
        ]

    def handle(self, request):
        if request.url.host == "navidrome.test":
            assert request.method == "POST"
            assert not request.url.query
            params = parse_qs(request.content.decode())
            assert params["u"] == ["listener"]
            assert params["t"] == [hashlib.md5((NAV_PASSWORD + params["s"][0]).encode()).hexdigest()]
            assert "p" not in params
            method = request.url.path.split("/")[-1].replace(".view", "")
            self.calls.append((method, params))
            if self.fail_connection:
                return httpx.Response(200, json={"subsonic-response": {"status": "failed", "error": {"code": 40}}})
            data = {"status": "ok", "version": "1.16.1"}
            if method == "getAlbumList2":
                data["albumList2"] = {"album": [{"id": "album1"}]}
            elif method == "getAlbum":
                if self.fail_album:
                    return httpx.Response(503)
                data["album"] = {"song": self.songs}
            elif method == "getArtistInfo2":
                data["artistInfo2"] = {"musicBrainzId": MBID} if params["id"] == ["a1"] else {}
            elif method == "createPlaylist":
                if self.fail_playlist:
                    raise httpx.ReadTimeout("Timeout after remote write", request=request)
                self.playlists.append(params)
                data["playlist"] = {"id": f"playlist-{len(self.playlists)}"}
            elif method != "ping":
                raise AssertionError(f"Unexpected Navidrome endpoint: {method}")
            return httpx.Response(200, json={"subsonic-response": data})
        if request.url.host == "musicbrainz.org":
            if request.url.path.endswith(MBID):
                return httpx.Response(200, json={"id": MBID, "name": "Radiohead", "genres": [
                    {"name": "alternative rock", "count": 12}, {"name": "art rock", "count": 5}], "relations": []})
            return httpx.Response(200, json={"count": 0, "artists": []})
        raise AssertionError(f"Unexpected host: {request.url.host}")


@pytest.fixture
def environment(tmp_path):
    remote = FakeNavidrome()
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(remote.handle))
    app = create_app(str(tmp_path), PASSWORD, upstream)
    with TestClient(app) as client:
        app.state.resolver.interval = 0
        yield client, app, remote


@pytest.fixture
def connected(environment):
    client, app, remote = environment
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 200
    assert client.post("/api/connection", json={"url": "http://navidrome.test", "username": "listener", "password": NAV_PASSWORD}).status_code == 200
    return environment


def wait_job(client):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get("/api/job").json()
        if job["status"] != "running":
            return job
        time.sleep(.01)
    raise AssertionError("Job did not finish")


def sync(client):
    assert client.post("/api/sync").status_code == 200
    assert wait_job(client)["status"] == "completed"
