"""HTTP server for the Discord Activity.

Runs in the same process and asyncio loop as the bot so both share one SQLite file on
the Fly volume. Discord serves Activities from a sandboxed iframe and rewrites requests
through its proxy, stripping a `/.proxy` prefix before they reach us, so the browser
calls `/.proxy/api/...` and we receive `/api/...`.

Scoring is server-side and the solution is withheld until a game ends. A leaderboard
built on results the browser reports about itself would be trivially forged.

Every handler is `async def` on purpose: FastAPI runs sync handlers in a worker thread,
which would touch the SQLite connection from a thread the bot is not on.
"""

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import words
from .auth import DiscordUser, current_user, exchange_code
from .board import Game, Status
from .config import BASE_DIR, MAX_GUESSES
from .db import IN_PROGRESS, LOST, WON, shared_db
from .words import GuessError

STATIC_DIR = Path(os.getenv('ZBORLE_STATIC_DIR', BASE_DIR / 'activity' / 'dist'))

STATUS_NAMES = {Status.ABSENT: 'absent', Status.PRESENT: 'present', Status.CORRECT: 'correct'}

app = FastAPI(title='Зборле Activity', docs_url=None, redoc_url=None)


class TokenRequest(BaseModel):
    code: str


class GuessRequest(BaseModel):
    guess: str
    instance_id: str | None = None


def _statuses(game: Game) -> list[list[str]]:
    return [[STATUS_NAMES[s] for s in statuses] for _, statuses in game.rows]


def _load(user_id: str) -> tuple[int, Game]:
    index = words.puzzle_index()
    db = shared_db()
    return index, Game(words.word_of_day(index), db.load_guesses(int(user_id), index))


def _state_payload(index: int, game: Game) -> dict:
    return {
        'puzzleIndex': index,
        'guesses': game.guesses,
        'statuses': _statuses(game),
        'isWon': game.is_won,
        'isLost': game.is_lost,
        # Revealed only once the game is over, never while it is winnable.
        'solution': game.solution if game.is_over else None,
        'secondsUntilNext': int(words.time_until_next_word().total_seconds()),
        'maxGuesses': MAX_GUESSES,
    }


@app.get('/api/health')
async def health() -> JSONResponse:
    """Liveness probe, and the smoke test for Discord's URL mapping."""
    return JSONResponse(
        {
            'status': 'ok',
            'puzzle_index': words.puzzle_index(),
            'seconds_until_next': int(words.time_until_next_word().total_seconds()),
            'static_built': STATIC_DIR.is_dir(),
            'oauth_configured': bool(os.getenv('DISCORD_CLIENT_SECRET')),
        }
    )


@app.post('/api/token')
async def token(body: TokenRequest) -> JSONResponse:
    access_token = await exchange_code(body.code)
    return JSONResponse({'access_token': access_token})


def _remember(guild_id: str | None, user: DiscordUser, channel_id: str | None = None) -> None:
    """Add the player to a server's leaderboard the first time they play there."""
    if not guild_id or not guild_id.isdigit():
        return
    db = shared_db()
    db.remember_player(int(guild_id), int(user.id), user.display_name, user.avatar_url)
    if channel_id and channel_id.isdigit():
        # So the daily summary lands where people play, with no setup command.
        db.remember_play_channel(int(guild_id), int(channel_id))


@app.get('/api/state')
async def state(
    guild_id: str | None = None,
    channel_id: str | None = None,
    user: DiscordUser = Depends(current_user),
) -> JSONResponse:
    _remember(guild_id, user, channel_id)
    index, game = _load(user.id)
    return JSONResponse(_state_payload(index, game))


@app.get('/api/leaderboard')
async def leaderboard(guild_id: str | None = None, user: DiscordUser = Depends(current_user)) -> JSONResponse:
    # No guild means a DM or group DM: personal stats still count, but there is no server
    # to rank within, so the board is empty rather than wrong.
    if not guild_id or not guild_id.isdigit():
        return JSONResponse({'rows': [], 'scope': 'dm'})

    # Deliberately no enrolment here. Reading a board must not join you to it, or a
    # player would appear on the leaderboard of every server they merely looked at.
    return JSONResponse({'rows': shared_db().leaderboard(int(guild_id)), 'scope': 'guild'})


@app.post('/api/guess')
async def guess(body: GuessRequest, user: DiscordUser = Depends(current_user)) -> JSONResponse:
    index, game = _load(user.id)

    if game.is_over:
        return JSONResponse({'ok': False, 'error': 'game_over', 'message': 'Играта за денес е завршена.'})

    try:
        scored = game.add_guess(body.guess)
    except GuessError as error:
        return JSONResponse({'ok': False, 'error': error.code, 'message': str(error)})

    status = WON if game.is_won else LOST if game.is_lost else IN_PROGRESS
    shared_db().save(int(user.id), index, game.guesses, status)

    return JSONResponse(
        {
            'ok': True,
            'statuses': [STATUS_NAMES[s] for s in scored],
            'isWon': game.is_won,
            'isLost': game.is_lost,
            'solution': game.solution if game.is_over else None,
        }
    )


@app.get('/api/stats')
async def stats(user: DiscordUser = Depends(current_user)) -> JSONResponse:
    computed = shared_db().stats(int(user.id))
    return JSONResponse(
        {
            'played': computed.played,
            'won': computed.won,
            'currentStreak': computed.current_streak,
            'maxStreak': computed.max_streak,
            'distribution': {str(k): v for k, v in computed.distribution.items()},
        }
    )


def mount_static() -> None:
    """Serve the built Activity, if it has been built.

    Mounted last so it cannot shadow /api. Kept out of import so the server still starts
    when activity/dist is absent, which is the case before the frontend is built.
    """
    if STATIC_DIR.is_dir():
        app.mount('/', StaticFiles(directory=STATIC_DIR, html=True), name='activity')
    else:

        @app.get('/')
        async def placeholder() -> JSONResponse:
            return JSONResponse(
                {
                    'app': 'Зборле',
                    'status': 'backend up, frontend not built yet',
                    'puzzle_index': words.puzzle_index(),
                }
            )


mount_static()
