"""
Update script for ComfyUI MCP Server Auto-Start Custom Node
This script updates the custom node in your ComfyUI installation.
"""

import os
import shutil
import json
from pathlib import Path


def find_comfyui_paths():
    possible_paths = [
        Path("D:/AI/ComfyUI"),
        Path("C:/ComfyUI"),
        Path("E:/ComfyUI"),
        Path.home() / "ComfyUI",
        Path("C:/AI/ComfyUI"),
        Path("E:/AI/ComfyUI"),
        Path.home() / "AI" / "ComfyUI",
        Path.home() / "Documents" / "ComfyUI",
    ]
    
    existing_paths = []
    for path in possible_paths:
        if path.exists():
            custom_nodes = path / "custom_nodes" / "comfyui_mcp_autostart"
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


def update_comfyui_node(comfyui_path: Path):
    source_dir = Path(__file__).parent
    source_file = source_dir / "__init__.py"
    target_dir = comfyui_path / "custom_nodes" / "comfyui_mcp_autostart"
    target_file = target_dir / "__init__.py"
    mcp_server_dir = source_dir.parent
    
    print(f"\nUpdating: {target_file}")
    
    if not target_file.exists():
        print(f"Target file not found: {target_file}")
        print("Please install the custom node first using install.py")
        return False
    
    shutil.copy2(source_file, target_file)
    
    venv_python = find_venv_python(mcp_server_dir)
    config_path = target_dir / "mcp_config.json"
    
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        if venv_python and not config.get("python_path"):
            config["python_path"] = venv_python
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            print(f"Updated python_path to: {venv_python}")
    
    print("\n" + "=" * 70)
    print("✓ Update successful!")
    print("=" * 70)
    print(f"  Updated: {target_file}")
    
    if venv_python:
        print(f"  Python path (venv): {venv_python}")
    else:
        print("  ⚠ No virtual environment found!")
        print("  Make sure 'mcp' package is installed in your Python environment")
    
    print("\nNext steps:")
    print("  1. Restart ComfyUI")
    print("  2. The MCP server should now start correctly")
    
    return True


def main():
    print("=" * 70)
    print("ComfyUI MCP Server Auto-Start - Update Script")
    print("=" * 70)
    
    print("\nSearching for ComfyUI installations with the custom node...")
    comfyui_paths = find_comfyui_paths()
    
    if not comfyui_paths:
        print("\nNo ComfyUI installations found with the custom node installed.")
        print("Please enter the path to your ComfyUI installation:")
        
        while True:
            user_path = input("\nComfyUI path: ").strip()
            if not user_path:
                print("Update cancelled.")
                return
            
            path = Path(user_path)
            target = path / "custom_nodes" / "comfyui_mcp_autostart" / "__init__.py"
            if path.exists() and target.exists():
                comfyui_paths = [path]
                break
            else:
                print("Invalid path or custom node not found.")
    
    if len(comfyui_paths) == 1:
        update_comfyui_node(comfyui_paths[0])
    else:
        print("\nMultiple ComfyUI installations found:")
        for i, path in enumerate(comfyui_paths, 1):
            print(f"  {i}. {path}")
        
        while True:
            try:
                choice = int(input("\nSelect installation to update (number): "))
                if 1 <= choice <= len(comfyui_paths):
                    update_comfyui_node(comfyui_paths[choice - 1])
                    break
                else:
                    print(f"Please enter a number between 1 and {len(comfyui_paths)}")
            except ValueError:
                print("Please enter a valid number.")


if __name__ == "__main__":
    main()
