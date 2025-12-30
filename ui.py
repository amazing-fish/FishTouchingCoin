import ctypes
import os
import threading
from datetime import datetime, timedelta

import tkinter as tk
from tkinter import messagebox
import pystray
from PIL import Image

from config import Config, SettingsDialog, SettingsManager
from storage import DataManager


class FishMoneyUI:
    def setup_window(self):
        self.root.overrideredirect(True)
        self.root.configure(bg=Config.BG_KEY_COLOR)
        self.root.wm_attributes("-transparentcolor", Config.BG_KEY_COLOR)
        self.root.attributes("-topmost", True)

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{Config.WINDOW_WIDTH}x{Config.WINDOW_HEIGHT}+{sw-150}+{sh-80}")

    def _update_windows_exstyle(self, to_toolwindow: bool):
        if os.name != "nt":
            return
        try:
            hwnd = self.root.winfo_id()
            user32 = ctypes.windll.user32
            gwl_exstyle = -20
            ws_ex_appwindow = 0x00040000
            ws_ex_toolwindow = 0x00000080
            swp_nomove = 0x0002
            swp_nosize = 0x0001
            swp_nozorder = 0x0004
            swp_framechanged = 0x0020
            exstyle = user32.GetWindowLongW(hwnd, gwl_exstyle)
            if self._original_exstyle is None:
                self._original_exstyle = exstyle
            if to_toolwindow:
                new_exstyle = (exstyle & ~ws_ex_appwindow) | ws_ex_toolwindow
            else:
                if self._original_exstyle is None:
                    return
                new_exstyle = self._original_exstyle
            if new_exstyle != exstyle:
                user32.SetWindowLongW(hwnd, gwl_exstyle, new_exstyle)
                user32.SetWindowPos(
                    hwnd,
                    0,
                    0,
                    0,
                    0,
                    0,
                    swp_nomove | swp_nosize | swp_nozorder | swp_framechanged,
                )
        except Exception:
            pass

    def create_widgets(self):
        self.canvas = tk.Canvas(
            self.root,
            width=Config.WINDOW_WIDTH,
            height=Config.WINDOW_HEIGHT,
            bg=Config.BG_KEY_COLOR,
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.canvas.pack(fill="both", expand=True)

        self.text_ids = []
        offsets = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        for ox, oy in offsets:
            tid = self.canvas.create_text(
                Config.WINDOW_WIDTH - 5 + ox, 12 + oy,
                text="",
                font=(Config.FONT_FAMILY, Config.FONT_SIZE, "bold"),
                fill=Config.COLOR_OUTLINE,
                anchor="e",
                tags=("drag",),
            )
            self.text_ids.append(tid)

        self.main_text_id = self.canvas.create_text(
            Config.WINDOW_WIDTH - 5, 12,
            text="",
            font=(Config.FONT_FAMILY, Config.FONT_SIZE, "bold"),
            fill=Config.COLOR_PAUSED,
            anchor="e",
            tags=("drag",),
        )

    # —— 5) 右键菜单 ——
    def create_context_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="暂停/继续", command=self.toggle_pause)
        self.menu.add_command(label="详情", command=self.open_details)
        self.menu.add_command(label="重新配置…", command=self.open_settings)
        self.menu.add_command(label="重置今日金额", command=self.reset_today)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.confirm_exit)

    def bind_events(self):
        # 拖动：左键
        for w in (self.root, self.canvas):
            w.bind("<ButtonPress-1>", self.start_move)
            w.bind("<B1-Motion>", self.do_move)
            w.bind("<ButtonRelease-1>", self.stop_move)

            # 右键：弹菜单
            w.bind("<Button-3>", self.show_menu)

        self.canvas.tag_bind("drag", "<ButtonPress-1>", self.start_move)
        self.canvas.tag_bind("drag", "<B1-Motion>", self.do_move)
        self.canvas.tag_bind("drag", "<ButtonRelease-1>", self.stop_move)
        self.canvas.tag_bind("drag", "<Button-3>", self.show_menu)

        # —— 4) 置顶：事件驱动反击 ——
        self.root.bind("<Map>", lambda e: self.lift_once())
        self.root.bind("<FocusOut>", lambda e: self.lift_soft())
        self.root.bind("<Visibility>", lambda e: self.lift_soft())
        self.root.bind("<Unmap>", self.on_minimize)

    # 置顶（强）
    def lift_once(self):
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
        except Exception:
            pass

    # 置顶（柔）：稍后反击，避免和某些窗口疯狂顶牛
    def lift_soft(self):
        if not self.is_visible or self.is_dragging or self.is_modal_open:
            return
        try:
            self.root.after(80, self.lift_once)
        except Exception:
            pass

    def on_minimize(self, event):
        # 最小化时收到托盘
        if self.root.state() == "iconic":
            try:
                self.root.after_idle(self.root.withdraw)
            except Exception:
                pass
            self.hide_to_tray()

    def hide_to_tray(self):
        if self.is_in_tray:
            return

        self.is_in_tray = True
        self.is_visible = False
        self._update_windows_exstyle(True)
        self.root.withdraw()
        self._start_tray_icon()

    def restore_from_tray(self):
        if not self.is_in_tray:
            return

        self.is_in_tray = False
        self.is_visible = True
        self._update_windows_exstyle(False)
        self.root.deiconify()
        try:
            self.root.state("normal")
        except Exception:
            pass
        self.lift_once()
        self._stop_tray_icon()

    def _start_tray_icon(self):
        def on_show(icon, item):
            self.root.after(0, self.restore_from_tray)

        def on_details(icon, item):
            self.root.after(0, self.open_details)

        def on_exit(icon, item):
            self.root.after(0, self.on_exit)

        def runner():
            image = self._load_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem("显示窗口", on_show),
                pystray.MenuItem("详情", on_details),
                pystray.MenuItem("退出", on_exit),
            )
            self.tray_icon = pystray.Icon("FishTouchingCoin", image, "摸鱼币", menu)
            self.tray_icon.run()

        self.tray_thread = threading.Thread(target=runner, daemon=True)
        self.tray_thread.start()

    def _stop_tray_icon(self):
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
            self.tray_thread = None

    def _load_tray_image(self):
        icon_path = os.path.join(os.path.dirname(__file__), "app.ico")
        try:
            return Image.open(icon_path)
        except Exception:
            return Image.new("RGB", (64, 64), Config.BG_KEY_COLOR)

    def open_details(self):
        if self.details_window is not None:
            try:
                if self.details_window.winfo_exists():
                    self.details_window.deiconify()
                    self.details_window.lift()
                    self.details_window.focus_force()
                    return
            except Exception:
                pass
            self.details_window = None
        if self.details_opening:
            return
        self.details_opening = True
        try:
            details = tk.Toplevel(self.root)
            self.details_window = details
            details.title("详情")
            details.resizable(False, False)
            details.attributes("-topmost", True)

            def on_details_destroy(event=None):
                if event is None or event.widget is details:
                    self.details_window = None

            def on_details_close():
                on_details_destroy()
                details.destroy()

            details.protocol("WM_DELETE_WINDOW", on_details_close)
            details.bind("<Destroy>", on_details_destroy)
        finally:
            self.details_opening = False

        now = datetime.now()
        data_map = dict(self.history)
        data_map[self.current_date] = float(self.earned_money)

        panel_bg = "#F6F7F9"
        section_bg = "#FFFFFF"
        border_color = "#E3E5E8"
        bar_bg = "#EEF2F6"
        bar_color = "#4A90E2"
        text_muted = "#6B7280"

        details.configure(bg=panel_bg)

        container = tk.Frame(details, bg=panel_bg)
        container.pack(padx=12, pady=12, fill="both", expand=True)

        tk.Label(
            container,
            text="详情概览",
            font=(Config.FONT_FAMILY, 11, "bold"),
            bg=panel_bg,
            fg="#111827",
        ).pack(anchor="w", pady=(0, 8))

        days = []
        for i in range(6, -1, -1):
            day = now.date() - timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")
            days.append((day_str, float(data_map.get(day_str, 0.0))))

        max_value = max((value for _, value in days), default=0.0)

        trend_card = tk.Frame(
            container,
            bg=section_bg,
            highlightthickness=1,
            highlightbackground=border_color,
        )
        trend_card.pack(fill="x", pady=(0, 10))

        tk.Label(
            trend_card,
            text="近7天摸鱼趋势",
            font=(Config.FONT_FAMILY, 10, "bold"),
            bg=section_bg,
            fg="#111827",
        ).pack(anchor="w", padx=10, pady=(8, 6))

        list_frame = tk.Frame(trend_card, bg=section_bg)
        list_frame.pack(padx=10, pady=(0, 10), fill="x")

        bar_canvas_width = 120
        bar_canvas_height = 8
        for day_str, value in days:
            row = tk.Frame(list_frame, bg=section_bg)
            row.pack(fill="x", pady=2)

            tk.Label(
                row,
                text=day_str,
                width=11,
                anchor="w",
                font=(Config.FONT_FAMILY, Config.FONT_SIZE),
                bg=section_bg,
                fg=text_muted,
            ).pack(side="left")

            tk.Label(
                row,
                text=f"￥{value:,.2f}",
                width=10,
                anchor="e",
                font=(Config.FONT_FAMILY, Config.FONT_SIZE),
                bg=section_bg,
                fg="#111827",
            ).pack(side="left", padx=(0, 8))

            bar_canvas = tk.Canvas(
                row,
                width=bar_canvas_width,
                height=bar_canvas_height,
                bg=section_bg,
                highlightthickness=0,
            )
            bar_canvas.pack(side="left", fill="x", expand=True)
            bar_canvas.create_rectangle(
                0,
                0,
                bar_canvas_width,
                bar_canvas_height,
                fill=bar_bg,
                outline=bar_bg,
            )
            if max_value > 0:
                fill_width = int(round((value / max_value) * bar_canvas_width))
            else:
                fill_width = 0
            if fill_width > 0:
                bar_canvas.create_rectangle(
                    0,
                    0,
                    fill_width,
                    bar_canvas_height,
                    fill=bar_color,
                    outline=bar_color,
                )

        usage_card = tk.Frame(
            container,
            bg=section_bg,
            highlightthickness=1,
            highlightbackground=border_color,
        )
        usage_card.pack(fill="x")

        tk.Label(
            usage_card,
            text="下班后最后使用时间",
            font=(Config.FONT_FAMILY, 10, "bold"),
            bg=section_bg,
            fg="#111827",
        ).pack(anchor="w", padx=10, pady=(8, 6))

        usage_frame = tk.Frame(usage_card, bg=section_bg)
        usage_frame.pack(padx=10, pady=(0, 8), fill="x")

        usage_map = dict(getattr(self, "last_after_work_usage", {}) or {})
        latest_time = None
        latest_day = None
        usage_rows = []
        for i in range(6, -1, -1):
            day = now.date() - timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")
            time_str = usage_map.get(day_str)
            usage_rows.append((day_str, time_str))
            if time_str:
                try:
                    parsed = datetime.strptime(time_str, "%H:%M").time()
                except Exception:
                    continue
                if latest_time is None or parsed > latest_time:
                    latest_time = parsed
                    latest_day = day_str

        for day_str, time_str in usage_rows:
            row = tk.Frame(usage_frame, bg=section_bg)
            row.pack(fill="x", pady=2)
            tk.Label(
                row,
                text=day_str,
                width=11,
                anchor="w",
                font=(Config.FONT_FAMILY, Config.FONT_SIZE),
                bg=section_bg,
                fg=text_muted,
            ).pack(side="left")
            tk.Label(
                row,
                text=time_str or "--:--",
                anchor="e",
                font=(Config.FONT_FAMILY, Config.FONT_SIZE),
                bg=section_bg,
                fg="#111827",
            ).pack(side="right")

        if latest_time is None:
            highlight = "近7天暂无下班后使用记录"
        else:
            highlight = f"最晚：{latest_time.strftime('%H:%M')}（{latest_day}）"
        tk.Label(
            usage_card,
            text=highlight,
            anchor="w",
            font=(Config.FONT_FAMILY, Config.FONT_SIZE),
            bg=section_bg,
            fg="#2563EB",
        ).pack(fill="x", padx=10, pady=(0, 10))

    # 拖动
    def start_move(self, event):
        self.is_dragging = True
        win_x = self.root.winfo_x()
        win_y = self.root.winfo_y()
        self.drag_offset_x = event.x_root - win_x
        self.drag_offset_y = event.y_root - win_y

    def do_move(self, event):
        if not self.is_dragging:
            return
        x = event.x_root - self.drag_offset_x
        y = event.y_root - self.drag_offset_y
        self.root.geometry(f"+{x}+{y}")

    def stop_move(self, event):
        self.is_dragging = False
        # 拖完再抬一下，避免被拖动过程夺顶后“沉下去”
        self.lift_soft()

    # 老板键：显隐
    def toggle_visibility(self):
        if self.is_in_tray:
            self.restore_from_tray()
        elif self.is_visible:
            self.root.withdraw()
            self.is_visible = False
        else:
            self.root.deiconify()
            self.is_visible = True
            self.lift_once()

    # —— 5) 右键菜单动作 ——
    def show_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._release_grab()

    def _release_grab(self):
        try:
            grab_widget = self.root.grab_current()
        except Exception:
            grab_widget = None
        if grab_widget is None:
            return
        try:
            grab_widget.grab_release()
        except Exception:
            pass

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        self.lift_soft()

    def open_settings(self):
        self._release_grab()
        if self.settings_dialog is not None:
            try:
                if self.settings_dialog.winfo_exists():
                    self.settings_dialog.deiconify()
                    self.settings_dialog.lift()
                    self.settings_dialog.focus_force()
                    return
            except Exception:
                pass
            self.settings_dialog = None

        if self._settings_opening:
            return

        self._settings_opening = True
        self.root.after_idle(self._open_settings_dialog)

    def _open_settings_dialog(self):
        if self.is_modal_open:
            self._settings_opening = False
            return
        # 打开配置：以当前 settings 为初值
        cur = SettingsManager.load_or_none() or SettingsManager.defaults()
        self.is_modal_open = True
        was_topmost = self.root.attributes("-topmost")
        self.root.attributes("-topmost", False)
        dlg = None
        try:
            dlg = SettingsDialog(self.root, cur, title="重新配置")
            self.settings_dialog = dlg
            dlg.transient(self.root)
            dlg.wait_visibility()
            dlg.focus_force()

            def finalize_dialog(event=None):
                if event is not None and event.widget is not dlg:
                    return
                self.is_modal_open = False
                self._settings_opening = False
                self.settings_dialog = None
                try:
                    if dlg.grab_current() is not None:
                        dlg.grab_release()
                    elif self.root.grab_current() is not None:
                        self.root.grab_release()
                except Exception:
                    pass
                self.root.attributes("-topmost", was_topmost)

                if dlg.result is None:
                    return

                try:
                    SettingsManager.save(dlg.result)
                    SettingsManager.apply_to_config(dlg.result)
                    self.base_salary_per_second = self.calculate_base_rate()
                    # 配置变了，避免锁屏计时残留
                    self.lock_start_time_m = None
                    self.lift_soft()
                except Exception as e:
                    messagebox.showerror("保存失败", str(e), parent=self.root)

            dlg.bind("<Destroy>", finalize_dialog)
        except Exception:
            self.is_modal_open = False
            self._settings_opening = False
            self.settings_dialog = None
            try:
                if dlg is not None and dlg.grab_current() is not None:
                    dlg.grab_release()
                elif self.root.grab_current() is not None:
                    self.root.grab_release()
            except Exception:
                pass
            self.root.attributes("-topmost", was_topmost)

    def reset_today(self):
        if not messagebox.askyesno("确认", "确定要把今日金额清零吗？", parent=self.root):
            return
        self.earned_money = 0.0
        self.lock_start_time_m = None
        try:
            DataManager.save(
                self.current_date,
                self.earned_money,
                self.settled_date,
                self.history,
                self.last_after_work_usage,
            )
        except Exception:
            pass
        self.lift_soft()

    def confirm_exit(self):
        if not messagebox.askyesno("退出", "确定退出吗？", parent=self.root):
            return
        self.on_exit()

    def on_exit(self, event=None):
        try:
            DataManager.save(
                self.current_date,
                self.earned_money,
                self.settled_date,
                self.history,
                self.last_after_work_usage,
            )
        except Exception:
            pass
        self._stop_tray_icon()
        try:
            self.root.destroy()
        except Exception:
            self.root.quit()
