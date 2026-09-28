import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from dataclasses import dataclass

from ..infra import windows
from . import theme


@dataclass
class MenuItem:
    label: str
    action: Callable[[], None] | None = None  # None 表示分隔线
    checked: bool | None = None  # None 表示非勾选项
    danger: bool = False
    hint: str = ""

    @classmethod
    def separator(cls) -> "MenuItem":
        return cls("")


class PopupMenu:
    """自绘右键菜单：替代 tk.Menu，避免其 grab/焦点问题并统一视觉。

    失焦或按 Esc 即关闭；点击菜单项先关闭再执行动作。
    """

    WIDTH = 188
    ROW_H = 32
    PAD = 5

    def __init__(self, root: tk.Tk, fonts: theme.Fonts):
        self.root = root
        self.k = theme.scale(root)
        self.font = tkfont.Font(root=root, family=fonts.ui, size=9)
        self.hint_font = tkfont.Font(root=root, family=fonts.ui, size=8)
        self.check_font = tkfont.Font(root=root, family="Segoe UI Symbol", size=9)
        self.win: tk.Toplevel | None = None

    @property
    def is_open(self) -> bool:
        return self.win is not None

    def _px(self, v: float) -> int:
        return round(v * self.k)

    def open(self, x: int, y: int, items: list[MenuItem]):
        self.close()
        win = self.win = tk.Toplevel(self.root, bg=theme.CARD)
        win.overrideredirect(True)
        win.attributes("-topmost", True)

        body = tk.Frame(win, bg=theme.CARD, padx=self._px(self.PAD), pady=self._px(self.PAD))
        body.pack(fill="both", expand=True)
        for item in items:
            if item.action is None:
                tk.Frame(body, bg=theme.BORDER, height=1).pack(fill="x", padx=self._px(8), pady=self._px(4))
            else:
                self._row(body, item)

        win.update_idletasks()
        w, h = self._px(self.WIDTH), win.winfo_reqheight()
        left, top, right, bottom = windows.work_area_at(x, y)
        # 靠近屏幕边缘时向内翻转
        px = x if x + w <= right else max(left, x - w)
        py = y if y + h <= bottom else max(top, y - h)
        win.geometry(f"{w}x{h}+{px}+{py}")
        windows.round_corners(win, small=False, border=theme.BORDER)

        win.bind("<FocusOut>", lambda e: self.close())
        win.bind("<Escape>", lambda e: self.close())
        win.focus_force()

    def _row(self, parent: tk.Frame, item: MenuItem):
        fg = theme.DANGER if item.danger else theme.TEXT
        hover_bg = theme.DANGER_SOFT if item.danger else theme.ACCENT_SOFT
        row = tk.Frame(parent, bg=theme.CARD, height=self._px(self.ROW_H), cursor="hand2")
        row.pack(fill="x")
        row.pack_propagate(False)

        check = tk.Label(row, text="✓" if item.checked else "", width=2, font=self.check_font,
                         bg=theme.CARD, fg=theme.ACCENT)
        check.pack(side="left", padx=(self._px(4), 0))
        label = tk.Label(row, text=item.label, font=self.font, bg=theme.CARD, fg=fg, anchor="w")
        label.pack(side="left", fill="x", expand=True)
        parts = [row, check, label]
        if item.hint:
            hint = tk.Label(row, text=item.hint, font=self.hint_font, bg=theme.CARD, fg=theme.SUBTLE)
            hint.pack(side="right", padx=(0, self._px(10)))
            parts.append(hint)

        def paint(bg: str):
            for w in parts:
                w.configure(bg=bg)

        def run(_e=None):
            self.close()
            self.root.after_idle(item.action)

        for w in parts:
            w.bind("<Enter>", lambda e: paint(hover_bg))
            w.bind("<Leave>", lambda e: paint(theme.CARD))
            w.bind("<ButtonRelease-1>", run)

    def close(self):
        win, self.win = self.win, None
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass
