from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .ledger import Ledger
from .schedule import Phase, phase_at, rate_on
from .settings import Settings

# 单次 tick 最多计入的秒数：防止休眠唤醒、调试断点等造成的时间跳变
MAX_DELTA_S = 1.0


class Status(Enum):
    PAUSED = "paused"
    BEFORE_WORK = "before_work"
    LUNCH = "lunch"
    OFF_WORK = "off_work"
    ACTIVE = "active"  # 工作时段，正在操作电脑
    IDLE_EARNING = "idle_earning"  # 工作时段，空闲摸鱼
    LOCK_EARNING = "lock_earning"  # 锁屏，带薪时长内
    LOCK_OVER = "lock_over"  # 锁屏，超出带薪时长
    UNKNOWN_EARNING = "unknown_earning"  # 锁屏状态未知，按空闲计费

    @property
    def earning(self) -> bool:
        return self in (Status.IDLE_EARNING, Status.LOCK_EARNING, Status.UNKNOWN_EARNING)


@dataclass(frozen=True)
class Sample:
    now: datetime  # 墙钟：决定时段与记账日期
    mono: float  # 单调时钟：决定时长
    idle_s: float
    locked: bool | None  # None = 未知
    paused: bool = False


class Meter:
    """摸鱼计费状态机。每个 tick 喂一个 Sample，把收入记到 ledger。"""

    def __init__(self, settings: Settings, ledger: Ledger):
        self.settings = settings
        self.ledger = ledger
        self._last_mono: float | None = None
        self._lock_since: float | None = None
        self.status = Status.BEFORE_WORK
        self.dirty = False

    def update_settings(self, settings: Settings):
        self.settings = settings

    def locked_for(self, mono: float) -> float:
        return 0.0 if self._lock_since is None else mono - self._lock_since

    def tick(self, s: Sample) -> Status:
        dt = 0.0 if self._last_mono is None else min(max(s.mono - self._last_mono, 0.0), MAX_DELTA_S)
        self._last_mono = s.mono

        # 锁屏计时只跟随真实锁屏会话，跨时段、跨天都不重置
        if s.locked is True:
            if self._lock_since is None:
                self._lock_since = s.mono
        else:
            self._lock_since = None

        phase = phase_at(self.settings, s.now)
        if phase is Phase.OFF_WORK and s.locked is not True and s.idle_s < self.settings.idle_threshold_s:
            self.dirty |= self.ledger.touch_after_work(s.now)

        self.status = self._classify(s, phase)
        if self.status.earning and dt > 0:
            self.ledger.add(s.now.date(), rate_on(self.settings, s.now.date()) * dt)
            self.dirty = True
        return self.status

    def _classify(self, s: Sample, phase: Phase) -> Status:
        if s.paused:
            return Status.PAUSED
        if phase is Phase.BEFORE_WORK:
            return Status.BEFORE_WORK
        if phase is Phase.LUNCH:
            return Status.LUNCH
        if phase is Phase.OFF_WORK:
            return Status.OFF_WORK
        if s.locked is True:
            within = self.locked_for(s.mono) <= self.settings.lock_grace_s
            return Status.LOCK_EARNING if within else Status.LOCK_OVER
        if s.idle_s < self.settings.idle_threshold_s:
            return Status.ACTIVE
        return Status.IDLE_EARNING if s.locked is False else Status.UNKNOWN_EARNING
