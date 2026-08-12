"""Discord client and slash commands."""

import io
import logging
import os

import discord
from discord import app_commands
from discord.ext import tasks
from discord.utils import MISSING

from . import config, words
from .board import Game
from .daily import post_due_summaries
from .db import IN_PROGRESS, LOST, WON, shared_db
from .words import GuessError

log = logging.getLogger(__name__)

# Discord's PRIMARY_ENTRY_POINT application command type, created automatically when
# Activities are enabled. discord.py 2.7's AppCommandType does not include it.
ENTRY_POINT_COMMAND_TYPE = 4

EMBED_COLOR = discord.Color.from_str(config.COLOR_CORRECT)
EMBED_COLOR_LOST = discord.Color.from_str(config.COLOR_ABSENT)

HELP_TEXT = (
    'Погоди го скриениот петбуквен македонски збор за 6 обиди.\n\n'
    '🟩 - буквата е точна и е на точно место\n'
    '🟨 - буквата ја има во зборот, но на друго место\n'
    '⬜ - буквата ја нема во зборот\n\n'
    '**Команди**\n'
    '`/зборле збор:<збор>` - направи обид\n'
    '`/табла` - прикажи ја твојата табла\n'
    '`/сподели` - сподели го резултатот во каналот\n'
    '`/статистика` - твојата статистика\n'
    '`/помош` - оваа порака\n\n'
    'Зборовите се пишуваат на македонска кирилица. Секој играч има своја табла, '
    'а зборот е ист за сите и се менува во полноќ по скопско време - истиот што е '
    'на https://zborle.mk'
)


class ZborleClient(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.db = shared_db()

    async def setup_hook(self) -> None:
        # A sync failure must not take the process down. setup_hook runs inside
        # Client.start(), so raising here kills the bot and, because both run under one
        # asyncio.gather, the Activity's web server with it.
        try:
            await self._sync_commands()
        except Exception:
            log.exception('Синхронизацијата на командите не успеа; ботот продолжува со постоечките')

    async def _sync_commands(self) -> None:
        dev_guild = os.getenv('DEV_GUILD_ID')
        if dev_guild:
            # Guild-scoped commands appear instantly; global ones can take up to an hour.
            guild = discord.Object(id=int(dev_guild))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info('Синхронизирани команди за тест-серверот %s', dev_guild)
        else:
            await self._sync_global_preserving_entry_point()

    async def _sync_global_preserving_entry_point(self) -> None:
        """Bulk-upsert our commands without deleting the Activity's entry point.

        Enabling Activities makes Discord create a type-4 "launch" command that we do not
        own and cannot rebuild from the tree. A plain tree.sync() bulk-overwrites the
        global command list, which would remove it, and Discord rejects the whole request
        with error 50240. discord.py 2.7 has no concept of entry-point commands, so we
        carry the existing one through by hand.
        """
        application_id = self.application_id
        assert application_id is not None

        existing = await self.http.get_global_commands(application_id)
        preserved = [command for command in existing if command.get('type') == ENTRY_POINT_COMMAND_TYPE]

        payload = [command.to_dict(self.tree) for command in self.tree.get_commands()]
        await self.http.bulk_upsert_global_commands(application_id, payload=payload + preserved)

        log.info(
            'Синхронизирани %s глобални команди (задржани %s entry point)',
            len(payload),
            len(preserved),
        )

    async def close(self) -> None:
        self.db.close()
        await super().close()


client = ZborleClient()


def load_game(user_id: int) -> tuple[int, Game]:
    index = words.puzzle_index()
    solution = words.word_of_day(index)
    return index, Game(solution, client.db.load_guesses(user_id, index))


def board_file(game: Game) -> discord.File:
    return discord.File(io.BytesIO(game.render()), filename='zborle.png')


def base_embed(index: int, game: Game) -> discord.Embed:
    embed = discord.Embed(
        title=f'Зборле #{index}',
        color=EMBED_COLOR_LOST if game.is_lost else EMBED_COLOR,
    )
    embed.set_image(url='attachment://zborle.png')
    return embed


def remember_player(interaction: discord.Interaction) -> None:
    """Enroll the player on this server's leaderboard.

    Playing is what puts someone on a board. Reading the actual member list would need
    the privileged Server Members intent, which this bot deliberately does not request.
    """
    if not interaction.guild_id:
        return
    client.db.remember_player(
        interaction.guild_id,
        interaction.user.id,
        interaction.user.display_name,
        interaction.user.display_avatar.url if interaction.user.display_avatar else None,
    )


def countdown_note() -> str:
    return f'Следниот збор за {words.format_countdown(words.time_until_next_word())}.'


@tasks.loop(minutes=10)
async def daily_summary_task() -> None:
    """Post yesterday's summary once the day has rolled over.

    Polls rather than sleeping until midnight: a restart at the wrong moment would
    otherwise skip a day entirely. `last_summary_index` in the database is what actually
    prevents double-posting, so running this often is harmless.
    """
    try:
        await post_due_summaries(client, client.db)
    except Exception:
        log.exception('Дневниот преглед не успеа')


@daily_summary_task.before_loop
async def _before_daily_summary() -> None:
    await client.wait_until_ready()


@client.event
async def on_ready() -> None:
    log.info('Најавен како %s (id %s)', client.user, client.user.id)
    log.info('Денешен збор: #%s', words.puzzle_index())
    if not daily_summary_task.is_running():
        daily_summary_task.start()


@client.tree.command(name='зборле', description='Направи обид за денешниот збор')
@app_commands.rename(word='збор')
@app_commands.describe(word='Петбуквен збор на македонска кирилица')
async def guess_command(interaction: discord.Interaction, word: str) -> None:
    # Defer up front: rendering and uploading the PNG can outlast Discord's 3s deadline.
    await interaction.response.defer(ephemeral=True)
    remember_player(interaction)
    index, game = load_game(interaction.user.id)

    if game.is_over:
        await interaction.followup.send(
            f'Веќе ја заврши денешната загатка. Види ја таблата со `/табла`. {countdown_note()}',
            ephemeral=True,
        )
        return

    try:
        game.add_guess(word)
    except GuessError as error:
        await interaction.followup.send(f'⚠️ {error}', ephemeral=True)
        return

    status = WON if game.is_won else LOST if game.is_lost else IN_PROGRESS
    client.db.save(interaction.user.id, index, game.guesses, status)

    embed = base_embed(index, game)
    if game.is_won:
        embed.description = (
            f'🎉 Браво! Го погоди за {len(game.guesses)}/{config.MAX_GUESSES}.\n'
            f'Сподели со `/сподели`. {countdown_note()}'
        )
    elif game.is_lost:
        embed.description = f'😔 Обидите завршија. Зборот беше **{game.solution}**.\n{countdown_note()}'
    else:
        embed.description = f'Преостанати обиди: {game.guesses_left}'

    await interaction.followup.send(embed=embed, file=board_file(game), ephemeral=True)


@client.tree.command(name='табла', description='Прикажи ја твојата денешна табла')
async def board_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    index, game = load_game(interaction.user.id)

    if not game.guesses:
        await interaction.followup.send(
            f'Сè уште немаш ниту еден обид за Зборле #{index}. Почни со `/зборле`.',
            ephemeral=True,
        )
        return

    embed = base_embed(index, game)
    if game.is_won:
        embed.description = f'Погодено за {len(game.guesses)}/{config.MAX_GUESSES}. {countdown_note()}'
    elif game.is_lost:
        embed.description = f'Зборот беше **{game.solution}**. {countdown_note()}'
    else:
        embed.description = f'Преостанати обиди: {game.guesses_left}'

    await interaction.followup.send(embed=embed, file=board_file(game), ephemeral=True)


@client.tree.command(name='сподели', description='Сподели го денешниот резултат во каналот')
async def share_command(interaction: discord.Interaction) -> None:
    index, game = load_game(interaction.user.id)

    if not game.is_over:
        await interaction.response.send_message(
            'Можеш да споделиш дури откако ќе ја завршиш денешната загатка.',
            ephemeral=True,
        )
        return

    # Public on purpose: the emoji grid is the whole point of sharing. It leaks no letters.
    await interaction.response.send_message(
        f'{interaction.user.mention}\n{game.share_text(index)}'
    )


@client.tree.command(name='статистика', description='Твојата статистика')
async def stats_command(interaction: discord.Interaction) -> None:
    stats = client.db.stats(interaction.user.id)

    if not stats.played:
        await interaction.response.send_message(
            'Сè уште немаш завршена загатка. Почни со `/зборле`.', ephemeral=True
        )
        return

    embed = discord.Embed(title=f'Статистика - {interaction.user.display_name}', color=EMBED_COLOR)
    embed.add_field(name='Одиграни', value=str(stats.played))
    embed.add_field(name='Успешност', value=f'{stats.win_percent}%')
    embed.add_field(name='Серија', value=f'{stats.current_streak} (најдолга {stats.max_streak})')

    rows = client.db.distribution_rows(stats)
    peak = max((count for _, count in rows), default=0)
    lines = []
    for score, count in rows:
        bar = '█' * max(1, round(12 * count / peak)) if count else ''
        lines.append(f'{score} {bar} {count}')
    embed.add_field(name='Распределба на обиди', value='```\n' + '\n'.join(lines) + '\n```', inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.command(name='преглед', description='Постави го каналот за дневниот преглед')
@app_commands.rename(channel='канал')
@app_commands.describe(channel='Каналот во кој да се објавува дневниот преглед. Празно за исклучување.')
# Deliberately ungated. default_permissions(manage_guild=True) hides the command outright
# from members without Manage Server, so it does not even autocomplete for them, which
# made it unusable in servers where players are not admins. The worst case here is one
# misdirected message a day.
#
# The union matters: annotating only TextChannel makes discord.py refuse announcement
# channels, forums and threads outright, raising before the command body ever runs.
async def summary_channel_command(
    interaction: discord.Interaction,
    channel: discord.TextChannel | discord.Thread | None = None,
) -> None:
    if not interaction.guild_id:
        await interaction.response.send_message('Оваа команда работи само на сервер.', ephemeral=True)
        return

    client.db.set_summary_channel(interaction.guild_id, channel.id if channel else None)
    message = (
        f'Дневниот преглед ќе се објавува во {channel.mention}.'
        if channel
        else 'Дневниот преглед е исклучен.'
    )
    await interaction.response.send_message(message, ephemeral=True)


@client.tree.command(name='помош', description='Правила и команди')
async def help_command(interaction: discord.Interaction) -> None:
    embed = discord.Embed(title='Зборле - помош', description=HELP_TEXT, color=EMBED_COLOR)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.error
async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    log.exception('Грешка во командата %s', interaction.command and interaction.command.name, exc_info=error)
    message = 'Се случи неочекувана грешка. Обиди се повторно.'
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def run() -> None:
    token = os.getenv('BOT_TOKEN')
    if not token:
        raise SystemExit('BOT_TOKEN не е поставен. Копирај .env.example во .env и внеси го токенот.')

    # Default to stderr so container platforms capture the output. Set ZBORLE_LOG_FILE
    # to also write to disk when running locally.
    handler = MISSING
    log_file = os.getenv('ZBORLE_LOG_FILE')
    if log_file:
        directory = os.path.dirname(log_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        handler = logging.FileHandler(filename=log_file, encoding='utf-8', mode='a')

    # root_logger=True is required, otherwise the handler is attached only to discord.py's
    # own logger and every log call in this module is silently discarded.
    client.run(token, log_handler=handler, log_level=logging.INFO, root_logger=True)
