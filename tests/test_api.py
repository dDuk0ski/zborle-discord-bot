"""Activity API tests. Run with: .venv/bin/python -m pytest -q"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient with a throwaway database and auth stubbed to a fixed user."""
    monkeypatch.setenv('ZBORLE_DB_PATH', str(tmp_path / 'api.db'))

    # Import inside the fixture so config picks up the patched DB path.
    for module in [m for m in list(sys.modules) if m.startswith('zborle_bot')]:
        del sys.modules[module]

    from fastapi.testclient import TestClient

    from zborle_bot.auth import DiscordUser, current_user
    from zborle_bot.web import app

    app.dependency_overrides[current_user] = lambda: DiscordUser(
        id='4242', username='tester', display_name='Tester', avatar_url=None
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def solution():
    from zborle_bot import words

    return words.word_of_day()


def test_health_reports_schedule(client):
    body = client.get('/api/health').json()
    assert body['status'] == 'ok'
    assert isinstance(body['puzzle_index'], int)
    assert 0 < body['seconds_until_next'] <= 86400


def test_state_starts_empty_and_hides_the_solution(client):
    body = client.get('/api/state').json()
    assert body['guesses'] == []
    assert body['isWon'] is False
    assert body['solution'] is None


def test_solution_is_withheld_until_the_game_ends(client, solution):
    # A losing guess must not leak the answer.
    body = client.post('/api/guess', json={'guess': 'отпад'}).json()
    assert body['ok'] is True
    assert body['solution'] is None
    assert client.get('/api/state').json()['solution'] is None

    body = client.post('/api/guess', json={'guess': solution}).json()
    assert body['isWon'] is True
    assert body['solution'] == solution


def test_guess_errors_carry_stable_codes(client):
    cases = [
        ('от', 'wrong_length'),
        ('otpad', 'not_cyrillic'),
        ('ттттт', 'not_a_word'),
    ]
    for guess, expected in cases:
        body = client.post('/api/guess', json={'guess': guess}).json()
        assert body['ok'] is False, (guess, body)
        assert body['error'] == expected, (guess, body)


def test_duplicate_and_post_game_guesses_are_rejected(client, solution):
    client.post('/api/guess', json={'guess': 'отпад'})
    assert client.post('/api/guess', json={'guess': 'отпад'}).json()['error'] == 'duplicate'

    client.post('/api/guess', json={'guess': solution})
    assert client.post('/api/guess', json={'guess': 'крема'}).json()['error'] == 'game_over'


def test_guesses_persist_across_requests(client):
    client.post('/api/guess', json={'guess': 'отпад'})
    client.post('/api/guess', json={'guess': 'крема'})

    body = client.get('/api/state').json()
    assert body['guesses'] == ['ОТПАД', 'КРЕМА']
    assert len(body['statuses']) == 2
    assert all(len(row) == 5 for row in body['statuses'])
    assert set(body['statuses'][0]) <= {'absent', 'present', 'correct'}


def test_stats_follow_a_completed_game(client, solution):
    assert client.get('/api/stats').json()['played'] == 0

    client.post('/api/guess', json={'guess': 'отпад'})
    client.post('/api/guess', json={'guess': solution})

    body = client.get('/api/stats').json()
    assert body['played'] == 1
    assert body['won'] == 1
    assert body['currentStreak'] == 1
    assert body['distribution'] == {'2': 1}


def test_auth_is_required_without_the_override(client):
    from zborle_bot.auth import current_user
    from zborle_bot.web import app

    app.dependency_overrides.clear()
    assert client.get('/api/state').status_code == 401
    assert client.post('/api/guess', json={'guess': 'отпад'}).status_code == 401
    # Restore so the fixture teardown is a no-op either way.
    app.dependency_overrides[current_user] = lambda: None


def test_leaderboard_is_empty_without_a_guild(client):
    body = client.get('/api/leaderboard').json()
    assert body['scope'] == 'dm'
    assert body['rows'] == []


def test_playing_enrolls_you_on_that_servers_board(client, solution):
    # Enrolment happens by playing; reading the member list would need a privileged intent.
    assert client.get('/api/leaderboard?guild_id=777').json()['rows'] == []

    client.get('/api/state?guild_id=777')
    client.post('/api/guess', json={'guess': 'отпад'})
    client.post('/api/guess', json={'guess': solution})

    body = client.get('/api/leaderboard?guild_id=777').json()
    assert body['scope'] == 'guild'
    assert len(body['rows']) == 1

    row = body['rows'][0]
    assert row['displayName'] == 'Tester'
    assert (row['won'], row['played'], row['currentStreak']) == (1, 1, 1)
    assert row['averageGuesses'] == 2.0


def test_unfinished_games_do_not_appear(client):
    client.get('/api/state?guild_id=778')
    client.post('/api/guess', json={'guess': 'отпад'})
    assert client.get('/api/leaderboard?guild_id=778').json()['rows'] == []


def test_boards_are_scoped_per_guild(client, solution):
    client.get('/api/state?guild_id=900')
    client.post('/api/guess', json={'guess': solution})

    assert len(client.get('/api/leaderboard?guild_id=900').json()['rows']) == 1
    # A server the player has never played in must not list them.
    assert client.get('/api/leaderboard?guild_id=901').json()['rows'] == []


def test_leaderboard_ranks_by_wins_then_average_guesses(tmp_path, monkeypatch):
    monkeypatch.setenv('ZBORLE_DB_PATH', str(tmp_path / 'rank.db'))
    for module in [m for m in list(sys.modules) if m.startswith('zborle_bot')]:
        del sys.modules[module]

    from zborle_bot.db import WON, ZborleDB

    db = ZborleDB(tmp_path / 'rank.db')
    # Same number of wins; the player who needed fewer guesses ranks higher.
    db.remember_player(5, 1, 'Slow', None)
    db.remember_player(5, 2, 'Fast', None)
    db.remember_player(5, 3, 'Loser', None)
    for index in (10, 11):
        db.save(1, index, ['А', 'Б', 'В', 'Г'], WON)
        db.save(2, index, ['А', 'Б'], WON)
    db.save(3, 10, ['А'], WON)

    rows = db.leaderboard(5)
    assert [row['displayName'] for row in rows] == ['Fast', 'Slow', 'Loser']
    db.close()
