"""Word lists and the daily-word schedule.

The puzzle index reproduces zborle.mk exactly. The deployed site computes:

    index = Math.floor((Date.now() - 1640995200000 - tzOffsetMs) / 86400000) % WORDS.length

where ``tzOffsetMs`` is ``new Date().getTimezoneOffset() * 60000``. Subtracting the
timezone offset shifts the epoch millisecond count onto the viewer's wall clock, so the
expression collapses to "whole local days elapsed since 2022-01-01". Working in local
dates instead of milliseconds gives the same answer and stays correct across DST shifts.

The site derives the index from each visitor's own timezone; we pin it to Europe/Skopje
so the bot agrees with players in North Macedonia.
"""

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import ANSWERS_PATH, GUESSES_PATH, MK_ALPHABET, WORD_LENGTH

EPOCH = date(2022, 1, 1)
TIMEZONE = ZoneInfo(os.getenv('ZBORLE_TIMEZONE', 'Europe/Skopje'))


def _load(path):
    with open(path, encoding='utf-8') as handle:
        return [line.strip() for line in handle if line.strip()]


# Order is load-bearing: the daily word is looked up by position in this list.
ANSWERS = tuple(_load(ANSWERS_PATH))
VALID_GUESSES = frozenset(_load(GUESSES_PATH))


class GuessError(ValueError):
    """A guess the player can fix, carrying a message already written in Macedonian."""


def today(now: datetime | None = None) -> date:
    now = now or datetime.now(TIMEZONE)
    return now.astimezone(TIMEZONE).date()


def puzzle_index(now: datetime | None = None) -> int:
    return (today(now) - EPOCH).days % len(ANSWERS)


def word_of_day(index: int | None = None) -> str:
    if index is None:
        index = puzzle_index()
    return ANSWERS[index % len(ANSWERS)].upper()


def time_until_next_word(now: datetime | None = None) -> timedelta:
    """Time left until the word rolls over at local midnight."""
    now = (now or datetime.now(TIMEZONE)).astimezone(TIMEZONE)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), TIMEZONE)
    return tomorrow - now


def format_countdown(delta: timedelta) -> str:
    total = max(0, int(delta.total_seconds()))
    return f'{total // 3600}ч {total % 3600 // 60}м'


def clean_guess(raw: str) -> str:
    """Normalize and validate a guess, raising GuessError with a player-facing message."""
    # ѐ and ѝ are written in Macedonian to disambiguate homographs, but never appear in
    # the word lists, so fold them onto their bare vowels rather than rejecting them.
    guess = raw.strip().translate(str.maketrans('ѐѝЀЍ', 'еиЕИ')).upper()

    if len(guess) != WORD_LENGTH:
        raise GuessError(f'Зборот мора да има точно {WORD_LENGTH} букви, а „{raw.strip()}“ има {len(guess)}.')

    unknown = [char for char in guess if char not in MK_ALPHABET]
    if unknown:
        raise GuessError(
            f'Зборот мора да биде напишан на македонска кирилица. Непознати знаци: {" ".join(unknown)}'
        )

    if guess.lower() not in VALID_GUESSES:
        raise GuessError(f'„{guess}“ не е во речникот.')

    return guess
