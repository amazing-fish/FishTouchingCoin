import tkinter as tk

from ..infra import windows


def present(win: tk.Toplevel, width: int | None = None, height: int | None = None, caption: str | None = None):
    """居中后再显示。调用方须在创建后立即 withdraw()，否则 Tk 会先在默认位置（左上）映射一次再跳到中央。"""
    win.update_idletasks()
    w = width or win.winfo_reqwidth()
    h = height or win.winfo_reqheight()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"{w}x{h}+{(sw - w) // 2}+{int((sh - h) / 2.4)}")
    win.deiconify()
    if caption:
        windows.set_caption_color(win, caption)
    win.lift()
    win.focus_force()
