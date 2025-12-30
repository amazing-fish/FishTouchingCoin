import os
import ctypes
from ctypes import wintypes


# ==========================================
# 系统底层 API
# ==========================================
class SystemUtils:
    if os.name == "nt":
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
    else:
        user32 = None
        kernel32 = None

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    @staticmethod
    def get_idle_time() -> float:
        if SystemUtils.user32 is None or SystemUtils.kernel32 is None:
            return 0.0
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
        if SystemUtils.user32 is None or SystemUtils.kernel32 is None:
            return None
        DESKTOP_SWITCHDESKTOP = 0x0100
        try:
            hDesktop = SystemUtils.user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
            if hDesktop == 0:
                return None
            SystemUtils.user32.CloseDesktop(hDesktop)
            return False
        except Exception:
            return None

    @staticmethod
    def is_key_pressed(vk_code: int) -> bool:
        if SystemUtils.user32 is None:
            return False
        return bool(SystemUtils.user32.GetAsyncKeyState(vk_code) & 0x8000)

    @staticmethod
    def is_process_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name != "nt":
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
            return True
        if SystemUtils.kernel32 is None:
            return False
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = SystemUtils.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        exit_code = wintypes.DWORD()
        try:
            if not SystemUtils.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            SystemUtils.kernel32.CloseHandle(handle)
