import unittest
import os
import shutil
from pathlib import Path

from agent.infrastructure.persistence.task_output_store_file import TaskOutputStoreFile


class TestTaskOutputStore(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(__file__).parent / "tmp_output_test"
        self.test_dir.mkdir(exist_ok=True)
        self.store = TaskOutputStoreFile(self.test_dir)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_append_and_read(self):
        job_id = "job_output_1"
        
        self.store.append(job_id, "Hello\n")
        self.store.append(job_id, "World\n")
        
        content, new_offset = self.store.read(job_id)
        self.assertEqual(content, "Hello\nWorld\n")
        
        self.store.append(job_id, "Test\n")
        
        content2, new_offset2 = self.store.read(job_id, offset=new_offset)
        self.assertEqual(content2, "Test\n")

    def test_file_size_limit(self):
        # Override limit for testing
        self.store._max_file_size = 10
        job_id = "job_limit_test"
        
        self.store.append(job_id, "1234567890") # 10 bytes
        self.store.append(job_id, "more")       # Should be ignored
        
        content, _ = self.store.read(job_id)
        self.assertEqual(content, "1234567890")

if __name__ == "__main__":
    unittest.main()
