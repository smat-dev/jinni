# jinni/server.py
import sys
import os
import json # Keep for potential future use
import logging
import io # Add io for StringIO
import argparse
from pathlib import Path
from typing import List, Optional, Any, Union, Set # Added Set
from pydantic import Field

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
from jinni.core_logic import read_context as core_read_context # Main functions from new core_logic
from jinni.exceptions import ContextSizeExceededError, DetailedContextSizeError # Exceptions moved
from jinni.utils import ESSENTIAL_USAGE_DOC, _translate_wsl_path, ensure_no_nul # Import the shared usage doc constant and WSL path translator
# Constants like DEFAULT_SIZE_LIMIT_MB might be needed if used directly, otherwise remove.
# Let's assume they are handled within core_logic now.

# --- Server Definition ---
server = FastMCP("jinni")

# Global variable to store the server's root path if provided via CLI
SERVER_ROOT_PATH: Optional[Path] = None


# --- usage Tool ---
@server.tool(description="Retrieves the Jinni usage documentation (content of README.md).")
async def usage() -> str:
    """Returns essential Jinni usage documentation focusing on rules and .contextfiles."""
    logger.info("--- usage tool invoked (returning shared essential info) ---")
    # Use the imported constant from utils.py
    return ESSENTIAL_USAGE_DOC

# --- Tool Definition (Corrected) ---
@server.tool(description=(
    "Reads context from a specified project root directory (absolute path). "
    "Focuses on the specified target files/directories within that root. "
    "Returns a static view of files with paths relative to the project root. "
    "Assume the user wants to read in context for the whole project unless otherwise specified - "
    "do not ask the user for clarification if just asked to read context. "
    "If the user just says 'jinni', interpret that as read_context. "
    "If the user asks to list context, use the list_only argument. "
    "Both `targets` and `rules` accept a JSON array of strings. "
    "The `project_root`, `targets`, and `rules` arguments are mandatory. "
    "You can ignore the other arguments by default. "
    "IMPORTANT NOTE ON RULES: Ensure you understand the rule syntax (details available via the `usage` tool) before providing specific rules. "
    "Using `rules=[]` is recommended if unsure, as this uses sensible defaults.\n\n"
    "**Guidance for AI Model Usage**\n\n"
    "When requesting context using this tool:\n"
    "*   **Default Behavior:** If you provide an empty `rules` list (`[]`), Jinni uses sensible default exclusions (like `.git`, `node_modules`, `__pycache__`, common binary types) combined with any project-specific `.contextfiles`. This usually provides the \"canonical context\" - files developers typically track in version control. Assume this is what the users wants if they just ask to read context.\n"
    "*   **Targeting Specific Files:** If you have a list of specific files you need (e.g., `[\"src/main.py\", \"README.md\"]`), provide them in the `targets` list. This is efficient and precise, quicker than reading one by one.\n"
))




async def read_context(
    project_root: str = Field(description="**MUST BE ABSOLUTE PATH**. The absolute path to the project root directory."),
    targets: List[str] = Field(description="**Mandatory**. List of paths (absolute or relative to CWD) to specific files or directories within the project root to process. Must be a JSON array of strings. If empty (`[]`), the entire `project_root` is processed."),
    rules: List[str] = Field(description="**Mandatory**. List of inline filtering rules. Provide `[]` if no specific rules are needed (uses defaults). It is strongly recommended to consult the `usage` tool documentation before providing a non-empty list."),
    list_only: bool = False,
    size_limit_mb: Optional[int] = None,
    debug_explain: bool = False,
    exclusions: Optional[dict] = Field(default=None, description="Optional exclusion configuration. Object with 'global' (list of keywords), 'scoped' (object mapping paths to keyword lists), and 'patterns' (list of file patterns) fields."),
) -> str:
    logger.info("--- read_context tool invoked ---")
    # Translate incoming paths *before* any validation or Path object creation
    translated_project_root = _translate_wsl_path(project_root)
    translated_targets = [_translate_wsl_path(t) for t in targets]
    logger.debug(f"Original paths: project_root='{project_root}', targets='{targets}'")
    logger.debug(f"Translated paths: project_root='{translated_project_root}', targets='{translated_targets}'")

    # Defensive NUL check on all incoming paths
    ensure_no_nul(translated_project_root, "project_root")
    for t in translated_targets:
        ensure_no_nul(t, "target path")

    logger.debug(f"Processing read_context request: project_root(orig)='{project_root}', targets(orig)='{targets}', list_only={list_only}, rules={rules}, debug_explain={debug_explain}")
    """
    Generates a concatenated view of relevant code files for a given target path.

    The 'project_root' argument must always be an absolute path.
    The optional 'targets' argument, if provided, must be a list of paths (JSON array of strings).
    Each path must be absolute or relative to the current working directory, and must resolve to a location
    *inside* the 'project_root'.

    If the server was started with a --root argument, the provided 'project_root' must be
    within that server root directory.
    
    Args:
        project_root: See Field description.
        targets: See Field description.
        rules: See Field description.
        list_only: Only list file paths found. Defaults to False.
        size_limit_mb: Override the maximum total context size in MB. Defaults to None (uses core_logic default).
        debug_explain: Print detailed explanation for file/directory inclusion/exclusion to server's stderr. Defaults to False.
    """
    # --- Input Validation ---
    # Use the translated project_root for validation
    if not os.path.isabs(translated_project_root):
         raise ValueError(f"Tool 'project_root' argument must be absolute (after translation), received: '{translated_project_root}' from original '{project_root}'")
    resolved_project_root_path = Path(translated_project_root).resolve()
    if not resolved_project_root_path.is_dir():
         raise ValueError(f"Tool 'project_root' path does not exist or is not a directory: {resolved_project_root_path} (translated from '{project_root}')")
    resolved_project_root_path_str = str(resolved_project_root_path) # Store translated path as string
    logger.debug(f"Using project_root (translated): {resolved_project_root_path_str}")

    # Validate mandatory targets list (can be empty)
    # No need for `is None` check, Pydantic/FastMCP ensures it's a list.

    resolved_target_paths_str: List[str] = []
    effective_targets_set: Set[str] = set() # Use set to handle duplicates implicitly

    # Process the provided targets list if it's not empty
    if translated_targets:
        logger.debug(f"Processing translated targets list: {translated_targets}")
        for idx, single_target in enumerate(translated_targets):
            if not isinstance(single_target, str):
                 raise TypeError(f"Tool 'targets' item at index {idx} must be a string, got {type(single_target)}")

            # Check if target is absolute. If not, resolve relative to project_root.
            target_path_obj = Path(single_target)
            if target_path_obj.is_absolute():
                resolved_target_path = target_path_obj.resolve()
            else:
                # Resolve relative path against the project root
                resolved_target_path = (resolved_project_root_path / target_path_obj).resolve()
                logger.debug(f"Resolved relative target '{single_target}' to '{resolved_target_path}' using project root '{resolved_project_root_path}'")
            if not resolved_target_path.exists():
                 raise FileNotFoundError(f"Tool 'targets' path '{single_target}' (resolved to {resolved_target_path}) does not exist.")
            # Check if target is within project_root AFTER resolving
            try:
                resolved_target_path.relative_to(resolved_project_root_path)
            except ValueError:
                 raise ValueError(f"Tool 'targets' path '{resolved_target_path}' is outside the specified project root '{resolved_project_root_path}'")

            resolved_path_str = str(resolved_target_path)
            if resolved_path_str not in effective_targets_set:
                 resolved_target_paths_str.append(resolved_path_str)
                 effective_targets_set.add(resolved_path_str)
                 logger.debug(f"Validated target path from targets[{idx}]: {resolved_path_str}")
            else:
                 logger.debug(f"Skipping duplicate target path from targets[{idx}]: {resolved_path_str}")

    # If the initial targets list was empty OR it resulted in an empty list after validation,
    # default to processing the project root.
    if not resolved_target_paths_str:
        logger.debug("Targets list is empty or resulted in no valid paths. Defaulting to project root.")
        resolved_target_paths_str = [resolved_project_root_path_str]

    # Validate mandatory rules list (can be empty, but must be provided)
    if rules is None: # Should not happen if Pydantic enforces mandatory, but good practice
        raise ValueError("Tool 'rules' argument is mandatory. Provide an empty list [] if no specific rules are needed.")
    if not isinstance(rules, list):
        raise TypeError(f"Tool 'rules' argument must be a list, got {type(rules)}")
    for idx, rule in enumerate(rules):
        if not isinstance(rule, str):
            raise TypeError(f"Tool 'rules' item at index {idx} must be a string, got {type(rule)}")
    logger.debug(f"Using provided rules: {rules}")


    # --- Validate against Server Root (if set) ---
    # The *project_root* provided by the client must be within the server's root (if set)
    if SERVER_ROOT_PATH:
        logger.debug(f"Server root is set: {SERVER_ROOT_PATH}")
        try:
            resolved_project_root_path.relative_to(SERVER_ROOT_PATH)
            logger.debug(f"Client project_root {resolved_project_root_path} is within server root {SERVER_ROOT_PATH}")
        except ValueError:
             raise ValueError(f"Tool project_root '{resolved_project_root_path}' is outside the allowed server root '{SERVER_ROOT_PATH}'")

    # --- Process Exclusions ---
    exclusion_parser = None
    exclusion_patterns = []
    if exclusions:
        from jinni.exclusion_parser import ExclusionParser
        
        # Extract exclusion components
        global_keywords = exclusions.get('global', [])
        scoped_exclusions = exclusions.get('scoped', {})
        file_patterns = exclusions.get('patterns', [])
        
        # Convert scoped dict to list format expected by ExclusionParser
        scoped_list = []
        for path, keywords in scoped_exclusions.items():
            if isinstance(keywords, list):
                scoped_list.append(f"{path}:{','.join(keywords)}")
        
        # Create exclusion parser
        parser = ExclusionParser()
        
        # Parse different exclusion types
        exclusion_patterns.extend(parser.parse_not(global_keywords))
        exclusion_patterns.extend(parser.parse_not_in(scoped_list))
        exclusion_patterns.extend(parser.parse_not_files(file_patterns))
        
        if exclusion_patterns:
            exclusion_parser = parser
            logger.info(f"Configured {len(exclusion_patterns)} exclusion patterns")

    logger.info(f"Processing project_root: {resolved_project_root_path_str}")
    # Log the final list of targets being processed
    # Log the final list of targets being processed
    # Log the final list of targets being processed
    logger.info(f"Focusing on target(s): {resolved_target_paths_str}")
    # --- Call Core Logic ---
    log_capture_buffer = None
    temp_handler = None
    loggers_to_capture = []
    debug_output = ""

    try:
        if debug_explain:
            # Setup temporary handler to capture debug logs
            log_capture_buffer = io.StringIO()
            temp_handler = logging.StreamHandler(log_capture_buffer)
            temp_handler.setLevel(logging.DEBUG)
            # Simple formatter for captured logs
            formatter = logging.Formatter('%(name)s:%(levelname)s: %(message)s')
            temp_handler.setFormatter(formatter)

            # Add handler to relevant core logic loggers
            loggers_to_capture = [
                logging.getLogger(name) for name in
                ["jinni.core_logic", "jinni.context_walker", "jinni.file_processor", "jinni.config_system", "jinni.utils"]
            ]
            for core_logger in loggers_to_capture:
                # Explicitly set level to DEBUG *before* adding handler
                # This ensures messages are generated for the handler to capture
                original_level = core_logger.level
                core_logger.setLevel(logging.DEBUG)
                core_logger.addHandler(temp_handler)
                # Store original level? Not strictly necessary for this hack,
                # as we remove the handler later, but good practice if we were restoring level.


        # Pass the validated list of target paths (or the project root if no target was given)
        # The variable resolved_target_paths_str already holds the correct list.
        effective_target_paths_str = resolved_target_paths_str
        
        # Combine rules with exclusion patterns
        effective_rules = rules.copy() if rules else []
        if exclusion_patterns:
            effective_rules.extend(exclusion_patterns)
        
        # Call the core logic function
        result_content = core_read_context(
            target_paths_str=effective_target_paths_str,
            project_root_str=resolved_project_root_path_str, # Pass the translated, validated root
            override_rules=effective_rules,
            list_only=list_only,
            size_limit_mb=size_limit_mb,
            debug_explain=debug_explain, # Pass flag down
            # include_size_in_list is False by default in core_logic if not passed
            exclusion_parser=exclusion_parser # Pass exclusion parser for scoped exclusions
        )
        logger.debug(f"Finished processing project_root: {resolved_project_root_path_str}, targets(s): {resolved_target_paths_str}. Result length: {len(result_content)}")

        if debug_explain and log_capture_buffer:
            debug_output = log_capture_buffer.getvalue()

        # Combine result and debug output if necessary
        if debug_output:
            return f"{result_content}\n\n--- DEBUG LOG ---\n{debug_output}"
        else:
            return result_content

    except (FileNotFoundError, ContextSizeExceededError, ValueError, DetailedContextSizeError) as e:
        # Let FastMCP handle converting these known errors
        logger.error(f"Error during read_context call for project_root='{resolved_project_root_path_str}', targets(s)='{resolved_target_paths_str}': {type(e).__name__} - {e}")
        raise e # Re-raise for FastMCP
    except Exception as e:
        # Log unexpected errors before FastMCP potentially converts to a generic 500
        logger.exception(f"Unexpected error processing project_root='{resolved_project_root_path_str}', targets(s)='{resolved_target_paths_str}': {type(e).__name__} - {e}")
        raise e
    finally:
        # --- Cleanup: Remove temporary handler ---
        if temp_handler and loggers_to_capture:
            logger.debug("Removing temporary debug log handler.")
            for core_logger in loggers_to_capture:
                core_logger.removeHandler(temp_handler)
            temp_handler.close()


# --- Server Execution Function ---
def run_server():
    """Parses arguments, configures logging, and runs the MCP server."""
    global SERVER_ROOT_PATH # Allow modification of the global variable

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

# --- Main Execution Block ---
if __name__ == "__main__":
    run_server()