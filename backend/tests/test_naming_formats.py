import unittest

from app.errors import AppError
from app.formats import summarize
from app.naming import build_filename, sanitize_title
from app.runner import build_format_args, classify_failure


def formats_fixture():
    return {"title": "T", "duration": 42, "webpage_url": "https://x.test/v", "formats": [
        {"vcodec": "avc1", "acodec": "none", "height": 2160, "width": 3840, "ext": "mp4", "filesize": 9000, "tbr": 9000},
        {"vcodec": "avc1", "acodec": "none", "height": 1080, "width": 1920, "ext": "mp4", "filesize": 2000, "tbr": 2000},
        {"vcodec": "vp09", "acodec": "none", "height": 1080, "width": 1920, "ext": "webm", "filesize": 1500, "tbr": 1500},
        {"vcodec": "avc1", "acodec": "none", "height": 720, "width": 1280, "ext": "mp4", "filesize_approx": 1000},
        {"vcodec": "avc1", "acodec": "none", "height": 360, "width": 640, "ext": "mp4"},
        {"vcodec": "none", "acodec": "mp4a", "abr": 129.5, "ext": "m4a", "filesize": 200},
        {"vcodec": "none", "acodec": "opus", "abr": 160.2, "ext": "webm", "filesize": 250},
        {"vcodec": "none", "acodec": "none", "ext": "mhtml"}]}


class Naming(unittest.TestCase):
    def test_format(self):
        self.assertEqual(build_filename("My Favorite Video", "mp4"), "My_Favorite_Video_FluxVid-created by shiv yogi.mp4")
        self.assertEqual(build_filename("Song", "MP3"), "Song_FluxVid-created by shiv yogi.mp3")

    def test_unsafe_characters_removed(self):
        name = build_filename('a/b:c*?"<>|d\\e', "mp4")
        self.assertEqual(name, "a_b_c_d_e_FluxVid-created by shiv yogi.mp4")
        self.assertNotIn("..", build_filename("../../etc/passwd", "mp4"))
        self.assertNotIn("/", build_filename("../../etc/passwd", "mp4"))

    def test_no_duplicate_suffix_and_fallbacks(self):
        self.assertEqual(build_filename("Clip FluxVid-created by shiv yogi", "mp4"), "Clip_FluxVid-created by shiv yogi.mp4")
        self.assertEqual(build_filename("   ", "mp4"), "media_FluxVid-created by shiv yogi.mp4")
        self.assertEqual(build_filename("x", "../sh"), "x_FluxVid-created by shiv yogi.sh")
        self.assertLessEqual(len(sanitize_title("a" * 500)), 100)
        self.assertEqual(sanitize_title("Caf\u00e9 \u65e5\u672c"), "Caf\u00e9_\u65e5\u672c")


class Formats(unittest.TestCase):
    def test_only_real_qualities_and_recommendation(self):
        info = summarize(formats_fixture(), max_download_size=5000)
        self.assertEqual([o["id"] for o in info["video"]], ["2160", "1080", "720", "360"])
        rec = [o["id"] for o in info["video"] if o["recommended"]]
        self.assertEqual(rec, ["1080"])
        self.assertEqual([o["label"] for o in info["audio"]], ["Best audio", "160 kbps", "128 kbps"])
        self.assertEqual(info["types"], ["video", "audio"])

    def test_sizes_only_when_known(self):
        by_id = {o["id"]: o for o in summarize(formats_fixture(), 5000)["video"]}
        self.assertEqual(by_id["1080"]["size"], 2200)    # h264 video + aac audio
        self.assertEqual(by_id["720"]["size"], 1200)     # filesize_approx counts
        self.assertEqual(by_id["2160"]["size"], 9200)
        self.assertIsNone(by_id["360"]["size"])          # unknown stays unknown
        self.assertTrue(by_id["2160"]["over_limit"])
        self.assertFalse(by_id["1080"]["over_limit"])
        audio = {o["id"]: o for o in summarize(formats_fixture(), 5000)["audio"]}
        self.assertIsNone(audio["best"]["size"])
        self.assertEqual(audio["128"]["size"], 42 * 128 * 125)

    def test_audio_only_source(self):
        info = summarize({"title": "Podcast", "formats": [{"vcodec": "none", "acodec": "mp3", "abr": 128, "ext": "mp3"}]}, 5000)
        self.assertEqual(info["types"], ["audio"])
        self.assertEqual(info["video"], [])

    def test_nothing_downloadable(self):
        with self.assertRaises(AppError) as ctx:
            summarize({"title": "x", "formats": [{"vcodec": "none", "acodec": "none", "ext": "mhtml"}]}, 5000)
        self.assertEqual(ctx.exception.code, "no_formats")

    def test_low_resolution_only_recommends_best_available(self):
        info = summarize({"formats": [{"vcodec": "avc1", "height": 4320, "width": 7680, "acodec": "none", "ext": "mp4"}]}, 5000)
        self.assertTrue(info["video"][0]["recommended"])


class Runner(unittest.TestCase):
    def test_format_args_validate_quality(self):
        self.assertIn("-x", build_format_args("audio", "128"))
        self.assertIn("bv*[height<=720]+ba/b[height<=720]", build_format_args("video", "720"))
        for t, q in [("video", "99999"), ("video", "50"), ("audio", "999"), ("audio", "5"), ("subs", "best")]:
            with self.assertRaises(AppError):
                build_format_args(t, q)

    def test_failure_classification(self):
        cases = {"ERROR: Unsupported URL: x": "unsupported", "ERROR: Private video": "restricted",
                 "This video is DRM protected": "drm", "File is larger than max-filesize": "too_large",
                 "Sign in to confirm you're not a bot": "restricted", "boom": "extraction_failed"}
        for text, code in cases.items():
            self.assertEqual(classify_failure(text).code, code, text)
            self.assertNotIn("Traceback", classify_failure(text).message)


if __name__ == "__main__":
    unittest.main()
