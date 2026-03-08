"""ComfyUI MCP Server - Main entry point"""

import logging
import os
import sys
import time
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import requests

from mcp.server.fastmcp import FastMCP

from comfyui_client import ComfyUIClient
from managers.asset_registry import AssetRegistry
from managers.defaults_manager import DefaultsManager
from managers.publish_manager import PublishConfig, PublishManager
from managers.workflow_manager import WorkflowManager
from tools.asset import register_asset_tools
from tools.configuration import register_configuration_tools
from tools.generation import register_workflow_generation_tools, register_regenerate_tool
from tools.job import register_job_tools
from tools.publish import register_publish_tools
from tools.workflow import register_workflow_tools

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MCP_Server")

# Configuration paths
WORKFLOW_DIR = Path(os.getenv("COMFY_MCP_WORKFLOW_DIR", str(Path(__file__).parent / "workflows")))

# Asset registry configuration
ASSET_TTL_HOURS = int(os.getenv("COMFY_MCP_ASSET_TTL_HOURS", "24"))

# ComfyUI connection configuration
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://localhost:8188")
COMFYUI_MAX_RETRIES = 5  # Number of retry attempts
COMFYUI_INITIAL_DELAY = 2  # Initial delay in seconds
COMFYUI_MAX_DELAY = 16  # Maximum delay in seconds

# Publish configuration (optional env var for COMFYUI_OUTPUT_ROOT only)
COMFYUI_OUTPUT_ROOT = os.getenv("COMFYUI_OUTPUT_ROOT")


def print_startup_banner():
    """Print a nice startup banner for the server."""
    print("\n" + "=" * 70)
    print("[*] ComfyUI-MCP-Server".center(70))
    print("=" * 70)
    print(f"  Connecting to ComfyUI at: {COMFYUI_URL}")
    print(f"  Workflow directory: {WORKFLOW_DIR}")
    print(f"  Asset TTL: {ASSET_TTL_HOURS} hours")
    print("=" * 70 + "\n")


def check_comfyui_available(base_url: str) -> bool:
    """Check if ComfyUI is available by attempting to fetch model list.
    
    Returns True if ComfyUI is responding, False otherwise.
    """
    try:
        response = requests.get(f"{base_url}/object_info/CheckpointLoaderSimple", timeout=5)
        if response.status_code == 200:
            # Try to parse the response to ensure it's valid
            data = response.json()
            checkpoint_info = data.get("CheckpointLoaderSimple", {})
            if isinstance(checkpoint_info, dict):
                return True
        return False
    except (requests.RequestException, ValueError, KeyError):
        return False


def wait_for_comfyui(base_url: str, max_retries: int = COMFYUI_MAX_RETRIES, 
                     initial_delay: float = COMFYUI_INITIAL_DELAY,
                     max_delay: float = COMFYUI_MAX_DELAY) -> bool:
    """Wait for ComfyUI to become available with exponential backoff.
    
    Args:
        base_url: ComfyUI base URL
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay in seconds between retries
    
    Returns:
        True if ComfyUI becomes available, False if all retries exhausted
    """
    print("\n" + "=" * 70)
    print("[!]  ALERT: ComfyUI is not available!")
    print("=" * 70)
    print(f"  Checking for ComfyUI at: {base_url}")
    print(f"  Waiting for ComfyUI to start (will retry {max_retries} times)...")
    print("=" * 70 + "\n")
    
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        logger.info(f"ComfyUI availability check (attempt {attempt}/{max_retries})...")
        
        if check_comfyui_available(base_url):
            print("\n" + "=" * 70)
            print("[+] ComfyUI is now available!")
            print("=" * 70 + "\n")
            logger.info("ComfyUI is available, proceeding with server startup")
            return True
        
        if attempt < max_retries:
            print(f"[...] Attempt {attempt}/{max_retries} failed. Retrying in {delay:.1f} seconds...")
            time.sleep(delay)
            # Exponential backoff: double the delay, but cap at max_delay
            delay = min(delay * 2, max_delay)
        else:
            print(f"[X] Attempt {attempt}/{max_retries} failed. No more retries.")
    
    return False


# Print startup banner
print_startup_banner()

# Check ComfyUI availability before initializing clients
if not check_comfyui_available(COMFYUI_URL):
    if not wait_for_comfyui(COMFYUI_URL):
        print("\n" + "=" * 70)
        print("[X] ERROR: ComfyUI is not available after all retry attempts!")
        print("=" * 70)
        print(f"  Please ensure ComfyUI is running at: {COMFYUI_URL}")
        print("  Start ComfyUI first, then restart this server.")
        print("=" * 70 + "\n")
        sys.exit(1)

# Global ComfyUI client (fallback since context isn't available)
comfyui_client = ComfyUIClient(COMFYUI_URL)
workflow_manager = WorkflowManager(WORKFLOW_DIR)
defaults_manager = DefaultsManager(comfyui_client)
asset_registry = AssetRegistry(ttl_hours=ASSET_TTL_HOURS, comfyui_base_url=COMFYUI_URL)

# Publish manager (always initialized, uses auto-detection)
try:
    publish_config = PublishConfig(
        comfyui_output_root=COMFYUI_OUTPUT_ROOT,
        comfyui_url=COMFYUI_URL
    )
    publish_manager = PublishManager(publish_config)
    logger.info(f"Publish manager initialized with project_root={publish_config.project_root} (method: {publish_config.project_root_method})")
    logger.info(f"Publish root: {publish_config.publish_root}")
    if publish_config.comfyui_output_root:
        logger.info(f"ComfyUI output root: {publish_config.comfyui_output_root} (method: {publish_config.comfyui_output_method})")
    else:
        logger.info(f"ComfyUI output root: not configured (tried {len(publish_config.comfyui_tried_paths)} paths)")
except Exception as e:
    logger.warning(f"Failed to initialize publish manager: {e}. Publishing features may be unavailable.")
    # Still create a minimal manager so tools can register and return errors
    try:
        from managers.publish_manager import PublishConfig, PublishManager
        publish_config = PublishConfig(comfyui_url=COMFYUI_URL)
        publish_manager = PublishManager(publish_config)
    except Exception:
        publish_manager = None


# Define application context (for future use)
class AppContext:
    def __init__(self, comfyui_client: ComfyUIClient):
        self.comfyui_client = comfyui_client


# Lifespan management (placeholder for future context support)
@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle"""
    logger.info("Starting MCP server lifecycle...")
    try:
        # Startup: Could add ComfyUI health check here in the future
        logger.info("ComfyUI client initialized globally")
        yield AppContext(comfyui_client=comfyui_client)
    finally:
        # Shutdown: Cleanup (if needed)
        logger.info("Shutting down MCP server")


# Initialize FastMCP with lifespan and port configuration
# Using port 9000 for consistency with previous version
# Enable stateless_http to avoid requiring session management
mcp = FastMCP(
    "ComfyUI_MCP_Server",
    lifespan=app_lifespan,
    port=9000,
    stateless_http=True
)

# Register all MCP tools
register_configuration_tools(mcp, comfyui_client, defaults_manager)
register_workflow_tools(mcp, workflow_manager, comfyui_client, defaults_manager, asset_registry)
register_asset_tools(mcp, asset_registry)
register_workflow_generation_tools(mcp, workflow_manager, comfyui_client, defaults_manager, asset_registry)
register_regenerate_tool(mcp, comfyui_client, asset_registry)
register_job_tools(mcp, comfyui_client, asset_registry)
# Always register publish tools (unconditional)
if publish_manager:
    register_publish_tools(mcp, asset_registry, publish_manager)
else:
    logger.error("Publish manager not available - publish tools will not be registered")


# ComfyUI Monitor - Auto-shutdown when ComfyUI disappears
class ComfyUIMonitor:
    """Monitor ComfyUI availability and shutdown MCP server when ComfyUI disappears."""
    
    def __init__(self, comfyui_url: str, check_interval: float = 1.0, max_failures: int = 1):
        self.comfyui_url = comfyui_url
        self.check_interval = check_interval
        self.max_failures = max_failures
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._failure_count = 0
    
    def _check_comfyui_alive(self) -> bool:
        """Check if ComfyUI is still responding."""
        try:
            response = requests.get(f"{self.comfyui_url}/system_stats", timeout=3)
            return response.status_code == 200
        except (requests.RequestException, ValueError):
            return False
    
    def _monitor_loop(self):
        """Background thread that monitors ComfyUI availability."""
        logger.info(f"[ComfyUI-Monitor] Started monitoring ComfyUI at {self.comfyui_url}")
        
        while not self._stop_event.is_set():
            if self._check_comfyui_alive():
                self._failure_count = 0  # Reset on success
            else:
                self._failure_count += 1
                logger.warning(f"[ComfyUI-Monitor] ComfyUI not responding (attempt {self._failure_count}/{self.max_failures})")
                
                if self._failure_count >= self.max_failures:
                    logger.warning("[ComfyUI-Monitor] ComfyUI has disappeared, shutting down MCP server...")
                    print("\n" + "=" * 70)
                    print("[!] ComfyUI has stopped - Shutting down MCP server")
                    print("=" * 70 + "\n")
                    # Kill all remaining ComfyUI processes
                    self._kill_comfyui_processes()
                    # Force exit the process
                    os._exit(0)
            
            self._stop_event.wait(self.check_interval)
    
    def _kill_comfyui_processes(self):
        """Kill all ComfyUI processes (including python processes running ComfyUI)."""
        killed_processes = []
        
        # Fast path: Use system commands first (much faster than psutil iteration)
        if sys.platform == "win32":
            try:
                import subprocess
                
                # Kill ComfyUI.exe directly (fastest)
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", "ComfyUI.exe"],
                    capture_output=True, timeout=2
                )
                if result.returncode == 0:
                    killed_processes.append("ComfyUI.exe")
                    logger.info("[ComfyUI-Monitor] Killed ComfyUI.exe")
                
                # Kill python processes running ComfyUI (use wmic for speed)
                result = subprocess.run(
                    ['wmic', 'process', 'where', "commandline like '%comfyui%' and name='python.exe'", 'delete'],
                    capture_output=True, timeout=3
                )
                if result.returncode == 0:
                    killed_processes.append("python.exe (ComfyUI)")
                    logger.info("[ComfyUI-Monitor] Killed python.exe ComfyUI processes")
                
                # Kill node processes related to ComfyUI
                result = subprocess.run(
                    ['wmic', 'process', 'where', "commandline like '%comfyui%' and name='node.exe'", 'delete'],
                    capture_output=True, timeout=3
                )
                if result.returncode == 0:
                    killed_processes.append("node.exe (ComfyUI)")
                    logger.info("[ComfyUI-Monitor] Killed node.exe ComfyUI processes")
                    
            except subprocess.TimeoutExpired:
                logger.warning("[ComfyUI-Monitor] Timeout while killing processes")
            except Exception as e:
                logger.warning(f"[ComfyUI-Monitor] System command failed: {e}")
        else:
            # Linux/Mac: use pkill
            try:
                import subprocess
                subprocess.run(["pkill", "-f", "comfyui"], capture_output=True, timeout=2)
                subprocess.run(["pkill", "-f", "main.py"], capture_output=True, timeout=2)
                killed_processes.append("ComfyUI processes")
                logger.info("[ComfyUI-Monitor] Killed ComfyUI processes via pkill")
            except Exception as e:
                logger.warning(f"[ComfyUI-Monitor] pkill failed: {e}")
        
        if killed_processes:
            logger.info(f"[ComfyUI-Monitor] Killed: {', '.join(killed_processes)}")
    
    def start(self):
        """Start the monitoring thread."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._thread.start()
    
    def stop(self):
        """Stop the monitoring thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)


# Global monitor instance
_comfyui_monitor: ComfyUIMonitor | None = None


def start_comfyui_monitor():
    """Start the ComfyUI availability monitor."""
    global _comfyui_monitor
    if _comfyui_monitor is None:
        _comfyui_monitor = ComfyUIMonitor(COMFYUI_URL)
        _comfyui_monitor.start()


def stop_comfyui_monitor():
    """Stop the ComfyUI availability monitor."""
    global _comfyui_monitor
    if _comfyui_monitor:
        _comfyui_monitor.stop()
        _comfyui_monitor = None


if __name__ == "__main__":
    # Start ComfyUI monitor to auto-shutdown when ComfyUI disappears
    start_comfyui_monitor()
    # Check if running as MCP command (stdio) or standalone (streamable-http)
    # When run as command by MCP client (like Cursor), use stdio transport
    # When run standalone, use streamable-http for HTTP access
    if len(sys.argv) > 1 and sys.argv[1] == "--stdio":
        print("\n" + "=" * 70)
        print("[+] Server Ready".center(70))
        print("=" * 70)
        print(f"  Transport: stdio (for MCP clients)")
        print(f"[+] ComfyUI verified at: {COMFYUI_URL}")
        print("=" * 70 + "\n")
        logger.info("Starting MCP server with stdio transport (for MCP clients)")
        logger.info(f"ComfyUI verified at: {COMFYUI_URL}")
        try:
            mcp.run(transport="stdio")
        except KeyboardInterrupt:
            print("\n[*] Server stopped.")
    else:
        print("\n" + "=" * 70)
        print("[+] Server Ready".center(70))
        print("=" * 70)
        print(f"  Transport: streamable-http")
        print(f"  Endpoint: http://127.0.0.1:9000/mcp")
        print(f"[+] ComfyUI verified at: {COMFYUI_URL}")
        print("=" * 70 + "\n")
        logger.info("Starting MCP server with streamable-http transport on http://127.0.0.1:9000/mcp")
        logger.info(f"ComfyUI verified at: {COMFYUI_URL}")
        try:
            mcp.run(transport="streamable-http")
        except KeyboardInterrupt:
            print("\n[*] Server stopped.")
