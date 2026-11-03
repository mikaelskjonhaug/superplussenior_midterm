import tempfile
import unittest
from pathlib import Path

from scripts.check_notebook import input_content


class InputChecksumTests(unittest.TestCase):
    def test_text_hash_input_is_independent_of_git_line_endings(self):
        with tempfile.TemporaryDirectory() as folder:
            for suffix in [".csv", ".json", ".txt"]:
                with self.subTest(suffix=suffix):
                    path = Path(folder) / ("input" + suffix)
                    path.write_bytes(b"first\r\nsecond\r\n")
                    windows = input_content(path)
                    path.write_bytes(b"first\nsecond\n")
                    self.assertEqual(windows, input_content(path))

    def test_binary_input_keeps_every_byte(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.parquet"
            data = b"\x00first\r\nsecond\x00"
            path.write_bytes(data)
            self.assertEqual(data, input_content(path))


if __name__ == "__main__":
    unittest.main()
