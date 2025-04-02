# jinni/server.py
import sys
import os
import json # Keep for potential future use
import logging # Added
from pathlib import Path
from typing import List, Optional, Any

# Ensure jinni package is importable if running script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)) # RESTORED
# Setup logger for the server
logger = logging.getLogger("jinni.server")
# Configure basic logging if no handlers are configured (e.g., when run directly)
if not logger.handlers and not logging.getLogger().handlers:
     logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# Restored conditional basicConfig above

# --- New MCP Imports ---
from mcp.server.fastmcp import FastMCP, Context
# Removed incorrect StdioTransport import

# --- Core Logic Imports ---
from jinni.core_logic import process_directory, ContextSizeExceededError, DEFAULT_SIZE_LIMIT_MB, ENV_VAR_SIZE_LIMIT # Keep custom exception
# Removed duplicate import on next line

# --- Server Definition ---
# FastMCP uses the server name passed here. Description/version might be inferred or set elsewhere.
server = FastMCP("jinni")

# --- Tool Definition ---
@server.tool()
async def read_context( # Add log here
    path: str,
    rules: Optional[List[str]] = None,
    list_only: bool = False,
    size_limit_mb: Optional[int] = None,
    debug_explain: bool = False,
    ctx: Context = None # Add context for potential future use (e.g., progress reporting)
) -> str:
    logger.info("--- read_context tool invoked ---") # Add prominent log
    logger.debug(f"Received read_context request: path='{path}', list_only={list_only}, rules={rules}, debug_explain={debug_explain}") # Keep as DEBUG
    """
    Generates a concatenated view of relevant code files from a specified directory,
    applying filtering rules.

    Args:
        path: Absolute path to the directory to process.
        rules: Optional list of inline filtering rules (using .contextfiles syntax). Defaults to None.
        list_only: Only list file paths found. Defaults to False.
        size_limit_mb: Override the maximum total context size in MB. Defaults to None (uses core_logic default).
        debug_explain: Print detailed explanation for file/directory inclusion/exclusion to server's stderr. Defaults to False.
        ctx: The MCP context object (currently unused).
    """
    # --- Input Validation ---
    if not os.path.isabs(path):
         # FastMCP should convert this to an appropriate MCP error
         raise ValueError(f"Path must be absolute: {path}")

    root_path = Path(path).resolve()
    if not root_path.is_dir():
         # FastMCP should convert this to an appropriate MCP error
         raise FileNotFoundError(f"Path is not a valid directory: {root_path}")

    # --- Call Core Logic ---
    try:
        logger.debug(f"Processing directory: {path}") # Change INFO to DEBUG
        # process_directory raises FileNotFoundError, ContextSizeExceededError, ValueError
        result_content = process_directory(
            root_path_str=str(root_path), # Pass resolved absolute path string
            list_only=list_only,
            inline_rules_str=rules, # Pass rules directly
            global_rules_str=None, # MCP tool doesn't use global config file directly
            size_limit_mb=size_limit_mb,
            debug_explain=debug_explain
        )
        logger.debug(f"Finished processing directory: {path}. Result length: {len(result_content)}") # Change INFO to DEBUG
        # Return the string result directly
        return result_content
    except (FileNotFoundError, ContextSizeExceededError, ValueError) as e:
        # Let FastMCP handle converting these known errors
        raise e
    except Exception as e:
        # Log unexpected errors before FastMCP potentially converts to a generic 500
        logger.exception(f"Unexpected error processing directory {path}: {type(e).__name__} - {e}")
        raise e # Re-raise for FastMCP


# --- Main Execution Block ---
if __name__ == "__main__":
    # Setup and run the server with StdioTransport
    # transport = StdioTransport() # Removed explicit transport setup
    # server.add_transport(transport) # Removed explicit transport setup
    logger.info("--- Jinni MCP Server: About to call server.run() ---") # Keep log
    try:
        server.run() # Run the server (FastMCP should handle stdio implicitly)
    except Exception as e:
        logger.critical(f"!!! Exception during server.run(): {e}", exc_info=True) # Add try/except around run
        sys.exit(1)
    logger.debug("Jinni MCP Server stopped.") # Change INFO to DEBUG