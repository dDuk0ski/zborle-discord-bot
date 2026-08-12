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

import asyncio
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import words
from .auth import DiscordUser, current_user, exchange_code, resolve_user
from .board import Game, Status, score_guess
from .config import BASE_DIR, MAX_GUESSES
from .db import IN_PROGRESS, LOST, WON, shared_db
from .live import hub
from .words import GuessError

# Set by the runner once the bot exists; the web server starts first.
sessions = None


def set_session_manager(manager) -> None:
    global sessions
    sessions = manager

STATIC_DIR = Path(os.getenv('ZBORLE_STATIC_DIR', BASE_DIR / 'activity' / 'dist'))

log = logging.getLogger(__name__)

STATUS_NAMES = {Status.ABSENT: 'absent', Status.PRESENT: 'present', Status.CORRECT: 'correct'}

app = FastAPI(title='Зборле Activity', docs_url=None, redoc_url=None)


class TokenRequest(BaseModel):
    code: str


class GuessRequest(BaseModel):
    guess: str
    instance_id: str | None = None
    guild_id: str | None = None
    channel_id: str | None = None


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
    instance_id: str | None = None,
    user: DiscordUser = Depends(current_user),
) -> JSONResponse:
    _remember(guild_id, user, channel_id)
    if sessions is not None:
        sessions.touch(instance_id, guild_id, channel_id, user.id)
    index, game = _load(user.id)
    return JSONResponse(_state_payload(index, game))


async def _broadcast_progress(instance_id: str | None) -> None:
    """Tell everyone in the instance how far each player has got.

    Colours and counts only. Sending letters would let a spectator reconstruct the
    answer from someone else's finished board.
    """
    if not instance_id:
        return

    db = shared_db()
    session = db.session(instance_id)
    if session is None:
        return

    solution = words.word_of_day(session['puzzle_index'])
    players = []
    for board in db.session_boards(instance_id):
        rows = [[STATUS_NAMES[s] for s in score_guess(guess, solution)] for guess in board['guesses']]
        players.append(
            {
                'userId': board['userId'],
                'displayName': board['displayName'],
                'avatarUrl': board['avatarUrl'],
                'guessCount': len(board['guesses']),
                'isWon': board['status'] == WON,
                'isLost': board['status'] == LOST,
                'rows': rows,
            }
        )

    await hub.broadcast(instance_id, {'type': 'participants', 'players': players})


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

    # Update the channel message and everyone watching, after the guess is committed.
    if body.instance_id:
        _remember(body.guild_id, user, body.channel_id)
        if sessions is not None:
            sessions.touch(body.instance_id, body.guild_id, body.channel_id, user.id)
            sessions.schedule(body.instance_id)
        await _broadcast_progress(body.instance_id)

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


@app.websocket('/api/ws')
async def live_socket(socket: WebSocket) -> None:
    """Live progress within one activity instance.

    The client authenticates in its first message rather than a query string, so the
    access token never lands in a URL, proxy log or history entry.
    """
    await socket.accept()
    instance_id: str | None = None

    try:
        hello = await asyncio.wait_for(socket.receive_json(), timeout=10)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
        await socket.close(code=4001)
        return

    token = hello.get('token')
    instance_id = hello.get('instance_id')
    if not token or not instance_id:
        await socket.close(code=4001)
        return

    try:
        await resolve_user(token)
    except HTTPException:
        await socket.close(code=4003)
        return

    await hub.join(instance_id, socket)
    try:
        await _broadcast_progress(instance_id)
        while True:
            # The client sends nothing meaningful; this keeps the socket open and
            # notices disconnects promptly.
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        log.debug('WebSocket за %s се затвори', instance_id, exc_info=True)
    finally:
        await hub.leave(instance_id, socket)


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
