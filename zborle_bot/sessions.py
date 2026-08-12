"""Live session messages.

When people play the Activity together, the bot posts one public message per activity
instance showing everyone's grid, and edits it as guesses land and players join. This is
what official Wordle does, and it is the thing that makes a session visible to a channel
rather than trapped inside the iframe.

Two constraints shape the design.

Discord rate-limits message edits per channel. Six players guessing at once would issue
six edits in a second and get throttled, so updates are coalesced: a dirty instance
schedules one edit after a short quiet period, and further changes during that window
fold into the same edit rather than queueing more.

Uploading a fresh PNG on every edit is also wasteful, so the image is only re-rendered
when the boards actually changed, keyed by a cheap fingerprint of their contents.
"""

import asyncio
import io
import logging

import discord

from . import words
from .board import Status, score_guess
from .db import IN_PROGRESS, WON, ZborleDB
from .summary import PlayerBoard, render_group_board

log = logging.getLogger(__name__)

# Long enough to absorb a flurry of guesses into one edit, short enough that the message
# still feels live. Discord allows roughly 5 edits per 5 seconds per channel.
DEBOUNCE_SECONDS = 2.0


def _describe(names: list[str]) -> str:
    if not names:
        return 'Некој игра Зборле'
    if len(names) == 1:
        return f'**{names[0]}** игра Зборле'
    if len(names) == 2:
        return f'**{names[0]}** и **{names[1]}** играат Зборле'
    return f'**{names[0]}** и уште {len(names) - 1} играат Зборле'


class SessionManager:
    """Owns the lifecycle of live session messages."""

    def __init__(self, client: discord.Client, db: ZborleDB) -> None:
        self._client = client
        self._db = db
        self._timers: dict[str, asyncio.Task] = {}
        self._fingerprints: dict[str, str] = {}
        # One lock per instance so two concurrent edits cannot post duplicate messages.
        self._locks: dict[str, asyncio.Lock] = {}
        self._avatars: dict[str, bytes | None] = {}

    def _lock(self, instance_id: str) -> asyncio.Lock:
        return self._locks.setdefault(instance_id, asyncio.Lock())

    def touch(
        self,
        instance_id: str | None,
        guild_id: str | None,
        channel_id: str | None,
        user_id: str,
    ) -> None:
        """Record presence and schedule an update. Safe to call on every request."""
        if not instance_id:
            return

        joined = self._db.join_session(
            instance_id,
            int(guild_id) if guild_id and guild_id.isdigit() else None,
            int(channel_id) if channel_id and channel_id.isdigit() else None,
            words.puzzle_index(),
            int(user_id),
        )
        # A new player changes the card layout, so force a redraw even if no guess landed.
        self.schedule(instance_id, force=joined)

    def schedule(self, instance_id: str, force: bool = False) -> None:
        """Coalesce updates: one pending edit per instance, regardless of traffic."""
        if force:
            self._fingerprints.pop(instance_id, None)

        existing = self._timers.get(instance_id)
        if existing and not existing.done():
            return

        self._timers[instance_id] = asyncio.create_task(self._run_after_delay(instance_id))

    async def _run_after_delay(self, instance_id: str) -> None:
        try:
            await asyncio.sleep(DEBOUNCE_SECONDS)
            await self.update(instance_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('Неуспешно ажурирање на сесијата %s', instance_id)
        finally:
            self._timers.pop(instance_id, None)

    async def _avatar(self, url: str | None) -> bytes | None:
        """Fetch and cache an avatar. Cached for the process lifetime; they rarely change."""
        if not url:
            return None
        if url in self._avatars:
            return self._avatars[url]

        data: bytes | None = None
        try:
            import httpx

            async with httpx.AsyncClient() as http:
                response = await http.get(url, timeout=8)
                if response.status_code == 200:
                    data = response.content
        except Exception:
            data = None

        self._avatars[url] = data
        return data

    async def update(self, instance_id: str) -> None:
        """Post or edit this instance's message, if anything actually changed."""
        async with self._lock(instance_id):
            session = self._db.session(instance_id)
            if session is None or not session['channel_id']:
                return

            boards = self._db.session_boards(instance_id)
            if not boards:
                return

            fingerprint = '|'.join(f'{b["userId"]}:{len(b["guesses"])}:{b["status"]}' for b in boards)
            if self._fingerprints.get(instance_id) == fingerprint:
                return

            solution = words.word_of_day(session['puzzle_index'])
            rendered: list[PlayerBoard] = []
            for board in boards:
                rendered.append(
                    PlayerBoard(
                        display_name=board['displayName'],
                        rows=[score_guess(guess, solution) for guess in board['guesses']],
                        avatar=await self._avatar(board['avatarUrl']),
                    )
                )

            content = self._content(boards)
            image = render_group_board(rendered, session['puzzle_index'])

            channel = self._client.get_channel(session['channel_id'])
            if channel is None:
                try:
                    channel = await self._client.fetch_channel(session['channel_id'])
                except (discord.NotFound, discord.Forbidden):
                    log.warning('Каналот %s е недостапен', session['channel_id'])
                    return

            file = discord.File(io.BytesIO(image), filename='zborle-session.png')
            try:
                if session['message_id']:
                    message = await channel.fetch_message(session['message_id'])
                    await message.edit(content=content, attachments=[file])
                else:
                    message = await channel.send(content=content, file=file)
                    self._db.set_session_message(instance_id, message.id)
            except discord.NotFound:
                # Message was deleted. Post a fresh one rather than failing forever.
                message = await channel.send(content=content, file=discord.File(io.BytesIO(image), filename='zborle-session.png'))
                self._db.set_session_message(instance_id, message.id)
            except discord.HTTPException:
                log.exception('Неуспешно објавување на сесијата %s', instance_id)
                return

            self._fingerprints[instance_id] = fingerprint

    def _content(self, boards: list[dict]) -> str:
        names = [board['displayName'] for board in boards]
        finished = [b for b in boards if b['status'] and b['status'] != IN_PROGRESS]

        line = _describe(names)
        if finished and len(finished) == len(boards):
            winners = [b for b in finished if b['status'] == WON]
            if winners:
                best = min(len(b['guesses']) for b in winners)
                champions = [b['displayName'] for b in winners if len(b['guesses']) == best]
                return f'{line}\n👑 {best}/6: {", ".join(champions)}'
            return f'{line}\nНикој не го погоди денес.'
        return line

    async def share(self, instance_id: str, content: str) -> bool:
        """Post a player's result to the session's channel.

        Discord blocks clipboard writes inside the Activity iframe, so "copy your grid"
        cannot work there. Posting through the bot achieves what sharing is actually for.
        """
        session = self._db.session(instance_id)
        if session is None or not session['channel_id']:
            return False

        channel = self._client.get_channel(session['channel_id'])
        if channel is None:
            try:
                channel = await self._client.fetch_channel(session['channel_id'])
            except (discord.NotFound, discord.Forbidden):
                return False

        try:
            await channel.send(content)
            return True
        except discord.HTTPException:
            log.exception('Неуспешно споделување за сесијата %s', instance_id)
            return False

    async def sweep(self) -> None:
        """Forget yesterday's instances so the tables do not grow without bound."""
        for instance_id in self._db.stale_sessions(words.puzzle_index()):
            self._db.drop_session(instance_id)
            self._fingerprints.pop(instance_id, None)
            self._locks.pop(instance_id, None)
