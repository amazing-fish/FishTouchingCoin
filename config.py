import json
import os
import tkinter as tk
from tkinter import messagebox
from datetime import datetime, time as dtime


# ==========================================
# 配置区域 (Configuration)
# ==========================================
class Config:
    APP_VERSION = "v0.4.0"
    APP_VERSION_TYPE = "feature"

    # —— 会被首次配置覆盖的参数（默认值）——
    MONTHLY_SALARY = 20000.0
    WORK_DAYS_PER_MONTH = 21.75
    WORK_HOURS_PER_DAY = 8.0
    IDLE_THRESHOLD = 3.0  # 秒

    # 允许的锁屏摸鱼时长 (秒) -> 默认 30 分钟
    LOCK_GRACE_PERIOD = 30 * 60

    LUNCH_START = dtime(12, 0)
    LUNCH_END = dtime(14, 0)
    WORK_START = dtime(9, 0)
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
    DATA_SCHEMA_VERSION = 1
    SETTINGS_SCHEMA_VERSION = 1
    DATA_FILE_NAME = f"data_schema_v{DATA_SCHEMA_VERSION}.json"
    SETTINGS_FILE_NAME = f"settings_schema_v{SETTINGS_SCHEMA_VERSION}.json"
    LEGACY_DATA_FILE_NAMES = ["fish_data_v1.5.json"]
    LEGACY_SETTINGS_FILE_NAMES = ["fish_settings_v1.json"]

    # 稳定性参数
    MAX_DELTA = 1.0
    SAVE_INTERVAL = 10.0
    HISTORY_RETENTION_DAYS = 365

    # 置顶兜底检查（很低频，避免顶牛）
    TOPMOST_FALLBACK_CHECK_INTERVAL = 2.0


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
        from storage import StoragePaths

        settings_file = StoragePaths.settings_file()
        StoragePaths.migrate_legacy_files(StoragePaths.legacy_settings_files(), settings_file)
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
        from storage import StoragePaths

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

        # 模态（延迟到窗口可见后再 grab，避免菜单残留 grab 导致弹窗闪退）
        self.after_idle(self._activate_modal)

    def _activate_modal(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

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
            we = SettingsManager._parse_hhmm(s["WORK_END"])
            if not (Config.WORK_START < we):
                raise ValueError("下班时间必须晚于上班时间")
            if not (ls >= Config.WORK_START):
                raise ValueError("午休开始必须晚于上班时间")
            if not (le <= we):
                raise ValueError("午休结束必须早于下班时间")

            self.result = s
            self.destroy()

        except Exception as e:
            messagebox.showerror("配置有误", str(e), parent=self)
