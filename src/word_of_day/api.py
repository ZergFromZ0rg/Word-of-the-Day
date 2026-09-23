"""HTTP API for a homepage widget. Run it with `word-of-the-day-api`, or
`uvicorn --factory word_of_day.api:app_from_env` for more uvicorn options.

Endpoints (interactive docs at /docs):
    GET /word-of-the-day          today's word
    GET /word-of-the-day/{date}   the word for a date (YYYY-MM-DD; future dates are a preview)
    GET /words/{word}             any word
    GET /recent?days=7            earlier days' words, most recent first (e.g. for a quiz)
    GET /health                   liveness check for Docker and monitors

Configured with the same environment variables as the CLI (a .env file in the working
directory is loaded too), plus WOTD_CORS_ORIGINS, WOTD_HOST and WOTD_PORT.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from dotenv import find_dotenv, load_dotenv
from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .errors import LookupFailedError, WordNotFoundError, WordOfTheDayError
from .models import WordEntry
from .service import WordOfTheDay


@dataclass
class DailyWord:
    date: dt.date
    entry: WordEntry


@dataclass
class PastWord:
    date: dt.date
    word: str


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
