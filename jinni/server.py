# jinni/server.py
import sys
import os
import json # Keep for potential future use
import logging
import argparse
from pathlib import Path
from typing import List, Optional, Any, Union, Set # Added Set

# Ensure jinni package is importable if running script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Setup logger for the server
logger = logging.getLogger("jinni.server")
# Configure basic logging if no handlers are configured (e.g., when run directly)
if not logger.handlers and not logging.getLogger().handlers:
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s') # Use INFO for server default

# --- New MCP Imports ---
from mcp.server.fastmcp import FastMCP, Context

# --- Core Logic Imports ---
# Updated import to use the new core function and renamed to avoid collision
from jinni.core_logic import read_context as core_read_context, ContextSizeExceededError, DEFAULT_SIZE_LIMIT_MB, ENV_VAR_SIZE_LIMIT

# --- Server Definition ---
server = FastMCP("jinni")

# Global variable to store the server's root path if provided via CLI
SERVER_ROOT_PATH: Optional[Path] = None

# --- Tool Definition ---
@server.tool(description="Read in context. Paths must be absolute.")
async def read_context( # Renamed tool function to match core logic for clarity
    path: str,
    # Removed 'root' argument as it's handled by SERVER_ROOT_PATH validation now
    rules: Optional[List[str]] = None,
    list_only: bool = False,
    size_limit_mb: Optional[int] = None,
    debug_explain: bool = False,
    ctx: Context = None # Add context for potential future use
) -> str:
    logger.info("--- read_context tool invoked ---")
    logger.debug(f"Received read_context request: path='{path}', list_only={list_only}, rules={rules}, debug_explain={debug_explain}")
    """
    Generates a concatenated view of relevant code files for a given target path.

    The 'path' argument must always be an absolute path.

    If the server was started with a --root argument, the provided 'path' must be
    within that server root directory.

    Args:
        path: **MUST BE ABSOLUTE PATH**. The absolute path to the file or directory to process.
        rules: Optional list of inline filtering rules (using .contextfiles syntax). Defaults to None.
        list_only: Only list file paths found. Defaults to False.
        size_limit_mb: Override the maximum total context size in MB. Defaults to None (uses core_logic default).
        debug_explain: Print detailed explanation for file/directory inclusion/exclusion to server's stderr. Defaults to False.
        ctx: The MCP context object (currently unused).
    """
    # --- Input Validation: Path must always be absolute ---
    if not os.path.isabs(path):
        raise ValueError(f"Tool 'path' argument must always be absolute, received: '{path}'")

    resolved_client_path = Path(path).resolve()
    # Use exists() which works for both files and directories
    if not resolved_client_path.exists():
        raise FileNotFoundError(f"Tool 'path' does not exist: {resolved_client_path}")

    # --- Determine Effective Paths and Validate against Server Root ---
    output_relative_to_path: Path

    if SERVER_ROOT_PATH:
        # Server has a fixed root path
        logger.debug(f"Server root is set: {SERVER_ROOT_PATH}")

        # Validate the absolute client path is within the server root
        try:
            # Check if the resolved path is relative to the server root
            resolved_client_path.relative_to(SERVER_ROOT_PATH)
            logger.debug(f"Client path {resolved_client_path} is within server root {SERVER_ROOT_PATH}")
        except ValueError:
             # This error means the path is not within the root
             raise ValueError(f"Tool path '{resolved_client_path}' is outside the allowed server root '{SERVER_ROOT_PATH}'")

        # Use server root for relative path calculations in output
        output_relative_to_path = SERVER_ROOT_PATH

    else:
        # Server does NOT have a fixed root path - use client-provided path to determine relative root
        logger.debug("Server root is not set. Determining output relative root from client path.")
        if resolved_client_path.is_dir():
            output_relative_to_path = resolved_client_path
        else:
            output_relative_to_path = resolved_client_path.parent
        logger.debug(f"Using output relative root: {output_relative_to_path}")


    # Convert paths to strings for core_logic function
    output_relative_to_str = str(output_relative_to_path)
    target_path_str = str(resolved_client_path)

    logger.info(f"Processing target: {target_path_str}")
    logger.info(f"Output paths relative to: {output_relative_to_str}")

    # --- Call Core Logic ---
    try:
        # Call the refactored core_logic function
        result_content = core_read_context( # Call the renamed core logic function
            target_paths_str=[target_path_str], # Pass the single target as a list
            output_relative_to_str=output_relative_to_str, # Pass determined relative root
            override_rules=rules, # Pass rules directly
            list_only=list_only,
            size_limit_mb=size_limit_mb,
            debug_explain=debug_explain
        )
        logger.debug(f"Finished processing target: {target_path_str}. Result length: {len(result_content)}")
        # Return the string result directly
        return result_content
    except (FileNotFoundError, ContextSizeExceededError, ValueError) as e:
        # Let FastMCP handle converting these known errors
        logger.error(f"Error during read_context call for '{target_path_str}': {type(e).__name__} - {e}")
        raise e
    except Exception as e:
        # Log unexpected errors before FastMCP potentially converts to a generic 500
        logger.exception(f"Unexpected error processing target {target_path_str}: {type(e).__name__} - {e}")
        raise e


# --- Main Execution Block ---
if __name__ == "__main__":
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(description="Jinni MCP Server")
    parser.add_argument(
        "--root",
        type=str,
        help="Optional absolute root path to constrain all 'read_context' operations.",
        default=None
    )
    # Add log level argument
    parser.add_argument(
        "--log-level",
        type=str,
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        default='INFO',
        help="Set the logging level for the server."
    )

    args = parser.parse_args()

    # --- Configure Logging Level ---
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    # Reconfigure root logger level if needed (affects handlers added later too)
    logging.getLogger().setLevel(log_level)
    # Also set the level for our specific logger
    logger.setLevel(log_level)
    # Update handler level if already configured (e.g., basicConfig ran)
    for handler in logging.getLogger().handlers:
        handler.setLevel(log_level)
    logger.info(f"Server log level set to: {args.log_level.upper()}")


    if args.root:
        server_root = Path(args.root).resolve()
        if not server_root.is_dir():
            logger.critical(f"Error: Provided --root path '{args.root}' is not a valid directory.")
            sys.exit(1)
        if not server_root.is_absolute():
             # Although resolve() should make it absolute, double-check
             logger.critical(f"Error: Provided --root path '{args.root}' must be absolute.")
             sys.exit(1)
        SERVER_ROOT_PATH = server_root # Store globally
        logger.info(f"--- Jinni MCP Server configured with root: {SERVER_ROOT_PATH} ---")
    else:
        logger.info("--- Jinni MCP Server starting without a fixed root path ---")


    # --- Run Server ---
    logger.info("--- Jinni MCP Server: About to call server.run() ---")
    try:
        server.run() # Run the server (FastMCP should handle stdio implicitly)
    except Exception as e:
        logger.critical(f"!!! Exception during server.run(): {e}", exc_info=True)
        sys.exit(1)
    logger.info("Jinni MCP Server stopped.") # Use INFO for start/stop messages