# ComfyUI MCP Server Auto-Start

This custom node automatically starts the MCP server when ComfyUI starts and stops it when ComfyUI closes.

## Installation

### Method 1: Manual Installation

1. Copy the `comfyui_mcp_autostart` folder to your ComfyUI's `custom_nodes` directory:
   ```
   ComfyUI/custom_nodes/comfyui_mcp_autostart/
   ```

2. Edit the `mcp_config.json` file to set the correct path to your MCP server:
   ```json
   {
     "enabled": true,
     "mcp_server_path": "path/to/your/comfyui-mcp-server/server.py",
     "python_path": "",
     "auto_start": true,
     "port": 9000,
     "comfyui_url": "http://localhost:8188"
   }
   ```

3. Restart ComfyUI

### Method 2: Using ComfyUI-Manager

If you have ComfyUI-Manager installed, you can install this custom node through the manager interface.

## Configuration

Edit `mcp_config.json` to customize the behavior:

- `enabled`: Enable or disable the auto-start feature (true/false)
- `mcp_server_path`: Path to the MCP server's `server.py` file
- `python_path`: Path to Python interpreter (leave empty to use system default)
- `auto_start`: Automatically start MCP server when ComfyUI starts (true/false)
- `port`: Port number for the MCP server (default: 9000)
- `comfyui_url`: URL where ComfyUI is running (default: http://localhost:8188)

## Nodes Provided

### 🔧 MCP Server Control

A node to manually control the MCP server:
- **Start**: Start the MCP server
- **Stop**: Stop the MCP server
- **Restart**: Restart the MCP server
- **Status**: Check the current status of the MCP server

### ⚙️ MCP Server Config

A node to configure the MCP server settings through the workflow:
- Set the MCP server path
- Configure the port
- Set the ComfyUI URL

## How It Works

1. When ComfyUI starts, the custom node automatically loads the configuration
2. If auto-start is enabled, it launches the MCP server as a subprocess
3. The MCP server runs in the background while ComfyUI is active
4. When ComfyUI closes, the custom node automatically stops the MCP server

## Troubleshooting

### MCP Server doesn't start

1. Check that the `mcp_server_path` in `mcp_config.json` is correct
2. Verify that the MCP server can be started manually: `python server.py`
3. Check ComfyUI's console output for error messages

### MCP Server doesn't stop

The custom node uses Python's `atexit` to stop the server when ComfyUI closes. If ComfyUI crashes or is force-closed, the MCP server process might remain running. You can:

1. Use the Task Manager (Windows) or Activity Monitor (Mac/Linux) to find and stop the process
2. Use the "Stop" action in the MCP Server Control node

### Port conflicts

If port 9000 is already in use:
1. Change the `port` setting in `mcp_config.json`
2. Restart ComfyUI

## Requirements

- ComfyUI
- comfyui-mcp-server (installed separately)
- Python 3.8+

## License

Apache License 2.0
