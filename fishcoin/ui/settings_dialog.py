import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from dataclasses import replace

from ..domain.settings import Settings, format_hhmm, parse_hhmm
from . import theme
from .windowing import present

# (字段, 标签, 单位)
SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("薪资", [
        ("monthly_salary", "月薪", "元"),
        ("work_days_per_month", "月工作天数", "天"),
        ("work_hours_per_day", "日工作时长", "小时"),
    ]),
    ("时间", [
        ("lunch", "午休", ""),
        ("work_end", "下班时间", ""),
    ]),
    ("摸鱼规则", [
        ("idle_threshold_s", "空闲多久算摸鱼", "秒"),
        ("lock_grace_min", "锁屏带薪时长", "分钟"),
        ("weekend_multiplier", "周末倍率", "倍"),
    ]),
]


class Button(tk.Label):
    """扁平按钮（tk.Button 在 Windows 上无法去掉原生边框）。"""

    def __init__(self, master, text: str, command: Callable[[], None], primary: bool, font):
        self.colors = ((theme.ACCENT, theme.ACCENT_HOVER, "#FFFFFF") if primary
                       else (theme.CARD, "#F3F4F6", theme.TEXT))
        bg, _, fg = self.colors
        super().__init__(master, text=text, font=font, bg=bg, fg=fg, padx=18, pady=6, cursor="hand2",
                         highlightthickness=0 if primary else 1, highlightbackground=theme.BORDER)
        self.bind("<Enter>", lambda e: self.configure(bg=self.colors[1]))
        self.bind("<Leave>", lambda e: self.configure(bg=self.colors[0]))
        self.bind("<ButtonRelease-1>", lambda e: command())


class Switch(tk.Canvas):
    W, H = 36, 20

    def __init__(self, master, value: bool, k: float):
        self.k = k
        super().__init__(master, width=self.W * k, height=self.H * k, bg=theme.CARD,
                         highlightthickness=0, cursor="hand2")
        self.value = value
        self.bind("<ButtonRelease-1>", lambda e: self.set(not self.value))
        self._draw()

    def set(self, value: bool):
        self.value = value
        self._draw()

    def _draw(self):
        k, w, h = self.k, self.W * self.k, self.H * self.k
        self.delete("all")
        color = theme.ACCENT if self.value else "#D1D5DB"
        r = h / 2
        self.create_oval(0, 0, h, h, fill=color, outline="")
        self.create_oval(w - h, 0, w, h, fill=color, outline="")
        self.create_rectangle(r, 0, w - r, h, fill=color, outline="")
        cx = w - r if self.value else r
        self.create_oval(cx - r + 3 * k, 3 * k, cx + r - 3 * k, h - 3 * k, fill="#FFFFFF", outline="")


class SettingsDialog:
    """配置窗口。on_done(settings, autostart) 仅在保存时调用。"""

    def __init__(self, root: tk.Tk, fonts: theme.Fonts, initial: Settings, autostart: bool, *,
                 first_run: bool, on_done: Callable[[Settings, bool], None], icon: str | None):
        self.initial = initial
        self.on_done = on_done
        self.k = k = theme.scale(root)
        self.f_body = tkfont.Font(root=root, family=fonts.ui, size=9)
        self.f_small = tkfont.Font(root=root, family=fonts.ui, size=8)
        self.f_section = tkfont.Font(root=root, family=fonts.ui, size=9, weight="bold")
        self.f_title = tkfont.Font(root=root, family=fonts.ui, size=13, weight="bold")

        win = self.win = tk.Toplevel(root, bg=theme.BG)
        win.withdraw()  # 布局完成并居中后再显示，避免先闪现在左上角
        win.title("欢迎使用摸鱼币" if first_run else "配置")
        win.resizable(False, False)
        if icon:
            win.iconbitmap(icon)
        win.protocol("WM_DELETE_WINDOW", self.cancel)
        win.bind("<Escape>", lambda e: self.cancel())
        win.bind("<Return>", lambda e: self.save())

        pad = round(20 * k)
        outer = tk.Frame(win, bg=theme.BG, padx=pad, pady=round(16 * k))
        outer.pack(fill="both", expand=True)
        tk.Label(outer, text="首次配置" if first_run else "配置", font=self.f_title, bg=theme.BG,
                 fg=theme.TEXT, anchor="w").pack(fill="x")
        tk.Label(outer, text="按你的真实情况填写，摸鱼收入据此换算。", font=self.f_small, bg=theme.BG,
                 fg=theme.MUTED, anchor="w").pack(fill="x", pady=(2, round(12 * k)))

        card = tk.Frame(outer, bg=theme.CARD, highlightthickness=1, highlightbackground=theme.BORDER,
                        padx=round(16 * k), pady=round(12 * k))
        card.pack(fill="x")
        card.columnconfigure(1, weight=1)

        self.vars: dict[str, tk.StringVar] = {}
        values = initial.to_dict()
        r = 0
        for si, (title, rows) in enumerate(SECTIONS):
            tk.Label(card, text=title, font=self.f_section, bg=theme.CARD, fg=theme.TEXT, anchor="w").grid(
                row=r, column=0, columnspan=3, sticky="w", pady=(round(10 * k) if si else 0, round(4 * k)))
            r += 1
            for key, label, unit in rows:
                tk.Label(card, text=label, font=self.f_body, bg=theme.CARD, fg=theme.MUTED, anchor="w").grid(
                    row=r, column=0, sticky="w", pady=round(4 * k), padx=(0, round(24 * k)))
                if key == "lunch":
                    box = tk.Frame(card, bg=theme.CARD)
                    box.grid(row=r, column=1, sticky="e")
                    self._entry(box, "lunch_start", values["lunch_start"], 6).pack(side="left")
                    tk.Label(box, text="—", font=self.f_body, bg=theme.CARD, fg=theme.SUBTLE).pack(
                        side="left", padx=round(6 * k))
                    self._entry(box, "lunch_end", values["lunch_end"], 6).pack(side="left")
                else:
                    width = 6 if key == "work_end" else 10
                    self._entry(card, key, values[key], width).grid(row=r, column=1, sticky="e")
                tk.Label(card, text=unit, font=self.f_small, bg=theme.CARD, fg=theme.SUBTLE, width=4,
                         anchor="w").grid(row=r, column=2, sticky="w", padx=(round(6 * k), 0))
                r += 1

        tk.Frame(card, bg=theme.BORDER, height=1).grid(row=r, column=0, columnspan=3, sticky="ew",
                                                       pady=round(10 * k))
        r += 1
        tk.Label(card, text="开机自启", font=self.f_body, bg=theme.CARD, fg=theme.MUTED, anchor="w").grid(
            row=r, column=0, sticky="w")
        self.switch = Switch(card, autostart, k)
        self.switch.grid(row=r, column=1, sticky="e")

        self.preview = tk.Label(outer, font=self.f_small, bg=theme.BG, anchor="w", justify="left")
        self.preview.pack(fill="x", pady=(round(10 * k), 0))

        btns = tk.Frame(outer, bg=theme.BG)
        btns.pack(fill="x", pady=(round(14 * k), 0))
        Button(btns, "保存", self.save, True, self.f_body).pack(side="right")
        Button(btns, "跳过" if first_run else "取消", self.cancel, False, self.f_body).pack(
            side="right", padx=(0, round(8 * k)))

        for var in self.vars.values():
            var.trace_add("write", lambda *_: self._update_preview())
        self._update_preview()

        present(win, caption=theme.BG)

    def _entry(self, parent, key: str, value, width: int) -> tk.Entry:
        text = f"{value:f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
        var = self.vars[key] = tk.StringVar(value=text)
        e = tk.Entry(parent, textvariable=var, width=width, justify="right", font=self.f_body, relief="flat",
                     bg="#F9FAFB", fg=theme.TEXT, insertbackground=theme.TEXT, highlightthickness=1,
                     highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT)
        e.bind("<FocusIn>", lambda ev: ev.widget.select_range(0, "end"))
        return e

    def _parse(self) -> Settings:
        raw = {k: v.get().strip() for k, v in self.vars.items()}
        return Settings.from_dict({**self.initial.to_dict(), **raw})

    def _update_preview(self):
        try:
            s = self._parse()
        except ValueError as e:
            self.preview.configure(text=f"⚠ {e}", fg=theme.DANGER)
            return
        hourly = s.base_rate * 3600
        self.preview.configure(
            text=f"摸鱼时薪 {theme.money(hourly)}/小时 · 每秒 {theme.money(s.base_rate, 4)}", fg=theme.MUTED)

    def exists(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def focus(self):
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def save(self):
        try:
            s = self._parse()
        except ValueError:
            self.win.bell()
            return
        self.win.destroy()
        self.on_done(s, self.switch.value)

    def cancel(self):
        self.win.destroy()
