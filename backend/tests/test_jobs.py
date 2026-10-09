import asyncio
import shutil
import unittest
from dataclasses import replace

from app.errors import AppError
from app.info import InfoService
from app.jobs import JobManager
from . import helpers
from .helpers import PUBLIC, make_settings


async def wait_for(job, states, limit=20.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + limit
    while job.state not in states:
        if loop.time() > end:
            raise AssertionError(f"job stuck in {job.state}/{job.stage}")
        await asyncio.sleep(0.05)


class JobLifecycle(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = helpers.tempdir()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def manager(self, **overrides):
        settings = make_settings(self.tmp, **overrides)
        info = InfoService(settings)
        return JobManager(settings, info), info

    async def test_info_then_video_job_produces_branded_mp4(self):
        jobs, info = self.manager()
        summary = await info.get(PUBLIC)
        self.assertEqual(summary["video"][1]["size"], 1200)
        job = jobs.create(PUBLIC, "video", "720", "1.2.3.4")
        self.assertEqual(job.expected, 1200)
        await wait_for(job, ("ready", "failed"))
        self.assertEqual(job.state, "ready", job.error and job.error.message)
        self.assertEqual(job.downloaded, 1200)        # 1000 + 200 from the two real streams
        self.assertEqual(job.filename, "My_Favorite_Video_Test_1_FluxVid-created by shiv yogi.mp4")
        self.assertTrue(job.path.exists())
        public = jobs.public(job)
        self.assertEqual(public["file_url"], f"/api/jobs/{job.id}/file")
        self.assertEqual(public["progress"], 1.0)
        await jobs.remove(job.id)
        self.assertFalse(job.workdir.exists())

    async def test_audio_job_produces_mp3(self):
        jobs, _ = self.manager()
        job = jobs.create(PUBLIC, "audio", "128", "1.2.3.4")
        await wait_for(job, ("ready", "failed"))
        self.assertEqual(job.state, "ready")
        self.assertTrue(job.filename.endswith("_FluxVid-created by shiv yogi.mp3"))
        self.assertEqual(job.mime, "audio/mpeg")
        self.assertIsNone(jobs.public(job)["expected_bytes"])  # unknown stays unknown

    async def test_failure_is_classified_and_cleaned_up(self):
        jobs, _ = self.manager()
        job = jobs.create("https://8.8.8.8/bad", "video", "best", "1.2.3.4")
        await wait_for(job, ("ready", "failed"))
        self.assertEqual((job.state, job.error.code), ("failed", "unsupported"))
        self.assertFalse(job.workdir.exists())
        self.assertIsNone(jobs.public(job)["file_url"])

    async def test_cancel_stops_process_and_removes_files(self):
        jobs, _ = self.manager()
        job = jobs.create("https://8.8.8.8/slow", "video", "best", "1.2.3.4")
        while job.stage != "downloading":
            await asyncio.sleep(0.05)
        self.assertGreater(job.downloaded, 0)
        workdir = job.workdir
        await asyncio.wait_for(jobs.remove(job.id), 5)   # would hang 30 s if the process were not killed
        self.assertFalse(workdir.exists())
        self.assertEqual(jobs.jobs, {})
        with self.assertRaises(AppError) as ctx:
            jobs.get(job.id)
        self.assertEqual(ctx.exception.status, 404)
        await jobs.remove(job.id)                        # idempotent

    async def test_timeout_kills_job(self):
        jobs, _ = self.manager(download_timeout=1)
        job = jobs.create("https://8.8.8.8/slow", "video", "best", "1.2.3.4")
        await wait_for(job, ("failed",), 10)
        self.assertEqual(job.error.code, "timeout")
        self.assertFalse(job.workdir.exists())

    async def test_size_limit_enforced_during_download(self):
        jobs, _ = self.manager(max_download_size=5000)
        job = jobs.create("https://8.8.8.8/huge", "video", "best", "1.2.3.4")
        await wait_for(job, ("failed",), 10)
        self.assertEqual(job.error.code, "too_large")

    async def test_size_limit_rejected_up_front_when_estimate_known(self):
        jobs, info = self.manager(max_download_size=1500)
        await info.get(PUBLIC)
        with self.assertRaises(AppError) as ctx:
            jobs.create(PUBLIC, "video", "1080", "1.2.3.4")
        self.assertEqual(ctx.exception.code, "too_large")

    async def test_rejects_unknown_quality_and_enforces_concurrency(self):
        jobs, info = self.manager()
        await info.get(PUBLIC)
        with self.assertRaises(AppError) as ctx:
            jobs.create(PUBLIC, "video", "480", "1.2.3.4")   # analyzed, but 480p does not exist
        self.assertEqual(ctx.exception.code, "invalid_quality")
        first = jobs.create("https://8.8.8.8/slow", "video", "best", "ip-a")
        with self.assertRaises(AppError) as ctx:
            jobs.create("https://8.8.8.8/slow", "video", "best", "ip-a")
        self.assertEqual(ctx.exception.code, "too_many_jobs")
        second = jobs.create("https://8.8.8.8/slow", "video", "best", "ip-b")
        with self.assertRaises(AppError) as ctx:
            jobs.create("https://8.8.8.8/slow", "video", "best", "ip-c")
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("busy", 503))
        await jobs.shutdown()
        self.assertEqual(jobs.jobs, {})

    async def test_sweep_expires_finished_jobs(self):
        jobs, _ = self.manager(job_ttl=1)
        job = jobs.create(PUBLIC, "audio", "best", "1.2.3.4")
        await wait_for(job, ("ready",))
        workdir = job.workdir
        job.finished -= 5
        jobs.sweep()
        self.assertEqual(jobs.jobs, {})
        self.assertFalse(workdir.exists())

    async def test_info_errors(self):
        _, info = self.manager()
        with self.assertRaises(AppError) as ctx:
            await info.get("https://8.8.8.8/private")
        self.assertEqual(ctx.exception.code, "restricted")


if __name__ == "__main__":
    unittest.main()
