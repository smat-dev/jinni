# jinni/server.py
import sys
import os
import json
from pathlib import Path
from typing import List, Optional, Dict, Any

# Ensure jinni package is importable if running script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP, StdioTransport, mcp_tool, ToolContext, ToolInput, ToolResult, MCPError

# Import core logic and custom exceptions
from jinni.core_logic import process_directory, ContextSizeExceededError

# Define the server
server = FastMCP(
    server_name="jinni",
    description="MCP Server for the Jinni project context reading tool.",
    version="0.1.0"
)

# Define the read_context tool
@mcp_tool(
    server=server,
    name="read_context",
    description="Generates a concatenated view of relevant code files from a specified directory, applying filtering rules.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the directory to process."
            },
            "rules": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of inline filtering rules (using .contextfiles syntax).",
                "default": []
            },
            "list_only": {
                "type": "boolean",
                "description": "Only list file paths found.",
                "default": False
            }
        },
        "required": ["path"]
    }
)
async def read_context_tool(context: ToolContext, input: ToolInput) -> ToolResult:
    """MCP Tool implementation for reading project context."""
    root_path_str: str = input.arguments.get("path")
    inline_rules: Optional[List[str]] = input.arguments.get("rules")
    list_only: bool = input.arguments.get("list_only", False)

    # --- Input Validation ---
    if not root_path_str:
        # Should be caught by schema validation, but double-check
        raise MCPError(code=400, message="Missing required argument: path")

    if not os.path.isabs(root_path_str):
         raise MCPError(code=400, message=f"Path must be absolute: {root_path_str}")

    root_path = Path(root_path_str).resolve() # Resolve path first
    # Check directory existence here, as core_logic check was removed for testing
    if not root_path.is_dir():
         raise MCPError(code=404, message=f"Path is not a valid directory: {root_path}")

    # --- Call Core Logic ---
    # --- Call Core Logic ---
    try:
        result_content = process_directory(
            root_path_str=str(root_path), # Pass resolved absolute path string
            list_only=list_only,
            inline_rules_str=inline_rules,
            # Pass None for global_rules and size_limit_mb, let core_logic use defaults/env vars
            global_rules_str=None,
            size_limit_mb=None
        )
        return ToolResult(data=result_content)

    except FileNotFoundError as e:
        # This might occur if the path becomes invalid between check and processing
        return ToolResult(error=MCPError(code=404, message=str(e)))
    except ContextSizeExceededError as e:
        return ToolResult(error=MCPError(code=413, message=str(e))) # 413 Payload Too Large
    except ValueError as e:
        # Likely from absolute path check within core_logic if validation missed it
        return ToolResult(error=MCPError(code=400, message=str(e)))
    except Exception as e:
        # Catch-all for unexpected errors during processing
        print(f"Error processing directory {root_path_str}: {e}", file=sys.stderr) # Log unexpected errors
        return ToolResult(error=MCPError(code=500, message=f"Internal server error during processing: {type(e).__name__}"))


if __name__ == "__main__":
    # Setup and run the server with StdioTransport
    transport = StdioTransport()
    server.add_transport(transport)
    print("Starting Jinni MCP Server via Stdio...", file=sys.stderr)
    server.run()
    print("Jinni MCP Server stopped.", file=sys.stderr)