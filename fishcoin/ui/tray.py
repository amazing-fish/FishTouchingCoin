import logging
import queue
import threading
from collections.abc import Callable

import pystray
from PIL import Image

from .. import APP_NAME

log = logging.getLogger(__name__)


def build_menu(post: Callable[[str], None]) -> pystray.Menu:
    """pystray 以 action(icon, item) 调用回调；显式接收参数，不依赖其对零参函数的自动包装。"""

    def emit(event: str):
        return lambda icon, item: post(event)

    return pystray.Menu(
        pystray.MenuItem("显示 / 隐藏", emit("toggle"), default=True),
        pystray.MenuItem("详情", emit("details")),
        pystray.MenuItem("配置…", emit("settings")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", emit("quit")),
    )


class Tray:
    """常驻托盘图标。pystray 跑在独立线程，菜单事件经队列交回 Tk 主线程处理。"""

    def __init__(self, icon_path: str | None):
        self.events: queue.Queue[str] = queue.Queue()
        try:
            image = Image.open(icon_path) if icon_path else None
        except OSError:
            image = None
        image = image or Image.new("RGBA", (64, 64), "#FACC15")

        self.icon = pystray.Icon(APP_NAME, image, "…", build_menu(self.events.put))
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()

    def _run(self):
        try:
            self.icon.run()
        except Exception:
            log.exception("托盘线程异常退出")

    def set_title(self, text: str):
        try:
            self.icon.title = text[:127]
        except Exception:
            log.debug("托盘标题更新失败", exc_info=True)

    def drain(self):
        while True:
            try:
                yield self.events.get_nowait()
            except queue.Empty:
                return

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass
