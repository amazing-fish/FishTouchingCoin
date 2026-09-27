import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from ..domain.meter import Status

# —— 悬浮窗（深色胶囊） ——
OVERLAY_BG = "#1B1E24"
OVERLAY_BORDER = "#3A404C"
OVERLAY_MUTED = "#8B93A1"

# —— 窗口（浅色卡片） ——
BG = "#F4F5F7"
CARD = "#FFFFFF"
BORDER = "#E5E7EB"
TEXT = "#111827"
MUTED = "#6B7280"
SUBTLE = "#9CA3AF"
ACCENT = "#2563EB"
ACCENT_HOVER = "#1D4ED8"
ACCENT_SOFT = "#EEF3FF"
WEEKEND = "#F97316"
DANGER = "#DC2626"
DANGER_SOFT = "#FEF2F2"
TRACK = "#EEF0F3"
GOLD = "#F5B301"


OVERLAY_REST = "#9AA1AD"  # 平时的数字颜色：中性灰，不随状态变色


@dataclass(frozen=True)
class StatusStyle:
    label: str
    color: str  # 悬停展开时的强调色
    rest: str  # 平时状态点颜色：低饱和，只有自己知道含义


_DIM_GRAY = "#565C66"

STATUS_STYLES: dict[Status, StatusStyle] = {
    Status.IDLE_EARNING: StatusStyle("摸鱼中", "#FACC15", "#8F7F3F"),
    Status.LOCK_EARNING: StatusStyle("带薪离开", "#34D399", "#4B8069"),
    Status.UNKNOWN_EARNING: StatusStyle("摸鱼中?", "#C4B5FD", "#7A7294"),
    Status.LOCK_OVER: StatusStyle("离开超时", "#F87171", "#8C5555"),
    Status.ACTIVE: StatusStyle("搬砖中", "#A1A8B3", _DIM_GRAY),
    Status.LUNCH: StatusStyle("午休", "#FB923C", _DIM_GRAY),
    Status.OFF_WORK: StatusStyle("已下班", "#60A5FA", _DIM_GRAY),
    Status.BEFORE_WORK: StatusStyle("未上班", "#A1A8B3", _DIM_GRAY),
    Status.PAUSED: StatusStyle("已暂停", "#6B7280", _DIM_GRAY),
}


class Fonts:
    """在 Tk 初始化后解析可用字体，缺失时逐级回退。"""

    def __init__(self, root: tk.Misc):
        families = set(tkfont.families(root))

        def pick(*names: str) -> str:
            return next((n for n in names if n in families), "TkDefaultFont")

        self.ui = pick("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
        self.num = pick("Segoe UI Semibold", "Segoe UI", self.ui)
        self.num_display = pick("Segoe UI Variable Display Semib", "Segoe UI Semibold", self.num)


def scale(root: tk.Misc) -> float:
    """当前 DPI 相对 96 的倍数，用于像素尺寸（字号按 pt 已自动缩放）。"""
    return root.winfo_fpixels("1i") / 96.0


def money(value: float, digits: int = 2) -> str:
    return f"¥{value:,.{digits}f}"
