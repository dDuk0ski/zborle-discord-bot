"""The daily summary posted to each server's channel.

Mirrors official Wordle's daily briefing: the group's streak, yesterday's results grouped
by score, and a board image showing everyone's grid.
"""

import asyncio
import logging

import discord
import httpx

from . import words
from .config import MAX_GUESSES
from .db import ZborleDB
from .board import Status
from .summary import PlayerBoard, render_group_board

log = logging.getLogger(__name__)

STATUS_BY_VALUE = {int(status): status for status in Status}


async def _fetch_avatars(urls: list[str | None]) -> list[bytes | None]:
    """Fetch avatars concurrently. A failure yields None and renders a placeholder."""

    async def fetch(client: httpx.AsyncClient, url: str | None) -> bytes | None:
        if not url:
            return None
        try:
            response = await client.get(url, timeout=8)
            return response.content if response.status_code == 200 else None
        except Exception:
            return None

    async with httpx.AsyncClient() as client:
        return await asyncio.gather(*(fetch(client, url) for url in urls))


def _score_rows(guesses: list[str], solution: str) -> list[list[Status]]:
    from .board import score_guess

    return [score_guess(guess, solution) for guess in guesses]


def _flames(streak: int) -> str:
    """More fire for longer streaks, capped so the line stays readable."""
    if streak >= 100:
        return '🔥🔥🔥'
    if streak >= 30:
        return '🔥🔥'
    return '🔥'


def _mention_groups(results: list[dict]) -> list[str]:
    """Group players by score, best first, as `👑 4/6: @a @b` lines."""
    by_score: dict[int | None, list[str]] = {}
    for result in results:
        by_score.setdefault(result['score'], []).append(f'<@{result["userId"]}>')

    lines = []
    for position, (score, mentions) in enumerate(
        sorted(by_score.items(), key=lambda item: (item[0] is None, item[0] or 0))
    ):
        label = f'{score}/{MAX_GUESSES}' if score else f'X/{MAX_GUESSES}'
        crown = '👑 ' if position == 0 and score else ''
        lines.append(f'{crown}{label}: {" ".join(mentions)}')
    return lines


async def build_summary(db: ZborleDB, guild_id: int, puzzle_index: int) -> tuple[str, discord.File] | None:
    """Compose yesterday's summary, or None when nobody played."""
    results = db.guild_results(guild_id, puzzle_index)
    if not results:
        return None

    solution = words.word_of_day(puzzle_index)
    avatars = await _fetch_avatars([result['avatarUrl'] for result in results])

    boards = [
        PlayerBoard(
            display_name=result['displayName'],
            rows=_score_rows(result['guesses'], solution),
            avatar=avatar,
        )
        for result, avatar in zip(results, avatars)
    ]

    # Streak wording stays in English by request, matching official Wordle's phrasing.
    streak = db.group_streak(guild_id, puzzle_index)
    header = (
        f'Your group is on a {streak} day streak! {_flames(streak)}\nЕве ги вчерашните резултати:'
        if streak > 1
        else 'Еве ги вчерашните резултати:'
    )
    body = '\n'.join(_mention_groups(results))
    text = f'{header}\n{body}\nЗборот беше **{solution}**.'

    image = render_group_board(boards, puzzle_index)
    return text, discord.File(__import__('io').BytesIO(image), filename='zborle-summary.png')


async def post_due_summaries(client: discord.Client, db: ZborleDB) -> None:
    """Post yesterday's summary to every configured server that has not had one yet."""
    yesterday = words.puzzle_index() - 1
    if yesterday < 0:
        return

    for guild_id, channel_id, last_posted in db.guilds_with_summary():
        if last_posted is not None and last_posted >= yesterday:
            continue

        try:
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden):
            log.warning('Каналот %s за серверот %s е недостапен', channel_id, guild_id)
            continue

        summary = await build_summary(db, guild_id, yesterday)
        if summary is None:
            # Nobody played. Still mark it, so we do not retry all day.
            db.mark_summary_posted(guild_id, yesterday)
            continue

        text, image = summary
        try:
            await channel.send(content=text, file=image)
            db.mark_summary_posted(guild_id, yesterday)
            log.info('Испратен дневен преглед за серверот %s (загатка #%s)', guild_id, yesterday)
        except discord.HTTPException:
            log.exception('Неуспешно испраќање преглед за серверот %s', guild_id)
