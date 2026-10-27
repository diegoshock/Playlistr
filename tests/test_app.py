import json

from conftest import MBID, NAV_PASSWORD, PASSWORD, sync, wait_job


def test_authentication_security_and_secret_redaction(environment):
    client, app, remote = environment
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/api/state").status_code == 401
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
    result = client.post("/api/login", json={"password": PASSWORD})
    assert result.status_code == 200
    assert "HttpOnly" in result.headers["set-cookie"]
    assert "SameSite=strict" in result.headers["set-cookie"]
    assert client.post("/api/sync", headers={"origin": "https://attacker.example"}).status_code == 403
    assert client.post("/api/sync", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.get("/api/state").headers["cache-control"] == "no-store"
    assert client.get("/").headers["cache-control"] == "no-store"
    assert client.get("/static/app.js").headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/state").status_code == 401


def test_login_throttling(environment):
    client, _, _ = environment
    for _ in range(10):
        assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 429


def test_password_encrypted_and_never_returned(connected):
    client, app, _ = connected
    saved = app.state.store.setting("navidrome")
    assert saved["password"] != NAV_PASSWORD
    assert NAV_PASSWORD not in json.dumps(saved)
    assert app.state.store.credentials()["password"] == NAV_PASSWORD
    assert "password" not in client.get("/api/state").text
    assert client.post("/api/connection", json={"url":"http://navidrome.test/", "username":"listener", "password":""}).status_code == 200


def test_full_sync_classification_preview_and_remote_playlist(connected):
    client, app, remote = connected
    sync(client)
    state = client.get("/api/state").json()
    assert state["stats"]["songs"] == 3
    assert state["stats"]["artists"] == 2
    assert client.post("/api/enrich", json={}).status_code == 200
    assert wait_job(client)["errors"] == 0
    state = client.get("/api/state").json()
    radiohead = next(a for a in state["artists"] if a["id"] == "a1")
    assert radiohead["mbid"] == MBID
    assert radiohead["genres"] == ["alternative rock", "art rock"]
    assert radiohead["status"] == "matched"
    assert "Wrong file genre" not in str(state["genres"])
    assert radiohead["evidence"][0]["votes"]["art rock"] == 5
    preview = client.post("/api/preview", json={"genres":["alternative rock"], "limit":1}).json()
    assert len(preview["songs"]) == 1
    assert preview["total_matches"] == 2
    assert preview["songs"][0]["id"] in ("s1", "s2")
    body = {"name":"Evening mix", "preview_id":preview["preview_id"]}
    result = client.post("/api/playlists", json=body)
    assert result.status_code == 200
    assert remote.playlists[0]["songId"] == [preview["songs"][0]["id"]]
    assert remote.playlists[0]["name"] == ["Evening mix"]
    assert client.post("/api/playlists", json=body).json() == result.json()
    assert len(remote.playlists) == 1
    assert client.get("/api/state").json()["stats"]["playlists"] == 1


def test_preview_tracks_can_be_removed_before_saving(connected):
    client, _, remote = connected
    sync(client)
    preview = client.post("/api/preview", json={"shuffle": False}).json()
    kept = [preview["songs"][1]["id"]]
    result = client.post("/api/playlists", json={
        "name": "Afinada", "preview_id": preview["preview_id"], "song_ids": kept,
    })
    assert result.status_code == 200
    assert result.json()["song_count"] == 1
    assert remote.playlists[0]["songId"] == kept

    another = client.post("/api/preview", json={"shuffle": False}).json()
    invalid = {"name": "Alterada", "preview_id": another["preview_id"], "song_ids": ["not-in-preview"]}
    assert client.post("/api/playlists", json=invalid).status_code == 422
    assert client.post("/api/playlists", json={**invalid, "song_ids": []}).status_code == 422


def test_filters_manual_genres_and_preservation(connected):
    client, app, _ = connected
    sync(client)
    assert client.put("/api/artists/a1", json={"genres":[" Art Rock ", "electronic", "art rock"]}).status_code == 200
    assert client.put("/api/artists/a2", json={"genres":["trip hop", "electronic"]}).status_code == 200
    both = client.post("/api/preview", json={"genres":["art rock", "electronic"], "mode":"all", "shuffle":False}).json()
    assert [s["id"] for s in both["songs"]] == ["s1", "s2"]
    any_genre = client.post("/api/preview", json={"genres":["trip hop", "art rock"]}).json()
    assert any_genre["total_matches"] == 3
    years = client.post("/api/preview", json={"year_to":1999}).json()
    assert [s["id"] for s in years["songs"]] == ["s3"]
    excluded = client.post("/api/preview", json={"exclude_artists":["a1"]}).json()
    assert [s["id"] for s in excluded["songs"]] == ["s3"]
    assert client.post("/api/enrich", json={"refresh":True}).status_code == 200
    assert wait_job(client)["total"] == 0
    sync(client)
    assert all(a["status"] == "manual" for a in client.get("/api/state").json()["artists"])
    assert client.post("/api/playlists", json={"name":"Stale", "preview_id":both["preview_id"]}).status_code == 409


def test_failed_sync_preserves_old_library_and_removes_stale_tracks_on_success(connected):
    client, app, remote = connected
    sync(client)
    remote.fail_album = True
    assert client.post("/api/sync").status_code == 200
    assert wait_job(client)["status"] == "failed"
    assert client.get("/api/state").json()["stats"]["songs"] == 3
    remote.fail_album = False
    remote.songs = [remote.songs[0]]
    sync(client)
    state = client.get("/api/state").json()
    assert state["stats"]["songs"] == 1
    assert state["stats"]["artists"] == 1


def test_multi_artist_songs_and_unknown_year(connected):
    client, _, remote = connected
    remote.songs = [{"id":"collab", "title":"Collaboration", "album":"Together", "artist":"A & B", "duration":60,
                     "artists":[{"id":"a1","name":"A"},{"id":"a2","name":"B"}]}]
    sync(client)
    assert client.get("/api/state").json()["stats"]["artists"] == 2
    client.put("/api/artists/a1", json={"genres":["rock"]})
    client.put("/api/artists/a2", json={"genres":["electronic"]})
    result = client.post("/api/preview", json={"genres":["rock","electronic"],"mode":"all"}).json()
    assert result["total_matches"] == 1
    assert client.post("/api/preview", json={"year_to":2020}).json()["total_matches"] == 0


def test_validation_empty_playlist_and_failed_connection(connected):
    client, app, remote = connected
    assert client.post("/api/connection", json={"url":"file:///etc/passwd", "username":"x", "password":"x"}).status_code == 422
    assert client.post("/api/connection", json={"url":"http://user:pass@navidrome.test", "username":"x"}).status_code == 422
    assert client.post("/api/preview", json={"limit":0}).status_code == 422
    assert client.post("/api/preview", json={"mode":"invalid"}).status_code == 422
    assert client.post("/api/preview", json={"year_from":2000,"year_to":1990}).status_code == 422
    preview = client.post("/api/preview", json={}).json()
    assert client.post("/api/playlists", json={"name":"Empty", "preview_id":preview["preview_id"]}).status_code == 422
    remote.fail_connection = True
    assert client.post("/api/connection", json={"url":"http://navidrome.test", "username":"listener", "password":NAV_PASSWORD}).status_code == 502
    assert app.state.store.credentials()["password"] == NAV_PASSWORD


def test_uncertain_remote_write_is_not_retried(connected):
    client, _, remote = connected
    sync(client)
    preview = client.post("/api/preview", json={}).json()
    remote.fail_playlist = True
    body = {"name":"Uncertain", "preview_id":preview["preview_id"]}
    assert client.post("/api/playlists", json=body).status_code == 502
    assert client.post("/api/playlists", json=body).status_code == 409
    assert len([method for method, _ in remote.calls if method == "createPlaylist"]) == 1
