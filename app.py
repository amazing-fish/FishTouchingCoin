import atexit
import time
from datetime import datetime

import tkinter as tk
from tkinter import messagebox

from config import Config, SettingsDialog, SettingsManager
from storage import DataManager, InstanceLock, StoragePaths
from system_utils import SystemUtils
from ui import FishMoneyUI


# ==========================================
# 主程序
# ==========================================
class FishMoneyApp(FishMoneyUI):
    def __init__(self, root: tk.Tk):
        self.root = root

        (
            self.current_date,
            self.earned_money,
            self.settled_date,
            self.history,
            self.last_after_work_usage,
        ) = DataManager.load()
        self.base_salary_per_second = self.calculate_base_rate()

        self.is_visible = True
        self.boss_key_pressed = False

        self.is_in_tray = False
        self.tray_icon = None
        self.tray_thread = None

        self.is_paused = False  # —— 右键菜单新增：暂停计费 ——

        self._original_exstyle = None
        self.is_modal_open = False
        self.settings_dialog = None
        self._settings_opening = False

        now_m = time.monotonic()
        self.last_update_time_m = now_m
        self.last_save_time_m = now_m

        self.lock_start_time_m = None

        self._last_display_text = None
        self._last_color = None
        self._last_alpha = None

        self.is_dirty = False
        self.save_requested = False

        # 置顶：事件驱动为主 + 低频兜底
        self._last_topmost_fallback_m = 0.0

        self.details_window = None
        self.details_opening = False

        # 拖动
        self.is_dragging = False
        self.drag_offset_x = 0
        self.drag_offset_y = 0

        self.setup_window()
        self.create_widgets()
        self.create_context_menu()
        self.bind_events()

        self.update_loop()

    def calculate_base_rate(self) -> float:
        daily = Config.MONTHLY_SALARY / Config.WORK_DAYS_PER_MONTH
        return daily / (Config.WORK_HOURS_PER_DAY * 3600)

    def get_rate_multiplier(self) -> float:
        wd = datetime.now().weekday()  # 0=Mon ... 5=Sat 6=Sun
        return Config.WEEKEND_MULTIPLIER if wd >= 5 else 1.0

    def get_time_status(self) -> str:
        now_time = datetime.now().time()
        if now_time < Config.WORK_START:
            return "BEFORE_WORK"
        if Config.LUNCH_START <= now_time < Config.LUNCH_END:
            return "LUNCH"
        if now_time >= Config.WORK_END:
            return "OFF_WORK"
        return "WORKING_HOURS"

    def maybe_rollover_day(self, now: datetime, now_m: float, locked_state: bool | None):
        today = now.strftime("%Y-%m-%d")
        if today != self.current_date:
            if self.settled_date != self.current_date:
                try:
                    self.history = DataManager.append_history(self.history, self.current_date, self.earned_money)
                except Exception:
                    pass
                self.settled_date = self.current_date
                self.mark_dirty(request_save=True)

            self.current_date = today
            self.earned_money = 0.0
            if locked_state is not True:
                self.lock_start_time_m = None

            self.last_update_time_m = now_m
            self.last_save_time_m = now_m

            self._last_display_text = None
            self._last_color = None
            self._last_alpha = None
            self.mark_dirty(request_save=True)

        if now.time() >= Config.WORK_END and self.settled_date != today:
            try:
                self.history = DataManager.append_history(self.history, today, self.earned_money)
            except Exception:
                pass
            self.settled_date = today
            self.mark_dirty(request_save=True)

    def mark_dirty(self, request_save: bool = False):
        self.is_dirty = True
        if request_save:
            self.save_requested = True

    def maybe_save(self, now_m: float):
        if not (self.is_dirty or self.save_requested):
            return
        if self.save_requested or (now_m - self.last_save_time_m) > Config.SAVE_INTERVAL:
            try:
                DataManager.save(
                    self.current_date,
                    self.earned_money,
                    self.settled_date,
                    self.history,
                    self.last_after_work_usage,
                )
            except Exception:
                return
            self.is_dirty = False
            self.save_requested = False
            self.last_save_time_m = now_m

    def update_ui_if_needed(self, display_text: str, color: str, alpha: float):
        if display_text == self._last_display_text and color == self._last_color and alpha == self._last_alpha:
            return

        for tid in self.text_ids:
            self.canvas.itemconfig(tid, text=display_text)
        self.canvas.itemconfig(self.main_text_id, text=display_text, fill=color)

        try:
            self.root.attributes("-alpha", alpha)
        except Exception:
            pass

        self._last_display_text = display_text
        self._last_color = color
        self._last_alpha = alpha

    def update_loop(self):
        now_m = time.monotonic()
        locked_state = SystemUtils.is_workstation_locked()
        idle_time = SystemUtils.get_idle_time()
        now = datetime.now()
        self.maybe_rollover_day(now, now_m, locked_state)

        # 老板键：边沿触发
        if SystemUtils.is_key_pressed(Config.BOSS_KEY):
            if not self.boss_key_pressed:
                self.toggle_visibility()
                self.boss_key_pressed = True
        else:
            self.boss_key_pressed = False

        # —— 4) 置顶：低频兜底（事件驱动为主）——
        self.topmost_fallback_check(now_m)

        # 隐藏时：不计费，防 delta 爆炸
        if not self.is_visible:
            self.last_update_time_m = now_m
            self.maybe_save(now_m)
            self.root.after(Config.REFRESH_RATE, self.update_loop)
            return

        # delta（钳制）
        delta = now_m - self.last_update_time_m
        self.last_update_time_m = now_m
        if delta < 0:
            delta = 0.0
        if delta > Config.MAX_DELTA:
            delta = Config.MAX_DELTA

        time_status = self.get_time_status()
        self.maybe_update_last_after_work_usage(time_status, now, idle_time, locked_state)

        display_text = ""
        main_color = Config.COLOR_PAUSED
        alpha = 0.6

        mult = self.get_rate_multiplier()
        rate = self.base_salary_per_second * mult

        earned_before = self.earned_money

        # 暂停：任何状态都不加钱，但仍显示
        if self.is_paused:
            display_text = f"⏸ {self.earned_money:.4f}"
            main_color = "#B0B0B0"
            alpha = 0.75
            self.lock_start_time_m = None
            self.update_ui_if_needed(display_text, main_color, alpha)
            if self.earned_money != earned_before:
                self.mark_dirty()
            self.maybe_save(now_m)
            self.root.after(Config.REFRESH_RATE, self.update_loop)
            return

        if time_status == "BEFORE_WORK":
            display_text = f"🌙 {self.earned_money:.4f}"
            main_color = Config.COLOR_PAUSED
            alpha = 0.7
            if locked_state is True:
                if self.lock_start_time_m is None:
                    self.lock_start_time_m = now_m
            else:
                self.lock_start_time_m = None

        elif time_status == "LUNCH":
            display_text = f"🍱 {self.earned_money:.4f}"
            main_color = "#FFA500"
            alpha = 0.85
            self.lock_start_time_m = None

        elif time_status == "OFF_WORK":
            display_text = f"🏠 {self.earned_money:.4f}"
            main_color = "#00BFFF"
            alpha = 0.85
            self.lock_start_time_m = None

        else:
            # 工作时段：分锁屏 / 非锁屏 / 未知锁屏
            if locked_state is True:
                if self.lock_start_time_m is None:
                    self.lock_start_time_m = now_m

                locked_duration = now_m - self.lock_start_time_m
                if locked_duration <= Config.LOCK_GRACE_PERIOD:
                    self.earned_money += rate * delta
                    display_text = f"🚽 {self.earned_money:.4f}"
                    main_color = Config.COLOR_TOILET
                    alpha = 1.0
                else:
                    display_text = f"🛑 {self.earned_money:.4f}"
                    main_color = "#FF4500"
                    alpha = 0.85

            elif locked_state is None:
                # 保守策略：锁屏状态未知 -> 不走“锁屏带薪”逻辑，避免误判
                # 仍然允许 idle 计费（你也可以改成完全停计费，看你想保守到哪一步）
                self.lock_start_time_m = None
                if idle_time >= Config.IDLE_THRESHOLD:
                    self.earned_money += rate * delta
                    display_text = f"?? {self.earned_money:.4f}"
                    main_color = "#E6E6FA"  # 淡紫：提示“锁屏未知”
                    alpha = 0.95
                else:
                    display_text = f"Zz {self.earned_money:.4f}"
                    main_color = Config.COLOR_PAUSED
                    alpha = 0.55

            else:
                # locked_state is False
                self.lock_start_time_m = None
                if idle_time >= Config.IDLE_THRESHOLD:
                    self.earned_money += rate * delta
                    display_text = f"$$ {self.earned_money:.4f}"
                    main_color = Config.COLOR_EARNING
                    alpha = 1.0
                else:
                    display_text = f"Zz {self.earned_money:.4f}"
                    main_color = Config.COLOR_PAUSED
                    alpha = 0.55

        self.update_ui_if_needed(display_text, main_color, alpha)

        if self.earned_money != earned_before:
            self.mark_dirty()
        self.maybe_save(now_m)

        self.root.after(Config.REFRESH_RATE, self.update_loop)

    # 置顶兜底：低频检查
    def topmost_fallback_check(self, now_m: float):
        if self.is_dragging or not self.is_visible or self.is_modal_open:
            return
        if (now_m - self._last_topmost_fallback_m) < Config.TOPMOST_FALLBACK_CHECK_INTERVAL:
            return
        self._last_topmost_fallback_m = now_m
        # 不做频繁反复 set topmost，只偶尔 lift 一次
        self.lift_soft()

    def maybe_update_last_after_work_usage(
        self,
        time_status: str,
        now: datetime,
        idle_time: float,
        locked_state: bool | None,
    ):
        if time_status != "OFF_WORK":
            return
        if locked_state is True:
            return
        if idle_time >= Config.IDLE_THRESHOLD:
            return
        today = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")
        if self.last_after_work_usage.get(today) != time_str:
            self.last_after_work_usage[today] = time_str
            self.mark_dirty()


def ensure_single_instance() -> InstanceLock | None:
    lock = InstanceLock(StoragePaths.instance_lock_file())
    if lock.acquire():
        atexit.register(lock.release)
        return lock
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("已在运行", "程序已在运行，请先关闭现有实例。")
        root.destroy()
    except Exception:
        pass
    return None


def main():
    instance_lock = ensure_single_instance()
    if instance_lock is None:
        return

    root = tk.Tk()
    root.withdraw()  # 先隐藏主窗体，避免闪一下

    settings = SettingsManager.load_or_none()
    if settings is None:
        dlg = SettingsDialog(root, SettingsManager.defaults(), title="首次启动配置")
        root.wait_window(dlg)
        settings = dlg.result or SettingsManager.defaults()
        SettingsManager.save(settings)

    SettingsManager.apply_to_config(settings)

    root.deiconify()
    app = FishMoneyApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
