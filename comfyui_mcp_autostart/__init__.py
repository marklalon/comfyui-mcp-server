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
    possible_paths = [
        Path(__file__).parent.parent.parent / "comfyui-mcp-server" / "server.py",
        Path(__file__).parent.parent / "comfyui-mcp-server" / "server.py",
        Path.home() / "comfyui-mcp-server" / "server.py",
        Path("d:/AI/comfyui-mcp-server/server.py"),
        Path("C:/AI/comfyui-mcp-server/server.py"),
    ]
    
    for path in possible_paths:
        if path.exists():
            return str(path.absolute())
    
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
        logger.info(f"Current search paths tried. Please configure mcp_server_path in config file.")
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
        _log_handle = open(log_file, 'a', encoding='utf-8')
        _log_handle.write(f"\n{'='*70}\n")
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


class TextOutput:
    """
    A ComfyUI node that outputs text for MCP consumption.
    Unlike PreviewAny which only displays text in the UI,
    this node returns the text as a proper output that can be
    captured by the MCP server, while also displaying in the UI.
    """
    
    def __init__(self):
        pass
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text": ("STRING", {"default": "", "multiline": True}),
            },
        }
    
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text_output",)
    FUNCTION = "output_text"
    CATEGORY = "MCP"
    OUTPUT_NODE = True
    
    def output_text(self, text):
        """
        Output text for MCP consumption.
        Returns the text directly so it can be captured by the MCP server.
        Also returns ui.text for display in the ComfyUI interface.
        """
        logger.info(f"[TextOutput] Outputting text ({len(text)} characters)")
        return {"ui": {"text": (text,)}, "result": (text,)}


NODE_CLASS_MAPPINGS = {
    "MCPServerControl": MCPServerControl,
    "MCPServerConfig": MCPServerConfig,
    "TextOutput": TextOutput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MCPServerControl": "🔧 MCP Server Control",
    "MCPServerConfig": "⚙️ MCP Server Config",
    "TextOutput": "📝 Text Output",
}


def setup_auto_start():
    config = load_config()
    
    if config.get("enabled", True) and config.get("auto_start", True):
        logger.info("[MCP-AutoStart] Auto-start enabled, starting MCP Server...")
        start_mcp_server()
    else:
        logger.info("[MCP-AutoStart] Auto-start disabled")


atexit.register(stop_mcp_server)

setup_auto_start()


__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
