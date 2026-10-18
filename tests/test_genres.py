import httpx
import pytest

from app.genres import GenreResolver, MB, WD
from app.navidrome import Navidrome, RemoteError
from conftest import MBID, NAV_PASSWORD


async def test_search_exact_artist_and_ignore_freeform_tags(respx_mock):
    search = respx_mock.get(MB + "/artist/").respond(json={"count":1,"artists":[{"id":MBID,"name":"Radiohead","score":100}]})
    respx_mock.get(MB + "/artist/" + MBID).respond(json={"genres":[{"name":"art rock","count":8},{"name":"pop","count":-1}],"tags":[{"name":"seen live","count":100}]})
    async with httpx.AsyncClient() as client:
        result = await GenreResolver(client, interval=0).resolve("Radiohead")
    assert search.called
    assert result["genres"] == ["art rock"]
    assert result["status"] == "matched"


async def test_homonyms_require_human_choice(respx_mock):
    respx_mock.get(MB + "/artist/").respond(json={"count":2,"artists":[
        {"id":MBID,"name":"Ghost","score":100,"disambiguation":"Swedish rock band"},
        {"id":"11111111-1111-1111-1111-111111111111","name":"Ghost","score":100,"disambiguation":"Japanese band"}]})
    async with httpx.AsyncClient() as client:
        result = await GenreResolver(client, interval=0).resolve("Ghost")
    assert result["status"] == "ambiguous"
    assert result["genres"] == []
    assert len(result["candidates"]) == 2


async def test_fuzzy_name_not_automatically_accepted(respx_mock):
    respx_mock.get(MB + "/artist/").respond(json={"count":1,"artists":[{"id":MBID,"name":"Another Artist","score":100}]})
    async with httpx.AsyncClient() as client:
        result = await GenreResolver(client, interval=0).resolve("Artist")
    assert result["status"] == "ambiguous"


async def test_wikidata_fallback_uses_linked_identity_and_genre_claims(respx_mock):
    respx_mock.get(MB + "/artist/" + MBID).respond(json={"genres":[],"relations":[{"url":{"resource":"https://www.wikidata.org/wiki/Q123"}}]})
    def wd(request):
        if request.url.params["props"] == "claims":
            return httpx.Response(200,json={"entities":{"Q123":{"claims":{"P136":[
                {"mainsnak":{"datavalue":{"value":{"id":"Q456"}}}},
                {"rank":"deprecated","mainsnak":{"datavalue":{"value":{"id":"Q999"}}}},
                {"mainsnak":{"snaktype":"novalue"}}]}}}})
        assert request.url.params["ids"] == "Q456"
        return httpx.Response(200,json={"entities":{"Q456":{"labels":{"en":{"value":"Trip hop"}}}}})
    respx_mock.get(WD).mock(side_effect=wd)
    async with httpx.AsyncClient() as client:
        result = await GenreResolver(client, interval=0).resolve("Artist", MBID)
    assert result["status"] == "matched"
    assert result["genres"] == ["trip hop"]
    assert result["evidence"][1]["source"] == "Wikidata"


async def test_sources_unavailable_and_no_data_are_distinct(respx_mock):
    route = respx_mock.get(MB + "/artist/").respond(403)
    async with httpx.AsyncClient() as client:
        resolver = GenreResolver(client, interval=0)
        with pytest.raises(RemoteError, match="403"):
            await resolver.resolve("Radiohead")
        route.respond(json={"count":0,"artists":[]})
        result = await resolver.resolve("Unknown Artist")
        assert result["status"] == "not_found"


async def test_album_pagination():
    offsets = []
    async def transport(request):
        from urllib.parse import parse_qs
        data = parse_qs(request.content.decode())
        result = {"status":"ok"}
        if "getAlbumList2" in request.url.path:
            offset = int(data["offset"][0]); offsets.append(offset)
            result["albumList2"] = {"album":[{"id":str(i)} for i in range(500)] if offset == 0 else [{"id":"500"}]}
        else:
            result["album"] = {"song":[{"id":"song-" + data["id"][0]}]}
        return httpx.Response(200,json={"subsonic-response":result})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        nav = Navidrome({"url":"http://nav.test","username":"listener","password":NAV_PASSWORD},client)
        songs = await nav.library(lambda _:None)
    assert len(songs) == 501
    assert offsets == [0,500]


async def test_does_not_follow_redirects_with_credentials():
    seen = []
    async def transport(request):
        seen.append(request.url.host)
        return httpx.Response(302,headers={"location":"https://attacker.example"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport),follow_redirects=False) as client:
        nav = Navidrome({"url":"http://nav.test","username":"listener","password":NAV_PASSWORD},client)
        with pytest.raises(RemoteError):
            await nav.call("ping")
    assert seen == ["nav.test"]
