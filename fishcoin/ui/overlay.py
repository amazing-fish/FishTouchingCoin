import re
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable

from ..domain.meter import Status
from ..infra import windows
from . import theme


class Overlay:
    """置顶悬浮胶囊。

    低调优先：平时只显示暗灰色数字（无 ¥、无状态文字、无描边），旁人一眼看不出是什么；
    鼠标悬停满 3 秒才展开状态、倍率与 4 位小数，移开立即收起。左键拖动，双击详情，右键菜单。
    """

    PAD_X = 9
    HEIGHT = 24
    DOT_R = 2.5
    GAP = 6
    LABEL_GAP = 8
    REST_ALPHA = 0.62
    HOVER_DELAY_MS = 3000  # 悬停满 3 秒才展开，鼠标路过不会闪出信息

    def __init__(self, root: tk.Tk, fonts: theme.Fonts, on_menu: Callable[[int, int], None],
                 on_double_click: Callable[[], None]):
        self.root = root
        self.k = theme.scale(root)
        self.on_menu = on_menu
        self.on_double_click = on_double_click

        self.f_label = tkfont.Font(root=root, family=fonts.ui, size=8)
        self.f_amount = tkfont.Font(root=root, family=fonts.num, size=9)

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=theme.OVERLAY_BG)

        self.canvas = tk.Canvas(root, bg=theme.OVERLAY_BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.dot = self.canvas.create_oval(0, 0, 0, 0, width=0)
        self.label = self.canvas.create_text(0, 0, anchor="w", font=self.f_label, fill=theme.OVERLAY_MUTED)
        self.amount = self.canvas.create_text(0, 0, anchor="e", font=self.f_amount)

        self.visible = True
        self._hover = False
        self._state: tuple[Status, float, float] | None = None
        self._last: tuple | None = None
        self._size: tuple[int, int] | None = None
        self._right: int | None = None
        self._bottom: int | None = None
        self._drag: tuple[int, int] | None = None
        self._hover_job: str | None = None

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", lambda e: self.on_double_click())
        self.canvas.bind("<Button-3>", lambda e: self.on_menu(e.x_root, e.y_root))
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        root.bind("<Map>", lambda e: self._decorate())
        # Win+D / Win+M 等会把无边框窗口最小化成桌面左下角的小标题条；改为隐藏，只留托盘
        root.bind("<Unmap>", self._on_unmap)

    def _px(self, v: float) -> int:
        return round(v * self.k)

    def _decorate(self):
        windows.round_corners(self.root, border=windows.BORDER_NONE)

    # —— 渲染 ——

    def render(self, status: Status, amount: float, multiplier: float = 1.0):
        self._state = (status, amount, multiplier)
        self._draw()

    def _draw(self):
        if self._state is None:
            return
        status, amount, multiplier = self._state
        style = theme.STATUS_STYLES[status]
        if self._hover:
            label = style.label + (f" ×{multiplier:g}" if multiplier != 1 and status.earning else "")
            text, color, dot = theme.money(amount, 4), style.color, style.color
        else:
            label, text, color, dot = "", f"{amount:,.2f}", theme.OVERLAY_REST, style.rest
        key = (label, text, color, dot, self._hover)
        if key == self._last:
            return
        self._last = key

        # 宽度按“全 0”模板测量：比例字体中 1 较窄，避免数字跳动时窗口抖动
        amount_w = self.f_amount.measure(re.sub(r"\d", "0", text))
        label_w = self.f_label.measure(label) + self._px(self.LABEL_GAP) if label else 0
        pad, dot_d, gap = self._px(self.PAD_X), self._px(self.DOT_R * 2), self._px(self.GAP)
        w = pad + dot_d + gap + label_w + amount_w + pad
        h = self._px(self.HEIGHT)
        cy = h / 2

        r = self.DOT_R * self.k
        self.canvas.coords(self.dot, pad, cy - r, pad + 2 * r, cy + r)
        self.canvas.itemconfigure(self.dot, fill=dot)
        self.canvas.coords(self.label, pad + dot_d + gap, cy)
        self.canvas.itemconfigure(self.label, text=label)
        self.canvas.coords(self.amount, w - pad, cy)
        self.canvas.itemconfigure(self.amount, text=text, fill=color)

        self._resize(w, h)
        self.root.attributes("-alpha", 1.0 if self._hover else self.REST_ALPHA)

    def _resize(self, w: int, h: int):
        if self._size == (w, h):
            return
        if self._right is None:
            left, top, right, bottom = windows.work_area_at(0, 0)
            self._right, self._bottom = right - self._px(12), bottom - self._px(12)
        self._size = (w, h)
        # 固定右下角：展开或位数增加时向左扩展
        self.root.geometry(f"{w}x{h}+{self._right - w}+{self._bottom - h}")

    def _on_enter(self, e):
        self._cancel_hover()
        self._hover_job = self.root.after(self.HOVER_DELAY_MS, self._hover_elapsed)

    def _on_leave(self, e):
        self._cancel_hover()
        self._set_hover(False)

    def _hover_elapsed(self):
        self._hover_job = None
        if not self.dragging:
            self._set_hover(True)

    def _cancel_hover(self):
        if self._hover_job is not None:
            self.root.after_cancel(self._hover_job)
            self._hover_job = None

    def _set_hover(self, hover: bool):
        if hover != self._hover:
            self._hover = hover
            self._draw()

    # —— 拖动 ——

    def _press(self, e):
        self._cancel_hover()  # 拖动中不展开，避免宽度变化导致跳动
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _motion(self, e):
        if self._drag:
            x, y = e.x_root - self._drag[0], e.y_root - self._drag[1]
            self.root.geometry(f"+{x}+{y}")

    def _release(self, e):
        if self._drag:
            self._drag = None
            self._right = self.root.winfo_x() + self.root.winfo_width()
            self._bottom = self.root.winfo_y() + self.root.winfo_height()

    @property
    def dragging(self) -> bool:
        return self._drag is not None

    # —— 显隐与置顶 ——

    def show(self):
        self.visible = True
        self.root.deiconify()
        self.lift()

    def hide(self):
        self.visible = False
        self.root.withdraw()

    def _on_unmap(self, e):
        if e.widget is self.root and self.root.state() == "iconic":
            self.root.after_idle(self.hide)

    def toggle(self):
        self.hide() if self.visible else self.show()

    def lift(self):
        if self.visible and not self.dragging:
            self.root.attributes("-topmost", True)
            self.root.lift()
