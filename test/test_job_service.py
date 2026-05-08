import unittest
import os
import shutil
from pathlib import Path

from agent.application.services.job_service import JobService
from agent.infrastructure.persistence.job_store_jsonl import JobStoreJsonl
from agent.infrastructure.persistence.task_output_store_file import TaskOutputStoreFile
from agent.domain.jobs import JobRecord, JobStatus, JobHandle


class TestJobService(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(__file__).parent / "tmp_job_test"
        self.test_dir.mkdir(exist_ok=True)
        
        self.job_store = JobStoreJsonl(self.test_dir)
        self.output_store = TaskOutputStoreFile(self.test_dir)
        self.service = JobService(self.job_store, self.output_store)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_job_lifecycle(self):
        handle = self.service.create_job(
            session_id="session_1",
            request_id="req_1",
            tool_call_id="call_1",
            tool_name="bash",
            metadata={"command": "echo test"}
        )
        
        self.assertIsNotNone(handle)
        self.assertEqual(handle.status, "pending")
        
        # Verify job is retrievable
        job = self.service.get_job(handle.job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.tool_name, "bash")
        
        # Update status
        self.service.update_status(handle.job_id, "running")
        job = self.service.get_job(handle.job_id)
        self.assertEqual(job.status, "running")
        self.assertIsNotNone(job.started_at)
        
        # Complete
        self.service.update_status(handle.job_id, "completed")
        job = self.service.get_job(handle.job_id)
        self.assertEqual(job.status, "completed")
        self.assertIsNotNone(job.ended_at)

    def test_job_output(self):
        handle = self.service.create_job("s1", "r1", "c1", "test")
        
        # Append output
        self.service.append_output(handle.job_id, "line 1\n")
        self.service.append_output(handle.job_id, "line 2\n")
        
        # Read full
        content, offset = self.service.read_output(handle.job_id)
        self.assertEqual(content, "line 1\nline 2\n")
        
        # Incremental read
        self.service.append_output(handle.job_id, "line 3\n")
        content2, _ = self.service.read_output(handle.job_id, offset=offset)
        self.assertEqual(content2, "line 3\n")

    def test_list_session_jobs(self):
        h1 = self.service.create_job("s1", "r1", "c1", "t1")
        h2 = self.service.create_job("s1", "r2", "c2", "t2")
        h3 = self.service.create_job("s2", "r3", "c3", "t3")
        
        jobs_s1 = self.service.list_session_jobs("s1")
        self.assertEqual(len(jobs_s1), 2)
        
        job_ids = {j.job_id for j in jobs_s1}
        self.assertIn(h1.job_id, job_ids)
        self.assertIn(h2.job_id, job_ids)
        self.assertNotIn(h3.job_id, job_ids)

if __name__ == "__main__":
    unittest.main()
