# jinni/file_processor.py
"""Handles processing of individual files for Jinni context."""

import os
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

# Import necessary components from other modules (adjust as needed)
from .utils import get_file_info, _is_binary # Assuming utils.py exists
from .exceptions import ContextSizeExceededError # Assuming exceptions.py exists

# Setup logger for this module
logger = logging.getLogger("jinni.file_processor")
if not logger.handlers and not logging.getLogger().handlers:
     logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Imports for summarization
from .utils import (
    call_gemini_api,
    load_cache,
    save_cache,
    get_summary_from_cache,
    update_cache,
    SUMMARY_CACHE_FILENAME, # Might not be used directly here if cache_dir is passed
    DEFAULT_CACHE_DIR,      # Might not be used directly here if cache_dir is passed
    _calculate_file_hash    # For direct use if needed, though cache utils might abstract
)
# Path is already imported from pathlib
import tiktoken # For token counting

# --- Helper Function: Get Project Structure ---
EXCLUDED_DIRS_FOR_STRUCTURE = {
    ".git", "__pycache__", "node_modules", ".venv", "dist", "build",
    ".vscode", ".idea", ".pytest_cache", "eggs", ".eggs", "htmlcov"
}
EXCLUDED_FILES_FOR_STRUCTURE = {
    ".DS_Store", ".gitignore", ".gitattributes"
}

def _get_project_structure(project_root: Path, current_file_path: Optional[Path] = None) -> str:
    """
    Generates a textual representation of the project directory structure.

    Args:
        project_root: The root directory of the project.
        current_file_path: Optional path to the file currently being summarized,
                           to mark it in the structure.

    Returns:
        A string representing the directory structure.
    """
    logger.debug(f"Generating project structure for root: {project_root}")
    structure_lines = []
    # Ensure project_root is absolute for consistent processing
    abs_project_root = project_root.resolve()
    abs_current_file = current_file_path.resolve() if current_file_path else None

    for root, dirs, files in os.walk(abs_project_root, topdown=True):
        # Exclude directories
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS_FOR_STRUCTURE]
        
        current_path = Path(root)
        # Calculate depth for indentation relative to the original project_root argument
        try:
            # Make sure to use the original project_root for relative path calculation
            # if the walked 'root' (current_path) started from a resolved abs_project_root.
            relative_path = current_path.relative_to(abs_project_root)
            depth = len(relative_path.parts)
        except ValueError:
            # This can happen if current_path is not under abs_project_root,
            # though os.walk should ensure this if abs_project_root is used as the start.
            # Or if project_root itself was a relative path initially.
            # Default to 0 depth if relative_path calculation fails.
            logger.warning(f"Could not determine relative path for {current_path} under {abs_project_root}. Using depth 0.")
            depth = 0

        indent = "  " * depth

        # Add current directory to structure
        if depth == 0: # Project root itself
             structure_lines.append(f"{abs_project_root.name}/")
        else:
             structure_lines.append(f"{indent}{current_path.name}/")

        # Add files in the current directory
        for f_name in sorted(files):
            if f_name in EXCLUDED_FILES_FOR_STRUCTURE:
                continue
            
            file_path_abs = current_path / f_name
            marker = " *" if abs_current_file and file_path_abs == abs_current_file else ""
            structure_lines.append(f"{indent}  {f_name}{marker}")

    logger.debug(f"Generated project structure with {len(structure_lines)} lines.")
    # Limit structure size to avoid excessive token usage
    # This is a simple line limit, could be token-based for more precision
    MAX_STRUCTURE_LINES = 100 
    if len(structure_lines) > MAX_STRUCTURE_LINES:
        logger.warning(f"Project structure exceeds {MAX_STRUCTURE_LINES} lines. Truncating.")
        structure_lines = structure_lines[:MAX_STRUCTURE_LINES]
        structure_lines.append("[... structure truncated ...]")

    return "\n".join(structure_lines)

# --- Helper Function: Get README Summary ---
README_FILENAMES = ["README.md", "readme.md", "README.txt", "readme.txt", "README", "readme"]
README_CACHE_KEY = "_PROJECT_README_SUMMARY_"

def _get_readme_summary(project_root: Path, cache_data: dict) -> str:
    """
    Finds and summarizes the project's README file, using a cache.

    Args:
        project_root: The root directory of the project.
        cache_data: The loaded cache data dictionary.

    Returns:
        A summary of the README file, or "No README summary available."
    """
    logger.debug(f"Attempting to get README summary for project: {project_root}")

    # Check cache first for the special README key
    if README_CACHE_KEY in cache_data:
        cached_readme_info = cache_data[README_CACHE_KEY]
        # For README, we might just store the summary without a hash, or hash of README content.
        # Assuming for now if key exists, summary is valid. Can add hash check if needed.
        logger.info("README summary found in cache.")
        return cached_readme_info.get("summary", "Error: Cached README summary malformed.")

    readme_file_path: Optional[Path] = None
    for name in README_FILENAMES:
        path = project_root / name
        if path.is_file():
            readme_file_path = path
            break
    
    if not readme_file_path:
        logger.info(f"No README file found in {project_root} from options: {README_FILENAMES}")
        return "No README summary available."

    logger.info(f"Found README file: {readme_file_path}")
    try:
        readme_content_bytes = readme_file_path.read_bytes()
        readme_content = readme_content_bytes.decode('utf-8', errors='replace') # Simple decode for README
        
        # Construct a simple prompt for README
        readme_prompt = f"Concisely summarize the following README content in 2-4 sentences, focusing on the project's purpose and key features:\n\n{readme_content[:3000]}" # Limit README content to avoid large prompt
        
        logger.debug("Calling Gemini API for README summary.")
        summary_text = call_gemini_api(prompt_text=readme_prompt) # API key handled by call_gemini_api

        if summary_text.startswith("[Error:") or summary_text.startswith("Error:"):
            logger.error(f"Failed to summarize README {readme_file_path}: {summary_text}")
            return f"Could not summarize README: {summary_text}"

        # Cache the README summary
        readme_hash = _calculate_file_hash(readme_file_path) # Hash the readme for future validation
        cache_data[README_CACHE_KEY] = {
            "summary": summary_text,
            "hash": readme_hash, # Store hash of the README content
            "source_path": str(readme_file_path.relative_to(project_root)).replace(os.sep, '/'),
            "last_updated_utc": datetime.datetime.utcnow().isoformat() + "Z"
        }
        logger.info(f"README summary generated and cached for {readme_file_path}.")
        return summary_text

    except OSError as e:
        logger.error(f"Error reading README file {readme_file_path}: {e}")
        return "Error reading README file."
    except Exception as e:
        logger.error(f"Unexpected error processing README {readme_file_path}: {e}", exc_info=True)
        return "Unexpected error processing README."


def summarize_file(file_path: Path, project_root: Path, cache_data: dict) -> str:
    """
    Summarizes a single file, using a cache if available.

    Args:
        file_path: Absolute path to the file to be summarized.
        project_root: Absolute path to the project root.
        cache_data: The loaded cache data dictionary.

    Returns:
        A string containing the summary of the file, or an error message.
    """
    logger.info(f"Summarization process started for: {file_path}")

    # 1. Cache Check
    # Calculate relative_file_path_str for logging before cache check
    try:
        relative_file_path_str = str(file_path.relative_to(project_root)).replace(os.sep, '/')
    except ValueError:
        # Fallback if file_path is not relative to project_root (e.g. if project_root is misconfigured or path is truly outside)
        relative_file_path_str = str(file_path)
        logger.warning(f"File path {file_path} is not under project root {project_root}. Using absolute path for logging.")

    cached_summary = get_summary_from_cache(cache_data, file_path, project_root)
    if cached_summary is not None:
        logger.info(f"Cache hit for file: {relative_file_path_str}")
        return cached_summary

    logger.info(f"Cache miss for file: {relative_file_path_str}. Proceeding to read file content.")

    # 2. Read File Content
    file_content: Optional[str] = None
    try:
        file_bytes = file_path.read_bytes()
        # Attempt to decode using common encodings
        encodings_to_try = ['utf-8', 'latin-1', 'cp1252']
        for enc in encodings_to_try:
            try:
                file_content = file_bytes.decode(enc)
                logger.debug(f"Successfully decoded {file_path} using {enc}.")
                break
            except UnicodeDecodeError:
                logger.debug(f"Failed to decode {file_path} with {enc}.")
                continue
        
        if file_content is None:
            logger.error(f"Could not decode file {file_path} using any of the attempted encodings: {encodings_to_try}.")
            return "[Error: Could not decode file content with attempted encodings]"

    except OSError as e:
        logger.error(f"Error reading file {file_path} for summarization: {e}")
        return "[Error: Could not read file content]"
    except Exception as e:
        logger.error(f"Unexpected error reading or decoding file {file_path} for summarization: {e}", exc_info=True)
        return "[Error: Unexpected error during file reading/decoding]"

    # 3. Get Project Structure and README Summary
    project_structure_str = _get_project_structure(project_root, file_path)
    readme_summary_str = _get_readme_summary(project_root, cache_data) # cache_data is passed to handle README caching

    # 4. Token Counting & Target Size
    try:
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception as e: # Broad exception for tiktoken issues
        logger.error(f"Could not initialize tiktoken encoder: {e}. Proceeding without token-based target length.")
        enc = None # Allow fallback if tiktoken is missing/broken

    num_tokens = 0
    if enc and file_content: # Ensure file_content is not None
        try:
            num_tokens = len(enc.encode(file_content))
        except Exception as e: # Catch potential errors during encoding
            logger.error(f"Error encoding file content with tiktoken: {e}. Proceeding with default target length.")
            num_tokens = 0 # Reset if encoding fails

    # Ensure target_summary_tokens has a reasonable minimum and maximum
    # Max is to prevent asking for summaries that are too long for the model or use case
    target_summary_tokens = max(50, min(int(num_tokens * 0.15), 400)) # Target 15%, min 50, max 400 tokens

    # 5. Construct Prompt
    try:
        relative_file_path_str = str(file_path.relative_to(project_root)).replace(os.sep, '/')
    except ValueError:
        logger.warning(f"Could not determine relative path for {file_path} in project {project_root}. Using absolute path in prompt.")
        relative_file_path_str = str(file_path)
        
    # Limit file_content length in prompt to avoid overly large prompts
    # This is a character limit, not token, but helps prevent extremely large API requests.
    # A more sophisticated approach might truncate based on tokens.
    MAX_FILE_CONTENT_CHARS_IN_PROMPT = 30000 # Approx 7.5k tokens, adjust as needed
    truncated_file_content = file_content
    if len(file_content) > MAX_FILE_CONTENT_CHARS_IN_PROMPT:
        logger.warning(f"File content for {relative_file_path_str} is very long ({len(file_content)} chars). Truncating for prompt.")
        # Truncate by taking a portion from the beginning and a portion from the end
        # This helps preserve context from both start and end of large files.
        # The exact split can be tuned.
        chars_from_start = MAX_FILE_CONTENT_CHARS_IN_PROMPT // 2
        chars_from_end = MAX_FILE_CONTENT_CHARS_IN_PROMPT - chars_from_start
        truncated_file_content = (
            file_content[:chars_from_start] +
            "\n\n[... CONTENT TRUNCATED ...]\n\n" +
            file_content[-chars_from_end:]
        )


    prompt_text = f"""Project Structure:
{project_structure_str}

Top-level README Summary:
{readme_summary_str}

File to Summarize: {relative_file_path_str}
Target Summary Length: Approximately {target_summary_tokens} tokens.

File Content:
{truncated_file_content}

Instruction:
Summarize the above file content. Focus on its main purpose, inputs, outputs, key functionalities, and its relationship with other parts of the project if evident from the context provided.
Do not include the file path or target length in the summary itself.
The summary should be a concise explanation of the code's role and function.
"""
    logger.debug(f"Constructed prompt for {relative_file_path_str}. Prompt length (chars): {len(prompt_text)}")

    # 6. Call Gemini API
    logger.info(f"Calling Gemini API for summarization of: {relative_file_path_str}")
    summary_text = call_gemini_api(prompt_text=prompt_text)

    # 7. Update Cache & Return
    if summary_text.startswith("[Error:") or summary_text.startswith("Error:"):
        logger.error(f"Failed to get summary for {relative_file_path_str} from API: {summary_text}")
        # Do not cache errors from the API as valid summaries
        return summary_text # Propagate API error message
    else:
        logger.info(f"Successfully generated summary for {relative_file_path_str}.")
        update_cache(cache_data, file_path, project_root, summary_text)
        # The main logic in core_logic.py will handle saving the cache_data
        return summary_text


def process_file(
    file_path: Path,
    output_rel_root: Path,
    size_limit_bytes: int,
    total_size_bytes: int,
    list_only: bool,
    include_size_in_list: bool,
    debug_explain: bool
) -> Tuple[Optional[str], int]:
    """
    Processes a single file: checks size, binary status, reads content, formats output.

    Args:
        file_path: Absolute path to the file to process.
        output_rel_root: The root directory for calculating relative paths in output.
        size_limit_bytes: Maximum total context size allowed in bytes.
        total_size_bytes: Current total size of context processed so far.
        list_only: If True, only return the relative path (optionally with size).
        include_size_in_list: If True and list_only is True, prepend size to path.
        debug_explain: If True, log detailed processing steps.

    Returns:
        A tuple containing:
        - The formatted output string (header + content or path string), or None if skipped.
        - The size of the file content added (0 if skipped or list_only).

    Raises:
        ContextSizeExceededError: If adding this file would exceed the size limit.
    """
    if debug_explain: logger.debug(f"Processing file: {file_path}")

    # Perform binary check first
    if _is_binary(file_path):
        if debug_explain: logger.debug(f"Skipping File: {file_path} -> Detected as binary (check applied for list_only={list_only})")
        return None, 0

    # Binary check passed, now get info and check size
    file_info = get_file_info(file_path)
    file_stat_size = file_info['size']

    if total_size_bytes + file_stat_size > size_limit_bytes:
        if file_stat_size > size_limit_bytes and total_size_bytes == 0:
            # Log warning only if size check fails *after* passing binary check
            logger.warning(f"File {file_path} ({file_stat_size} bytes) exceeds size limit of {size_limit_bytes / (1024*1024):.2f}MB. Skipping.")
            return None, 0 # Skip this file
        else:
            # Raise error if adding this file exceeds limit (even if file itself is smaller)
            raise ContextSizeExceededError(int(size_limit_bytes / (1024*1024)), total_size_bytes + file_stat_size, file_path)

    # --- Both binary and size checks passed ---

    # Get relative path for output
    try:
        relative_path_str = str(file_path.relative_to(output_rel_root)).replace(os.sep, '/')
    except ValueError:
        relative_path_str = str(file_path) # Fallback

    # Prepare output
    if list_only:
        output_line = f"{file_stat_size}\t{relative_path_str}" if include_size_in_list else relative_path_str
        if debug_explain: logger.debug(f"Adding to list: {output_line}")
        return output_line, 0 # No size added in list_only mode
    else:
        try:
            file_bytes = file_path.read_bytes()
            actual_file_size = len(file_bytes)
            # Double check size after reading (important!)
            if total_size_bytes + actual_file_size > size_limit_bytes:
                if actual_file_size > size_limit_bytes and total_size_bytes == 0:
                    logger.warning(f"File {file_path} ({actual_file_size} bytes) exceeds size limit of {size_limit_bytes / (1024*1024):.2f}MB after read. Skipping.")
                    return None, 0
                else:
                    raise ContextSizeExceededError(int(size_limit_bytes / (1024*1024)), total_size_bytes + actual_file_size, file_path)

            content: Optional[str] = None
            encodings_to_try = ['utf-8', 'latin-1', 'cp1252']
            for enc in encodings_to_try:
                try:
                    content = file_bytes.decode(enc)
                    if debug_explain: logger.debug(f"Decoded {file_path} using {enc}")
                    break
                except UnicodeDecodeError:
                    continue
            if content is None:
                logger.warning(f"Could not decode file {file_path} using {encodings_to_try}. Skipping content.")
                return None, 0

            # New header format
            header = f"```path={relative_path_str}"
            formatted_output = header + "\n" + content + "\n```\n" # Add closing backticks
            if debug_explain: logger.debug(f"Adding content for: {relative_path_str}")
            return formatted_output, actual_file_size

        except OSError as e_read:
            logger.warning(f"Error reading file {file_path}: {e_read}")
            return None, 0
        except Exception as e_general:
            logger.warning(f"Unexpected error processing file {file_path}: {e_general}")
            return None, 0