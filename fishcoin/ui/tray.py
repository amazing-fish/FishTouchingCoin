import logging
import queue
import threading

import pystray
from PIL import Image

from .. import APP_NAME

log = logging.getLogger(__name__)


class Tray:
    """常驻托盘图标。pystray 跑在独立线程，菜单事件经队列交回 Tk 主线程处理。"""

    def __init__(self, icon_path: str | None):
        self.events: queue.Queue[str] = queue.Queue()
        try:
            image = Image.open(icon_path) if icon_path else None
        except OSError:
            image = None
        image = image or Image.new("RGBA", (64, 64), "#FACC15")

        post = self.events.put
        menu = pystray.Menu(
            pystray.MenuItem("显示 / 隐藏", lambda: post("toggle"), default=True),
            pystray.MenuItem("详情", lambda: post("details")),
            pystray.MenuItem("配置…", lambda: post("settings")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: post("quit")),
        )
        self.icon = pystray.Icon(APP_NAME, image, "…", menu)
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
