"""Windows "start with Windows" toggle (PRD F23).

The ONLY module that touches the registry. Uses the per-user Run key
(HKCU\\...\\CurrentVersion\\Run), which launches the app at login with no
elevation and no scheduled-task plumbing. Every function is defensive: a
registry hiccup logs and no-ops rather than crashing the app.
"""

import logging
import sys

try:
    import winreg
except ImportError:  # non-Windows: the whole feature is a no-op
    winreg = None

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "VibeCheck.lol"


def _launch_command() -> str:
    """The command Windows should run at login.

    Frozen build: the exe itself. Source checkout: pythonw -m kiffance so it
    starts silently (no console window).
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pythonw}" -m kiffance'


def is_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        log.warning("Could not read auto-start setting", exc_info=True)
        return False


def set_enabled(enabled: bool) -> bool:
    """Enable or disable launch-at-login. Returns the resulting state."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(key, _VALUE_NAME)
                except FileNotFoundError:
                    pass
        log.info("Auto-start %s", "enabled" if enabled else "disabled")
        return enabled
    except OSError:
        log.warning("Could not change auto-start setting", exc_info=True)
        return is_enabled()
