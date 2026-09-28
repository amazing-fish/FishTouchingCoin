from datetime import date, datetime, time, timedelta

import pytest

from fishcoin.domain.ledger import DayRecord, Ledger
from fishcoin.domain.meter import MAX_DELTA_S, Meter, Sample, Status
from fishcoin.domain.schedule import Phase, phase_at, rate_on
from fishcoin.domain.settings import Settings, parse_hhmm

S = Settings()  # 默认：09:00-18:00，午休 12:00-14:00，阈值 3s，锁屏 30min，周末 x2
MON = date(2026, 4, 13)
SAT = date(2026, 4, 18)


def at(day: date, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm, ss))


def run(meter: Meter, day: date, hh: int, mm: int, seconds: int, *, idle=10.0, locked=False, paused=False,
        mono0=1000.0):
    """从 hh:mm 开始每秒一个 tick，共 seconds 秒；返回最后状态。"""
    status = None
    start = at(day, hh, mm)
    for i in range(seconds + 1):
        now = start + timedelta(seconds=i)
        status = meter.tick(Sample(now=now, mono=mono0 + i, idle_s=idle, locked=locked, paused=paused))
    return status


# ---------- settings ----------

def test_base_rate():
    assert S.base_rate == pytest.approx(20000 / 21.75 / (8 * 3600))


def test_settings_roundtrip_and_defaults_for_missing_keys():
    s = Settings(monthly_salary=30000, work_end=time(19, 30))
    assert Settings.from_dict(s.to_dict()) == s
    assert Settings.from_dict({"monthly_salary": 1}) == Settings(monthly_salary=1.0)


@pytest.mark.parametrize("patch, msg", [
    ({"monthly_salary": 0}, "月薪"),
    ({"lunch_start": "14:00", "lunch_end": "12:00"}, "午休开始必须早于"),
    ({"work_end": "13:00"}, "午休结束"),
    ({"lunch_start": "08:00"}, "上班"),
    ({"weekend_multiplier": "abc"}, "不是数字"),
])
def test_settings_validation(patch, msg):
    with pytest.raises(ValueError, match=msg):
        Settings.from_dict(patch)


@pytest.mark.parametrize("text", ["9:00x", "24:00", "12:60", "1200", "12:5"])
def test_parse_hhmm_rejects(text):
    with pytest.raises(ValueError):
        parse_hhmm(text)


# ---------- schedule ----------

@pytest.mark.parametrize("hh, mm, phase", [
    (8, 59, Phase.BEFORE_WORK),
    (9, 0, Phase.WORKING),
    (11, 59, Phase.WORKING),
    (12, 0, Phase.LUNCH),
    (13, 59, Phase.LUNCH),
    (14, 0, Phase.WORKING),
    (17, 59, Phase.WORKING),
    (18, 0, Phase.OFF_WORK),
    (23, 59, Phase.OFF_WORK),
])
def test_phase_boundaries(hh, mm, phase):
    assert phase_at(S, at(MON, hh, mm)) is phase


def test_weekend_rate():
    assert rate_on(S, SAT) == pytest.approx(S.base_rate * 2)
    assert rate_on(S, MON) == pytest.approx(S.base_rate)


# ---------- meter ----------

def test_idle_earns_active_does_not():
    m = Meter(S, Ledger())
    assert run(m, MON, 10, 0, 100, idle=10) is Status.IDLE_EARNING
    assert m.ledger.get(MON).money == pytest.approx(S.base_rate * 100)
    before = m.ledger.get(MON).money
    assert run(m, MON, 10, 5, 50, idle=0, mono0=2000) is Status.ACTIVE
    # 跨 mono0 的第一个 tick 被 MAX_DELTA_S 钳制，但 ACTIVE 不计费
    assert m.ledger.get(MON).money == pytest.approx(before)


def test_delta_is_clamped_after_sleep():
    m = Meter(S, Ledger())
    m.tick(Sample(at(MON, 10), 0.0, 10, False))
    m.tick(Sample(at(MON, 11), 3600.0, 10, False))  # 休眠一小时
    assert m.ledger.get(MON).money == pytest.approx(S.base_rate * MAX_DELTA_S)


def test_no_earning_outside_working_hours():
    for hh, status in [(8, Status.BEFORE_WORK), (12, Status.LUNCH), (19, Status.OFF_WORK)]:
        m = Meter(S, Ledger())
        assert run(m, MON, hh, 30, 60) is status
        assert m.ledger.get(MON).money == 0


def test_paused_does_not_earn():
    m = Meter(S, Ledger())
    assert run(m, MON, 10, 0, 60, paused=True) is Status.PAUSED
    assert m.ledger.get(MON).money == 0


def test_lock_grace_then_over():
    m = Meter(S, Ledger())
    grace = int(S.lock_grace_s)
    assert run(m, MON, 10, 0, grace, locked=True) is Status.LOCK_EARNING
    assert m.ledger.get(MON).money == pytest.approx(S.base_rate * grace)
    assert run(m, MON, 10, 30, 600, locked=True, mono0=1000 + grace + 1) is Status.LOCK_OVER
    # 超时后不再计费：总额恰为 grace 秒
    assert m.ledger.get(MON).money == pytest.approx(S.base_rate * grace)


def test_lock_timer_spans_lunch():
    """11:50 锁屏到午休后，14:00 不应重新获得 30 分钟带薪。"""
    m = Meter(S, Ledger())
    run(m, MON, 11, 50, 600, locked=True)  # 11:50-12:00 带薪
    # 午休 2 小时仍锁屏（mono 连续）
    run(m, MON, 12, 0, 7199, locked=True, mono0=1601)
    assert run(m, MON, 14, 0, 10, locked=True, mono0=8801) is Status.LOCK_OVER


def test_unlock_resets_lock_timer():
    m = Meter(S, Ledger())
    run(m, MON, 10, 0, 3600, locked=True)
    run(m, MON, 11, 0, 1, locked=False, mono0=4601)
    assert run(m, MON, 11, 1, 10, locked=True, mono0=4700) is Status.LOCK_EARNING


def test_unknown_lock_falls_back_to_idle():
    m = Meter(S, Ledger())
    assert run(m, MON, 10, 0, 10, idle=10, locked=None) is Status.UNKNOWN_EARNING
    assert run(m, MON, 10, 1, 10, idle=0, locked=None, mono0=2000) is Status.ACTIVE


def test_weekend_multiplier_applies():
    m = Meter(S, Ledger())
    run(m, SAT, 10, 0, 100)
    assert m.ledger.get(SAT).money == pytest.approx(S.base_rate * 2 * 100)


def test_midnight_rollover_books_to_new_day():
    m = Meter(S, Ledger())
    m.ledger.add(MON, 5.0)
    tue = date(2026, 4, 14)
    m.tick(Sample(at(MON, 23, 59, 59), 0.0, 0, False))
    m.tick(Sample(at(tue, 0, 0, 0), 1.0, 0, False))
    assert m.ledger.get(MON).money == 5.0
    assert m.ledger.get(tue).money == 0.0


def test_after_work_usage_recorded_only_when_active():
    m = Meter(S, Ledger())
    run(m, MON, 20, 15, 1, idle=0)
    assert m.ledger.get(MON).last_after_work == "20:15"
    run(m, MON, 21, 0, 1, idle=10, mono0=5000)  # 空闲不更新
    run(m, MON, 21, 30, 1, idle=0, locked=True, mono0=6000)  # 锁屏不更新
    assert m.ledger.get(MON).last_after_work == "20:15"


def test_reset_today_after_work_end_is_consistent():
    """旧版问题：18:00 日结后重置，历史仍是旧值。新模型只有一份数据。"""
    m = Meter(S, Ledger())
    run(m, MON, 17, 58, 60)
    m.ledger.reset(MON)
    assert m.ledger.get(MON).money == 0
    assert m.ledger.to_dict()["days"][MON.isoformat()]["money"] == 0


# ---------- ledger ----------

def test_ledger_roundtrip_recent_prune():
    lg = Ledger({MON: DayRecord(1.5, "19:02"), SAT: DayRecord(2.0)})
    assert Ledger.from_dict(lg.to_dict()).to_dict() == lg.to_dict()
    recent = lg.recent(SAT, 7)
    assert [d for d, _ in recent][0] == date(2026, 4, 12) and recent[-1][0] == SAT
    assert lg.total(MON, SAT) == pytest.approx(3.5)
    lg.prune(SAT, 3)
    assert lg.get(MON).money == 0 and lg.get(SAT).money == 2.0


def test_ledger_rejects_unknown_schema():
    with pytest.raises(ValueError):
        Ledger.from_dict({"schema": 99, "days": {}})
