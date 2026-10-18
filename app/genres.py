"""Resolve artist identity first. Never infer a genre from an arbitrary web snippet."""
import asyncio
import re
import time
import unicodedata
from urllib.parse import urlsplit

import httpx

from .navidrome import RemoteError

MB = "https://musicbrainz.org/ws/2"
WD = "https://www.wikidata.org/w/api.php"
UUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


def normalized(value):
    return " ".join(re.sub(r"[^\w\s]", " ", "".join(
        c for c in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(c))).split())


class GenreResolver:
    def __init__(self, client: httpx.AsyncClient, interval=1.1):
        self.client = client
        self.interval = interval
        self.lock = asyncio.Lock()
        self.last_request = 0.0

    async def get(self, url, params):
        for attempt in range(3):
            # A single resolver is shared by all requests, honoring MusicBrainz's 1 req/s policy.
            async with self.lock:
                await asyncio.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
                try:
                    response = await self.client.get(url, params=params)
                except httpx.HTTPError as exc:
                    raise RemoteError("La fuente de géneros no responde. Revisa la conexión a internet.") from exc
            if response.status_code in (429, 503) and attempt < 2:
                await asyncio.sleep(2 ** (attempt + 1))
                continue
            if response.status_code != 200:
                raise RemoteError(f"La fuente de géneros respondió HTTP {response.status_code}; puedes reintentar más tarde.")
            try:
                data = response.json()
            except ValueError as exc:
                raise RemoteError("La fuente devolvió una respuesta no válida.") from exc
            if "error" in data:
                raise RemoteError("La fuente de géneros rechazó la consulta.")
            return data

    async def resolve(self, name, mbid=None):
        if not mbid or not UUID.fullmatch(mbid):
            # Escape Lucene's reserved characters inside the quoted artist name.
            query = name.replace("\\", "\\\\").replace('"', '\\"')
            data = await self.get(MB + "/artist/", {"query": f'artist:"{query}"', "fmt": "json", "limit": 25})
            candidates = []
            for artist in data.get("artists", []):
                names = [artist.get("name", "")] + [a.get("name", "") for a in artist.get("aliases", [])]
                exact = any(normalized(value) == normalized(name) for value in names)
                candidates.append({"id": artist["id"], "name": artist["name"],
                                   "description": artist.get("disambiguation", ""),
                                   "country": artist.get("country", artist.get("area", {}).get("name", "")),
                                   "exact": exact, "score": int(artist.get("score", 0)),
                                   "url": f'https://musicbrainz.org/artist/{artist["id"]}'})
            matches = [a for a in candidates if a["exact"] and a["score"] >= 95]
            if len(matches) != 1 or int(data.get("count", 0)) > 25:
                return {"status": "ambiguous" if candidates else "not_found", "genres": [],
                        "evidence": [], "candidates": candidates, "mbid": None}
            mbid = matches[0]["id"]
        artist = await self.get(MB + "/artist/" + mbid,
                                {"fmt": "json", "inc": "genres+url-rels"})
        # MusicBrainz's curated genre vocabulary excludes free tags such as "seen live".
        genre_items = [item for item in artist.get("genres", []) if item.get("count", 0) > 0]
        genres = sorted({item["name"].strip().lower() for item in genre_items})
        evidence = [{"source": "MusicBrainz", "url": f"https://musicbrainz.org/artist/{mbid}",
                     "genres": genres, "votes": {g["name"]: g["count"] for g in genre_items}}]
        warning = None
        if not genres:
            for relation in artist.get("relations", []):
                target = relation.get("url", {}).get("resource", "")
                parts = urlsplit(target)
                entity = parts.path.rsplit("/", 1)[-1]
                if parts.hostname in ("www.wikidata.org", "wikidata.org") and re.fullmatch(r"Q\d+", entity):
                    try:
                        genres = await self.wikidata(entity)
                    except RemoteError as exc:
                        warning = str(exc)
                    else:
                        evidence.append({"source": "Wikidata", "url": f"https://www.wikidata.org/wiki/{entity}", "genres": genres})
                    break
        return {"status": "matched" if genres else ("error" if warning else "not_found"),
                "genres": genres, "evidence": evidence, "candidates": [], "mbid": mbid, "error": warning}

    async def wikidata(self, entity):
        data = await self.get(WD, {"action": "wbgetentities", "ids": entity, "props": "claims", "format": "json"})
        claims = data.get("entities", {}).get(entity, {}).get("claims", {}).get("P136", [])
        ids = []
        for claim in claims:
            if claim.get("rank") == "deprecated":
                continue
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(value, dict) and re.fullmatch(r"Q\d+", value.get("id", "")):
                ids.append(value["id"])
        if not ids:
            return []
        labels = await self.get(WD, {"action": "wbgetentities", "ids": "|".join(dict.fromkeys(ids)),
                                    "props": "labels", "languages": "en|es", "format": "json"})
        genres = set()
        for item in labels.get("entities", {}).values():
            label = item.get("labels", {}).get("en") or item.get("labels", {}).get("es")
            if label:
                genres.add(label["value"].lower())
        return sorted(genres)
