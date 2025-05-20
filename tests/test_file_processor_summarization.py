# tests/test_file_processor_summarization.py
import pytest
import os
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# Functions to test
from jinni.file_processor import (
    summarize_file,
    _get_project_structure,
    _get_readme_summary,
    EXCLUDED_DIRS_FOR_STRUCTURE,
    EXCLUDED_FILES_FOR_STRUCTURE,
    README_FILENAMES,
    README_CACHE_KEY
)
# For mocking
from jinni.utils import _calculate_file_hash # Used by _get_readme_summary internally

# --- Fixtures ---

@pytest.fixture
def temp_project(tmp_path: Path):
    """Creates a temporary project structure."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    
    (project_dir / "src").mkdir()
    (project_dir / "src" / "main.py").write_text("print('hello from main')")
    (project_dir / "src" / "utils.py").write_text("def helper(): pass")
    
    (project_dir / "docs").mkdir()
    (project_dir / "docs" / "index.md").write_text("# Main Docs")
    
    (project_dir / "README.md").write_text("This is the main project README.")
    (project_dir / ".git").mkdir() # Excluded dir
    (project_dir / "node_modules").mkdir() # Excluded dir
    (project_dir / "__pycache__").mkdir() # Excluded dir
    (project_dir / "src" / ".DS_Store").touch() # Excluded file
    
    return project_dir

@pytest.fixture
def sample_file(temp_project: Path):
    """A sample file within the temp project."""
    return temp_project / "src" / "main.py"

@pytest.fixture
def mock_cache_data():
    """Returns a fresh, empty cache dictionary for each test."""
    return {}

# --- Tests for _get_project_structure ---

def test_get_project_structure_basic(temp_project):
    structure = _get_project_structure(temp_project)
    
    assert "test_project/" in structure
    assert "  src/" in structure
    assert "    main.py" in structure
    assert "    utils.py" in structure
    assert "  docs/" in structure
    assert "    index.md" in structure
    assert "  README.md" in structure
    
    # Check for exclusions
    assert ".git" not in structure
    assert "node_modules" not in structure
    assert "__pycache__" not in structure
    assert ".DS_Store" not in structure

def test_get_project_structure_with_current_file(temp_project, sample_file):
    structure = _get_project_structure(temp_project, current_file_path=sample_file)
    assert "    main.py *" in structure # Current file marked with *
    assert "    utils.py" in structure and "*" not in structure # Other file not marked

def test_get_project_structure_empty_project(tmp_path):
    empty_dir = tmp_path / "empty_project"
    empty_dir.mkdir()
    structure = _get_project_structure(empty_dir)
    assert "empty_project/" in structure
    # Check that it doesn't error and produces minimal output
    assert len(structure.splitlines()) == 1 

def test_get_project_structure_max_lines(temp_project):
    # Create many files to exceed max lines
    for i in range(150): # MAX_STRUCTURE_LINES is 100 in current implementation
        (temp_project / f"file_{i}.txt").touch()
        
    structure = _get_project_structure(temp_project)
    assert "[... structure truncated ...]" in structure
    # MAX_STRUCTURE_LINES + root line + truncated message line
    # The exact count depends on how many directories are listed before files
    # but it should be close to MAX_STRUCTURE_LINES + a few extra for root/truncation.
    # For this test, we'll check it's more than MAX_STRUCTURE_LINES but not by too much.
    # MAX_STRUCTURE_LINES = 100
    # Root line (test_project/) + 100 lines + "[... structure truncated ...]" = 102
    # However, the current implementation might list directories first.
    # Let's check if the number of lines is MAX_STRUCTURE_LINES + 1 (for the truncation message)
    # and the root itself.
    # The structure generation adds the root dir name first, then walks.
    # So, 1 (root) + MAX_LINES (from walk) + 1 (truncation) = 102
    # This needs to be adjusted if MAX_STRUCTURE_LINES changes in the source.
    # The current implementation has MAX_STRUCTURE_LINES = 100.
    # It lists the root dir, then files/subdirs. The limit is applied to all lines *after* root.
    # So, if root + 100 items + truncated message.
    # Let's simplify: Check that "truncated" is present and line count is reasonable.
    assert len(structure.splitlines()) <= 105 # Allowing some leeway for dir entries before truncation

# --- Tests for _get_readme_summary ---

@patch('jinni.file_processor.call_gemini_api')
def test_get_readme_summary_found_and_cached(mock_call_gemini, temp_project, mock_cache_data, caplog):
    mock_call_gemini.return_value = "Mocked README summary."
    
    # Mock _calculate_file_hash as it's used internally by _get_readme_summary
    with patch('jinni.file_processor._calculate_file_hash', return_value="readme_hash_123"):
        summary = _get_readme_summary(temp_project, mock_cache_data)

    assert summary == "Mocked README summary."
    mock_call_gemini.assert_called_once()
    readme_path = temp_project / "README.md"
    assert README_CACHE_KEY in mock_cache_data
    assert mock_cache_data[README_CACHE_KEY]["summary"] == "Mocked README summary."
    assert mock_cache_data[README_CACHE_KEY]["hash"] == "readme_hash_123" # Check hash is stored
    assert mock_cache_data[README_CACHE_KEY]["source_path"] == "README.md"
    assert "README summary generated and cached" in caplog.text

    # Second call should hit cache
    mock_call_gemini.reset_mock()
    caplog.clear()
    with patch('jinni.file_processor._calculate_file_hash', return_value="readme_hash_123"): # Ensure hash matches
        summary_cached = _get_readme_summary(temp_project, mock_cache_data)
    
    assert summary_cached == "Mocked README summary."
    mock_call_gemini.assert_not_called()
    assert "README summary found in cache" in caplog.text

@patch('jinni.file_processor.call_gemini_api')
def test_get_readme_summary_not_found(mock_call_gemini, tmp_path, mock_cache_data, caplog):
    project_no_readme = tmp_path / "no_readme_project"
    project_no_readme.mkdir()
    
    summary = _get_readme_summary(project_no_readme, mock_cache_data)
    
    assert summary == "No README summary available."
    mock_call_gemini.assert_not_called()
    assert f"No README file found in {project_no_readme}" in caplog.text

@patch('jinni.file_processor.call_gemini_api')
def test_get_readme_summary_api_error(mock_call_gemini, temp_project, mock_cache_data, caplog):
    mock_call_gemini.return_value = "[Error: API failed]"
    with patch('jinni.file_processor._calculate_file_hash', return_value="readme_hash_123"):
        summary = _get_readme_summary(temp_project, mock_cache_data)
    
    assert "Could not summarize README: [Error: API failed]" in summary
    assert README_CACHE_KEY not in mock_cache_data # Should not cache on API error
    assert f"Failed to summarize README {temp_project / 'README.md'}" in caplog.text

@patch('jinni.file_processor.call_gemini_api')
def test_get_readme_summary_read_error(mock_call_gemini, temp_project, mock_cache_data, caplog):
    readme_path = temp_project / "README.md"
    with patch.object(Path, 'read_bytes', side_effect=OSError("Cannot read file")):
        summary = _get_readme_summary(temp_project, mock_cache_data)
    
    assert summary == "Error reading README file."
    mock_call_gemini.assert_not_called()
    assert f"Error reading README file {readme_path}" in caplog.text


# --- Tests for summarize_file ---

@patch('jinni.file_processor.call_gemini_api')
@patch('jinni.file_processor.get_summary_from_cache')
def test_summarize_file_cache_hit(mock_get_summary, mock_call_gemini, sample_file, temp_project, mock_cache_data, caplog):
    mock_get_summary.return_value = "Cached summary from previous run."
    
    summary = summarize_file(sample_file, temp_project, mock_cache_data)
    
    assert summary == "Cached summary from previous run."
    mock_get_summary.assert_called_once_with(mock_cache_data, sample_file, temp_project)
    mock_call_gemini.assert_not_called()
    assert f"Cache hit for file: src/main.py" in caplog.text


@patch('jinni.file_processor.call_gemini_api')
@patch('jinni.file_processor.update_cache')
@patch('jinni.file_processor.get_summary_from_cache')
@patch('jinni.file_processor._get_project_structure') # Mock helper
@patch('jinni.file_processor._get_readme_summary')    # Mock helper
def test_summarize_file_cache_miss_success(
    mock_readme_summary, mock_project_structure, 
    mock_get_summary, mock_update_cache, mock_call_gemini, 
    sample_file, temp_project, mock_cache_data, caplog
):
    mock_get_summary.return_value = None # Cache miss
    mock_project_structure.return_value = "Mock project structure..."
    mock_readme_summary.return_value = "Mock README summary..."
    mock_call_gemini.return_value = "Successfully generated summary."

    original_content = sample_file.read_text()

    summary = summarize_file(sample_file, temp_project, mock_cache_data)

    assert summary == "Successfully generated summary."
    mock_get_summary.assert_called_once_with(mock_cache_data, sample_file, temp_project)
    mock_project_structure.assert_called_once_with(temp_project, sample_file)
    mock_readme_summary.assert_called_once_with(temp_project, mock_cache_data)
    mock_call_gemini.assert_called_once()
    
    # Check prompt elements (basic check)
    prompt_arg = mock_call_gemini.call_args[0][0] # First positional argument (prompt_text)
    assert "Mock project structure..." in prompt_arg["prompt_text"]
    assert "Mock README summary..." in prompt_arg["prompt_text"]
    assert f"File to Summarize: src/main.py" in prompt_arg["prompt_text"]
    assert original_content in prompt_arg["prompt_text"]

    mock_update_cache.assert_called_once_with(mock_cache_data, sample_file, temp_project, "Successfully generated summary.")
    assert f"Cache miss for file: src/main.py" in caplog.text
    assert f"Successfully generated summary for src/main.py" in caplog.text

@patch('jinni.file_processor.call_gemini_api')
@patch('jinni.file_processor.get_summary_from_cache')
def test_summarize_file_read_error(mock_get_summary, mock_call_gemini, sample_file, temp_project, mock_cache_data, caplog):
    mock_get_summary.return_value = None # Cache miss
    
    with patch.object(Path, 'read_bytes', side_effect=OSError("File read error")):
        summary = summarize_file(sample_file, temp_project, mock_cache_data)
        
    assert summary == "[Error: Could not read file content]"
    mock_call_gemini.assert_not_called()
    assert f"Error reading file {sample_file} for summarization: File read error" in caplog.text

@patch('jinni.file_processor.call_gemini_api')
@patch('jinni.file_processor.get_summary_from_cache')
def test_summarize_file_decode_error(mock_get_summary, mock_call_gemini, sample_file, temp_project, mock_cache_data, caplog):
    mock_get_summary.return_value = None # Cache miss
    # Write content that cannot be decoded by utf-8, latin-1, cp1252
    sample_file.write_bytes(b'\x80\xff') # Invalid for these encodings

    summary = summarize_file(sample_file, temp_project, mock_cache_data)
        
    assert summary == "[Error: Could not decode file content with attempted encodings]"
    mock_call_gemini.assert_not_called()
    assert f"Could not decode file {sample_file} using any of the attempted encodings" in caplog.text


@patch('jinni.file_processor.call_gemini_api')
@patch('jinni.file_processor.update_cache')
@patch('jinni.file_processor.get_summary_from_cache')
@patch('jinni.file_processor._get_project_structure')
@patch('jinni.file_processor._get_readme_summary')
def test_summarize_file_api_returns_error(
    mock_readme_summary, mock_project_structure, 
    mock_get_summary, mock_update_cache, mock_call_gemini, 
    sample_file, temp_project, mock_cache_data, caplog
):
    mock_get_summary.return_value = None # Cache miss
    mock_project_structure.return_value = "Mock structure"
    mock_readme_summary.return_value = "Mock README"
    mock_call_gemini.return_value = "[Error: Gemini API unavailable]"

    summary = summarize_file(sample_file, temp_project, mock_cache_data)

    assert summary == "[Error: Gemini API unavailable]"
    mock_call_gemini.assert_called_once()
    mock_update_cache.assert_not_called() # Should not update cache if API failed
    assert f"Failed to get summary for src/main.py from API: [Error: Gemini API unavailable]" in caplog.text

def test_summarize_file_content_truncation(sample_file, temp_project, mock_cache_data):
    # Make content very long
    long_content = "start " * 20000 # > 30000 chars
    sample_file.write_text(long_content)

    with patch('jinni.file_processor.call_gemini_api', return_value="Summary of long file") as mock_api_call, \
         patch('jinni.file_processor.get_summary_from_cache', return_value=None), \
         patch('jinni.file_processor._get_project_structure', return_value="Struct"), \
         patch('jinni.file_processor._get_readme_summary', return_value="ReadmeSum"), \
         patch('jinni.file_processor.update_cache'):

        summarize_file(sample_file, temp_project, mock_cache_data)

        mock_api_call.assert_called_once()
        prompt_text = mock_api_call.call_args[0][0]['prompt_text']
        assert "[... CONTENT TRUNCATED ...]" in prompt_text
        # MAX_FILE_CONTENT_CHARS_IN_PROMPT is 30000.
        # The actual content in prompt should be around this + boilerplate.
        # Rough check:
        assert len(prompt_text) < (30000 * 1.2) # Allow 20% for prompt boilerplate and truncation message
        assert len(prompt_text) > (30000 * 0.8)


# Ensure the logger for file_processor is available
@pytest.fixture(autouse=True)
def ensure_file_processor_logger_handler():
    fp_logger = logging.getLogger("jinni.file_processor")
    if not fp_logger.hasHandlers():
        fp_logger.addHandler(logging.NullHandler())
        fp_logger.propagate = False
    yield
    if fp_logger.handlers and isinstance(fp_logger.handlers[-1], logging.NullHandler):
        fp_logger.removeHandler(fp_logger.handlers[-1])
        fp_logger.propagate = True
