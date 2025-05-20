# tests/test_utils_summarization.py
import pytest
import os
import json
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# Import functions to test from jinni.utils
from jinni.utils import (
    call_gemini_api,
    load_cache,
    save_cache,
    get_summary_from_cache,
    update_cache,
    _calculate_file_hash,
    SUMMARY_CACHE_FILENAME,
    DEFAULT_CACHE_DIR, # Assuming this is where the cache is stored by default in tests
    setup_file_logging # For testing logging aspects
)

# --- Fixtures ---

@pytest.fixture
def mock_gemini_model():
    """Fixture to mock the Gemini API model."""
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "This is a mock summary."
    mock_model.generate_content.return_value = mock_response
    return mock_model

@pytest.fixture
def mock_genai_module(mock_gemini_model):
    """Fixture to mock the google.generativeai module."""
    mock_genai = MagicMock()
    mock_genai.GenerativeModel.return_value = mock_gemini_model
    return mock_genai

@pytest.fixture(autouse=True)
def prevent_actual_api_calls(mock_genai_module):
    """Patch google.generativeai for all tests in this module."""
    with patch.dict('sys.modules', {'google.generativeai': mock_genai_module}):
        yield

@pytest.fixture
def temp_file(tmp_path: Path):
    """Creates a temporary file with some content."""
    file_path = tmp_path / "test_file.txt"
    content = "Hello, world!\nThis is a test file."
    file_path.write_text(content, encoding='utf-8')
    return file_path, content

@pytest.fixture
def temp_cache_dir(tmp_path: Path) -> Path:
    """Creates a temporary directory for cache files."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return cache_dir

# --- Tests for _calculate_file_hash ---

def test_calculate_file_hash_success(temp_file):
    file_path, content = temp_file
    expected_hash = "c9e8c5a9f9b7a9c5e2a5c8e8c5a9f9b7a9c5e2a5c8e8c5a9f9b7a9c5e2a5c8e8" # Example, replace with actual hash
    
    # Calculate a known hash for the content.
    # Using a fixed known hash for "Hello, world!\nThis is a test file."
    # SHA256 hash of "Hello, world!\nThis is a test file." is 3f67f44a0b70021092843725044969f553f80e68981c9193c54b66b019ab8938
    expected_hash_actual = "3f67f44a0b70021092843725044969f553f80e68981c9193c54b66b019ab8938"
    
    actual_hash = _calculate_file_hash(file_path)
    assert actual_hash == expected_hash_actual

def test_calculate_file_hash_file_not_found():
    non_existent_file = Path("non_existent_file.txt")
    assert _calculate_file_hash(non_existent_file) == ""

# --- Tests for call_gemini_api ---

def test_call_gemini_api_success(mock_gemini_model, caplog):
    prompt = "Summarize this document."
    api_key = "test_api_key"
    
    with caplog.at_level(logging.INFO):
        summary = call_gemini_api(prompt_text=prompt, api_key=api_key)
    
    assert summary == "This is a mock summary."
    mock_gemini_model.generate_content.assert_called_once_with(prompt)
    assert "Gemini API call initiated." in caplog.text
    assert "Gemini API call successful." in caplog.text
    assert "Prompt length:" in caplog.text # Check for API call stats logging
    assert "Summary length:" in caplog.text # Check for API call stats logging

def test_call_gemini_api_env_var_key(mock_gemini_model, monkeypatch):
    prompt = "Summarize with env key."
    monkeypatch.setenv("GEMINI_API_KEY", "env_provided_key")
    
    summary = call_gemini_api(prompt_text=prompt)
    assert summary == "This is a mock summary."
    mock_gemini_model.generate_content.assert_called_once_with(prompt)

def test_call_gemini_api_no_key_error():
    prompt = "Test no key."
    # Ensure no key is in env for this specific test
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="Gemini API key not provided and not found"):
            call_gemini_api(prompt_text=prompt)

def test_call_gemini_api_api_error(mock_gemini_model, caplog):
    prompt = "Test API error."
    api_key = "test_api_key"
    mock_gemini_model.generate_content.side_effect = Exception("Simulated API Error")
    
    with caplog.at_level(logging.ERROR):
        summary = call_gemini_api(prompt_text=prompt, api_key=api_key)
    
    assert "Error: Gemini API call failed - Simulated API Error" in summary
    assert "Gemini API call failed: Simulated API Error" in caplog.text

def test_call_gemini_api_import_error(caplog):
    prompt = "Test import error"
    api_key = "test_api_key"
    with patch.dict('sys.modules', {'google.generativeai': None}):
         with caplog.at_level(logging.ERROR):
            summary = call_gemini_api(prompt_text=prompt, api_key=api_key)
    assert "Error: google-generativeai library not installed" in summary
    assert "google-generativeai library not found" in caplog.text


# --- Tests for Cache Functions ---

def test_load_cache_non_existent(temp_cache_dir, caplog):
    with caplog.at_level(logging.INFO):
        cache = load_cache(temp_cache_dir)
    assert cache == {}
    assert f"Cache file not found at: {temp_cache_dir / SUMMARY_CACHE_FILENAME}" in caplog.text

def test_save_and_load_cache(temp_cache_dir):
    cache_data_to_save = {"file1.txt": {"hash": "abc", "summary": "Summary 1"}}
    save_cache(temp_cache_dir, cache_data_to_save)
    
    loaded_cache = load_cache(temp_cache_dir)
    assert loaded_cache == cache_data_to_save

def test_load_cache_corrupted(temp_cache_dir, caplog):
    cache_file = temp_cache_dir / SUMMARY_CACHE_FILENAME
    cache_file.write_text("this is not json")
    
    with caplog.at_level(logging.ERROR):
        cache = load_cache(temp_cache_dir)
    assert cache == {}
    assert f"Error decoding JSON from cache file {cache_file}" in caplog.text

def test_get_summary_from_cache_hit(temp_file):
    file_path, content = temp_file
    project_root = file_path.parent
    file_hash = _calculate_file_hash(file_path)
    
    cache_data = {
        str(file_path.relative_to(project_root)): {"hash": file_hash, "summary": "Cached summary"}
    }
    
    summary = get_summary_from_cache(cache_data, file_path, project_root)
    assert summary == "Cached summary"

def test_get_summary_from_cache_miss_hash_mismatch(temp_file):
    file_path, content = temp_file
    project_root = file_path.parent
    
    cache_data = {
        str(file_path.relative_to(project_root)): {"hash": "wrong_hash", "summary": "Old summary"}
    }
    
    summary = get_summary_from_cache(cache_data, file_path, project_root)
    assert summary is None

def test_get_summary_from_cache_miss_not_in_cache(temp_file):
    file_path, content = temp_file
    project_root = file_path.parent
    cache_data = {} # Empty cache
    
    summary = get_summary_from_cache(cache_data, file_path, project_root)
    assert summary is None

def test_update_cache(temp_file):
    file_path, content = temp_file
    project_root = file_path.parent
    file_hash = _calculate_file_hash(file_path)
    new_summary = "This is an updated summary."
    
    cache_data = {}
    update_cache(cache_data, file_path, project_root, new_summary)
    
    relative_path_str = str(file_path.relative_to(project_root))
    assert relative_path_str in cache_data
    assert cache_data[relative_path_str]["hash"] == file_hash
    assert cache_data[relative_path_str]["summary"] == new_summary
    assert "last_updated_utc" in cache_data[relative_path_str]

def test_get_summary_from_cache_file_unreadable(temp_file, caplog):
    file_path, content = temp_file
    project_root = file_path.parent
    file_hash = _calculate_file_hash(file_path) # Original hash

    cache_data = {
        str(file_path.relative_to(project_root)): {"hash": file_hash, "summary": "Cached summary"}
    }

    # Make the file unreadable for the _calculate_file_hash call within get_summary_from_cache
    with patch('jinni.utils._calculate_file_hash', return_value=""): # Simulate hash calculation failure
        with caplog.at_level(logging.WARNING):
            summary = get_summary_from_cache(cache_data, file_path, project_root)
    
    assert summary is None
    assert f"Could not calculate current hash for {file_path}. Invalidating cache entry." in caplog.text

def test_update_cache_file_unreadable(temp_file, caplog):
    file_path, content = temp_file
    project_root = file_path.parent
    new_summary = "This is an updated summary."
    cache_data = {}

    with patch('jinni.utils._calculate_file_hash', return_value=""): # Simulate hash calculation failure
        with caplog.at_level(logging.WARNING):
            update_cache(cache_data, file_path, project_root, new_summary)
            
    assert str(file_path.relative_to(project_root)) not in cache_data
    assert f"Could not calculate hash for {file_path}. Cannot update cache." in caplog.text

# --- Test setup_file_logging ---
# Minimal test, mainly to ensure it runs without error and logs its action.
# More detailed testing of logging handlers can be complex.
def test_setup_file_logging_runs(tmp_path, caplog):
    logger_instance = logging.getLogger("test_setup_logger")
    # Ensure the logger has a level that allows INFO messages to be processed
    logger_instance.setLevel(logging.INFO)
    # Add a stream handler to capture logs for assertion if needed (or use caplog)
    stream_handler = logging.StreamHandler()
    logger_instance.addHandler(stream_handler)

    log_filename = tmp_path / "test_jinni.log"

    with caplog.at_level(logging.INFO): # Capture logs from the logger_instance
        setup_file_logging(logger_instance, True, log_filename=str(log_filename))

    assert f"File logging active. Logging to: {log_filename.resolve()}" in caplog.text
    assert log_filename.exists()

    # Clean up handler to avoid interference
    logger_instance.removeHandler(stream_handler)

def test_setup_file_logging_disabled(tmp_path, caplog):
    logger_instance = logging.getLogger("test_setup_logger_disabled")
    log_filename = tmp_path / "test_jinni_disabled.log"
    
    with caplog.at_level(logging.INFO):
         setup_file_logging(logger_instance, False, log_filename=str(log_filename))
    
    assert f"File logging active. Logging to: {log_filename.resolve()}" not in caplog.text
    assert not log_filename.exists()

def test_setup_file_logging_permission_error(tmp_path, caplog):
    logger_instance = logging.getLogger("test_setup_logger_perm_error")
    # Attempt to log to a path that should typically cause a permission error
    # (e.g., root directory, or a specially crafted non-writable path by mocking Path.mkdir)
    # For simplicity, we'll mock Path.mkdir to raise an error.
    
    with patch.object(Path, 'mkdir', side_effect=PermissionError("Simulated permission denied")):
        with caplog.at_level(logging.ERROR):
            setup_file_logging(logger_instance, True, log_filename="/non_writable_path/jinni.log")
    
    assert "Failed to setup file logging to /non_writable_path/jinni.log: Simulated permission denied" in caplog.text

# Note: Consider adding tests for relative path handling in get_summary_from_cache and update_cache
# if project_root or file_path are not absolute, although the functions log warnings for this.
# The current tests use absolute paths derived from tmp_path.

# Test for SUMMARY_CACHE_FILENAME and DEFAULT_CACHE_DIR constants
def test_cache_constants():
    assert SUMMARY_CACHE_FILENAME == ".jinni_summary_cache.json"
    assert DEFAULT_CACHE_DIR == Path(".")

# Ensure the `jinni.utils` logger is available for tests that might use it directly or indirectly
# and that it has a default handler if none are configured (e.g. by setup_file_logging)
@pytest.fixture(autouse=True)
def ensure_utils_logger_handler():
    utils_logger = logging.getLogger("jinni.utils")
    if not utils_logger.hasHandlers():
        # Add a null handler to prevent "No handlers could be found" warnings
        # if tests trigger logs from jinni.utils without explicit setup.
        utils_logger.addHandler(logging.NullHandler())
        utils_logger.propagate = False # Prevent duplication if a root handler is added later by other tests

    # Also ensure the root logger has a handler if it's going to be used by caplog effectively
    # or if any code directly logs to the root logger without specific module loggers.
    # However, caplog should handle this.
    # root_logger = logging.getLogger()
    # if not root_logger.hasHandlers():
    #     root_logger.addHandler(logging.NullHandler())

    yield # Test runs here

    if utils_logger.handlers and isinstance(utils_logger.handlers[-1], logging.NullHandler):
        utils_logger.removeHandler(utils_logger.handlers[-1])
        utils_logger.propagate = True

# This is a very basic test for tiktoken integration within call_gemini_api
# It mainly checks that the token counting part doesn't crash.
def test_call_gemini_api_tiktoken_integration(mock_gemini_model, caplog):
    prompt = "This is a test prompt with several tokens."
    api_key = "test_api_key"
    
    with caplog.at_level(logging.INFO):
        call_gemini_api(prompt_text=prompt, api_key=api_key)
    
    # Expected token count for "This is a test prompt with several tokens." using cl100k_base
    # "This is a test prompt with several tokens." -> 8 tokens
    # This can be verified, e.g. with https://tiktokenizer.vercel.app/
    expected_token_count = 8 
    assert f"{expected_token_count} tokens" in caplog.text

def test_call_gemini_api_tiktoken_missing(mock_gemini_model, caplog):
    prompt = "Test prompt."
    api_key = "test_api_key"
    with patch('tiktoken.get_encoding', side_effect=Exception("Tiktoken not available")):
        with caplog.at_level(logging.DEBUG): # Capture debug logs for this
            call_gemini_api(prompt_text=prompt, api_key=api_key)
    
    assert "Could not count prompt tokens with tiktoken: Tiktoken not available" in caplog.text
    assert "0 tokens" in caplog.text # Fallback to 0 tokens
