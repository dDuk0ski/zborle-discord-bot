"""SQLite persistence.

Only the guesses are stored -- tile colors, win state and stats all derive from
``guesses + solution``, so there is nothing to keep in sync. Games are keyed by
(user, puzzle) rather than by guild, so a player gets one attempt at each day's
word no matter which server they play from.
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import DB_PATH, MAX_GUESSES

IN_PROGRESS = 'in_progress'
WON = 'won'
LOST = 'lost'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS games (
    user_id      INTEGER NOT NULL,
    puzzle_index INTEGER NOT NULL,
    guesses      TEXT    NOT NULL DEFAULT '',
    status       TEXT    NOT NULL DEFAULT 'in_progress',
    updated_at   TEXT    NOT NULL,
    PRIMARY KEY (user_id, puzzle_index)
);
CREATE INDEX IF NOT EXISTS games_by_user ON games (user_id, puzzle_index DESC);

-- Who belongs on which server's leaderboard.
--
-- Reading a guild's real member list needs the privileged Server Members intent, which
-- this app deliberately does not request. Instead a player joins a server's board the
-- first time they actually play there, via a slash command or by launching the Activity.
-- Games themselves stay global: one puzzle per person per day, ranked in every server
-- they have played in.
CREATE TABLE IF NOT EXISTS guild_players (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    display_name TEXT    NOT NULL DEFAULT '',
    avatar_url   TEXT,
    last_seen    TEXT    NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS guild_players_by_guild ON guild_players (guild_id);

-- Live Activity sessions, one row per Discord activity instance.
--
-- The message id is persisted rather than held in memory so a redeploy mid-game keeps
-- editing the same message instead of orphaning it and posting a duplicate.
CREATE TABLE IF NOT EXISTS sessions (
    instance_id  TEXT    NOT NULL PRIMARY KEY,
    guild_id     INTEGER,
    channel_id   INTEGER,
    message_id   INTEGER,
    puzzle_index INTEGER NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS session_players (
    instance_id TEXT    NOT NULL,
    user_id     INTEGER NOT NULL,
    joined_at   TEXT    NOT NULL,
    PRIMARY KEY (instance_id, user_id)
);
CREATE INDEX IF NOT EXISTS session_players_by_instance ON session_players (instance_id);

-- Per-server settings. Only the daily summary channel for now.
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id           INTEGER NOT NULL PRIMARY KEY,
    summary_channel_id INTEGER,
    last_summary_index INTEGER
);
'''


@dataclass
class Stats:
    played: int = 0
    won: int = 0
    current_streak: int = 0
    max_streak: int = 0
    distribution: dict[int, int] = field(default_factory=dict)

    @property
    def win_percent(self) -> int:
        return round(100 * self.won / self.played) if self.played else 0


class ZborleDB:
    def __init__(self, path=DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def load_guesses(self, user_id: int, puzzle_index: int) -> list[str]:
        row = self.conn.execute(
            'SELECT guesses FROM games WHERE user_id = ? AND puzzle_index = ?',
            (user_id, puzzle_index),
        ).fetchone()
        if row is None or not row['guesses']:
            return []
        return row['guesses'].split(',')

    def save(self, user_id: int, puzzle_index: int, guesses: list[str], status: str) -> None:
        self.conn.execute(
            '''INSERT INTO games (user_id, puzzle_index, guesses, status, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (user_id, puzzle_index)
               DO UPDATE SET guesses = excluded.guesses,
                             status = excluded.status,
                             updated_at = excluded.updated_at''',
            (
                user_id,
                puzzle_index,
                ','.join(guesses),
                status,
                datetime.now(timezone.utc).isoformat(timespec='seconds'),
            ),
        )
        self.conn.commit()

    def stats(self, user_id: int) -> Stats:
        rows = self.conn.execute(
            '''SELECT puzzle_index, guesses, status FROM games
               WHERE user_id = ? AND status != ?
               ORDER BY puzzle_index DESC''',
            (user_id, IN_PROGRESS),
        ).fetchall()

        stats = Stats(played=len(rows))
        for row in rows:
            if row['status'] == WON:
                stats.won += 1
                score = len(row['guesses'].split(','))
                stats.distribution[score] = stats.distribution.get(score, 0) + 1

        # Rows are newest-first. The current streak runs back from the most recent
        # finished puzzle and breaks on a loss or a skipped day.
        streak = 0
        expected = None
        for row in rows:
            if row['status'] != WON or (expected is not None and row['puzzle_index'] != expected):
                break
            streak += 1
            expected = row['puzzle_index'] - 1
        stats.current_streak = streak

        best = current = 0
        expected = None
        for row in reversed(rows):
            if row['status'] == WON and (expected is None or row['puzzle_index'] == expected):
                current += 1
            elif row['status'] == WON:
                current = 1
            else:
                current = 0
            best = max(best, current)
            expected = row['puzzle_index'] + 1
        stats.max_streak = best

        return stats

    def distribution_rows(self, stats: Stats) -> list[tuple[int, int]]:
        return [(score, stats.distribution.get(score, 0)) for score in range(1, MAX_GUESSES + 1)]

    def remember_player(
        self, guild_id: int, user_id: int, display_name: str, avatar_url: str | None
    ) -> None:
        """Note that a player is active in a server, refreshing their name and avatar."""
        self.conn.execute(
            '''INSERT INTO guild_players (guild_id, user_id, display_name, avatar_url, last_seen)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (guild_id, user_id)
               DO UPDATE SET display_name = excluded.display_name,
                             avatar_url = excluded.avatar_url,
                             last_seen = excluded.last_seen''',
            (
                guild_id,
                user_id,
                display_name,
                avatar_url,
                datetime.now(timezone.utc).isoformat(timespec='seconds'),
            ),
        )
        self.conn.commit()

    def leaderboard(self, guild_id: int) -> list[dict]:
        """Rank a server's players.

        Stats are computed per player with the same tested code the bot uses, rather than
        reimplemented as one big aggregate query, because streaks need ordered traversal
        and duplicating that logic in SQL is how the two would drift apart.
        """
        members = self.conn.execute(
            '''SELECT user_id, display_name, avatar_url FROM guild_players
               WHERE guild_id = ?''',
            (guild_id,),
        ).fetchall()

        rows = []
        for member in members:
            stats = self.stats(member['user_id'])
            if not stats.played:
                continue
            total_guesses = sum(score * count for score, count in stats.distribution.items())
            rows.append(
                {
                    'userId': str(member['user_id']),
                    'displayName': member['display_name'] or 'Играч',
                    'avatarUrl': member['avatar_url'],
                    'played': stats.played,
                    'won': stats.won,
                    'winPercent': stats.win_percent,
                    'currentStreak': stats.current_streak,
                    'maxStreak': stats.max_streak,
                    'averageGuesses': round(total_guesses / stats.won, 2) if stats.won else None,
                }
            )

        # Most wins first; ties broken by fewer average guesses, then longer streak.
        rows.sort(
            key=lambda row: (
                -row['won'],
                row['averageGuesses'] if row['averageGuesses'] is not None else 99,
                -row['currentStreak'],
            )
        )
        return rows


    # ---- Live session support ----

    def join_session(
        self, instance_id: str, guild_id: int | None, channel_id: int | None, puzzle_index: int, user_id: int
    ) -> bool:
        """Register a player in an activity instance. True if they were not already in it."""
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        self.conn.execute(
            '''INSERT INTO sessions (instance_id, guild_id, channel_id, puzzle_index, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (instance_id) DO UPDATE SET
                 channel_id = COALESCE(excluded.channel_id, sessions.channel_id),
                 guild_id = COALESCE(excluded.guild_id, sessions.guild_id),
                 updated_at = excluded.updated_at''',
            (instance_id, guild_id, channel_id, puzzle_index, now),
        )
        cursor = self.conn.execute(
            '''INSERT INTO session_players (instance_id, user_id, joined_at) VALUES (?, ?, ?)
               ON CONFLICT (instance_id, user_id) DO NOTHING''',
            (instance_id, user_id, now),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def session(self, instance_id: str) -> dict | None:
        row = self.conn.execute('SELECT * FROM sessions WHERE instance_id = ?', (instance_id,)).fetchone()
        return dict(row) if row else None

    def set_session_message(self, instance_id: str, message_id: int) -> None:
        self.conn.execute(
            'UPDATE sessions SET message_id = ? WHERE instance_id = ?', (message_id, instance_id)
        )
        self.conn.commit()

    def session_boards(self, instance_id: str) -> list[dict]:
        """Every player in an instance with their board for that instance's puzzle.

        Ordered by join time so cards do not reshuffle between edits, which would make
        the message look like it is flickering.
        """
        session = self.session(instance_id)
        if session is None:
            return []

        rows = self.conn.execute(
            '''SELECT sp.user_id, sp.joined_at, g.guesses, g.status
               FROM session_players sp
               LEFT JOIN games g
                 ON g.user_id = sp.user_id AND g.puzzle_index = ?
               WHERE sp.instance_id = ?
               ORDER BY sp.joined_at, sp.user_id''',
            (session['puzzle_index'], instance_id),
        ).fetchall()

        boards = []
        for row in rows:
            names = self.conn.execute(
                '''SELECT display_name, avatar_url FROM guild_players
                   WHERE user_id = ? ORDER BY last_seen DESC LIMIT 1''',
                (row['user_id'],),
            ).fetchone()
            boards.append(
                {
                    'userId': str(row['user_id']),
                    'displayName': (names['display_name'] if names else '') or 'Играч',
                    'avatarUrl': names['avatar_url'] if names else None,
                    'guesses': row['guesses'].split(',') if row['guesses'] else [],
                    'status': row['status'],
                }
            )
        return boards

    def stale_sessions(self, older_than_index: int) -> list[str]:
        rows = self.conn.execute(
            'SELECT instance_id FROM sessions WHERE puzzle_index < ?', (older_than_index,)
        ).fetchall()
        return [row['instance_id'] for row in rows]

    def drop_session(self, instance_id: str) -> None:
        self.conn.execute('DELETE FROM session_players WHERE instance_id = ?', (instance_id,))
        self.conn.execute('DELETE FROM sessions WHERE instance_id = ?', (instance_id,))
        self.conn.commit()

    # ---- Daily summary support ----

    def remember_play_channel(self, guild_id: int, channel_id: int) -> None:
        """Adopt the channel people actually play in, unless one was chosen explicitly.

        Official Wordle needs no setup: it posts where the game is happening. This makes
        the daily summary work with zero commands, while an explicit /преглед still wins.
        """
        self.conn.execute(
            '''INSERT INTO guild_config (guild_id, summary_channel_id) VALUES (?, ?)
               ON CONFLICT (guild_id) DO UPDATE SET
                 summary_channel_id = COALESCE(guild_config.summary_channel_id, excluded.summary_channel_id)''',
            (guild_id, channel_id),
        )
        self.conn.commit()

    def set_summary_channel(self, guild_id: int, channel_id: int | None) -> None:
        self.conn.execute(
            '''INSERT INTO guild_config (guild_id, summary_channel_id) VALUES (?, ?)
               ON CONFLICT (guild_id) DO UPDATE SET summary_channel_id = excluded.summary_channel_id''',
            (guild_id, channel_id),
        )
        self.conn.commit()

    def summary_channel(self, guild_id: int) -> int | None:
        row = self.conn.execute(
            'SELECT summary_channel_id FROM guild_config WHERE guild_id = ?', (guild_id,)
        ).fetchone()
        return row['summary_channel_id'] if row else None

    def guilds_with_summary(self) -> list[tuple[int, int, int | None]]:
        rows = self.conn.execute(
            '''SELECT guild_id, summary_channel_id, last_summary_index FROM guild_config
               WHERE summary_channel_id IS NOT NULL'''
        ).fetchall()
        return [(r['guild_id'], r['summary_channel_id'], r['last_summary_index']) for r in rows]

    def mark_summary_posted(self, guild_id: int, puzzle_index: int) -> None:
        """Record the last summary posted, so a restart cannot double-post."""
        self.conn.execute(
            'UPDATE guild_config SET last_summary_index = ? WHERE guild_id = ?',
            (puzzle_index, guild_id),
        )
        self.conn.commit()

    def guild_results(self, guild_id: int, puzzle_index: int) -> list[dict]:
        """Everyone on this server who finished a given day's puzzle, best score first."""
        rows = self.conn.execute(
            '''SELECT p.user_id, p.display_name, p.avatar_url, g.guesses, g.status
               FROM guild_players p
               JOIN games g ON g.user_id = p.user_id
               WHERE p.guild_id = ? AND g.puzzle_index = ? AND g.status != ?''',
            (guild_id, puzzle_index, IN_PROGRESS),
        ).fetchall()

        results = [
            {
                'userId': str(row['user_id']),
                'displayName': row['display_name'] or 'Играч',
                'avatarUrl': row['avatar_url'],
                'guesses': row['guesses'].split(',') if row['guesses'] else [],
                'won': row['status'] == WON,
                'score': len(row['guesses'].split(',')) if row['status'] == WON else None,
            }
            for row in rows
        ]
        # Winners first, fewest guesses first; players who lost go last.
        results.sort(key=lambda r: (r['score'] is None, r['score'] or 0))
        return results

    def group_streak(self, guild_id: int, up_to_index: int) -> int:
        """Consecutive days ending at up_to_index where somebody here finished the puzzle.

        A shared streak that survives as long as one person keeps playing, which is what
        makes it a group streak rather than everyone's individual streak intersected.
        """
        rows = self.conn.execute(
            '''SELECT DISTINCT g.puzzle_index FROM games g
               JOIN guild_players p ON p.user_id = g.user_id
               WHERE p.guild_id = ? AND g.puzzle_index <= ? AND g.status != ?
               ORDER BY g.puzzle_index DESC''',
            (guild_id, up_to_index, IN_PROGRESS),
        ).fetchall()

        streak = 0
        expected = up_to_index
        for row in rows:
            if row['puzzle_index'] != expected:
                break
            streak += 1
            expected -= 1
        return streak


_shared: ZborleDB | None = None


def shared_db() -> ZborleDB:
    """One connection for the whole process.

    The bot and the Activity's web server run in the same asyncio loop and must see the
    same rows, so they share this instance rather than opening the database twice.
    """
    global _shared
    if _shared is None:
        _shared = ZborleDB()
    return _shared
