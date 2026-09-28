from dataclasses import asdict, dataclass, fields, replace
from datetime import time


def parse_hhmm(value: str) -> time:
    text = str(value).strip()
    hh, sep, mm = text.partition(":")
    if not sep or not hh.isdigit() or not mm.isdigit() or len(mm) != 2:
        raise ValueError(f"时间格式应为 HH:MM：{text!r}")
    h, m = int(hh), int(mm)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"时间超出范围：{text!r}")
    return time(h, m)


def format_hhmm(value: time) -> str:
    return value.strftime("%H:%M")


@dataclass(frozen=True)
class Settings:
    monthly_salary: float = 20000.0
    work_days_per_month: float = 21.75
    work_hours_per_day: float = 8.0
    # 上班时间暂不在 UI 暴露，固定 09:00
    work_start: time = time(9, 0)
    work_end: time = time(18, 0)
    lunch_start: time = time(12, 0)
    lunch_end: time = time(14, 0)
    idle_threshold_s: float = 3.0
    lock_grace_min: float = 30.0
    weekend_multiplier: float = 2.0

    @property
    def base_rate(self) -> float:
        """每秒基础收入。"""
        return self.monthly_salary / self.work_days_per_month / (self.work_hours_per_day * 3600)

    @property
    def lock_grace_s(self) -> float:
        return self.lock_grace_min * 60

    def validate(self) -> "Settings":
        if self.monthly_salary <= 0:
            raise ValueError("月薪必须大于 0")
        if not (0 < self.work_days_per_month <= 31):
            raise ValueError("月工作天数应在 0~31 之间")
        if not (0 < self.work_hours_per_day <= 24):
            raise ValueError("日工作时长应在 0~24 小时之间")
        if self.idle_threshold_s < 0:
            raise ValueError("摸鱼判定阈值不能为负")
        if self.lock_grace_min < 0:
            raise ValueError("锁屏带薪时长不能为负")
        if self.weekend_multiplier <= 0:
            raise ValueError("周末倍率必须大于 0")
        if not (self.work_start <= self.lunch_start):
            raise ValueError("午休开始不能早于上班时间")
        if not (self.lunch_start < self.lunch_end):
            raise ValueError("午休开始必须早于午休结束")
        if not (self.lunch_end <= self.work_end):
            raise ValueError("午休结束不能晚于下班时间")
        return self

    def to_dict(self) -> dict:
        data = asdict(self)
        for key, value in data.items():
            if isinstance(value, time):
                data[key] = format_hhmm(value)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        """缺失字段取默认值；类型或取值非法时抛 ValueError。"""
        values = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            raw = data[f.name]
            if f.type in (time, "time"):
                values[f.name] = parse_hhmm(raw)
            else:
                try:
                    values[f.name] = float(raw)
                except (TypeError, ValueError):
                    raise ValueError(f"{f.name} 不是数字：{raw!r}") from None
        return replace(cls(), **values).validate()
