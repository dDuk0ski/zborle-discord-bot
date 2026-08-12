"""Live session tests. Run with: .venv/bin/python -m pytest -q"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('ZBORLE_DB_PATH', str(tmp_path / 'sess.db'))
    for module in [m for m in list(sys.modules) if m.startswith('zborle_bot')]:
        del sys.modules[module]
    from zborle_bot.db import ZborleDB

    database = ZborleDB(tmp_path / 'sess.db')
    yield database
    database.close()


def test_join_session_reports_only_new_players(db):
    assert db.join_session('inst-1', 10, 20, 700, 1) is True
    assert db.join_session('inst-1', 10, 20, 700, 1) is False
    assert db.join_session('inst-1', 10, 20, 700, 2) is True

    session = db.session('inst-1')
    assert session['guild_id'] == 10
    assert session['channel_id'] == 20
    assert session['puzzle_index'] == 700


def test_session_boards_keep_join_order_and_pick_up_games(db):
    from zborle_bot.db import IN_PROGRESS, WON

    db.remember_player(10, 1, 'First', 'http://a')
    db.remember_player(10, 2, 'Second', None)
    db.join_session('inst-2', 10, 20, 700, 1)
    db.join_session('inst-2', 10, 20, 700, 2)

    db.save(1, 700, ['ОТПАД', 'КРЕМА'], IN_PROGRESS)
    db.save(2, 700, ['ЖЕНКА'], WON)

    boards = db.session_boards('inst-2')
    assert [b['displayName'] for b in boards] == ['First', 'Second']
    assert [len(b['guesses']) for b in boards] == [2, 1]
    assert boards[0]['avatarUrl'] == 'http://a'
    assert boards[1]['status'] == WON


def test_a_player_with_no_game_still_appears(db):
    db.remember_player(10, 3, 'Lurker', None)
    db.join_session('inst-3', 10, 20, 700, 3)

    boards = db.session_boards('inst-3')
    assert len(boards) == 1
    assert boards[0]['guesses'] == []


def test_message_id_survives_and_is_reused(db):
    db.join_session('inst-4', 10, 20, 700, 1)
    assert db.session('inst-4')['message_id'] is None
    db.set_session_message('inst-4', 555)
    assert db.session('inst-4')['message_id'] == 555


def test_sweep_drops_only_older_puzzles(db):
    db.join_session('old', 10, 20, 699, 1)
    db.join_session('current', 10, 20, 700, 1)

    assert db.stale_sessions(700) == ['old']
    db.drop_session('old')
    assert db.session('old') is None
    assert db.session('current') is not None


def test_debounce_coalesces_many_updates_into_one(monkeypatch, db):
    """Six players guessing at once must not produce six Discord edits."""
    from zborle_bot import sessions as sessions_module

    monkeypatch.setattr(sessions_module, 'DEBOUNCE_SECONDS', 0.05)

    calls = []

    class FakeManager(sessions_module.SessionManager):
        async def update(self, instance_id):
            calls.append(instance_id)

    async def scenario():
        manager = FakeManager(client=None, db=db)
        for _ in range(6):
            manager.schedule('inst-5')
        await asyncio.sleep(0.2)
        return calls

    assert asyncio.run(scenario()) == ['inst-5']


def test_fingerprint_skips_redundant_edits(db):
    """Reopening the Activity without guessing must not re-upload the image."""
    from zborle_bot.db import IN_PROGRESS

    db.remember_player(10, 1, 'P', None)
    db.join_session('inst-6', 10, 20, 700, 1)
    db.save(1, 700, ['ОТПАД'], IN_PROGRESS)

    boards = db.session_boards('inst-6')
    fingerprint = '|'.join(f'{b["userId"]}:{len(b["guesses"])}:{b["status"]}' for b in boards)

    # Same state, same fingerprint.
    again = db.session_boards('inst-6')
    assert '|'.join(f'{b["userId"]}:{len(b["guesses"])}:{b["status"]}' for b in again) == fingerprint

    # A new guess changes it.
    db.save(1, 700, ['ОТПАД', 'КРЕМА'], IN_PROGRESS)
    changed = db.session_boards('inst-6')
    assert '|'.join(f'{b["userId"]}:{len(b["guesses"])}:{b["status"]}' for b in changed) != fingerprint


def test_socket_rejects_missing_or_bad_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv('ZBORLE_DB_PATH', str(tmp_path / 'ws.db'))
    for module in [m for m in list(sys.modules) if m.startswith('zborle_bot')]:
        del sys.modules[module]

    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from zborle_bot.web import app

    client = TestClient(app)

    # No token at all.
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/ws') as socket:
            socket.send_json({'instance_id': 'inst-1'})
            socket.receive_json()

    # A token Discord will not recognise.
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/ws') as socket:
            socket.send_json({'token': 'not-a-real-token', 'instance_id': 'inst-1'})
            socket.receive_json()


def test_hub_broadcast_drops_dead_sockets():
    from zborle_bot.live import LiveHub

    class Fake:
        def __init__(self, ok=True):
            self.ok = ok
            self.sent = []

        async def send_json(self, payload):
            if not self.ok:
                raise RuntimeError('closed')
            self.sent.append(payload)

    async def scenario():
        hub = LiveHub()
        good, bad = Fake(), Fake(ok=False)
        await hub.join('room', good)
        await hub.join('room', bad)
        assert hub.occupancy('room') == 2

        await hub.broadcast('room', {'type': 'participants', 'players': []})
        # The broken socket is evicted; the healthy one still received its payload.
        assert hub.occupancy('room') == 1
        assert len(good.sent) == 1

    asyncio.run(scenario())


def test_session_message_text(db):
    from zborle_bot.db import IN_PROGRESS, LOST, WON
    from zborle_bot.sessions import SessionManager

    manager = SessionManager(client=None, db=db)

    playing = [{'displayName': 'Ана', 'status': IN_PROGRESS, 'guesses': ['А']}]
    assert 'Ана' in manager._content(playing)

    two = [
        {'displayName': 'Ана', 'status': IN_PROGRESS, 'guesses': ['А']},
        {'displayName': 'Бојан', 'status': IN_PROGRESS, 'guesses': []},
    ]
    assert 'играат' in manager._content(two)

    # Everyone finished: the fewest-guess winner is crowned.
    done = [
        {'displayName': 'Ана', 'status': WON, 'guesses': ['А', 'Б', 'В']},
        {'displayName': 'Бојан', 'status': WON, 'guesses': ['А', 'Б']},
        {'displayName': 'Цветан', 'status': LOST, 'guesses': ['А'] * 6},
    ]
    text = manager._content(done)
    assert '👑 2/6: Бојан' in text

    all_lost = [{'displayName': 'Ана', 'status': LOST, 'guesses': ['А'] * 6}]
    assert 'Никој не го погоди' in manager._content(all_lost)
