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
