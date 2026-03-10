"""
ComfyUI MCP Server Auto-Start Custom Node
Automatically starts the MCP server when ComfyUI starts and stops it when ComfyUI closes.
"""

import os
import sys
import subprocess
import atexit
import logging
import time
import signal
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ComfyUI-MCP-AutoStart")

_mcp_process: Optional[subprocess.Popen] = None
_mcp_server_path: Optional[str] = None
_log_handle: Optional[object] = None
_job_handle: Optional[int] = None  # Windows Job Object handle


def _create_windows_job_object():
    """Create a Windows Job Object with KILL_ON_JOB_CLOSE so all child
    processes are automatically terminated when ComfyUI exits (including crashes)."""
    global _job_handle
    if sys.platform != "win32" or _job_handle is not None:
        return

    import ctypes
    import ctypes.wintypes

    kernel32 = ctypes.windll.kernel32

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        logger.warning("[MCP-AutoStart] Failed to create Windows Job Object")
        return

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.wintypes.DWORD),
            ("SchedulingClass", ctypes.wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

    ok = kernel32.SetInformationJobObject(
        job,
        9,  # JobObjectExtendedLimitInformation
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        logger.warning("[MCP-AutoStart] Failed to configure Job Object limits")
        kernel32.CloseHandle(job)
        return

    _job_handle = job
    logger.info("[MCP-AutoStart] Windows Job Object created (KILL_ON_JOB_CLOSE)")


def _assign_to_job_object(pid: int):
    """Assign a process to the Windows Job Object."""
    if sys.platform != "win32" or _job_handle is None:
        return

    import ctypes

    kernel32 = ctypes.windll.kernel32
    PROCESS_ALL_ACCESS = 0x1F0FFF
    handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not handle:
        logger.warning(f"[MCP-AutoStart] Cannot open process {pid} for Job Object assignment")
        return
    try:
        if kernel32.AssignProcessToJobObject(_job_handle, handle):
            logger.info(f"[MCP-AutoStart] Process {pid} assigned to Job Object")
        else:
            logger.warning(f"[MCP-AutoStart] Failed to assign process {pid} to Job Object")
    finally:
        kernel32.CloseHandle(handle)


def get_config_path() -> Path:
    config_dir = Path(__file__).parent
    return config_dir / "mcp_config.json"


def load_config() -> dict:
    import json
    config_path = get_config_path()

    default_config = {
        "enabled": True,
        "mcp_server_path": "",
        "python_path": sys.executable,
        "auto_start": True,
        "port": 9000,
        "comfyui_url": "http://localhost:8188"
    }

    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                default_config.update(config)
        except Exception as e:
            logger.warning(f"Failed to load config: {e}, using defaults")

    return default_config


def find_mcp_server_path() -> Optional[str]:
    # server.py 与 __init__.py 在同一目录
    server = Path(__file__).parent / "server.py"
    if server.exists():
        return str(server.absolute())
    return None


def start_mcp_server():
    global _mcp_process, _mcp_server_path, _log_handle

    config = load_config()

    if not config.get("enabled", True):
        logger.info("MCP Server auto-start is disabled in config")
        return

    if not config.get("auto_start", True):
        logger.info("MCP Server auto-start is disabled")
        return

    mcp_path = config.get("mcp_server_path", "")
    if not mcp_path:
        mcp_path = find_mcp_server_path()

    if not mcp_path or not Path(mcp_path).exists():
        logger.warning(f"MCP Server not found. Please set the correct path in {get_config_path()}")
        return

    _mcp_server_path = mcp_path
    python_path = config.get("python_path") or sys.executable
    port = config.get("port", 9000)

    mcp_dir = str(Path(mcp_path).parent)

    env = os.environ.copy()
    env["COMFYUI_URL"] = config.get("comfyui_url", "http://localhost:8188")

    log_dir = Path(mcp_dir) / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "mcp_server.log"

    logger.info("=" * 70)
    logger.info("[MCP-AutoStart] Starting MCP Server...")
    logger.info(f"  MCP Server Path: {mcp_path}")
    logger.info(f"  Python Path: {python_path}")
    logger.info(f"  Working Directory: {mcp_dir}")
    logger.info(f"  Port: {port}")
    logger.info(f"  Log File: {log_file}")
    logger.info("=" * 70)

    try:
        _log_handle = open(log_file, 'w', encoding='utf-8')
        _log_handle.write(f"{'='*70}\n")
        _log_handle.write(f"MCP Server starting at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        _log_handle.write(f"{'='*70}\n")
        _log_handle.flush()

        if sys.platform == "win32":
            _mcp_process = subprocess.Popen(
                [python_path, mcp_path],
                cwd=mcp_dir,
                env=env,
                stdout=_log_handle,
                stderr=_log_handle,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            _mcp_process = subprocess.Popen(
                [python_path, mcp_path],
                cwd=mcp_dir,
                env=env,
                stdout=_log_handle,
                stderr=_log_handle,
                preexec_fn=os.setsid
            )

        logger.info(f"[MCP-AutoStart] MCP Server started with PID: {_mcp_process.pid}")
        logger.info(f"[MCP-AutoStart] Logs redirected to: {log_file}")
        _assign_to_job_object(_mcp_process.pid)

    except Exception as e:
        logger.error(f"[MCP-AutoStart] Failed to start MCP Server: {e}")
        _mcp_process = None
        if _log_handle:
            _log_handle.close()
            _log_handle = None


def stop_mcp_server():
    global _mcp_process, _log_handle

    if _mcp_process is None:
        return

    logger.info("=" * 70)
    logger.info("[MCP-AutoStart] Stopping MCP Server...")
    logger.info("=" * 70)

    try:
        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.GenerateConsoleCtrlEvent(0, _mcp_process.pid)
                time.sleep(2)
            except:
                pass

            if _mcp_process.poll() is None:
                _mcp_process.terminate()
                try:
                    _mcp_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _mcp_process.kill()
        else:
            try:
                os.killpg(os.getpgid(_mcp_process.pid), signal.SIGTERM)
                time.sleep(2)
            except:
                if _mcp_process.poll() is None:
                    _mcp_process.terminate()
                    try:
                        _mcp_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        _mcp_process.kill()

        logger.info("[MCP-AutoStart] MCP Server stopped successfully")

    except Exception as e:
        logger.error(f"[MCP-AutoStart] Error stopping MCP Server: {e}")
    finally:
        _mcp_process = None
        if _log_handle:
            _log_handle.write(f"\nMCP Server stopped at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            _log_handle.close()
            _log_handle = None


class MCPServerControl:
    """
    A ComfyUI node to control the MCP Server manually.
    """

    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "action": (["start", "stop", "restart", "status"],),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status_message",)
    FUNCTION = "control_server"
    CATEGORY = "MCP"

    def control_server(self, action):
        global _mcp_process

        if action == "start":
            if _mcp_process is not None and _mcp_process.poll() is None:
                return ("MCP Server is already running",)
            start_mcp_server()
            if _mcp_process is not None and _mcp_process.poll() is None:
                return ("MCP Server started successfully",)
            return ("Failed to start MCP Server",)

        elif action == "stop":
            stop_mcp_server()
            return ("MCP Server stopped",)

        elif action == "restart":
            stop_mcp_server()
            time.sleep(2)
            start_mcp_server()
            if _mcp_process is not None and _mcp_process.poll() is None:
                return ("MCP Server restarted successfully",)
            return ("Failed to restart MCP Server",)

        elif action == "status":
            if _mcp_process is None:
                return ("MCP Server is not running",)
            if _mcp_process.poll() is None:
                return (f"MCP Server is running (PID: {_mcp_process.pid})",)
            return ("MCP Server has stopped",)

        return ("Unknown action",)


class MCPServerConfig:
    """
    A ComfyUI node to configure the MCP Server.
    """

    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "mcp_server_path": ("STRING", {"default": "", "multiline": False}),
                "port": ("INT", {"default": 9000, "min": 1024, "max": 65535}),
                "comfyui_url": ("STRING", {"default": "http://localhost:8188"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("config_status",)
    FUNCTION = "configure_server"
    CATEGORY = "MCP"

    def configure_server(self, mcp_server_path, port, comfyui_url):
        import json

        config = {
            "enabled": True,
            "mcp_server_path": mcp_server_path,
            "python_path": sys.executable,
            "auto_start": True,
            "port": port,
            "comfyui_url": comfyui_url
        }

        config_path = get_config_path()
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            return (f"Configuration saved to {config_path}",)
        except Exception as e:
            return (f"Failed to save configuration: {e}",)


NODE_CLASS_MAPPINGS = {
    "MCPServerControl": MCPServerControl,
    "MCPServerConfig": MCPServerConfig,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MCPServerControl": "🔧 MCP Server Control",
    "MCPServerConfig": "⚙️ MCP Server Config",
}


def setup_auto_start():
    _create_windows_job_object()

    config = load_config()

    if config.get("enabled", True) and config.get("auto_start", True):
        logger.info("[MCP-AutoStart] Auto-start enabled, starting MCP Server...")
        start_mcp_server()
    else:
        logger.info("[MCP-AutoStart] Auto-start disabled")


atexit.register(stop_mcp_server)

setup_auto_start()


__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
