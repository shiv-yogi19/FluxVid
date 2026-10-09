"""HTTP-level tests. They need FastAPI and httpx (pip install -r requirements-dev.txt)."""
import shutil
import time
import unittest

try:
    from fastapi.testclient import TestClient
    from app.main import create_app
    HAVE_STACK = True
except ImportError:
    HAVE_STACK = False

from . import helpers
from .helpers import PUBLIC, make_settings

ORIGIN = "https://shiv-yogi19.github.io"


@unittest.skipUnless(HAVE_STACK, "fastapi/httpx not installed")
class Api(unittest.TestCase):
    def setUp(self):
        self.tmp = helpers.tempdir()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.client_cm = TestClient(create_app(make_settings(self.tmp)))
        self.client = self.client_cm.__enter__()
        self.addCleanup(self.client_cm.__exit__, None, None, None)

    def test_health_root_docs(self):
        body = self.client.get("/api/health").json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("ffmpeg", body)
        self.assertEqual(self.client.get("/").json()["docs"], "/docs")
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertIn("/api/jobs", self.client.get("/openapi.json").json()["paths"])

    def test_error_shape_everywhere(self):
        for response in (self.client.get("/nope"), self.client.post("/api/info", json={}),
                         self.client.post("/api/info", json={"url": "http://127.0.0.1/"}),
                         self.client.post("/api/info", json={"url": "ftp://x"}),
                         self.client.get("/api/jobs/" + "a" * 20),
                         self.client.post("/api/jobs", json={"url": PUBLIC, "type": "video", "quality": "abc"})):
            self.assertGreaterEqual(response.status_code, 400)
            error = response.json()["error"]
            self.assertTrue(error["code"] and error["message"])
            self.assertNotIn("detail", response.json())

    def test_cors_allows_only_configured_origin(self):
        ok = self.client.options("/api/info", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"})
        self.assertEqual(ok.headers.get("access-control-allow-origin"), ORIGIN)
        bad = self.client.options("/api/info", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
        self.assertIsNone(bad.headers.get("access-control-allow-origin"))

    def test_full_flow_with_stub_extractor(self):
        info = self.client.post("/api/info", json={"url": PUBLIC}).json()
        self.assertEqual(info["types"], ["video", "audio"])
        job = self.client.post("/api/jobs", json={"url": PUBLIC, "type": "video", "quality": "720"})
        self.assertEqual(job.status_code, 202)
        job_id = job.json()["id"]
        for _ in range(200):
            status = self.client.get(f"/api/jobs/{job_id}").json()
            if status["state"] in ("ready", "failed"):
                break
            time.sleep(0.05)
        self.assertEqual(status["state"], "ready", status)
        file = self.client.get(status["file_url"])
        self.assertEqual(file.status_code, 200)
        self.assertIn("FluxVid-created by shiv yogi.mp4", file.headers["content-disposition"])
        self.assertEqual(self.client.delete(f"/api/jobs/{job_id}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").status_code, 404)

    def test_rate_limit(self):
        for _ in range(30):
            self.client.post("/api/info", json={"url": "ftp://x"})
        self.assertEqual(self.client.post("/api/info", json={"url": "ftp://x"}).status_code, 429)


if __name__ == "__main__":
    unittest.main()
