# jinni/server.py
import sys
import os
import json # Keep for potential future use
import logging # Added
import argparse # NEW: For CLI arguments
from pathlib import Path
from typing import List, Optional, Any, Union # Union added for type hint

# Ensure jinni package is importable if running script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)) # RESTORED
# Setup logger for the server
logger = logging.getLogger("jinni.server")
# Configure basic logging if no handlers are configured (e.g., when run directly)
if not logger.handlers and not logging.getLogger().handlers:
     logging.basicConfig(level=logging.WARN, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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

# Global variable to store the server's root path if provided via CLI
SERVER_ROOT_PATH: Optional[Path] = None

# --- Tool Definition ---
@server.tool()
async def read_context( # Add log here
    path: str,
    root: Optional[str] = None, # NEW: Optional root path constraint
    rules: Optional[List[str]] = None,
    list_only: bool = False,
    size_limit_mb: Optional[int] = None,
    debug_explain: bool = False,
    ctx: Context = None # Add context for potential future use (e.g., progress reporting)
) -> str:
    logger.info("--- read_context tool invoked ---")
    logger.debug(f"Received read_context request: path='{path}', root='{root}', list_only={list_only}, rules={rules}, debug_explain={debug_explain}")
    """
    Generates a concatenated view of relevant code files.

    The 'path' argument must always be an absolute path.

    If the server was started with a --root argument, the provided 'path' must be
    within that server root directory, and the 'root' argument in this tool call must be None.

    If the server was *not* started with --root, the 'root' argument can optionally be
    an absolute path within 'path' to further constrain processing.

    Args:
        path: Absolute path to the directory to process.
        root: Optional absolute path constraint (only usable if server --root is NOT set). Defaults to None.
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
    if not resolved_client_path.is_dir():
        raise FileNotFoundError(f"Tool 'path' is not a valid directory: {resolved_client_path}")

    # --- Determine Effective Paths based on Server Root ---
    effective_root_path: Path
    effective_processing_root_path: Path

    if SERVER_ROOT_PATH:
        # Server has a fixed root path
        logger.debug(f"Server root is set: {SERVER_ROOT_PATH}")
        if root is not None:
             raise ValueError(f"When server --root is set ('{SERVER_ROOT_PATH}'), the tool 'root' argument must be None, but received: '{root}'")

        # Validate the absolute client path is within the server root
        if not str(resolved_client_path).startswith(str(SERVER_ROOT_PATH)):
             raise ValueError(f"Tool path '{resolved_client_path}' is outside the server root '{SERVER_ROOT_PATH}'")

        effective_root_path = SERVER_ROOT_PATH # The overall project root for context file hierarchy
        effective_processing_root_path = resolved_client_path # The actual starting point for the walk

    else:
        # Server does NOT have a fixed root path - use client-provided paths
        logger.debug("Server root is not set. Using client-provided paths.")

        effective_root_path = resolved_client_path # Base path for context file hierarchy

        # Handle optional client-provided root constraint
        if root:
            if not os.path.isabs(root):
                raise ValueError(f"Optional tool 'root' path must be absolute: {root}")
            client_root_resolved = Path(root).resolve()
            if not client_root_resolved.is_dir():
                raise FileNotFoundError(f"Optional tool 'root' path is not a valid directory: {client_root_resolved}")
            # Check if client root is within client path
            if not str(client_root_resolved).startswith(str(resolved_client_path)):
                 raise ValueError(f"Optional tool 'root' path '{client_root_resolved}' must be inside the main tool 'path' '{resolved_client_path}'")
            effective_processing_root_path = client_root_resolved
            logger.debug(f"Constraining processing to client root: {effective_processing_root_path}")
        else:
            # If no client root provided, process starting from the client path
            effective_processing_root_path = resolved_client_path

    # Convert paths to strings for core_logic function
    effective_root_path_str = str(effective_root_path)
    effective_processing_root_path_str = str(effective_processing_root_path)
    logger.info(f"Effective root for context files: {effective_root_path_str}")
    logger.info(f"Effective processing start path: {effective_processing_root_path_str}")

    # --- Call Core Logic ---
    try:
        logger.debug(f"Processing directory: {path}") # Change INFO to DEBUG
        # process_directory raises FileNotFoundError, ContextSizeExceededError, ValueError
        # MCP tool processes a single target path at a time.
        # Initialize an empty set for processed files for this single call.
        processed_files_init: Set[Path] = set()
        result_content, _ = process_directory( # Ignore the returned processed_files set
            root_path_str=effective_root_path_str, # Root for rule discovery
            output_rel_root_str=effective_root_path_str, # Root for output relative paths (same as rule root for server)
            processing_target_str=effective_processing_root_path_str,
            processed_files_set=processed_files_init,
            list_only=list_only,
            inline_rules_str=rules,
            global_rules_str=None,
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
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(description="Jinni MCP Server")
    parser.add_argument(
        "--root",
        type=str,
        help="Optional absolute root path to constrain all 'read_context' operations.",
        default=None
    )
    args = parser.parse_args()

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
    logger.info("--- Jinni MCP Server: About to call server.run() ---") # Keep log
    try:
        server.run() # Run the server (FastMCP should handle stdio implicitly)
    except Exception as e:
        logger.critical(f"!!! Exception during server.run(): {e}", exc_info=True) # Add try/except around run
        sys.exit(1)
    logger.debug("Jinni MCP Server stopped.") # Change INFO to DEBUG