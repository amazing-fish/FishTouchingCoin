import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from ..domain.ledger import Ledger
from ..domain.meter import Status
from ..domain.schedule import is_weekend, rate_on
from ..domain.settings import Settings
from ..infra import windows
from . import theme

WEEKDAYS = "一二三四五六日"

# 详情页状态标签：(背景, 文字)
CHIP_COLORS: dict[Status, tuple[str, str]] = {
    Status.IDLE_EARNING: ("#FEF7D6", "#A16207"),
    Status.LOCK_EARNING: ("#DCFCE7", "#15803D"),
    Status.UNKNOWN_EARNING: ("#EDE9FE", "#6D28D9"),
    Status.LOCK_OVER: ("#FEE2E2", "#B91C1C"),
    Status.ACTIVE: ("#F1F2F4", "#4B5563"),
    Status.LUNCH: ("#FFEDD5", "#C2410C"),
    Status.OFF_WORK: ("#DBEAFE", "#1D4ED8"),
    Status.BEFORE_WORK: ("#F1F2F4", "#4B5563"),
    Status.PAUSED: ("#F1F2F4", "#4B5563"),
}


@dataclass(frozen=True)
class Snapshot:
    today: date
    status: Status
    settings: Settings
    ledger: Ledger


def round_rect(c: tk.Canvas, x0, y0, x1, y1, r, **kw):
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)


class DetailsWindow:
    W, H = 440, 392
    M = 16

    def __init__(self, root: tk.Tk, fonts: theme.Fonts, snapshot: Callable[[], Snapshot], icon: str | None):
        self.snapshot = snapshot
        self.k = theme.scale(root)
        self.win = tk.Toplevel(root, bg=theme.BG)
        self.win.title("统计")  # 标题会出现在 Alt-Tab / 任务栏，保持中性
        self.win.resizable(False, False)
        if icon:
            self.win.iconbitmap(icon)
        self.win.geometry(f"{round(self._px(self.W))}x{round(self._px(self.H))}")
        self._center()

        self.f = {
            "small": tkfont.Font(root=root, family=fonts.ui, size=8),
            "body": tkfont.Font(root=root, family=fonts.ui, size=9),
            "title": tkfont.Font(root=root, family=fonts.ui, size=10, weight="bold"),
            "hero": tkfont.Font(root=root, family=fonts.num_display, size=24),
            "stat": tkfont.Font(root=root, family=fonts.num, size=12),
            "bar": tkfont.Font(root=root, family=fonts.num, size=8),
        }
        self.canvas = tk.Canvas(self.win, bg=theme.BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.win.update_idletasks()
        windows.set_caption_color(self.win, theme.BG)
        self._job: str | None = None
        self.refresh()

    def _px(self, v: float) -> float:
        return v * self.k

    def _center(self):
        self.win.update_idletasks()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        w, h = self._px(self.W), self._px(self.H)
        self.win.geometry(f"+{int((sw - w) / 2)}+{int((sh - h) / 2.4)}")

    def exists(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def focus(self):
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def refresh(self):
        if not self.exists():
            return
        self._draw(self.snapshot())
        self._job = self.win.after(1000, self.refresh)

    # —— 绘制 ——

    def _card(self, x0, y0, x1, y1):
        round_rect(self.canvas, x0, y0, x1, y1, self._px(10), fill=theme.CARD, outline=theme.BORDER)

    def _draw(self, s: Snapshot):
        c, p, f = self.canvas, self._px, self.f
        c.delete("all")
        M, W = p(self.M), p(self.W)
        today = s.today
        lg = s.ledger
        today_money = lg.get(today).money

        # 今日卡片
        y0, y1 = M, M + p(104)
        self._card(M, y0, W - M, y1)
        c.create_text(M + p(16), y0 + p(20), text="今日", font=f["body"], fill=theme.MUTED, anchor="w")
        c.create_text(M + p(16), y0 + p(54), text=theme.money(today_money, 2), font=f["hero"],
                      fill=theme.TEXT, anchor="w")
        rate_h = rate_on(s.settings, today) * 3600
        mult = f"（周末 ×{s.settings.weekend_multiplier:g}）" if is_weekend(today) else ""
        c.create_text(M + p(16), y0 + p(86), text=f"时薪 {theme.money(rate_h)}/小时{mult}",
                      font=f["small"], fill=theme.SUBTLE, anchor="w")
        self._chip(W - M - p(16), y0 + p(20), s.status)

        # 统计三联
        week = lg.total(today - timedelta(days=today.weekday()), today)
        month = lg.total(today.replace(day=1), today)
        recent = lg.recent(today, 7)
        avg = sum(r.money for _, r in recent) / 7
        stats = [("本周", theme.money(week)), ("本月", theme.money(month)), ("近7天日均", theme.money(avg))]
        sy0, sy1 = y1 + p(12), y1 + p(12) + p(62)
        gap = p(10)
        cw = (W - 2 * M - 2 * gap) / 3
        for i, (label, value) in enumerate(stats):
            x0 = M + i * (cw + gap)
            self._card(x0, sy0, x0 + cw, sy1)
            c.create_text(x0 + p(12), sy0 + p(18), text=label, font=f["small"], fill=theme.MUTED, anchor="w")
            c.create_text(x0 + p(12), sy0 + p(42), text=value, font=f["stat"], fill=theme.TEXT, anchor="w")

        # 近 7 天柱状图
        cy0, cy1 = sy1 + p(12), p(self.H) - M
        self._card(M, cy0, W - M, cy1)
        c.create_text(M + p(16), cy0 + p(20), text="近 7 天", font=f["title"], fill=theme.TEXT, anchor="w")
        latest = max((r.last_after_work for _, r in recent if r.last_after_work), default=None)
        if latest:
            c.create_text(W - M - p(16), cy0 + p(20), text=f"最晚下班 {latest}", font=f["small"],
                          fill=theme.MUTED, anchor="e")

        top, base = cy0 + p(58), cy1 - p(52)
        max_v = max((r.money for _, r in recent), default=0.0)
        slot = (W - 2 * M - p(24)) / 7
        bar_w = min(p(26), slot * 0.5)
        for i, (d, r) in enumerate(recent):
            cx = M + p(12) + slot * (i + 0.5)
            is_today = d == today
            weekend = is_weekend(d)
            # 轨道 + 柱
            round_rect(c, cx - bar_w / 2, top, cx + bar_w / 2, base, bar_w / 2, fill=theme.TRACK, outline="")
            if r.money > 0 and max_v > 0:
                h = max(bar_w, (base - top) * r.money / max_v)
                color = theme.ACCENT if is_today else ("#FDBA74" if weekend else "#BFD3FB")
                round_rect(c, cx - bar_w / 2, base - h, cx + bar_w / 2, base, bar_w / 2, fill=color, outline="")
                c.create_text(cx, base - h - p(9), text=f"{r.money:,.0f}", font=f["bar"],
                              fill=theme.TEXT if is_today else theme.MUTED)
            # 日期与星期
            wd_color = theme.WEEKEND if weekend else (theme.TEXT if is_today else theme.MUTED)
            c.create_text(cx, base + p(14), text="今天" if is_today else f"周{WEEKDAYS[d.weekday()]}",
                          font=f["small"], fill=wd_color)
            c.create_text(cx, base + p(29), text=d.strftime("%m-%d"), font=f["small"], fill=theme.SUBTLE)
            if r.last_after_work:
                hl = r.last_after_work == latest
                c.create_text(cx, base + p(43), text=r.last_after_work, font=f["small"],
                              fill=theme.ACCENT if hl else theme.SUBTLE)

    def _chip(self, right: float, cy: float, status: Status):
        c, p = self.canvas, self._px
        bg, fg = CHIP_COLORS[status]
        text = theme.STATUS_STYLES[status].label
        tw = self.f["small"].measure(text)
        dot = p(6)
        w = p(10) + dot + p(6) + tw + p(10)
        h = p(22)
        x0 = right - w
        round_rect(c, x0, cy - h / 2, right, cy + h / 2, h / 2, fill=bg, outline="")
        c.create_oval(x0 + p(10), cy - dot / 2, x0 + p(10) + dot, cy + dot / 2, fill=fg, outline="")
        c.create_text(x0 + p(10) + dot + p(6), cy, text=text, font=self.f["small"], fill=fg, anchor="w")
