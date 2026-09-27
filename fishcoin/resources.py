import sys
from pathlib import Path


def resource(name: str) -> str | None:
    """资源路径：兼容源码运行与 PyInstaller onefile（资源解压到 sys._MEIPASS）。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    path = base / name
    return str(path) if path.exists() else None
