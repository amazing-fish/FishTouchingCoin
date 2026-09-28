import json
import logging
import os
from datetime import datetime
from pathlib import Path

from .. import APP_NAME
from ..domain.ledger import Ledger
from ..domain.settings import Settings

log = logging.getLogger(__name__)


def data_dir() -> Path:
    base = os.getenv("APPDATA") or str(Path.home())
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_json(path: Path, data: dict):
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _quarantine(path: Path):
    """文件损坏时改名备份，避免下一次写入覆盖掉可人工恢复的数据。"""
    target = path.with_name(f"{path.name}.corrupt.{datetime.now():%Y%m%d_%H%M%S}")
    try:
        os.replace(path, target)
        log.warning("已备份损坏文件：%s", target)
    except OSError:
        log.exception("备份损坏文件失败：%s", path)


class Store:
    SETTINGS = "settings.json"
    LEDGER = "ledger.json"

    def __init__(self, root: Path | None = None):
        self.root = root or data_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def settings_path(self) -> Path:
        return self.root / self.SETTINGS

    @property
    def ledger_path(self) -> Path:
        return self.root / self.LEDGER

    def _load(self, path: Path, parse):
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return parse(json.load(f))
        except Exception:
            log.exception("读取失败：%s", path)
            _quarantine(path)
            return None

    def load_settings(self) -> Settings | None:
        """None 表示首次启动（或配置损坏已备份）。"""
        return self._load(self.settings_path, Settings.from_dict)

    def save_settings(self, settings: Settings):
        atomic_write_json(self.settings_path, settings.to_dict())

    def load_ledger(self) -> Ledger:
        return self._load(self.ledger_path, Ledger.from_dict) or Ledger()

    def save_ledger(self, ledger: Ledger):
        atomic_write_json(self.ledger_path, ledger.to_dict())
