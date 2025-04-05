# jinni/exceptions.py
"""Custom exceptions for the Jinni context processing tool."""

class ContextSizeExceededError(Exception):
    """Custom exception for when context size limit is reached during processing."""
    def __init__(self, limit_mb: int, current_size_bytes: int, file_path: 'Optional[Path]' = None): # Forward reference Path
        from pathlib import Path # Import locally to avoid circular dependency if Path is needed here
        self.limit_mb = limit_mb
        self.current_size_bytes = current_size_bytes
        self.file_path: Optional[Path] = file_path # The file that potentially caused the exceedance
        message = f"Total content size exceeds limit of {limit_mb}MB"
        if file_path:
            message += f" while processing or checking {file_path}"
        message += ". Processing aborted."
        super().__init__(message)

class DetailedContextSizeError(Exception):
    """Custom exception raised after ContextSizeExceededError, including details."""
    def __init__(self, detailed_message: str):
        self.detailed_message = detailed_message
        super().__init__(detailed_message)

# Note: Need to import Optional and Path within the __init__ or globally
# if type hints are evaluated at definition time and cause issues.
# Using forward reference 'Optional[Path]' for now. Consider adding:
# from typing import Optional
# from pathlib import Path
# at the top if needed, ensuring no circular imports with utils.py later.