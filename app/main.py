import asyncio
import hashlib
import hmac
import json
import logging
import os
import random
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from .genres import GenreResolver, UUID
from .navidrome import Navidrome, RemoteError, validate_url
from .storage import Store

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("playlistr")


def now():
    return datetime.now(timezone.utc).isoformat()


class Login(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class Connection(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(default="", max_length=1024)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        return validate_url(value)


class Filters(BaseModel):
    genres: list[str] = Field(default_factory=list, max_length=30)
    mode: str = "any"
    year_from: int | None = Field(default=None, ge=1000, le=3000)
    year_to: int | None = Field(default=None, ge=1000, le=3000)
    limit: int = Field(default=50, ge=1, le=2000)
    shuffle: bool = True
    exclude_artists: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, value):
        if value not in ("any", "all"):
            raise ValueError("Modo de género inválido")
        return value

    @model_validator(mode="after")
    def ordered_years(self):
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("El año inicial debe ser menor o igual al final")
        return self


class PlaylistRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    preview_id: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if not value.strip():
            raise ValueError("Escribe un nombre para la playlist")
        return value.strip()


class ArtistEdit(BaseModel):
    genres: list[str] = Field(max_length=30)

    @field_validator("genres")
    @classmethod
    def valid_genres(cls, values):
        if any(len(v) > 80 for v in values):
            raise ValueError("Cada género admite hasta 80 caracteres")
        return sorted({v.strip().lower() for v in values if v.strip()})


class ArtistChoice(BaseModel):
    mbid: str

    @field_validator("mbid")
    @classmethod
    def valid_mbid(cls, value):
        if not UUID.fullmatch(value):
            raise ValueError("MusicBrainz ID inválido")
        return value


class EnrichRequest(BaseModel):
    refresh: bool = False


def create_app(data_dir=None, password=None, client=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.password = password if password is not None else os.environ.get("PLAYLISTR_PASSWORD", "")
        if len(app.state.password) < 12:
            raise RuntimeError("Define PLAYLISTR_PASSWORD con al menos 12 caracteres antes de iniciar Playlistr.")
        app.state.store = Store(data_dir or os.environ.get("PLAYLISTR_DATA_DIR", "/data"))
        app.state.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=10), follow_redirects=False,
            headers={"User-Agent": os.environ.get("PLAYLISTR_USER_AGENT", "Playlistr/0.1 (https://github.com/diegoshock/Playlistr)")})
        app.state.resolver = GenreResolver(app.state.client)
        app.state.sessions = {}
        app.state.attempts = defaultdict(deque)
        app.state.previews = {}
        app.state.job = {"status": "idle", "message": "Listo", "done": 0, "total": 0, "errors": 0}
        app.state.task = None
        app.state.mutation = asyncio.Lock()
        try:
            yield
        finally:
            if app.state.task and not app.state.task.done():
                app.state.task.cancel()
                try:
                    await app.state.task
                except asyncio.CancelledError:
                    pass
            if client is None:
                await app.state.client.aclose()

    app = FastAPI(title="Playlistr", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if (origin and urlsplit(origin).netloc != request.headers.get("host")) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Solicitud de otro origen rechazada."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RemoteError)
    async def remote_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    def auth(request: Request):
        session = request.cookies.get("playlistr_session", "")
        expiry = app.state.sessions.get(session, 0)
        if expiry < time.time():
            app.state.sessions.pop(session, None)
            raise HTTPException(401, "Inicia sesión para continuar.")

    def navidrome():
        credentials = app.state.store.credentials()
        if not credentials:
            raise HTTPException(409, "Primero conecta tu servidor Navidrome.")
        return Navidrome(credentials, app.state.client)

    def idle():
        if app.state.task and not app.state.task.done():
            raise HTTPException(409, "Hay una tarea en curso. Espera a que termine.")

    def artist_exists(artist_id):
        with app.state.store.db() as db:
            artist = db.execute("SELECT * FROM artists WHERE id=?", (artist_id,)).fetchone()
        if not artist:
            raise HTTPException(404, "Artista no encontrado.")
        return dict(artist)

    def update_progress(message):
        app.state.job["message"] = message

    async def job_runner(kind, worker):
        try:
            await worker()
            app.state.job.update(status="completed", message="Tarea completada", finished_at=now())
        except asyncio.CancelledError:
            app.state.job.update(status="cancelled", message="Tarea cancelada")
            raise
        except (RemoteError, HTTPException) as exc:
            app.state.job.update(status="failed", message=str(exc.detail if isinstance(exc, HTTPException) else exc))
        except Exception:
            log.error("Falló la tarea %s; se conservan los datos confirmados.", kind)
            app.state.job.update(status="failed", message="La tarea falló por un error interno. Revisa la configuración y reintenta.")

    def launch(kind, worker):
        idle()
        app.state.job = {"kind": kind, "status": "running", "message": "Iniciando…", "done": 0,
                         "total": 0, "errors": 0, "started_at": now()}
        app.state.task = asyncio.create_task(job_runner(kind, worker))
        return app.state.job

    @app.get("/healthz")
    async def health():
        with app.state.store.db() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/api/login")
    async def login(body: Login, request: Request, response: Response):
        key = request.client.host if request.client else "unknown"
        stamp = time.monotonic()
        # Bound memory and expire both successful sessions and failed login buckets.
        app.state.sessions = {token: expiry for token, expiry in app.state.sessions.items() if expiry > time.time()}
        for address in list(app.state.attempts):
            attempts = app.state.attempts[address]
            while attempts and attempts[0] < stamp - 300:
                attempts.popleft()
            if not attempts:
                del app.state.attempts[address]
        attempts = app.state.attempts[key]
        if len(attempts) >= 10 or sum(map(len, app.state.attempts.values())) >= 100:
            raise HTTPException(429, "Demasiados intentos. Espera cinco minutos.")
        if not hmac.compare_digest(body.password.encode(), app.state.password.encode()):
            attempts.append(stamp)
            raise HTTPException(401, "Contraseña incorrecta.")
        attempts.clear()
        token = secrets.token_urlsafe(32)
        app.state.sessions[token] = time.time() + 43200
        response.set_cookie("playlistr_session", token, httponly=True, samesite="strict", max_age=43200,
                            secure=os.environ.get("PLAYLISTR_SECURE_COOKIE", "false").lower() == "true")
        return {"ok": True}

    @app.post("/api/logout", dependencies=[Depends(auth)])
    async def logout(request: Request, response: Response):
        app.state.sessions.pop(request.cookies.get("playlistr_session"), None)
        response.delete_cookie("playlistr_session")
        return {"ok": True}

    @app.get("/api/state", dependencies=[Depends(auth)])
    async def state():
        store = app.state.store
        credentials = store.setting("navidrome", {})
        artists = store.artists()
        with store.db() as db:
            songs = db.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
            playlists = [dict(row) for row in db.execute("SELECT * FROM playlists ORDER BY id DESC")]
        genres = defaultdict(int)
        for artist in artists:
            for genre in artist["genres"]:
                genres[genre] += 1
        return {"connection": {"configured": bool(credentials), "url": credentials.get("url", ""),
                               "username": credentials.get("username", "")},
                "stats": {"songs": songs, "artists": len(artists), "genres": len(genres),
                          "classified": sum(bool(a["genres"]) for a in artists), "playlists": len(playlists)},
                "genres": [{"name": name, "artists": count} for name, count in sorted(genres.items())],
                "artists": artists, "playlists": playlists, "last_sync": store.setting("last_sync"),
                "job": app.state.job}

    @app.post("/api/connection", dependencies=[Depends(auth)])
    async def connection(body: Connection):
        async with app.state.mutation:
            idle()
            old = app.state.store.credentials()
            values = body.model_dump()
            if not values["password"]:
                if not old or (old["url"], old["username"]) != (body.url, body.username):
                    raise HTTPException(422, "Introduce la contraseña de la cuenta de Navidrome.")
                values["password"] = old["password"]
            await Navidrome(values, app.state.client).call("ping")
            changed = old and (old["url"], old["username"]) != (body.url, body.username)
            app.state.store.save_credentials(values)
            if changed:
                with app.state.store.db() as db:
                    for table in ("song_artists", "songs", "artists", "playlists"):
                        db.execute(f"DELETE FROM {table}")
                    db.execute("DELETE FROM settings WHERE key='last_sync'")
            app.state.previews.clear()
            return {"ok": True}

    async def sync_library():
        songs = await navidrome().library(update_progress)
        # Swap the local library in one transaction; failed scans retain the old library.
        with app.state.store.db() as db:
            db.execute("DELETE FROM song_artists")
            db.execute("DELETE FROM songs")
            for song in songs:
                db.execute("INSERT INTO songs VALUES (?,?,?,?,?,?,?)", (
                    song["id"], song.get("title", "Sin título"), song.get("artist", "Artista desconocido"),
                    song.get("album", "Sin álbum"), int(song.get("duration", 0)), song.get("year"), song.get("genre")))
                artists = song.get("artists") or [{"id": song.get("artistId"), "name": song.get("artist", "Artista desconocido")}]
                for artist in artists:
                    name = artist.get("name") or song.get("artist") or "Artista desconocido"
                    artist_id = artist.get("id") or "name:" + hashlib.sha256(name.encode()).hexdigest()[:24]
                    db.execute("INSERT INTO artists(id,name) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name", (artist_id, name))
                    db.execute("INSERT OR IGNORE INTO song_artists VALUES (?,?)", (song["id"], artist_id))
            db.execute("DELETE FROM artists WHERE id NOT IN (SELECT artist_id FROM song_artists)")
            db.execute("INSERT OR REPLACE INTO settings VALUES ('last_sync',?)", (json.dumps(now()),))
        app.state.previews.clear()
        app.state.job.update(done=len(songs), total=len(songs))

    @app.post("/api/sync", dependencies=[Depends(auth)])
    async def sync():
        async with app.state.mutation:
            navidrome()
            return launch("sync", sync_library)

    def save_resolution(artist_id, result):
        with app.state.store.db() as db:
            db.execute("""UPDATE artists SET mbid=?,status=?,genres=?,evidence=?,candidates=?,checked_at=?,error=?
                WHERE id=?""", (result.get("mbid"), result["status"], json.dumps(result["genres"]),
                json.dumps(result["evidence"]), json.dumps(result["candidates"]), now(), result.get("error"), artist_id))

    async def resolve_artist(artist, chosen=None):
        try:
            mbid = chosen or artist.get("mbid") or await navidrome().artist_mbid(artist["id"])
            result = await app.state.resolver.resolve(artist["name"], mbid)
            save_resolution(artist["id"], result)
            if result["status"] == "error":
                app.state.job["errors"] += 1
        except RemoteError as exc:
            # Preserve a previously verified classification on transient network failure.
            with app.state.store.db() as db:
                db.execute("UPDATE artists SET error=?,status=CASE WHEN genres='[]' THEN 'error' ELSE status END WHERE id=?", (str(exc), artist["id"]))
            app.state.job["errors"] += 1

    @app.post("/api/enrich", dependencies=[Depends(auth)])
    async def enrich(body: EnrichRequest):
        async with app.state.mutation:
            navidrome()
            artists = [a for a in app.state.store.artists() if a["status"] != "manual" and
                       (body.refresh or a["status"] in ("pending", "error") or a["error"])]
            async def work():
                app.state.job["total"] = len(artists)
                consecutive_errors = 0
                for index, artist in enumerate(artists):
                    update_progress(f'Buscando géneros · {artist["name"]}')
                    errors_before = app.state.job["errors"]
                    await resolve_artist(artist)
                    app.state.job["done"] = index + 1
                    consecutive_errors = consecutive_errors + 1 if app.state.job["errors"] > errors_before else 0
                    if consecutive_errors >= 3:
                        raise RemoteError("Se detuvo la búsqueda tras tres errores consecutivos. Revisa el acceso a las fuentes y vuelve a buscar pendientes.")
            return launch("enrich", work)

    @app.post("/api/artists/{artist_id}/resolve", dependencies=[Depends(auth)])
    async def resolve(artist_id: str, body: ArtistChoice):
        async with app.state.mutation:
            artist = artist_exists(artist_id)
            async def work():
                app.state.job["total"] = 1
                await resolve_artist(artist, body.mbid)
                app.state.job["done"] = 1
            return launch("resolve", work)

    @app.put("/api/artists/{artist_id}", dependencies=[Depends(auth)])
    async def edit_artist(artist_id: str, body: ArtistEdit):
        async with app.state.mutation:
            idle()
            artist = artist_exists(artist_id)
            save_resolution(artist_id, {"mbid": artist["mbid"], "status": "manual", "genres": body.genres,
                                       "evidence": [{"source": "Manual", "genres": body.genres}], "candidates": []})
            return {"ok": True}

    @app.get("/api/job", dependencies=[Depends(auth)])
    async def job():
        return app.state.job

    @app.post("/api/preview", dependencies=[Depends(auth)])
    async def preview(body: Filters):
        artists = {a["id"]: a for a in app.state.store.artists()}
        with app.state.store.db() as db:
            songs = [dict(row) for row in db.execute("SELECT * FROM songs ORDER BY artist COLLATE NOCASE,title COLLATE NOCASE,id")]
            associations = defaultdict(list)
            for row in db.execute("SELECT * FROM song_artists"):
                associations[row["song_id"]].append(row["artist_id"])
        selected = set(body.genres)
        excluded = set(body.exclude_artists)
        matches = []
        for song in songs:
            ids = associations[song["id"]]
            genres = {genre for aid in ids for genre in artists[aid]["genres"]}
            if excluded.intersection(ids):
                continue
            if selected and not (selected.issubset(genres) if body.mode == "all" else selected.intersection(genres)):
                continue
            year = song["year"] or 0
            if (body.year_from and year < body.year_from) or (body.year_to and (not year or year > body.year_to)):
                continue
            song["genres"] = sorted(genres)
            matches.append(song)
        total = len(matches)
        if body.shuffle:
            random.SystemRandom().shuffle(matches)
        songs = matches[:body.limit]
        token = secrets.token_urlsafe(24)
        app.state.previews = {k: v for k, v in app.state.previews.items() if v["expires"] > time.time()}
        if len(app.state.previews) >= 100:
            app.state.previews.pop(next(iter(app.state.previews)))
        app.state.previews[token] = {"ids": [s["id"] for s in songs], "filters": body.model_dump(),
                                     "expires": time.time() + 900, "result": None, "attempted": False}
        return {"preview_id": token, "songs": songs, "total_matches": total,
                "duration": sum(s["duration"] for s in songs)}

    @app.post("/api/playlists", dependencies=[Depends(auth)])
    async def create_playlist(body: PlaylistRequest):
        async with app.state.mutation:
            idle()
            preview = app.state.previews.get(body.preview_id)
            if not preview or preview["expires"] < time.time():
                raise HTTPException(409, "La vista previa venció o cambió la biblioteca. Genera una nueva.")
            if preview["result"]:
                return preview["result"]
            if preview["attempted"]:
                raise HTTPException(409, "El intento anterior tuvo un resultado incierto. Revisa Navidrome antes de generar otra vista previa.")
            if not preview["ids"]:
                raise HTTPException(422, "No hay canciones para crear la playlist.")
            remote = navidrome()
            preview["attempted"] = True
            remote_id = await remote.create_playlist(body.name, preview["ids"])
            with app.state.store.db() as db:
                db.execute("INSERT INTO playlists(name,remote_id,song_count,filters,created_at) VALUES (?,?,?,?,?)",
                           (body.name, remote_id, len(preview["ids"]), json.dumps(preview["filters"]), now()))
            preview["result"] = {"ok": True, "remote_id": remote_id, "song_count": len(preview["ids"])}
            return preview["result"]

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    return app


app = create_app()
