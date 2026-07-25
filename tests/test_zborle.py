"""Tests. Run with: .venv/bin/python -m pytest -q"""

import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zborle_bot import words  # noqa: E402
from zborle_bot.board import Game, Status, score_guess  # noqa: E402
from zborle_bot.db import IN_PROGRESS, LOST, WON, ZborleDB  # noqa: E402
from zborle_bot.words import GuessError, clean_guess  # noqa: E402

JS_EPOCH_MS = 1640995200000
MS_IN_DAY = 86400000


def js_puzzle_index(moment: datetime) -> int:
    """Literal port of zborle.mk's `Math.floor((now - EPOCH - tzOffset) / DAY) % len`."""
    moment = moment.astimezone(words.TIMEZONE)
    now_ms = moment.timestamp() * 1000
    # JS getTimezoneOffset() is the negation of the UTC offset, in minutes.
    offset_ms = -moment.utcoffset().total_seconds() * 1000
    return math.floor((now_ms - JS_EPOCH_MS - offset_ms) / MS_IN_DAY) % len(words.ANSWERS)


def test_word_lists_are_well_formed():
    assert len(words.ANSWERS) == 964
    assert all(len(word) == 5 for word in words.ANSWERS)
    assert set(words.ANSWERS) <= words.VALID_GUESSES
    assert len(set(words.ANSWERS)) == len(words.ANSWERS)


def test_every_answer_uses_only_macedonian_letters():
    from zborle_bot.config import MK_ALPHABET
    for word in words.ANSWERS:
        assert set(word.upper()) <= MK_ALPHABET, word


def test_puzzle_index_matches_the_live_site_formula():
    """Cover two full years hourly, which includes every DST transition in that span."""
    moment = datetime(2025, 1, 1, tzinfo=words.TIMEZONE)
    end = datetime(2027, 1, 1, tzinfo=words.TIMEZONE)
    while moment < end:
        assert words.puzzle_index(moment) == js_puzzle_index(moment), moment
        moment += timedelta(hours=1)


def test_index_advances_once_per_local_day():
    a = datetime(2026, 7, 24, 23, 59, tzinfo=words.TIMEZONE)
    b = datetime(2026, 7, 25, 0, 1, tzinfo=words.TIMEZONE)
    assert words.puzzle_index(b) == (words.puzzle_index(a) + 1) % len(words.ANSWERS)


def test_epoch_day_is_index_zero():
    assert words.puzzle_index(datetime(2022, 1, 1, 12, tzinfo=words.TIMEZONE)) == 0
    assert words.word_of_day(0) == 'ОТПАД'


def zborle_guess_statuses(guess: str, solution: str) -> list[Status]:
    """Direct port of zborle.mk's getGuessStatuses, used as the reference implementation."""
    taken = [False] * len(solution)
    statuses: list[Status | None] = [None] * len(guess)

    for i, letter in enumerate(guess):
        if letter == solution[i]:
            statuses[i] = Status.CORRECT
            taken[i] = True

    for i, letter in enumerate(guess):
        if statuses[i] is not None:
            continue
        if letter not in solution:
            statuses[i] = Status.ABSENT
            continue
        index = next((j for j, c in enumerate(solution) if c == letter and not taken[j]), -1)
        if index > -1:
            statuses[i] = Status.PRESENT
            taken[index] = True
        else:
            statuses[i] = Status.ABSENT

    return statuses


def test_scoring_duplicate_letters():
    # Solution has one А, guess has two: the first gets yellow, the second grey.
    assert score_guess('АБАЖУ', 'ОТПАД') == [
        Status.PRESENT, Status.ABSENT, Status.ABSENT, Status.ABSENT, Status.ABSENT
    ]
    # A positional match claims the letter before any yellow can.
    assert score_guess('АТПАД', 'ОТПАД') == [
        Status.ABSENT, Status.CORRECT, Status.CORRECT, Status.CORRECT, Status.CORRECT
    ]


def test_scoring_matches_zborle_reference():
    import random

    rng = random.Random(20260724)
    pool = [word.upper() for word in words.ANSWERS]
    for _ in range(20000):
        guess, solution = rng.choice(pool), rng.choice(pool)
        assert score_guess(guess, solution) == zborle_guess_statuses(guess, solution), (guess, solution)


def test_scoring_marks_present_letters():
    assert score_guess('РОБОТ', 'РОБОТ') == [Status.CORRECT] * 5
    statuses = score_guess('ТОБОР', 'РОБОТ')
    assert statuses[0] is Status.PRESENT
    assert statuses[1] is Status.CORRECT
    assert statuses[4] is Status.PRESENT


def test_clean_guess_rejects_bad_input():
    for bad, fragment in [
        ('отпа', 'точно 5 букви'),
        ('otpad', 'кирилица'),
        ('ттттт', 'не е во речникот'),
    ]:
        try:
            clean_guess(bad)
        except GuessError as error:
            assert fragment in str(error), (bad, error)
        else:
            raise AssertionError(f'{bad!r} should have been rejected')


def test_clean_guess_normalizes_case_and_accents():
    assert clean_guess('  отпад  ') == 'ОТПАД'
    assert clean_guess('ѝдења') == clean_guess('идења')


def test_game_win_and_loss():
    game = Game('РОБОТ')
    game.add_guess('отпад')
    assert not game.is_over
    assert game.guesses_left == 5
    game.add_guess('робот')
    assert game.is_won and game.is_over

    lost = Game('РОБОТ', ['ОТПАД', 'КРЕМА', 'ЖЕНКА', 'ТУТУН', 'ЛЕКАР'])
    lost.add_guess('ефект')
    assert lost.is_lost and not lost.is_won


def test_game_rejects_repeat_and_post_game_guesses():
    game = Game('РОБОТ', ['ОТПАД'])
    for bad in ['отпад', 'ОТПАД']:
        try:
            game.add_guess(bad)
        except GuessError as error:
            assert 'Веќе' in str(error)
        else:
            raise AssertionError('repeat guess should be rejected')

    game.add_guess('робот')
    try:
        game.add_guess('крема')
    except GuessError as error:
        assert 'завршена' in str(error)
    else:
        raise AssertionError('post-game guess should be rejected')


def test_share_text_shape():
    game = Game('РОБОТ', ['ОТПАД', 'РОБОТ'])
    text = game.share_text(701)
    assert text.startswith('Зборле 701 2/6')
    assert '🟩🟩🟩🟩🟩' in text
    assert Game('РОБОТ', ['ОТПАД'] * 6).share_text(701).startswith('Зборле 701 X/6')


def test_render_produces_a_png():
    data = Game('РОБОТ', ['ОТПАД', 'КРЕМА']).render()
    assert data.startswith(b'\x89PNG')
    assert len(data) > 1000


def test_db_roundtrip_and_stats(tmp_path):
    db = ZborleDB(tmp_path / 'test.db')

    db.save(1, 100, ['ОТПАД', 'РОБОТ'], WON)
    assert db.load_guesses(1, 100) == ['ОТПАД', 'РОБОТ']
    assert db.load_guesses(1, 999) == []
    assert db.load_guesses(2, 100) == []

    # Overwriting the same (user, puzzle) updates rather than duplicating.
    db.save(1, 100, ['ОТПАД', 'КРЕМА', 'РОБОТ'], WON)
    assert db.load_guesses(1, 100) == ['ОТПАД', 'КРЕМА', 'РОБОТ']

    db.save(1, 101, ['ОТПАД'], LOST)
    db.save(1, 102, ['ОТПАД', 'РОБОТ'], WON)
    db.save(1, 103, ['ОТПАД'], IN_PROGRESS)  # unfinished games are excluded

    stats = db.stats(1)
    assert stats.played == 3
    assert stats.won == 2
    assert stats.win_percent == 67
    assert stats.current_streak == 1  # 102 won, 101 lost breaks it
    assert stats.max_streak == 1
    assert stats.distribution == {3: 1, 2: 1}
    db.close()


def test_streak_breaks_on_a_skipped_day(tmp_path):
    db = ZborleDB(tmp_path / 'streak.db')
    for index in (200, 201, 202):
        db.save(7, index, ['РОБОТ'], WON)
    db.save(7, 205, ['РОБОТ'], WON)  # gap at 203-204

    stats = db.stats(7)
    assert stats.current_streak == 1
    assert stats.max_streak == 3
    db.close()
