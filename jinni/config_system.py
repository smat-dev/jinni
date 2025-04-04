# jinni/config_system.py
import logging
from pathlib import Path
from typing import List, Optional, Iterable

# Attempt to import pathspec, provide guidance if missing
try:
    import pathspec
except ImportError:
    print("Error: 'pathspec' library not found.")
    print("Please install it: pip install pathspec")
    # Or add it to your requirements.txt / project dependencies
    raise # Re-raise the error to stop execution if critical

# Setup logger for this module
logger = logging.getLogger(__name__)
# Configure basic logging if no handlers are configured by the application
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')

# --- Constants ---
CONTEXT_FILENAME = ".contextfiles"

# Intent is general inclusions/exclusions for context in a wide range of projects
DEFAULT_RULES: List[str] = [
    # Include all by default - lowest priority
    "*",
    # Dotfiles / Dirs at any level
    "!.*",
    f"!{CONTEXT_FILENAME}", # Explicitly exclude jinni context files
    "!node_modules/",
    # Python Exclusions
    "!__pycache__/",
    "!*.pyc",
    "!*.pyo",
    "!venv/", # Standard virtualenv
    "!env/",  # Standard virtualenv
    "!.venv/", # Common virtualenv
    "!.env/",  # Common environment files dir/prefix
    "!*.egg-info/", # Python packaging metadata
    # Build artifacts / Logs / Output / Temp Exclusions
    "!build/",
    "!dist/",
    "!target/", # Common Java/Rust build output
    "!out/",    # Common build output
    "!bin/",    # Compiled binaries
    "!obj/",    # Compiled object files
    "!output/", # General output directory
    "!logs/",   # Log directory
    "!*.log",   # Log files
    "!log.*",   # Files starting with log.
    "!*.bak",   # Backup files
    "!*.tmp",   # Temporary files
    "!*.temp",  # Temporary files
    "!*.swp",   # Swap files (e.g., Vim)
    "!*~",      # Backup files (e.g., Emacs)
    # Archive files
    "!*.gz",
    "!*.zip",
    "!*.tar",
    "!*.bz2",
    "!*.xz",
    "!*.7z",
    "!*.rar",
    "!*.zipx",
    # OS-specific
    "!Thumbs.db", # Windows thumbnail cache
]

def load_rules_from_file(file_path: Path) -> List[str]:
    """
    Reads rules (lines) from a given file path.
    Handles potential file reading errors.
    Returns an empty list if the file doesn't exist or cannot be read.
    """
    if not file_path.is_file():
        logger.debug(f"Rule file not found: {file_path}")
        return []
    try:
        # Read lines respecting encoding, ignore errors for simplicity now
        lines = file_path.read_text(encoding='utf-8', errors='ignore').splitlines()
        logger.debug(f"Read {len(lines)} lines from {file_path}")
        return lines
    except Exception as e:
        logger.warning(f"Could not read rule file {file_path}: {e}")
        return []

def compile_spec_from_rules(rules: Iterable[str], source_description: str = "rules list") -> pathspec.PathSpec:
    """
    Compiles a pathspec.PathSpec object from an iterable of rule strings.
    Uses 'gitwildmatch' syntax.
    Filters out empty lines and comments.
    Returns an empty PathSpec if no valid rules are provided or on error.
    """
    valid_lines = [line for line in rules if line.strip() and not line.strip().startswith('#')]
    if not valid_lines:
        logger.debug(f"No valid pattern lines found in {source_description}.")
        # Return an empty spec instead of None
        return pathspec.PathSpec.from_lines('gitwildmatch', [])
    try:
        spec = pathspec.PathSpec.from_lines('gitwildmatch', valid_lines)
        logger.debug(f"Compiled PathSpec from {source_description} with {len(spec.patterns)} patterns.")
        return spec
    except Exception as e:
        logger.warning(f"Could not compile PathSpec from {source_description}: {e}")
        # Return an empty spec on error
        return pathspec.PathSpec.from_lines('gitwildmatch', [])

# --- End of config_system.py ---
# Obsolete functions (check_item, find_and_compile_contextfile) and types removed.