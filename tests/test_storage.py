from datetime import date

from fishcoin.domain.ledger import Ledger
from fishcoin.domain.settings import Settings
from fishcoin.infra.storage import Store


def test_first_launch_has_no_settings(tmp_path):
    store = Store(tmp_path)
    assert store.load_settings() is None
    assert store.load_ledger().to_dict() == Ledger().to_dict()


def test_roundtrip(tmp_path):
    store = Store(tmp_path)
    store.save_settings(Settings(monthly_salary=12345))
    lg = Ledger()
    lg.add(date(2026, 4, 13), 1.25)
    store.save_ledger(lg)
    assert store.load_settings() == Settings(monthly_salary=12345)
    assert store.load_ledger().get(date(2026, 4, 13)).money == 1.25
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_files_are_quarantined(tmp_path):
    store = Store(tmp_path)
    store.settings_path.write_text("{not json", encoding="utf-8")
    store.ledger_path.write_text('{"schema": 99}', encoding="utf-8")
    assert store.load_settings() is None
    assert store.load_ledger().to_dict()["days"] == {}
    assert len(list(tmp_path.glob("settings.json.corrupt.*"))) == 1
    assert len(list(tmp_path.glob("ledger.json.corrupt.*"))) == 1
    assert not store.settings_path.exists()
