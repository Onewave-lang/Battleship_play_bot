from datetime import datetime, timedelta

from game_board15 import storage
from game_board15.models import Match15, Player


def test_second_place_recorded(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "data15.json")
    m = Match15.new(1, 1, "A")
    m.players['B'] = Player(user_id=2, chat_id=2, name="B")
    m.players['C'] = Player(user_id=3, chat_id=3, name="C")
    now = datetime.utcnow()
    m.shots['B']['last_result'] = 'lose'
    m.shots['B']['lost_at'] = (now - timedelta(seconds=5)).isoformat()
    m.shots['C']['last_result'] = 'lose'
    m.shots['C']['lost_at'] = now.isoformat()
    storage.finish(m, 'A')
    assert m.shots['A']['last_result'] == 'win'
    assert m.shots['C']['last_result'] == 'second'
