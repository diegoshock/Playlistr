import hashlib
import secrets
from urllib.parse import urlsplit

import httpx


class RemoteError(Exception):
    pass


def validate_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError("Usa una URL http(s) sin credenciales, parámetros ni fragmentos.")
    return value.strip().rstrip("/")


class Navidrome:
    def __init__(self, credentials, client: httpx.AsyncClient):
        self.credentials = credentials
        self.client = client

    async def call(self, method, params=None):
        salt = secrets.token_hex(12)
        token = hashlib.md5((self.credentials["password"] + salt).encode()).hexdigest()
        auth = {"u": self.credentials["username"], "t": token, "s": salt,
                "v": "1.16.1", "c": "Playlistr", "f": "json"}
        # POST keeps authentication and large song lists out of URLs and access logs.
        data = dict(auth)
        data.update(params or {})
        try:
            response = await self.client.post(
                self.credentials["url"] + "/rest/" + method + ".view", data=data)
            response.raise_for_status()
            payload = response.json()["subsonic-response"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise RemoteError("No se pudo contactar con Navidrome. Revisa URL, red y certificado TLS.") from exc
        if payload.get("status") != "ok":
            code = payload.get("error", {}).get("code", 0)
            messages = {40: "Credenciales de Navidrome incorrectas.",
                        50: "La cuenta de Navidrome no tiene permiso para esta operación.",
                        70: "Navidrome no encuentra el recurso solicitado."}
            raise RemoteError(messages.get(code, f"Navidrome rechazó la operación (código {code})."))
        return payload

    async def library(self, progress):
        songs = {}
        seen_albums = set()
        offset = 0
        while True:
            payload = await self.call("getAlbumList2", {"type": "alphabeticalByName", "size": 500, "offset": offset})
            albums = payload.get("albumList2", {}).get("album", [])
            if not albums:
                break
            fresh = [album for album in albums if album["id"] not in seen_albums]
            if not fresh:
                raise RemoteError("Navidrome repitió una página de álbumes; se conservó la biblioteca anterior.")
            for album in fresh:
                detail = (await self.call("getAlbum", {"id": album["id"]}))["album"]
                for song in detail.get("song", []):
                    if not song.get("isVideo", False):
                        songs[song["id"]] = song
                seen_albums.add(album["id"])
                progress(f"Leyendo biblioteca · {len(seen_albums)} álbumes · {len(songs)} canciones")
            offset += len(albums)
            if len(albums) < 500:
                break
        return list(songs.values())

    async def artist_mbid(self, artist_id):
        if artist_id.startswith("name:"):
            return None
        try:
            payload = await self.call("getArtistInfo2", {"id": artist_id, "count": 0})
        except RemoteError:
            return None
        return payload.get("artistInfo2", {}).get("musicBrainzId") or None

    async def create_playlist(self, name, song_ids):
        response = await self.call("createPlaylist", {"name": name, "songId": song_ids})
        playlist = response.get("playlist", {})
        if not playlist.get("id"):
            raise RemoteError("Navidrome no devolvió el identificador de la playlist; revisa Navidrome antes de reintentar.")
        return playlist["id"]
