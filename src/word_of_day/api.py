"""HTTP API for a homepage widget. Run it with `word-of-the-day-api`, or
`uvicorn --factory word_of_day.api:app_from_env` for more uvicorn options.

Endpoints (interactive docs at /docs):
    GET /word-of-the-day          today's word
    GET /word-of-the-day/{date}   the word for a date (YYYY-MM-DD; future dates are a preview)
    GET /words/{word}             any word
    GET /recent?days=7            earlier days' words, most recent first (e.g. for a quiz)
    GET /widget                   today's word as a flat object, for dashboard widgets
    GET /word-list                the current word list
    PUT /word-list                replace the list with an uploaded text file (needs a token)
    GET /manage                   a web page for uploading a word list
    GET /health                   liveness check for Docker and monitors

Configured with the same environment variables as the CLI (a .env file in the working
directory is loaded too), plus WOTD_CORS_ORIGINS, WOTD_HOST and WOTD_PORT.

Uploading a word list is off unless WOTD_ADMIN_TOKEN is set; requests must then send
`Authorization: Bearer <token>`. Example:

    curl -X PUT -H "Authorization: Bearer $TOKEN" --data-binary @mywords.txt \\
        http://localhost:8000/word-list
    curl -X PUT -H "Authorization: Bearer $TOKEN" --data-binary @more.txt \\
        "http://localhost:8000/word-list?mode=add"
"""

from __future__ import annotations

import datetime as dt
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Literal

from dotenv import find_dotenv, load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__
from .errors import LookupFailedError, WordNotFoundError, WordOfTheDayError
from .models import WordEntry
from .selector import parse_words, save_words
from .service import WordOfTheDay
from .web import CSP, MANAGE_PAGE

MAX_UPLOAD_BYTES = 1_000_000


@dataclass
class DailyWord:
    date: dt.date
    entry: WordEntry


@dataclass
class PastWord:
    date: dt.date
    word: str


@dataclass
class Widget:
    """Today's word flattened to plain strings, for dashboards that can't index into lists."""

    date: dt.date
    word: str
    pronunciation: str
    part_of_speech: str
    definition: str
    example: str
    synonyms: str
    etymology: str
    first_known_use: str
    source: str
    url: str


@dataclass
class WordList:
    words: list[str]
    count: int
    added: int = 0


@dataclass
class Health:
    status: str
    version: str
    today: dt.date
    words: int


def create_app(wotd: WordOfTheDay | None = None) -> FastAPI:
    """Build the app. Without `wotd`, one is created from the environment at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.wotd = wotd or service_from_env()
        try:
            yield
        finally:
            if wotd is None:
                app.state.wotd.close()

    app = FastAPI(title="Word of the Day", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        # The homepage usually runs on another host or port, so browsers need CORS.
        # The data is public and read-only, so any origin is allowed unless restricted.
        allow_origins=_cors_origins(),
        allow_methods=["GET"],
    )
    _add_error_handlers(app)

    # Sync endpoints: FastAPI runs them in a thread pool, which suits the blocking
    # dictionary lookups. WordOfTheDay is safe to share between threads.

    @app.get("/word-of-the-day")
    def word_of_the_day(wotd: Service) -> DailyWord:
        day = wotd.current_date()
        return DailyWord(date=day, entry=wotd.for_date(day))

    @app.get("/word-of-the-day/{day}")
    def word_for_date(day: dt.date, wotd: Service) -> DailyWord:
        return DailyWord(date=day, entry=wotd.for_date(day))

    @app.get("/words/{word}")
    def lookup(word: str, wotd: Service) -> WordEntry:
        return wotd.lookup(word)

    @app.get("/recent")
    def recent(wotd: Service, days: Annotated[int, Query(ge=1, le=365)] = 7) -> list[PastWord]:
        return [PastWord(date=day, word=word) for day, word in wotd.recent(days)]

    @app.get("/widget")
    def widget(wotd: Service) -> Widget:
        day = wotd.current_date()
        entry = wotd.for_date(day)
        first = entry.senses[0]
        return Widget(
            date=day,
            word=entry.word,
            pronunciation=entry.pronunciation or "",
            part_of_speech=first.part_of_speech or "",
            definition=first.definition,
            example=(first.examples or entry.examples or [""])[0],
            synonyms=", ".join(entry.synonyms[:6]),
            etymology=entry.etymology or "",
            first_known_use=entry.first_known_use or "",
            source=", ".join(entry.sources),
            url=entry.source_url or "",
        )

    @app.get("/word-list")
    def get_word_list(wotd: Service) -> WordList:
        words = wotd.words()
        return WordList(words=words, count=len(words))

    @app.put("/word-list", dependencies=[Depends(_require_admin)])
    async def put_word_list(
        request: Request,
        wotd: Service,
        mode: Literal["replace", "add"] = "replace",
    ) -> WordList:
        raw = await request.body()
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"word list is larger than {MAX_UPLOAD_BYTES} bytes")
        try:
            uploaded = parse_words(raw.decode("utf-8-sig"))
        except UnicodeDecodeError:
            raise HTTPException(400, "the file must be UTF-8 text") from None
        if not uploaded:
            raise HTTPException(400, "the file contains no words")
        current = wotd.words() if mode == "add" and wotd.words_file.exists() else []
        combined = parse_words("\n".join([*current, *uploaded]))
        save_words(wotd.words_file, combined)
        return WordList(words=combined, count=len(combined), added=len(combined) - len(current))

    @app.get("/manage", response_class=HTMLResponse, include_in_schema=False)
    def manage() -> HTMLResponse:
        """A small page for viewing today's word and uploading a word list."""
        return HTMLResponse(MANAGE_PAGE, headers={"Content-Security-Policy": CSP})

    @app.get("/health")
    def health(wotd: Service) -> Health:
        # Reading the word list catches the most common misconfiguration (wrong path).
        return Health(
            status="ok", version=__version__, today=wotd.current_date(), words=len(wotd.words())
        )

    return app


def app_from_env() -> FastAPI:
    """App factory for uvicorn: loads .env, then builds the app from the environment."""
    load_dotenv(find_dotenv(usecwd=True))
    return create_app()


def service_from_env() -> WordOfTheDay:
    return WordOfTheDay.from_env(
        os.environ.get("WOTD_WORDS_FILE", "words.txt"),
        os.environ.get("WOTD_CACHE_DIR", "cache"),
        os.environ.get("WOTD_HISTORY_FILE", "history.json"),
    )


def _get_service(request: Request) -> WordOfTheDay:
    service: WordOfTheDay = request.app.state.wotd
    return service


Service = Annotated[WordOfTheDay, Depends(_get_service)]


def _require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
    """Uploading changes what everyone sees, so it needs the WOTD_ADMIN_TOKEN secret."""
    token = os.environ.get("WOTD_ADMIN_TOKEN")
    if not token:
        raise HTTPException(403, "uploads are disabled; set WOTD_ADMIN_TOKEN to enable them")
    expected = f"Bearer {token}"
    if not secrets.compare_digest((authorization or "").encode(), expected.encode()):
        raise HTTPException(401, "missing or wrong token", headers={"WWW-Authenticate": "Bearer"})


def _cors_origins() -> list[str]:
    origins = os.environ.get("WOTD_CORS_ORIGINS", "*")
    return [origin.strip() for origin in origins.split(",") if origin.strip()]


def _add_error_handlers(app: FastAPI) -> None:
    # Starlette picks the most specific handler, so the subclasses win over the base.
    def respond(status: int, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    @app.exception_handler(WordNotFoundError)
    async def not_found(request: Request, exc: WordNotFoundError) -> JSONResponse:
        return respond(404, exc)

    @app.exception_handler(LookupFailedError)
    async def upstream_failed(request: Request, exc: LookupFailedError) -> JSONResponse:
        # The dictionaries couldn't be reached; the word may well exist.
        return respond(502, exc)

    @app.exception_handler(WordOfTheDayError)
    async def misconfigured(request: Request, exc: WordOfTheDayError) -> JSONResponse:
        return respond(500, exc)

    @app.exception_handler(OSError)
    async def file_error(request: Request, exc: OSError) -> JSONResponse:
        return respond(500, exc)


def main() -> None:
    """Run the server: `word-of-the-day-api`. Listens on 127.0.0.1:8000 by default."""
    import uvicorn

    load_dotenv(find_dotenv(usecwd=True))
    uvicorn.run(
        "word_of_day.api:app_from_env",
        factory=True,
        host=os.environ.get("WOTD_HOST", "127.0.0.1"),
        port=int(os.environ.get("WOTD_PORT", "8000")),
    )
