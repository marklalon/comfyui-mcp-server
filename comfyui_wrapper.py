"""
ComfyUI Wrapper Script
启动、监控和终止 ComfyUI 进程的包装器。

使用方法:
    python comfyui_wrapper.py [options]

选项:
    --comfyui-path PATH    ComfyUI 根目录路径 (默认: 自动检测)
    --port PORT           监听端口 (默认: 8188)
    --listen ADDRESS      监听地址 (默认: 127.0.0.1)
    --cuda-device DEVICE  CUDA 设备编号 (默认: 0)
    --lowvram             启用低显存模式
    --normalvram          使用普通显存模式
    --highvram            使用高显存模式
    --cpu                 使用 CPU 模式
    --dont-upcast-attention  禁止 attention upcast
    --auto-launch         自动在浏览器打开
    --disable-xformers    禁用 xformers
    --enable-xformers     启用 xformers
    --log-level LEVEL     日志级别 (默认: INFO)
    --restart-on-crash    崩溃时自动重启
    --max-restarts N      最大重启次数 (默认: 3)
"""

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, List

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ComfyUI-Wrapper")

# 全局变量
_comfyui_process: Optional[subprocess.Popen] = None
_comfyui_path: Optional[Path] = None
_shutdown_requested: bool = False
_restart_count: int = 0


def find_comfyui_path() -> Optional[Path]:
    """自动检测 ComfyUI 安装路径（支持 Desktop 和便携版）"""
    current_dir = Path(__file__).parent

    if current_dir.name == "custom_nodes":
        return current_dir.parent

    parent = current_dir.parent
    if (parent / "main.py").exists() or (parent / "comfy").is_dir():
        return parent

    for ancestor in current_dir.parents:
        if (ancestor / "main.py").exists() and (ancestor / "comfy").is_dir():
            return ancestor

    common_paths = [
        Path("D:/AI/ComfyUI"),
        Path("C:/AI/ComfyUI"),
        Path.home() / "ComfyUI",
        Path("/opt/ComfyUI"),
        Path("/home/ComfyUI"),
    ]

    for path in common_paths:
        if path.exists() and (path / "main.py").exists():
            return path
        if path.exists() and (path / ".venv").is_dir():
            return path

    desktop_paths = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ComfyUI",
        Path.home() / "AppData" / "Local" / "Programs" / "ComfyUI",
    ]

    for path in desktop_paths:
        if path.exists() and (path / "ComfyUI.exe").exists():
            return path

    return None


def is_desktop_version(base_path: Path) -> bool:
    """检测是否为 ComfyUI Desktop 版本"""
    return (base_path / "ComfyUI.exe").exists()


def find_comfyui_main_py(base_path: Path) -> Optional[Path]:
    """查找 ComfyUI 的 main.py 位置"""
    main_py = base_path / "main.py"
    if main_py.exists():
        return main_py

    main_py = base_path / "resources" / "ComfyUI" / "main.py"
    if main_py.exists():
        return main_py

    return None


def find_comfyui_venv(base_path: Path) -> Optional[Path]:
    """查找 ComfyUI 的 Python 虚拟环境"""
    venv_path = base_path / ".venv"
    if venv_path.exists():
        return venv_path

    appdata_config = Path(os.environ.get("APPDATA", "")) / "ComfyUI" / "config.json"
    if appdata_config.exists():
        try:
            import json
            with open(appdata_config, 'r', encoding='utf-8') as f:
                config = json.load(f)
                base_path_config = config.get("basePath")
                if base_path_config:
                    venv_path = Path(base_path_config) / ".venv"
                    if venv_path.exists():
                        return venv_path
        except Exception:
            pass

    return None


def get_python_executable(base_path: Path = None) -> str:
    """获取 Python 可执行文件路径（优先使用虚拟环境）"""
    if base_path:
        venv_path = find_comfyui_venv(base_path)
        if venv_path:
            venv_python = venv_path / "Scripts" / "python.exe" if sys.platform == "win32" else venv_path / "bin" / "python"
            if venv_python.exists():
                return str(venv_python)

    return sys.executable


def build_command(args: argparse.Namespace) -> List[str]:
    """构建 ComfyUI 启动命令"""
    python_exe = get_python_executable(_comfyui_path)
    main_py = find_comfyui_main_py(_comfyui_path)

    if main_py is None:
        logger.error(f"无法找到 main.py，路径: {_comfyui_path}")
        return []

    cmd = [python_exe, str(main_py)]
    cmd.extend(["--port", str(args.port)])
    cmd.extend(["--listen", args.listen])

    if args.cuda_device is not None:
        cmd.extend(["--cuda-device", str(args.cuda_device)])

    if args.lowvram:
        cmd.append("--lowvram")
    elif args.normalvram:
        cmd.append("--normalvram")
    elif args.highvram:
        cmd.append("--highvram")
    elif args.cpu:
        cmd.append("--cpu")

    if args.dont_upcast_attention:
        cmd.append("--dont-upcast-attention")
    if args.auto_launch:
        cmd.append("--auto-launch")
    if args.disable_xformers:
        cmd.append("--disable-xformers")
    if args.enable_xformers:
        cmd.append("--enable-xformers")

    return cmd


def setup_signal_handlers():
    """设置信号处理器"""
    def signal_handler(signum, frame):
        global _shutdown_requested
        logger.info(f"收到信号 {signum}，准备关闭...")
        _shutdown_requested = True
        stop_comfyui()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGBREAK, signal_handler)
        except AttributeError:
            pass


def start_comfyui(args: argparse.Namespace) -> bool:
    """启动 ComfyUI 进程"""
    global _comfyui_process

    if _comfyui_process is not None and _comfyui_process.poll() is None:
        logger.warning("ComfyUI 已经在运行中")
        return False

    _is_desktop = is_desktop_version(_comfyui_path)

    if _is_desktop:
        cmd = [str(_comfyui_path / "ComfyUI.exe")]
        cwd = str(_comfyui_path)
    else:
        cmd = build_command(args)
        if not cmd:
            return False
        cwd = str(_comfyui_path)

    logger.info("=" * 70)
    logger.info("[ComfyUI-Wrapper] 启动 ComfyUI...")
    logger.info(f"  版本: {'Desktop' if _is_desktop else '便携版'}")
    logger.info(f"  工作目录: {cwd}")
    logger.info(f"  命令: {' '.join(cmd)}")
    logger.info("=" * 70)

    try:
        env = os.environ.copy()
        _comfyui_process = subprocess.Popen(cmd, cwd=cwd, env=env)
        logger.info(f"[ComfyUI-Wrapper] ComfyUI 已启动，PID: {_comfyui_process.pid}")
        return True

    except Exception as e:
        logger.error(f"[ComfyUI-Wrapper] 启动 ComfyUI 失败: {e}")
        _comfyui_process = None
        return False


def stop_comfyui(timeout: int = 10) -> bool:
    """停止 ComfyUI 进程"""
    global _comfyui_process

    if _comfyui_process is None:
        return True

    if _comfyui_process.poll() is not None:
        _comfyui_process = None
        return True

    logger.info("[ComfyUI-Wrapper] 正在停止 ComfyUI...")

    try:
        _comfyui_process.terminate()
        try:
            _comfyui_process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("[ComfyUI-Wrapper] 强制终止进程")
            _comfyui_process.kill()
            try:
                _comfyui_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

        logger.info("[ComfyUI-Wrapper] ComfyUI 已停止")
        _comfyui_process = None
        return True

    except Exception as e:
        logger.error(f"[ComfyUI-Wrapper] 停止 ComfyUI 时出错: {e}")
        _comfyui_process = None
        return False


def monitor_comfyui(args: argparse.Namespace):
    """监控 ComfyUI 进程状态"""
    global _restart_count, _shutdown_requested

    while not _shutdown_requested:
        if _comfyui_process is None:
            time.sleep(1)
            continue

        return_code = _comfyui_process.poll()

        if return_code is not None:
            if _shutdown_requested:
                logger.info(f"[ComfyUI-Wrapper] ComfyUI 已退出，返回码: {return_code}")
                break

            logger.warning(f"[ComfyUI-Wrapper] ComfyUI 意外退出，返回码: {return_code}")

            if args.restart_on_crash and _restart_count < args.max_restarts:
                _restart_count += 1
                logger.info(f"[ComfyUI-Wrapper] 尝试重启 ({_restart_count}/{args.max_restarts})...")
                time.sleep(3)

                if start_comfyui(args):
                    logger.info("[ComfyUI-Wrapper] ComfyUI 重启成功")
                else:
                    logger.error("[ComfyUI-Wrapper] ComfyUI 重启失败")
                    break
            else:
                if _restart_count >= args.max_restarts:
                    logger.error(f"[ComfyUI-Wrapper] 达到最大重启次数 ({args.max_restarts})")
                break

        time.sleep(2)


def run(args: argparse.Namespace):
    """主运行函数"""
    global _comfyui_path, _shutdown_requested

    if args.comfyui_path:
        _comfyui_path = Path(args.comfyui_path)
    else:
        _comfyui_path = find_comfyui_path()

    if _comfyui_path is None:
        logger.error("无法找到 ComfyUI 安装路径，请使用 --comfyui-path 参数指定")
        sys.exit(1)

    is_desktop = is_desktop_version(_comfyui_path)
    has_main_py = find_comfyui_main_py(_comfyui_path) is not None

    if not is_desktop and not has_main_py and (_comfyui_path / ".venv").exists():
        logger.info(f"检测到用户数据目录: {_comfyui_path}")
        logger.info("正在查找 ComfyUI Desktop 安装目录...")

        desktop_paths = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ComfyUI",
            Path.home() / "AppData" / "Local" / "Programs" / "ComfyUI",
        ]

        for path in desktop_paths:
            if path.exists() and (path / "ComfyUI.exe").exists():
                _comfyui_path = path
                is_desktop = True
                logger.info(f"找到 Desktop 安装目录: {_comfyui_path}")
                break

    if not is_desktop and not has_main_py:
        logger.error(f"无效的 ComfyUI 路径: {_comfyui_path}")
        logger.error("请确保路径包含 main.py (便携版) 或 ComfyUI.exe (Desktop版)")
        sys.exit(1)

    logging.getLogger().setLevel(args.log_level.upper())
    setup_signal_handlers()

    if not start_comfyui(args):
        sys.exit(1)

    try:
        monitor_comfyui(args)
    except KeyboardInterrupt:
        _shutdown_requested = True

    if _comfyui_process is not None and _comfyui_process.poll() is None:
        stop_comfyui()

    logger.info("[ComfyUI-Wrapper] 包装器已退出")


def main():
    parser = argparse.ArgumentParser(
        description="ComfyUI 包装器 - 启动、监控和终止 ComfyUI 进程",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("--comfyui-path", type=str, default=None,
                        help="ComfyUI 根目录路径")
    parser.add_argument("--port", type=int, default=8188,
                        help="监听端口 (默认: 8188)")
    parser.add_argument("--listen", type=str, default="127.0.0.1",
                        help="监听地址 (默认: 127.0.0.1)")
    parser.add_argument("--cuda-device", type=int, default=None,
                        help="CUDA 设备编号")
    parser.add_argument("--lowvram", action="store_true",
                        help="启用低显存模式")
    parser.add_argument("--normalvram", action="store_true",
                        help="使用普通显存模式")
    parser.add_argument("--highvram", action="store_true",
                        help="使用高显存模式")
    parser.add_argument("--cpu", action="store_true",
                        help="使用 CPU 模式")
    parser.add_argument("--dont-upcast-attention", action="store_true",
                        help="禁止 attention upcast")
    parser.add_argument("--auto-launch", action="store_true",
                        help="自动在浏览器打开")
    parser.add_argument("--disable-xformers", action="store_true",
                        help="禁用 xformers")
    parser.add_argument("--enable-xformers", action="store_true",
                        help="启用 xformers")
    parser.add_argument("--log-level", type=str, default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别 (默认: INFO)")
    parser.add_argument("--restart-on-crash", action="store_true",
                        help="崩溃时自动重启")
    parser.add_argument("--max-restarts", type=int, default=3,
                        help="最大重启次数 (默认: 3)")

    args = parser.parse_args()

    if sum([args.lowvram, args.normalvram, args.highvram, args.cpu]) > 1:
        parser.error("只能选择一种显存模式")

    if args.disable_xformers and args.enable_xformers:
        parser.error("不能同时启用和禁用 xformers")

    run(args)


if __name__ == "__main__":
    main()
