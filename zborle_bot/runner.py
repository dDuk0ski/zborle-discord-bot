"""Runs the Discord bot and the Activity's web server in one process.

They share an asyncio loop, and more importantly one SQLite file: Fly volumes attach to
a single machine, so splitting these into separate machines would split the database and
with it the leaderboard and streaks.
"""

import asyncio
import logging
import os

import uvicorn
from discord.utils import MISSING, setup_logging

from .bot import client
from .web import app

log = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Mirror what Client.run() would have set up, since we call start() instead."""
    handler = MISSING
    log_file = os.getenv('ZBORLE_LOG_FILE')
    if log_file:
        directory = os.path.dirname(log_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        handler = logging.FileHandler(filename=log_file, encoding='utf-8', mode='a')

    setup_logging(handler=handler, level=logging.INFO, root=True)


async def _serve_web(port: int) -> None:
    config = uvicorn.Config(app, host='0.0.0.0', port=port, log_level='info', access_log=False)
    await uvicorn.Server(config).serve()


async def _amain(token: str, port: int) -> None:
    # gather() so either task failing propagates instead of silently leaving half the
    # process running: a live web server with a dead bot looks healthy to Fly.
    await asyncio.gather(_serve_web(port), client.start(token))


def run() -> None:
    token = os.getenv('BOT_TOKEN')
    if not token:
        raise SystemExit('BOT_TOKEN не е поставен. Копирај .env.example во .env и внеси го токенот.')

    _configure_logging()
    port = int(os.getenv('PORT', '8080'))
    log.info('Стартувам бот и веб-сервер на порта %s', port)

    try:
        asyncio.run(_amain(token, port))
    except KeyboardInterrupt:
        pass
