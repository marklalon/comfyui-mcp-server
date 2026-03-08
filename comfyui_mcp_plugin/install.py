"""
Installation script for ComfyUI MCP Server Auto-Start Custom Node
This script helps you install the custom node to your ComfyUI installation.
"""

import os
import sys
import shutil
import json
from pathlib import Path


def find_comfyui_paths():
    possible_paths = [
        Path("C:/ComfyUI"),
        Path("D:/ComfyUI"),
        Path("E:/ComfyUI"),
        Path.home() / "ComfyUI",
        Path("C:/AI/ComfyUI"),
        Path("D:/AI/ComfyUI"),
        Path("E:/AI/ComfyUI"),
        Path.home() / "AI" / "ComfyUI",
        Path.home() / "Documents" / "ComfyUI",
        Path(__file__).parent.parent.parent / "ComfyUI",
        Path(__file__).parent.parent / "ComfyUI",
    ]
    
    existing_paths = []
    for path in possible_paths:
        if path.exists():
            custom_nodes = path / "custom_nodes"
            if custom_nodes.exists():
                existing_paths.append(path)
    
    return existing_paths


def find_venv_python(mcp_server_dir: Path) -> str:
    venv_paths = [
        mcp_server_dir / ".venv" / "Scripts" / "python.exe",
        mcp_server_dir / "venv" / "Scripts" / "python.exe",
        mcp_server_dir / ".venv" / "bin" / "python",
        mcp_server_dir / "venv" / "bin" / "python",
    ]
    
    for venv_python in venv_paths:
        if venv_python.exists():
            return str(venv_python).replace("\\", "/")
    
    return ""


def install_to_comfyui(comfyui_path: Path):
    source_dir = Path(__file__).parent
    target_dir = comfyui_path / "custom_nodes" / "comfyui_mcp_plugin"
    mcp_server_dir = source_dir.parent
    
    print(f"\nInstalling to: {target_dir}")
    
    if target_dir.exists():
        response = input("Target directory already exists. Overwrite? (y/n): ")
        if response.lower() != 'y':
            print("Installation cancelled.")
            return False
        shutil.rmtree(target_dir)
    
    shutil.copytree(source_dir, target_dir)
    
    venv_python = find_venv_python(mcp_server_dir)
    
    config_path = target_dir / "mcp_config.json"
    config = {
        "enabled": True,
        "mcp_server_path": str(mcp_server_dir / "server.py").replace("\\", "/"),
        "python_path": venv_python,
        "auto_start": True,
        "port": 9000,
        "comfyui_url": "http://localhost:8188"
    }
    
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)
    
    print("\n" + "=" * 70)
    print("✓ Installation successful!")
    print("=" * 70)
    print(f"  Custom node installed to: {target_dir}")
    print(f"  MCP server path: {config['mcp_server_path']}")
    
    if venv_python:
        print(f"  Python path (venv): {venv_python}")
        print("\n  ✓ Using virtual environment Python (recommended)")
    else:
        print("  Python path: (system default)")
        print("\n  ⚠ Warning: No virtual environment found!")
        print("  The MCP server requires the 'mcp' package.")
        print("  Please either:")
        print("    1. Create a virtual environment and install dependencies:")
        print(f"       cd {mcp_server_dir}")
        print("       python -m venv .venv")
        print("       .venv\\Scripts\\pip install -r requirements.txt")
        print("    2. Or install mcp package to your system Python:")
        print("       pip install mcp")
    
    print("\nNext steps:")
    print("  1. Review the configuration (if needed):")
    print(f"     Config file: {config_path}")
    print("  2. Restart ComfyUI")
    print("  3. The MCP server will start automatically when ComfyUI starts")
    
    return True


def main():
    print("=" * 70)
    print("ComfyUI MCP Server Auto-Start - Installation Script")
    print("=" * 70)
    
    print("\nSearching for ComfyUI installations...")
    comfyui_paths = find_comfyui_paths()
    
    if not comfyui_paths:
        print("\nNo ComfyUI installations found automatically.")
        print("Please enter the path to your ComfyUI installation:")
        print("Example: C:/ComfyUI or D:/AI/ComfyUI")
        
        while True:
            user_path = input("\nComfyUI path: ").strip()
            if not user_path:
                print("Installation cancelled.")
                return
            
            path = Path(user_path)
            if path.exists() and (path / "custom_nodes").exists():
                comfyui_paths = [path]
                break
            else:
                print("Invalid path. Please make sure the path contains a 'custom_nodes' directory.")
    
    if len(comfyui_paths) == 1:
        install_to_comfyui(comfyui_paths[0])
    else:
        print("\nMultiple ComfyUI installations found:")
        for i, path in enumerate(comfyui_paths, 1):
            print(f"  {i}. {path}")
        
        while True:
            try:
                choice = int(input("\nSelect installation (number): "))
                if 1 <= choice <= len(comfyui_paths):
                    install_to_comfyui(comfyui_paths[choice - 1])
                    break
                else:
                    print(f"Please enter a number between 1 and {len(comfyui_paths)}")
            except ValueError:
                print("Please enter a valid number.")


if __name__ == "__main__":
    main()
