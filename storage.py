import json
import logging
import os
from datetime import datetime, timedelta

from config import Config


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
    def legacy_data_files() -> list[str]:
        return StoragePaths._legacy_files(Config.LEGACY_DATA_FILE_NAMES)

    @staticmethod
    def legacy_settings_files() -> list[str]:
        return StoragePaths._legacy_files(Config.LEGACY_SETTINGS_FILE_NAMES)

    @staticmethod
    def _legacy_files(file_names: list[str]) -> list[str]:
        legacy_paths = []
        data_dir = StoragePaths.ensure_dir()
        for name in file_names:
            legacy_paths.append(os.path.abspath(name))
            legacy_paths.append(os.path.join(data_dir, name))
        return legacy_paths

    @staticmethod
    def migrate_legacy_files(legacy_paths: list[str], target_path: str):
        if os.path.exists(target_path):
            return
        for legacy_path in legacy_paths:
            if not os.path.exists(legacy_path):
                continue
            try:
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                os.replace(legacy_path, target_path)
                return
            except Exception:
                pass


# ==========================================
# 数据管理（原子写 + 损坏备份）
# ==========================================
class DataManager:
    _logger = logging.getLogger(__name__)

    @staticmethod
    def _today_str() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _prune_date_map(
        history: dict[str, float] | dict[str, str], now: datetime | None = None
    ) -> dict[str, float] | dict[str, str]:
        if not history:
            return history
        now = now or datetime.now()
        cutoff_date = now.date() - timedelta(days=Config.HISTORY_RETENTION_DAYS - 1)
        pruned: dict[str, float] | dict[str, str] = {}
        for date_key, value in history.items():
            try:
                parsed_date = datetime.strptime(date_key, "%Y-%m-%d").date()
            except Exception:
                pruned[date_key] = value
                continue
            if parsed_date >= cutoff_date:
                pruned[date_key] = value
        return pruned

    @staticmethod
    def _prune_history(history: dict[str, float], now: datetime | None = None) -> dict[str, float]:
        pruned = DataManager._prune_date_map(history, now)
        return {date_key: float(value) for date_key, value in pruned.items()}

    @staticmethod
    def load():
        today = DataManager._today_str()
        data_file = StoragePaths.data_file()
        StoragePaths.migrate_legacy_files(StoragePaths.legacy_data_files(), data_file)
        if not os.path.exists(data_file):
            return today, 0.0, "", {}, {}

        try:
            with open(data_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            _ = data.get("schema_version", Config.DATA_SCHEMA_VERSION)
            file_date = data.get("date") or today
            money = float(data.get("money", 0.0))
            settled_date = data.get("settled_date", "")
            history = data.get("history", {})
            last_after_work_usage = data.get("last_after_work_usage", {})

            return file_date, money, settled_date, history, last_after_work_usage

        except Exception:
            try:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                os.replace(data_file, f"{data_file}.corrupt.{ts}")
            except Exception:
                pass
            return today, 0.0, "", {}, {}

    @staticmethod
    def save(
        date_str: str,
        money: float,
        settled_date: str,
        history: dict[str, float],
        last_after_work_usage: dict[str, str],
    ):
        try:
            pruned_history = DataManager._prune_history(history)
            pruned_last_usage = DataManager._prune_date_map(last_after_work_usage)
            data = {
                "schema_version": Config.DATA_SCHEMA_VERSION,
                "date": date_str,
                "money": float(money),
                "settled_date": settled_date,
                "history": pruned_history,
                "last_after_work_usage": pruned_last_usage,
            }
            data_file = StoragePaths.data_file()
            tmp = data_file + ".tmp"

            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, data_file)
        except Exception:
            DataManager._logger.exception("保存数据失败")
            raise

    @staticmethod
    def append_history(history: dict[str, float], date_str: str, money: float) -> dict[str, float]:
        history[str(date_str)] = float(money)
        return DataManager._prune_history(history)
