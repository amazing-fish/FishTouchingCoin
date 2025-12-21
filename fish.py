import tkinter as tk
from tkinter import messagebox
import ctypes
from ctypes import wintypes
import time
import json
import os
from datetime import datetime, time as dtime, timedelta
import threading

import pystray
from PIL import Image


# ==========================================
# 配置区域 (Configuration)
# ==========================================
class Config:
    # —— 会被首次配置覆盖的参数（默认值）——
    MONTHLY_SALARY = 20000.0
    WORK_DAYS_PER_MONTH = 21.75
    WORK_HOURS_PER_DAY = 8.0
    IDLE_THRESHOLD = 3.0  # 秒

    # 允许的锁屏摸鱼时长 (秒) -> 默认 30 分钟
    LOCK_GRACE_PERIOD = 30 * 60

    LUNCH_START = dtime(12, 0)
    LUNCH_END = dtime(14, 0)
    WORK_END = dtime(18, 0)

    # 周末摸鱼倍率
    WEEKEND_MULTIPLIER = 2.0

    # —— UI 配置（一般不需要首次配置）——
    FONT_SIZE = 9
    FONT_FAMILY = "Verdana"
    COLOR_EARNING = "#FFD700"
    COLOR_TOILET = "#00FF7F"
    COLOR_PAUSED = "#AAAAAA"
    COLOR_OUTLINE = "#000000"
    BG_KEY_COLOR = "#000001"

    WINDOW_WIDTH = 130
    WINDOW_HEIGHT = 25
    REFRESH_RATE = 100  # ms

    BOSS_KEY = 0x78  # F9

    # 数据文件
    DATA_FILE_NAME = "fish_data_v1.5.json"
    SETTINGS_FILE_NAME = "fish_settings_v1.json"

    # 稳定性参数
    MAX_DELTA = 1.0
    SAVE_INTERVAL = 10.0

    # 置顶兜底检查（很低频，避免顶牛）
    TOPMOST_FALLBACK_CHECK_INTERVAL = 2.0


# ==========================================
# 路径管理（本地数据持久化）
# ==========================================
class StoragePaths:
    @staticmethod
    def data_dir() -> str:
        appdata = os.getenv("APPDATA")
        if appdata:
            base = appdata
        else:
            base = os.getenv("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        return os.path.join(base, "FishTouchingCoin")

    @staticmethod
    def ensure_dir() -> str:
        path = StoragePaths.data_dir()
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def data_file() -> str:
        return os.path.join(StoragePaths.ensure_dir(), Config.DATA_FILE_NAME)

    @staticmethod
    def settings_file() -> str:
        return os.path.join(StoragePaths.ensure_dir(), Config.SETTINGS_FILE_NAME)

    @staticmethod
    def legacy_data_file() -> str:
        return os.path.abspath(Config.DATA_FILE_NAME)

    @staticmethod
    def legacy_settings_file() -> str:
        return os.path.abspath(Config.SETTINGS_FILE_NAME)

    @staticmethod
    def migrate_legacy_file(legacy_path: str, target_path: str):
        if os.path.exists(target_path) or not os.path.exists(legacy_path):
            return
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            os.replace(legacy_path, target_path)
        except Exception:
            pass


# ==========================================
# Settings 管理（首次启动配置）
# ==========================================
class SettingsManager:
    @staticmethod
    def defaults() -> dict:
        return {
            "MONTHLY_SALARY": Config.MONTHLY_SALARY,
            "WORK_DAYS_PER_MONTH": Config.WORK_DAYS_PER_MONTH,
            "WORK_HOURS_PER_DAY": Config.WORK_HOURS_PER_DAY,
            "IDLE_THRESHOLD": Config.IDLE_THRESHOLD,
            "LOCK_GRACE_PERIOD_MIN": int(Config.LOCK_GRACE_PERIOD / 60),
            "LUNCH_START": Config.LUNCH_START.strftime("%H:%M"),
            "LUNCH_END": Config.LUNCH_END.strftime("%H:%M"),
            "WORK_END": Config.WORK_END.strftime("%H:%M"),
            "WEEKEND_MULTIPLIER": Config.WEEKEND_MULTIPLIER,
        }

    @staticmethod
    def load_or_none() -> dict | None:
        settings_file = StoragePaths.settings_file()
        StoragePaths.migrate_legacy_file(StoragePaths.legacy_settings_file(), settings_file)
        if not os.path.exists(settings_file):
            return None
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # 配置损坏：备份并当作首次启动
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                os.replace(settings_file, f"{settings_file}.corrupt.{ts}")
            except Exception:
                pass
            return None

    @staticmethod
    def save(settings: dict):
        settings_file = StoragePaths.settings_file()
        tmp = settings_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, settings_file)

    @staticmethod
    def apply_to_config(settings: dict):
        # 数值
        Config.MONTHLY_SALARY = float(settings["MONTHLY_SALARY"])
        Config.WORK_DAYS_PER_MONTH = float(settings["WORK_DAYS_PER_MONTH"])
        Config.WORK_HOURS_PER_DAY = float(settings["WORK_HOURS_PER_DAY"])
        Config.IDLE_THRESHOLD = float(settings["IDLE_THRESHOLD"])
        Config.WEEKEND_MULTIPLIER = float(settings["WEEKEND_MULTIPLIER"])

        # 分钟 -> 秒
        lock_min = float(settings["LOCK_GRACE_PERIOD_MIN"])
        Config.LOCK_GRACE_PERIOD = int(lock_min * 60)

        # 时间
        Config.LUNCH_START = SettingsManager._parse_hhmm(settings["LUNCH_START"])
        Config.LUNCH_END = SettingsManager._parse_hhmm(settings["LUNCH_END"])
        Config.WORK_END = SettingsManager._parse_hhmm(settings["WORK_END"])

    @staticmethod
    def _parse_hhmm(s: str) -> dtime:
        dt = datetime.strptime(s.strip(), "%H:%M")
        return dtime(dt.hour, dt.minute)


class SettingsDialog(tk.Toplevel):
    """配置弹窗（首次启动 / 手动重新配置）。"""

    def __init__(self, master: tk.Tk, initial: dict, title="配置"):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self.result = None

        self.vars = {
            "MONTHLY_SALARY": tk.StringVar(value=str(initial["MONTHLY_SALARY"])),
            "WORK_DAYS_PER_MONTH": tk.StringVar(value=str(initial["WORK_DAYS_PER_MONTH"])),
            "WORK_HOURS_PER_DAY": tk.StringVar(value=str(initial["WORK_HOURS_PER_DAY"])),
            "IDLE_THRESHOLD": tk.StringVar(value=str(initial["IDLE_THRESHOLD"])),
            "LOCK_GRACE_PERIOD_MIN": tk.StringVar(value=str(initial["LOCK_GRACE_PERIOD_MIN"])),
            "LUNCH_START": tk.StringVar(value=str(initial["LUNCH_START"])),
            "LUNCH_END": tk.StringVar(value=str(initial["LUNCH_END"])),
            "WORK_END": tk.StringVar(value=str(initial["WORK_END"])),
            "WEEKEND_MULTIPLIER": tk.StringVar(value=str(initial["WEEKEND_MULTIPLIER"])),
        }

        self._build_ui()
        self._center()

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # 模态
        self.grab_set()
        self.focus_force()

    def _build_ui(self):
        pad = 10
        frm = tk.Frame(self)
        frm.pack(padx=pad, pady=pad)

        def row(r, label, key, hint=""):
            tk.Label(frm, text=label, anchor="w", width=18).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=4)
            tk.Entry(frm, textvariable=self.vars[key], width=18).grid(row=r, column=1, sticky="w", pady=4)
            if hint:
                tk.Label(frm, text=hint, fg="#666666", anchor="w").grid(row=r, column=2, sticky="w", padx=(8, 0), pady=4)

        row(0, "月薪", "MONTHLY_SALARY", "例如 20000")
        row(1, "月工作天数", "WORK_DAYS_PER_MONTH", "例如 21.75")
        row(2, "日工作时长(小时)", "WORK_HOURS_PER_DAY", "例如 8")
        row(3, "摸鱼判定阈值(秒)", "IDLE_THRESHOLD", "空闲≥此值算摸鱼")
        row(4, "锁屏带薪时长(分钟)", "LOCK_GRACE_PERIOD_MIN", "例如 30")
        row(5, "午休开始(HH:MM)", "LUNCH_START", "例如 12:00")
        row(6, "午休结束(HH:MM)", "LUNCH_END", "例如 14:00")
        row(7, "下班时间(HH:MM)", "WORK_END", "例如 18:00")
        row(8, "周末倍率", "WEEKEND_MULTIPLIER", "例如 2")

        btns = tk.Frame(self)
        btns.pack(padx=pad, pady=(0, pad), fill="x")

        tk.Button(btns, text="保存", command=self._on_ok, width=10).pack(side="right", padx=(6, 0))
        tk.Button(btns, text="取消", command=self._on_cancel, width=10).pack(side="right")

    def _center(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"+{x}+{y}")

    def _on_cancel(self):
        self.result = None
        self.destroy()

    def _on_ok(self):
        try:
            s = {k: v.get().strip() for k, v in self.vars.items()}

            # 数值校验
            s["MONTHLY_SALARY"] = float(s["MONTHLY_SALARY"])
            s["WORK_DAYS_PER_MONTH"] = float(s["WORK_DAYS_PER_MONTH"])
            s["WORK_HOURS_PER_DAY"] = float(s["WORK_HOURS_PER_DAY"])
            s["IDLE_THRESHOLD"] = float(s["IDLE_THRESHOLD"])
            s["LOCK_GRACE_PERIOD_MIN"] = float(s["LOCK_GRACE_PERIOD_MIN"])
            s["WEEKEND_MULTIPLIER"] = float(s["WEEKEND_MULTIPLIER"])

            if s["MONTHLY_SALARY"] <= 0:
                raise ValueError("月薪必须 > 0")
            if s["WORK_DAYS_PER_MONTH"] <= 0:
                raise ValueError("月工作天数必须 > 0")
            if s["WORK_HOURS_PER_DAY"] <= 0:
                raise ValueError("日工作时长必须 > 0")
            if s["IDLE_THRESHOLD"] < 0:
                raise ValueError("摸鱼阈值不能为负")
            if s["LOCK_GRACE_PERIOD_MIN"] < 0:
                raise ValueError("锁屏带薪分钟数不能为负")
            if s["WEEKEND_MULTIPLIER"] <= 0:
                raise ValueError("周末倍率必须 > 0")

            # 时间格式校验
            SettingsManager._parse_hhmm(s["LUNCH_START"])
            SettingsManager._parse_hhmm(s["LUNCH_END"])
            SettingsManager._parse_hhmm(s["WORK_END"])

            # 午休逻辑校验
            ls = SettingsManager._parse_hhmm(s["LUNCH_START"])
            le = SettingsManager._parse_hhmm(s["LUNCH_END"])
            if not (ls < le):
                raise ValueError("午休开始必须早于午休结束")

            self.result = s
            self.destroy()

        except Exception as e:
            messagebox.showerror("配置有误", str(e), parent=self)


# ==========================================
# 系统底层 API
# ==========================================
class SystemUtils:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    @staticmethod
    def get_idle_time() -> float:
        lii = SystemUtils.LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(SystemUtils.LASTINPUTINFO)
        if not SystemUtils.user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        now = SystemUtils.kernel32.GetTickCount()
        elapsed_ms = (now - lii.dwTime) & 0xFFFFFFFF
        return elapsed_ms / 1000.0

    @staticmethod
    def is_workstation_locked() -> bool | None:
        """
        更稳的锁屏检测：返回 True/False/None(未知)
        - OpenInputDesktop 可用时较可靠
        - 但在某些权限/远程/安全软件环境会失败：此时返回 None，不做武断误判
        """
        DESKTOP_SWITCHDESKTOP = 0x0100
        try:
            hDesktop = SystemUtils.user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
            if hDesktop == 0:
                return True
            SystemUtils.user32.CloseDesktop(hDesktop)
            return False
        except Exception:
            return None

    @staticmethod
    def is_key_pressed(vk_code: int) -> bool:
        return bool(SystemUtils.user32.GetAsyncKeyState(vk_code) & 0x8000)


# ==========================================
# 数据管理（原子写 + 损坏备份）
# ==========================================
class DataManager:
    @staticmethod
    def _today_str() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def load():
        today = DataManager._today_str()
        data_file = StoragePaths.data_file()
        StoragePaths.migrate_legacy_file(StoragePaths.legacy_data_file(), data_file)
        if not os.path.exists(data_file):
            return today, 0.0, "", {}

        try:
            with open(data_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            file_date = data.get("date") or today
            money = float(data.get("money", 0.0))
            settled_date = data.get("settled_date", "")
            history = data.get("history", {})

            return file_date, money, settled_date, history

        except Exception:
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                os.replace(data_file, f"{data_file}.corrupt.{ts}")
            except Exception:
                pass
            return today, 0.0, "", {}

    @staticmethod
    def save(date_str: str, money: float, settled_date: str, history: dict[str, float]):
        data = {
            "date": date_str,
            "money": float(money),
            "settled_date": settled_date,
            "history": history,
        }
        data_file = StoragePaths.data_file()
        tmp = data_file + ".tmp"

        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, data_file)

    @staticmethod
    def append_history(history: dict[str, float], date_str: str, money: float) -> dict[str, float]:
        history[str(date_str)] = float(money)
        return history


# ==========================================
# 主程序
# ==========================================
class FishMoneyApp:
    def __init__(self, root: tk.Tk):
        self.root = root

        (
            self.current_date,
            self.earned_money,
            self.settled_date,
            self.history,
        ) = DataManager.load()
        self.base_salary_per_second = self.calculate_base_rate()

        self.is_visible = True
        self.boss_key_pressed = False

        self.is_in_tray = False
        self.tray_icon = None
        self.tray_thread = None

        self.is_paused = False  # —— 右键菜单新增：暂停计费 ——

        self._original_exstyle = None

        now_m = time.monotonic()
        self.last_update_time_m = now_m
        self.last_save_time_m = now_m

        self.lock_start_time_m = None

        self._last_display_text = None
        self._last_color = None
        self._last_alpha = None

        # 置顶：事件驱动为主 + 低频兜底
        self._last_topmost_fallback_m = 0.0

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
        if not self.is_visible or self.is_dragging:
            return
        try:
            self.root.after(80, self.lift_once)
        except Exception:
            pass

    # 置顶兜底：低频检查
    def topmost_fallback_check(self, now_m: float):
        if self.is_dragging or not self.is_visible:
            return
        if (now_m - self._last_topmost_fallback_m) < Config.TOPMOST_FALLBACK_CHECK_INTERVAL:
            return
        self._last_topmost_fallback_m = now_m
        # 不做频繁反复 set topmost，只偶尔 lift 一次
        self.lift_soft()

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
        details = tk.Toplevel(self.root)
        details.title("详情")
        details.resizable(False, False)
        details.attributes("-topmost", True)

        now = datetime.now()
        data_map = dict(self.history)
        data_map[self.current_date] = float(self.earned_money)

        days = []
        for i in range(6, -1, -1):
            day = now.date() - timedelta(days=i)
            day_str = day.strftime("%Y-%m-%d")
            days.append((day_str, float(data_map.get(day_str, 0.0))))

        max_value = max((value for _, value in days), default=0.0)
        bar_width = 20

        header = tk.Label(details, text="近7天摸鱼趋势", font=(Config.FONT_FAMILY, 10, "bold"))
        header.pack(padx=12, pady=(12, 6))

        list_frame = tk.Frame(details)
        list_frame.pack(padx=12, pady=(0, 12), fill="both", expand=True)

        for day_str, value in days:
            if max_value > 0:
                bar_count = int(round((value / max_value) * bar_width))
            else:
                bar_count = 0
            bar_text = "█" * bar_count
            row_text = f"{day_str}  ￥{value:,.2f}  {bar_text}"
            tk.Label(list_frame, text=row_text, anchor="w", font=(Config.FONT_FAMILY, Config.FONT_SIZE)).pack(
                fill="x"
            )

    def get_time_status(self) -> str:
        now_time = datetime.now().time()
        if Config.LUNCH_START <= now_time < Config.LUNCH_END:
            return "LUNCH"
        if now_time >= Config.WORK_END:
            return "OFF_WORK"
        return "WORKING_HOURS"

    def maybe_rollover_day(self):
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if today != self.current_date:
            if self.settled_date != self.current_date:
                try:
                    self.history = DataManager.append_history(self.history, self.current_date, self.earned_money)
                except Exception:
                    pass
                self.settled_date = self.current_date

            self.current_date = today
            self.earned_money = 0.0
            self.lock_start_time_m = None

            now_m = time.monotonic()
            self.last_update_time_m = now_m
            self.last_save_time_m = now_m

            self._last_display_text = None
            self._last_color = None
            self._last_alpha = None
            try:
                DataManager.save(self.current_date, self.earned_money, self.settled_date, self.history)
            except Exception:
                pass

        if now.time() >= Config.WORK_END and self.settled_date != today:
            try:
                self.history = DataManager.append_history(self.history, today, self.earned_money)
            except Exception:
                pass
            self.settled_date = today
            try:
                DataManager.save(self.current_date, self.earned_money, self.settled_date, self.history)
            except Exception:
                pass

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
        self.maybe_rollover_day()

        # 老板键：边沿触发
        if SystemUtils.is_key_pressed(Config.BOSS_KEY):
            if not self.boss_key_pressed:
                self.toggle_visibility()
                self.boss_key_pressed = True
        else:
            self.boss_key_pressed = False

        now_m = time.monotonic()

        # —— 4) 置顶：低频兜底（事件驱动为主）——
        self.topmost_fallback_check(now_m)

        # 隐藏时：不计费，防 delta 爆炸
        if not self.is_visible:
            self.last_update_time_m = now_m
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

        # —— 3) 锁屏三态（True/False/None）——
        locked_state = SystemUtils.is_workstation_locked()
        idle_time = SystemUtils.get_idle_time()

        display_text = ""
        main_color = Config.COLOR_PAUSED
        alpha = 0.6

        mult = self.get_rate_multiplier()
        rate = self.base_salary_per_second * mult

        # 暂停：任何状态都不加钱，但仍显示
        if self.is_paused:
            display_text = f"⏸ {self.earned_money:.4f}"
            main_color = "#B0B0B0"
            alpha = 0.75
            self.lock_start_time_m = None
            self.update_ui_if_needed(display_text, main_color, alpha)
            self.root.after(Config.REFRESH_RATE, self.update_loop)
            return

        if time_status == "LUNCH":
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

        # 定时保存
        if (now_m - self.last_save_time_m) > Config.SAVE_INTERVAL:
            try:
                DataManager.save(self.current_date, self.earned_money, self.settled_date, self.history)
            except Exception:
                pass
            self.last_save_time_m = now_m

        self.root.after(Config.REFRESH_RATE, self.update_loop)

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
            try:
                self.menu.grab_release()
            except Exception:
                pass

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        self.lift_soft()

    def open_settings(self):
        # 打开配置：以当前 settings 为初值
        cur = SettingsManager.load_or_none() or SettingsManager.defaults()
        dlg = SettingsDialog(self.root, cur, title="重新配置")
        self.root.wait_window(dlg)
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

    def reset_today(self):
        if not messagebox.askyesno("确认", "确定要把今日金额清零吗？", parent=self.root):
            return
        self.earned_money = 0.0
        self.lock_start_time_m = None
        try:
            DataManager.save(self.current_date, self.earned_money, self.settled_date, self.history)
        except Exception:
            pass
        self.lift_soft()

    def confirm_exit(self):
        if not messagebox.askyesno("退出", "确定退出吗？", parent=self.root):
            return
        self.on_exit()

    def on_exit(self, event=None):
        try:
            DataManager.save(self.current_date, self.earned_money, self.settled_date, self.history)
        except Exception:
            pass
        self._stop_tray_icon()
        try:
            self.root.destroy()
        except Exception:
            self.root.quit()


# ==========================================
# 启动入口：首次配置 -> 应用配置 -> 启动悬浮窗
# ==========================================
if __name__ == "__main__":
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
