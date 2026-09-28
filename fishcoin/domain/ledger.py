from dataclasses import dataclass
from datetime import date, datetime, timedelta

SCHEMA = 1


@dataclass
class DayRecord:
    money: float = 0.0
    # 下班后最后一次操作电脑的时刻 "HH:MM"
    last_after_work: str | None = None


class Ledger:
    """按日期记账：每天一条记录，今天的收入就是 ledger[today]，无需“日结”。"""

    def __init__(self, days: dict[date, DayRecord] | None = None):
        self._days: dict[date, DayRecord] = dict(days or {})

    def get(self, day: date) -> DayRecord:
        return self._days.get(day) or DayRecord()

    def _ensure(self, day: date) -> DayRecord:
        rec = self._days.get(day)
        if rec is None:
            rec = self._days[day] = DayRecord()
        return rec

    def add(self, day: date, amount: float):
        if amount:
            self._ensure(day).money += amount

    def reset(self, day: date):
        if day in self._days:
            self._days[day].money = 0.0

    def touch_after_work(self, now: datetime) -> bool:
        """记录下班后使用时刻，值变化时返回 True。"""
        stamp = now.strftime("%H:%M")
        rec = self._ensure(now.date())
        if rec.last_after_work == stamp:
            return False
        rec.last_after_work = stamp
        return True

    def recent(self, today: date, n: int) -> list[tuple[date, DayRecord]]:
        """从旧到新返回最近 n 天（含今天），缺失日期补空记录。"""
        return [(d, self.get(d)) for d in (today - timedelta(days=i) for i in range(n - 1, -1, -1))]

    def total(self, start: date, end: date) -> float:
        return sum(r.money for d, r in self._days.items() if start <= d <= end)

    def prune(self, today: date, keep_days: int):
        cutoff = today - timedelta(days=keep_days - 1)
        self._days = {d: r for d, r in self._days.items() if d >= cutoff}

    def to_dict(self) -> dict:
        days = {}
        for d in sorted(self._days):
            rec = self._days[d]
            item: dict = {"money": round(rec.money, 6)}
            if rec.last_after_work:
                item["last_after_work"] = rec.last_after_work
            days[d.isoformat()] = item
        return {"schema": SCHEMA, "days": days}

    @classmethod
    def from_dict(cls, data: dict) -> "Ledger":
        if data.get("schema") != SCHEMA:
            raise ValueError(f"不支持的账本版本：{data.get('schema')!r}")
        days = {}
        for key, item in (data.get("days") or {}).items():
            days[date.fromisoformat(key)] = DayRecord(
                money=float(item.get("money", 0.0)),
                last_after_work=item.get("last_after_work") or None,
            )
        return cls(days)
