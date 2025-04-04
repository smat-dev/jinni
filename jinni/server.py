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
# Import from refactored modules
from jinni.core_logic import read_context as core_read_context, get_jinni_doc # Main functions from new core_logic
from jinni.exceptions import ContextSizeExceededError, DetailedContextSizeError # Exceptions moved
# Constants like DEFAULT_SIZE_LIMIT_MB might be needed if used directly, otherwise remove.
# Let's assume they are handled within core_logic now.

# --- Server Definition ---
server = FastMCP("jinni")

# Global variable to store the server's root path if provided via CLI
SERVER_ROOT_PATH: Optional[Path] = None


# --- jinni_doc Tool ---
@server.tool(description="Retrieves the content of the project's README.md file.")
async def jinni_doc() -> str:
    """Returns documentation for advanced usage of Jinni"""
    logger.info("--- jinni_doc tool invoked ---")
    try:
        readme_content = get_jinni_doc() # Use directly imported function
        # Prepend the requested message
        return f"Jinni Doc (accessed via MCP Client):\n\n{readme_content}"
    except Exception as e:
        logger.exception(f"Unexpected error in jinni_doc tool: {e}")
        # Let FastMCP handle the exception formatting
        raise e

# --- Tool Definition (Corrected) ---
@server.tool(description=(
    "Reads context from a specified project root directory (absolute path). "
    "Optionally focuses on a specific target file/directory within that root. "
    "Returns a concatenated string of files with metadata including paths relative to the project root. "
    "Assume the user wants to read in context for the whole project unless otherwise specified - "
    "do not ask the user for clarification if just asked to use the tool / read in context. "
    "You can ignore the other arguments by default. "
    "If the user just says 'jinni', interpret that as read_context."
))
async def read_context(
    project_root: str, # Mandatory project root path
    target: Optional[str] = None, # Optional target path within project_root
    rules: Optional[List[str]] = None,
    list_only: bool = False,
    size_limit_mb: Optional[int] = None,
    debug_explain: bool = False,
) -> str:
    logger.info("--- read_context tool invoked ---")
    logger.debug(f"Received read_context request: project_root='{project_root}', target='{target}', list_only={list_only}, rules={rules}, debug_explain={debug_explain}")
    """
    Generates a concatenated view of relevant code files for a given target path.

    The 'project_root' argument must always be an absolute path.
    The optional 'target' argument, if provided, must be an absolute path or a path
    relative to the current working directory, and it must resolve to a location
    *inside* the 'project_root'.

    If the server was started with a --root argument, the provided 'project_root' must be
    within that server root directory.
    Args:
        project_root: **MUST BE ABSOLUTE PATH**. The absolute path to the project root directory.
        target: Optional path (absolute or relative to CWD) to a specific file or directory
                within the project root to process. If omitted, the entire project root is processed.
        rules: Optional list of inline filtering rules (using .contextfiles syntax). Defaults to None.
        list_only: Only list file paths found. Defaults to False.
        size_limit_mb: Override the maximum total context size in MB. Defaults to None (uses core_logic default).
        debug_explain: Print detailed explanation for file/directory inclusion/exclusion to server's stderr. Defaults to False.
    """
    # --- Input Validation ---
    # Validate project_root
    if not os.path.isabs(project_root):
         raise ValueError(f"Tool 'project_root' argument must be absolute, received: '{project_root}'")
    resolved_project_root_path = Path(project_root).resolve()
    if not resolved_project_root_path.is_dir():
         raise ValueError(f"Tool 'project_root' path does not exist or is not a directory: {resolved_project_root_path}")
    resolved_project_root_path_str = str(resolved_project_root_path) # Store as string for core_logic
    logger.debug(f"Using project_root: {resolved_project_root_path_str}")

    # Validate target if provided
    resolved_target_path_str: Optional[str] = None
    if target:
        # Resolve target relative to CWD (Path default) before checking if it's inside project_root
        resolved_target_path = Path(target).resolve()
        if not resolved_target_path.exists():
             raise FileNotFoundError(f"Tool 'target' path does not exist: {resolved_target_path}")
        # Check if target is within project_root AFTER resolving
        try:
            resolved_target_path.relative_to(resolved_project_root_path)
        except ValueError:
             raise ValueError(f"Tool 'target' path '{resolved_target_path}' is outside the specified project root '{resolved_project_root_path}'")
        resolved_target_path_str = str(resolved_target_path)
        logger.debug(f"Using target path: {resolved_target_path_str}")
    else:
        logger.debug("No target provided. Processing entire project_root.")

    # --- Validate against Server Root (if set) ---
    # The *project_root* provided by the client must be within the server's root (if set)
    if SERVER_ROOT_PATH:
        logger.debug(f"Server root is set: {SERVER_ROOT_PATH}")
        try:
            resolved_project_root_path.relative_to(SERVER_ROOT_PATH)
            logger.debug(f"Client project_root {resolved_project_root_path} is within server root {SERVER_ROOT_PATH}")
        except ValueError:
             raise ValueError(f"Tool project_root '{resolved_project_root_path}' is outside the allowed server root '{SERVER_ROOT_PATH}'")

    logger.info(f"Processing project_root: {resolved_project_root_path_str}")
    if resolved_target_path_str:
        logger.info(f"Focusing on target: {resolved_target_path_str}")
    # --- Call Core Logic ---
    try:
        # Adapt server args (mandatory project_root, optional target)
        # to core_logic args (list of targets, optional project_root for relativity)
        effective_target_paths_str: List[str]
        if resolved_target_path_str:
            # If target is given, it's the single path to process
            effective_target_paths_str = [resolved_target_path_str]
        else:
            # If no target is given, process the project root itself
            effective_target_paths_str = [resolved_project_root_path_str]

        result_content = core_read_context( # Use the directly imported function name
            target_paths_str=effective_target_paths_str,
            project_root_str=resolved_project_root_path_str, # Pass the server's mandatory root
            override_rules=rules,
            list_only=list_only,
            size_limit_mb=size_limit_mb,
            debug_explain=debug_explain
            # include_size_in_list is False by default in core_logic if not passed
        )
        logger.debug(f"Finished processing project_root: {resolved_project_root_path_str}, target: {resolved_target_path_str}. Result length: {len(result_content)}")
        # Return the string result directly
        return result_content
    except (FileNotFoundError, ContextSizeExceededError, ValueError, DetailedContextSizeError) as e:
        # Let FastMCP handle converting these known errors
        logger.error(f"Error during read_context call for project_root='{resolved_project_root_path_str}', target='{resolved_target_path_str}': {type(e).__name__} - {e}")
        raise e # Re-raise for FastMCP
    except Exception as e:
        # Log unexpected errors before FastMCP potentially converts to a generic 500
        logger.exception(f"Unexpected error processing project_root='{resolved_project_root_path_str}', target='{resolved_target_path_str}': {type(e).__name__} - {e}")
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