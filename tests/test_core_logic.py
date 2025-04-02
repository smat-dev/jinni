import unittest
from unittest.mock import patch, MagicMock
import datetime
from pathlib import Path

# Import the actual function and exception to test
from jinni.core_logic import process_directory, ContextSizeExceededError, get_file_info
# We also need check_item for patching, even if it's from config_system
from jinni.config_system import check_item
import os # Need os for patching os.walk

class TestCoreLogicFormatting(unittest.TestCase):

    # Note: Patches assume the real implementation will be in 'jinni.core_logic' module
    @patch('jinni.core_logic.get_file_info') # Mock get_file_info if it's separate
    @patch('jinni.core_logic.os.walk')
    @patch('jinni.core_logic.check_item', return_value=True) # Assume check_item allows all
    @patch('jinni.core_logic.Path.read_bytes') # Patch read_bytes as implementation uses it
    def test_output_with_content_and_headers(self, mock_read_bytes, mock_check, mock_walk, mock_getinfo):
        """Test the output format when including content and headers."""
        # Setup mock return values
        mock_walk.return_value = [
            (str(Path('/fake/root')), ['sub'], ['file1.txt']), # Need to include 'sub' in dirs list
            (str(Path('/fake/root/sub')), [], ['file2.py']),
        ]
        mock_getinfo.side_effect = [
            # Info for file1.txt
            {'size': 10, 'last_modified': '2024-01-01 10:00:00'},
            # Info for file2.py
            {'size': 25, 'last_modified': '2024-01-01 11:00:00'}
        ]
        # Mock return value for Path.read_bytes()
        mock_read_bytes.side_effect = [
            b"Hello",          # Content for file1.txt
            b"print('World')"  # Content for file2.py
        ]

        # Call the actual implementation function
        # Pass path as string, as expected by the implementation
        result = process_directory(str(Path('/fake/root')), list_only=False)

        # Define expected output
        sep = "\n\n" + "=" * 80 + "\n"
        # Size in header should match actual bytes read
        expected_header1 = "File: file1.txt\nSize: 5 bytes\nLast Modified: 2024-01-01 10:00:00"
        expected_content1 = "Hello"
        expected_header2 = "File: sub/file2.py\nSize: 14 bytes\nLast Modified: 2024-01-01 11:00:00" # Corrected size
        expected_content2 = "print('World')"
        expected_output = f"{expected_header1}\n{'=' * 80}\n\n{expected_content1}{sep}{expected_header2}\n{'=' * 80}\n\n{expected_content2}"

        # Assertions
        self.assertEqual(result.strip(), expected_output.strip())
        # Check that mocks were called as expected
        mock_walk.assert_called_once_with(Path('/fake/root'), topdown=True, followlinks=False)
        self.assertEqual(mock_check.call_count, 3) # Called for sub, file1.txt, file2.py
        self.assertEqual(mock_read_bytes.call_count, 2)


    @patch('jinni.core_logic.os.walk')
    @patch('jinni.core_logic.check_item', return_value=True) # Assume check_item allows all
    def test_output_list_only(self, mock_check, mock_walk):
        """Test the output format when list_only is True."""
        mock_walk.return_value = [
            (str(Path('/fake/root')), ['sub'], ['file1.txt']), # Include 'sub' in dirs
            (str(Path('/fake/root/sub')), [], ['file2.py']),
        ]

        # Call the actual implementation function
        result = process_directory(str(Path('/fake/root')), list_only=True)

        expected_output = "file1.txt\nsub/file2.py"
        # Assertions
        self.assertEqual(result.strip(), expected_output.strip())
        mock_walk.assert_called_once_with(Path('/fake/root'), topdown=True, followlinks=False)
        self.assertEqual(mock_check.call_count, 3) # Called for sub, file1.txt, file2.py

# Add more tests for formatting edge cases, empty files, etc. later

if __name__ == '__main__':
    unittest.main()