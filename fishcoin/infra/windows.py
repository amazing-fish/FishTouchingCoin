"""Windows 系统能力：空闲时长、锁屏、按键、开机自启、单实例、DPI、窗口外观。"""

import ctypes
import logging
import os
import sys
import time
import winreg
from ctypes import wintypes

from .. import APP_NAME

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.GetTickCount.restype = wintypes.DWORD
dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]


# ---------- DPI ----------

def enable_dpi_awareness():
    """系统级 DPI 感知，避免 125%/150% 缩放下窗口模糊。须在创建 Tk 之前调用。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


# ---------- 空闲时长 ----------

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float:
    lii = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    return ((kernel32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000.0


# ---------- 锁屏（WTS 会话状态） ----------

WTSSessionInfoEx = 25
WTS_SESSIONSTATE_LOCK = 0
WTS_SESSIONSTATE_UNLOCK = 1


class WTSINFOEX_LEVEL1_W(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.ULONG),
        ("SessionState", ctypes.c_int),
        ("SessionFlags", wintypes.LONG),
        ("WinStationName", wintypes.WCHAR * 33),
        ("UserName", wintypes.WCHAR * 21),
        ("DomainName", wintypes.WCHAR * 18),
        ("LogonTime", ctypes.c_longlong),
        ("ConnectTime", ctypes.c_longlong),
        ("DisconnectTime", ctypes.c_longlong),
        ("LastInputTime", ctypes.c_longlong),
        ("CurrentTime", ctypes.c_longlong),
        ("IncomingBytes", wintypes.DWORD),
        ("OutgoingBytes", wintypes.DWORD),
        ("IncomingFrames", wintypes.DWORD),
        ("OutgoingFrames", wintypes.DWORD),
        ("IncomingCompressedBytes", wintypes.DWORD),
        ("OutgoingCompressedBytes", wintypes.DWORD),
    ]


class WTSINFOEXW(ctypes.Structure):
    _fields_ = [("Level", wintypes.DWORD), ("Data", WTSINFOEX_LEVEL1_W)]


wtsapi32.WTSQuerySessionInformationW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD),
]
wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]


def _session_id() -> int:
    sid = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid)):
        raise ctypes.WinError(ctypes.get_last_error())
    return sid.value


def query_session_info() -> WTSINFOEX_LEVEL1_W:
    buf = ctypes.c_void_p()
    size = wintypes.DWORD()
    if not wtsapi32.WTSQuerySessionInformationW(None, _session_id(), WTSSessionInfoEx,
                                               ctypes.byref(buf), ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = ctypes.cast(buf, ctypes.POINTER(WTSINFOEXW)).contents
        if info.Level != 1:
            raise OSError(f"unexpected WTSINFOEX level {info.Level}")
        return WTSINFOEX_LEVEL1_W.from_buffer_copy(info.Data)
    finally:
        wtsapi32.WTSFreeMemory(buf)


class LockProbe:
    """查询当前会话是否锁屏。结果短暂缓存，避免每 100ms 发一次 RPC。"""

    def __init__(self, ttl_s: float = 0.5):
        self.ttl_s = ttl_s
        self._at = -1e9
        self._value: bool | None = None
        self._warned = False

    def locked(self) -> bool | None:
        now = time.monotonic()
        if now - self._at < self.ttl_s:
            return self._value
        self._at = now
        try:
            flags = query_session_info().SessionFlags
            self._value = {WTS_SESSIONSTATE_LOCK: True, WTS_SESSIONSTATE_UNLOCK: False}.get(flags)
        except Exception:
            if not self._warned:
                log.exception("锁屏状态查询失败，按未知处理")
                self._warned = True
            self._value = None
        return self._value


# ---------- 按键 ----------

VK_F9 = 0x78


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


# ---------- 开机自启（HKCU Run，注册表即唯一事实来源） ----------

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pythonw):
        exe = pythonw
    entry = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "fish.py"))
    return f'"{exe}" "{entry}"'


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
    except OSError:
        return False
    return str(value).strip() == autostart_command()


def set_autostart(enabled: bool):
    """失败时抛 OSError。"""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


# ---------- 单实例（命名互斥锁，进程退出由系统回收） ----------

ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self, name: str = f"Local\\{APP_NAME}.SingleInstance"):
        self._handle = kernel32.CreateMutexW(None, False, name)
        self.already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def release(self):
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None


# ---------- 显示器工作区（不含任务栏） ----------

class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
MONITOR_DEFAULTTONEAREST = 2


def work_area_at(x: int, y: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom)，物理像素。"""
    mon = user32.MonitorFromPoint(wintypes.POINT(x, y), MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    if mon and user32.GetMonitorInfoW(mon, ctypes.byref(info)):
        r = info.rcWork
        return r.left, r.top, r.right, r.bottom
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


# ---------- 窗口外观（Windows 11 DWM） ----------

GA_ROOT = 2
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3


def toplevel_hwnd(widget) -> int:
    return user32.GetAncestor(widget.winfo_id(), GA_ROOT) or widget.winfo_id()


def _dwm_set_int(hwnd: int, attr: int, value: int) -> bool:
    v = ctypes.c_int(value)
    return dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0


DWMWA_CAPTION_COLOR = 35


def _colorref(hex_color: str) -> int:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return r | (g << 8) | (b << 16)  # COLORREF = 0x00BBGGRR


def set_caption_color(widget, color: str) -> bool:
    """Win11：标题栏与窗口背景同色，视觉上更一体。"""
    return _dwm_set_int(toplevel_hwnd(widget), DWMWA_CAPTION_COLOR, _colorref(color))


BORDER_NONE = "none"
DWMWA_COLOR_NONE = 0xFFFFFFFE  # 不绘制系统默认的 1px 窗口描边


def round_corners(widget, small: bool = False, border: str | None = None) -> bool:
    """Win11 系统级抗锯齿圆角；Win10 上静默失败（返回 False）。

    border: "#RRGGBB" 指定描边色；BORDER_NONE 去掉描边；None 保留系统默认。
    """
    hwnd = toplevel_hwnd(widget)
    ok = _dwm_set_int(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUNDSMALL if small else DWMWCP_ROUND)
    if ok and border:
        color = DWMWA_COLOR_NONE if border == BORDER_NONE else _colorref(border)
        _dwm_set_int(hwnd, DWMWA_BORDER_COLOR, ctypes.c_int(color & 0xFFFFFFFF).value)
    return ok
