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
