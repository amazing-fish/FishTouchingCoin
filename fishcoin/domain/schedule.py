from datetime import date, datetime
from enum import Enum

from .settings import Settings


class Phase(Enum):
    BEFORE_WORK = "before_work"
    WORKING = "working"
    LUNCH = "lunch"
    OFF_WORK = "off_work"


def phase_at(settings: Settings, now: datetime) -> Phase:
    t = now.time()
    if t < settings.work_start:
        return Phase.BEFORE_WORK
    if t >= settings.work_end:
        return Phase.OFF_WORK
    if settings.lunch_start <= t < settings.lunch_end:
        return Phase.LUNCH
    return Phase.WORKING


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def rate_on(settings: Settings, day: date) -> float:
    """当天每秒摸鱼收入（含周末倍率）。"""
    mult = settings.weekend_multiplier if is_weekend(day) else 1.0
    return settings.base_rate * mult
