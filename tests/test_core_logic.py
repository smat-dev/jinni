import unittest
from unittest.mock import patch, MagicMock
import datetime
from pathlib import Path
import tempfile # For temporary directory
import shutil   # For removing the directory
import os       # For path manipulation

# Import the actual function and exception to test
from jinni.core_logic import process_directory, ContextSizeExceededError, get_file_info
# We also need check_item for patching, even if it's from config_system
from jinni.config_system import check_item

class TestCoreLogicFormatting(unittest.TestCase):

    def setUp(self):
        """Create a temporary directory and test file structure."""
        self.test_dir = tempfile.mkdtemp()
        self.root_path = Path(self.test_dir)

        # Create files and directories
        (self.root_path / "sub").mkdir()
        (self.root_path / "file1.txt").write_text("Hello", encoding='utf-8')
        (self.root_path / "sub" / "file2.py").write_text("print('World')", encoding='utf-8')
        # Add a file that should be skipped by binary check
        (self.root_path / "binary.bin").write_bytes(b'\x00\x01\x02\x00')

    def tearDown(self):
        """Remove the temporary directory."""
        shutil.rmtree(self.test_dir)

    # Note: Patches assume the real implementation will be in 'jinni.core_logic' module
    # Decorators are applied bottom-up, so args are inner-most first
    @patch('jinni.core_logic.get_file_info') # mock_getinfo
    @patch('jinni.core_logic.check_item', return_value=(True, "Mock Reason")) # mock_check
    def test_output_with_content_and_headers(self, mock_check, mock_getinfo):
        """Test the output format when including content and headers."""
        # Setup mock for get_file_info (size doesn't matter much here as actual size is used)
        mock_getinfo.side_effect = [
             {'size': 5, 'last_modified': '2024-01-01 10:00:00'}, # file1.txt
             {'size': 14, 'last_modified': '2024-01-01 11:00:00'}, # sub/file2.py
             # Note: binary.bin is skipped by binary check, so get_file_info isn't called for it
        ]

        # Call the actual implementation function
        result = process_directory(self.test_dir, list_only=False) # Use real temp dir

        # Define expected output
        sep = "\n\n" + "=" * 80 + "\n"
        # Size in header should match actual bytes read
        expected_header1 = "File: file1.txt\nSize: 5 bytes\nLast Modified: 2024-01-01 10:00:00"
        expected_content1 = "Hello"
        expected_header2 = "File: sub/file2.py\nSize: 14 bytes\nLast Modified: 2024-01-01 11:00:00"
        expected_content2 = "print('World')"
        expected_output = f"{expected_header1}\n{'=' * 80}\n\n{expected_content1}{sep}{expected_header2}\n{'=' * 80}\n\n{expected_content2}"

        # Assertions
        self.assertEqual(result.strip(), expected_output.strip())
        # Check that check_item was called (adjust count based on actual walk)
        # Expected calls: sub/, file1.txt, binary.bin, sub/file2.py
        self.assertEqual(mock_check.call_count, 4)
        # Check get_file_info calls (only for non-binary included files)
        self.assertEqual(mock_getinfo.call_count, 2)

    @patch('jinni.core_logic.check_item', return_value=(True, "Mock Reason")) # mock_check
    def test_output_list_only(self, mock_check):
        """Test the output format when list_only is True."""

        # Call the actual implementation function
        result = process_directory(self.test_dir, list_only=True) # Use real temp dir

        # Expected output based on files created in setUp (binary.bin is skipped)
        expected_output = "file1.txt\nsub/file2.py"
        # Assertions
        self.assertEqual(result.strip(), expected_output.strip())
        # Check that check_item was called (adjust count based on actual walk)
        # Expected calls: sub/, file1.txt, binary.bin, sub/file2.py
        self.assertEqual(mock_check.call_count, 4)

# Add more tests for formatting edge cases, empty files, etc. later

if __name__ == '__main__':
    unittest.main()