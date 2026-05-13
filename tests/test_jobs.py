import tempfile
import unittest
from pathlib import Path

import jobs


class JobTests(unittest.TestCase):
    def test_create_and_update_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            object.__setattr__(jobs.config, "database_path", Path(tmp) / "jobs.sqlite3")
            object.__setattr__(jobs.config, "output_dir", Path(tmp) / "outputs")

            jobs.init_db()
            job_id = jobs.create_job(
                {
                    "board_url": "https://example.com/images",
                    "youtube_url": "https://youtube.com/watch?v=x",
                    "start_time": "0",
                    "end_time": "10",
                    "frame_rate": 12,
                }
            )

            job = jobs.get_job(job_id)
            self.assertEqual(job["status"], "queued")
            self.assertRegex(job["name"], r"^[a-z]+-[a-z]+-[a-z-]+$")
            self.assertEqual(job["frame_rate"], 12)
            self.assertTrue(jobs.job_dir(job_id).exists())

            jobs.update_job(job_id, status="complete", step="complete", progress=100, output_path=Path(tmp) / "out.mp4")
            updated = jobs.get_job(job_id)
            self.assertEqual(updated["status"], "complete")
            self.assertEqual(updated["progress"], 100)
            self.assertEqual(updated["download_url"], f"/download/{job_id}")

    def test_blocklist_and_unsaved_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            object.__setattr__(jobs.config, "database_path", Path(tmp) / "jobs.sqlite3")
            object.__setattr__(jobs.config, "output_dir", Path(tmp) / "outputs")

            jobs.init_db()
            jobs.block_checksums(["abc", "def"])
            self.assertEqual(jobs.blocked_checksums(), {"abc", "def"})

            output_path = Path(tmp) / "output.mp4"
            output_path.write_bytes(b"video")
            job_id = jobs.create_job(
                {
                    "board_url": "https://example.com/images",
                    "youtube_url": "https://youtube.com/watch?v=x",
                    "start_time": "0",
                    "end_time": "10",
                    "frame_rate": 12,
                }
            )
            jobs.update_job(job_id, status="complete", output_path=output_path)
            jobs.cleanup_unsaved_outputs()

            self.assertFalse(output_path.exists())
            self.assertIsNone(jobs.get_job(job_id)["output_path"])


if __name__ == "__main__":
    unittest.main()
