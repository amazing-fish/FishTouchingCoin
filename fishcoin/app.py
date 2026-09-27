"""组装根：采样 → Meter.tick → 渲染 → 节流落盘。所有 Tk 操作都在主线程。"""

import logging
import time
import tkinter as tk
from datetime import datetime
from logging.handlers import RotatingFileHandler
from tkinter import messagebox

from . import APP_TITLE, APP_VERSION
from .domain.meter import Meter, Sample
from .domain.schedule import is_weekend
from .domain.settings import Settings
from .infra import windows
from .infra.storage import Store, data_dir
from .resources import resource
from .ui import theme
from .ui.details import DetailsWindow, Snapshot
from .ui.menu import MenuItem, PopupMenu
from .ui.overlay import Overlay
from .ui.settings_dialog import SettingsDialog
from .ui.tray import Tray

log = logging.getLogger(__name__)

TICK_MS = 100
SAVE_INTERVAL_S = 10.0
LIFT_INTERVAL_S = 2.0
TITLE_INTERVAL_S = 1.0
RETENTION_DAYS = 365
BOSS_KEY = windows.VK_F9


class App:
    def __init__(self, root: tk.Tk, store: Store, settings: Settings):
        self.root = root
        self.store = store
        self.fonts = theme.Fonts(root)
        self.icon = resource("app.ico")

        today = datetime.now().date()
        self.today = today
        ledger = store.load_ledger()
        ledger.prune(today, RETENTION_DAYS)
        self.meter = Meter(settings, ledger)
        self.lock = windows.LockProbe()
        self.paused = False
        self.closing = False

        self.menu = PopupMenu(root, self.fonts)
        self.overlay = Overlay(root, self.fonts, on_menu=self.open_menu, on_double_click=self.open_details)
        self.tray = Tray(self.icon)
        self.details: DetailsWindow | None = None
        self.settings_dialog: SettingsDialog | None = None

        now_m = time.monotonic()
        self._saved_at = now_m
        self._lifted_at = now_m
        self._titled_at = 0.0
        self._boss_down = False

        root.report_callback_exception = self._report_tk_error
        self._tick()

    # —— 主循环 ——

    def _tick(self):
        if self.closing:
            return
        try:
            self._step()
        except Exception:
            log.exception("主循环异常")
        finally:
            if not self.closing:
                self.root.after(TICK_MS, self._tick)

    def _step(self):
        now, mono = datetime.now(), time.monotonic()
        status = self.meter.tick(Sample(now=now, mono=mono, idle_s=windows.idle_seconds(),
                                        locked=self.lock.locked(), paused=self.paused))
        if now.date() != self.today:
            self.today = now.date()
            self.meter.ledger.prune(self.today, RETENTION_DAYS)

        settings = self.meter.settings
        today_money = self.meter.ledger.get(self.today).money
        mult = settings.weekend_multiplier if is_weekend(self.today) else 1.0
        self.overlay.render(status, today_money, mult)

        # 老板键：边沿触发
        down = windows.key_down(BOSS_KEY)
        if down and not self._boss_down:
            self.toggle_overlay()
        self._boss_down = down

        for event in self.tray.drain():
            self._on_tray(event)

        if mono - self._lifted_at >= LIFT_INTERVAL_S:
            self._lifted_at = mono
            if not self.menu.is_open:
                self.overlay.lift()

        if mono - self._titled_at >= TITLE_INTERVAL_S:
            self._titled_at = mono
            # 托盘提示保持中性，不出现“摸鱼”等字样
            self.tray.set_title(f"今日 {today_money:,.2f}")

        if self.meter.dirty and mono - self._saved_at >= SAVE_INTERVAL_S:
            self.save()

    def save(self):
        self._saved_at = time.monotonic()
        try:
            self.store.save_ledger(self.meter.ledger)
            self.meter.dirty = False
        except OSError:
            log.exception("保存账本失败")

    def _report_tk_error(self, exc, val, tb):
        log.error("Tk 回调异常", exc_info=(exc, val, tb))

    # —— 交互 ——

    def _on_tray(self, event: str):
        {
            "toggle": self.toggle_overlay,
            "details": self.open_details,
            "settings": self.open_settings,
            "quit": self.quit,
        }[event]()

    def toggle_overlay(self):
        self.menu.close()
        self.overlay.toggle()

    def open_menu(self, x: int, y: int):
        autostart = windows.autostart_enabled()
        self.menu.open(x, y, [
            MenuItem("继续计费" if self.paused else "暂停计费", self.toggle_pause),
            MenuItem("详情", self.open_details),
            MenuItem("配置…", self.open_settings),
            MenuItem("开机自启", self.toggle_autostart, checked=autostart),
            MenuItem("隐藏", self.toggle_overlay, hint="F9"),
            MenuItem.separator(),
            MenuItem("重置今日金额", self.reset_today),
            MenuItem("退出", self.confirm_quit, danger=True),
        ])

    def toggle_pause(self):
        self.paused = not self.paused

    def toggle_autostart(self):
        self._set_autostart(not windows.autostart_enabled())

    def _set_autostart(self, enabled: bool):
        try:
            windows.set_autostart(enabled)
        except OSError:
            log.exception("设置开机自启失败")
            messagebox.showwarning("开机自启", "设置失败：没有注册表写入权限。")

    def reset_today(self):
        if messagebox.askyesno("重置", "确定把今日金额清零吗？", icon="warning"):
            self.meter.ledger.reset(self.today)
            self.save()

    def confirm_quit(self):
        if messagebox.askyesno("退出", "确定退出摸鱼币吗？"):
            self.quit()

    def quit(self):
        self.closing = True
        self.menu.close()
        self.save()
        self.tray.stop()
        self.root.destroy()

    def _snapshot(self) -> Snapshot:
        return Snapshot(self.today, self.meter.status, self.meter.settings, self.meter.ledger)

    def open_details(self):
        if self.details and self.details.exists():
            self.details.focus()
            return
        self.details = DetailsWindow(self.root, self.fonts, self._snapshot, self.icon)

    def open_settings(self):
        if self.settings_dialog and self.settings_dialog.exists():
            self.settings_dialog.focus()
            return
        before = windows.autostart_enabled()

        def done(settings: Settings, autostart: bool):
            try:
                self.store.save_settings(settings)
            except OSError:
                log.exception("保存配置失败")
                messagebox.showerror("配置", "保存配置失败，详见日志。")
                return
            self.meter.update_settings(settings)
            if autostart != before:
                self._set_autostart(autostart)

        self.settings_dialog = SettingsDialog(self.root, self.fonts, self.meter.settings, before,
                                              first_run=False, on_done=done, icon=self.icon)


def first_run(root: tk.Tk, store: Store) -> Settings:
    result: dict = {}

    def done(settings: Settings, autostart: bool):
        result["settings"], result["autostart"] = settings, autostart

    dlg = SettingsDialog(root, theme.Fonts(root), Settings(), False, first_run=True, on_done=done,
                         icon=resource("app.ico"))
    root.wait_window(dlg.win)
    settings = result.get("settings", Settings())
    store.save_settings(settings)
    if result.get("autostart"):
        try:
            windows.set_autostart(True)
        except OSError:
            log.exception("设置开机自启失败")
    return settings


def setup_logging():
    handler = RotatingFileHandler(data_dir() / "app.log", maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main():
    setup_logging()
    log.info("启动 %s", APP_VERSION)
    windows.enable_dpi_awareness()

    instance = windows.SingleInstance()
    if instance.already_running:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(APP_TITLE, "摸鱼币已在运行，可在任务栏托盘找到它。")
        root.destroy()
        return

    try:
        root = tk.Tk()
        root.withdraw()
        root.title(APP_TITLE)
        if icon := resource("app.ico"):
            root.iconbitmap(default=icon)

        store = Store()
        settings = store.load_settings() or first_run(root, store)
        App(root, store, settings)
        root.deiconify()
        root.mainloop()
    finally:
        instance.release()
        log.info("退出")
