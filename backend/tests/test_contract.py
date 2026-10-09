"""Static checks that frontend, backend, Docker and hosting config agree. No network or FastAPI needed."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS, BACKEND = ROOT / "docs", ROOT / "backend"
read = lambda p: Path(p).read_text(encoding="utf-8")
norm = lambda path: re.sub(r"\{[^}]*\}|\$\{[^}]*\}", "{}", path)


def backend_routes():
    return {(m.upper(), norm(p)) for m, p in re.findall(r'@app\.(get|post|delete)\(\s*"([^"]+)"', read(BACKEND / "app/main.py"))}


class ApiContract(unittest.TestCase):
    def test_every_frontend_call_has_a_backend_route(self):
        calls = {(m, norm(p)) for m, _, p in re.findall(r'request\("(GET|POST|DELETE)",\s*([`"\'])(/api/[^`"\']*)\2', read(DOCS / "js/api.js"))}
        self.assertTrue(calls, "no API calls found in api.js")
        self.assertLessEqual(calls, backend_routes(), calls - backend_routes())

    def test_file_url_comes_from_a_real_route(self):
        self.assertIn(("GET", "/api/jobs/{}/file"), backend_routes())
        self.assertIn('f"/api/jobs/{job.id}/file"', read(BACKEND / "app/jobs.py"))

    def test_fields_used_by_the_ui_exist_in_the_api_models(self):
        schemas, app = read(BACKEND / "app/schemas.py"), read(DOCS / "app.js")
        used = ["title", "duration", "thumbnail", "platform", "source_url", "types", "video", "audio", "video_format", "audio_format",
                "id", "label", "size", "recommended", "over_limit", "state", "stage", "progress", "downloaded_bytes",
                "expected_bytes", "filename", "file_url", "error"]
        for key in used:
            self.assertRegex(schemas, rf"\b{key}\b", f"{key} missing from schemas.py")
            if key in ("video_format", "audio_format"):
                self.assertIn('"_format"', app)   # read as info[type + "_format"]
            else:
                self.assertRegex(app, rf"\b{key}\b", f"{key} not used by app.js")

    def test_frontend_never_targets_localhost_in_production(self):
        config = read(DOCS / "config.js")
        base = re.search(r'apiBase:\s*"([^"]*)"', config).group(1)
        self.assertTrue(base.startswith("https://"), base)
        self.assertNotRegex(base, r"localhost|127\.0\.0\.1")
        self.assertRegex(read(DOCS / "js/api.js"), r"isLocalPage")  # devApiBase is gated on the page itself being local


class DeploymentFiles(unittest.TestCase):
    def check_dockerfile(self, dockerfile: Path, context: Path):
        text = read(dockerfile)
        sources = re.findall(r"(?m)^COPY (?!--from)(\S+) \S+", text)
        self.assertTrue(sources)
        for src in sources:
            self.assertTrue((context / src).exists(), f"{dockerfile.name}: COPY {src} not found in context {context}")
        self.assertIn("0.0.0.0", text)
        self.assertIn("${PORT", text)
        self.assertIn("app.main:app", text)
        self.assertIn("ffmpeg", text)
        self.assertIn("USER ", text)

    def test_root_dockerfile_matches_repo_layout(self):
        self.check_dockerfile(ROOT / "Dockerfile", ROOT)

    def test_backend_dockerfile_matches_backend_context(self):
        self.check_dockerfile(BACKEND / "Dockerfile", BACKEND)

    def test_both_dockerfiles_copy_the_same_things(self):
        a = re.findall(r"^(?:RUN|CMD|ENV|USER|EXPOSE)\b.*$", read(ROOT / "Dockerfile"), re.M)
        b = re.findall(r"^(?:RUN|CMD|ENV|USER|EXPOSE)\b.*$", read(BACKEND / "Dockerfile"), re.M)
        self.assertEqual(a, b)

    def test_app_entrypoint_exists(self):
        self.assertRegex(read(BACKEND / "app/main.py"), r"(?m)^app = create_app\(\)")
        self.assertTrue((BACKEND / "app/__init__.py").exists())

    def test_render_blueprint_points_at_real_files_and_health_route(self):
        text = read(ROOT / "render.yaml")
        dockerfile = re.search(r"dockerfilePath:\s*(\S+)", text).group(1)
        context = re.search(r"dockerContext:\s*(\S+)", text).group(1)
        self.assertTrue((ROOT / context / dockerfile).exists() or (ROOT / dockerfile).exists())
        self.assertEqual((dockerfile, context), ("./Dockerfile", "."))
        health = re.search(r"healthCheckPath:\s*(\S+)", text).group(1)
        self.assertIn(("GET", health), backend_routes())

    def test_no_doubled_backend_path_anywhere(self):
        for f in [ROOT / "render.yaml", ROOT / "Dockerfile", BACKEND / "Dockerfile"]:
            self.assertNotIn("backend/backend", read(f), f.name)

    def test_env_example_documents_every_variable(self):
        names = set(re.findall(r'(?:_int|_flag)\(env,\s*"([A-Z_]+)"|env\.get\("([A-Z_]+)"', read(BACKEND / "app/config.py")))
        names = {a or b for a, b in names}
        example = read(BACKEND / ".env.example")
        for name in names:
            self.assertRegex(example, rf"(?m)^{name}=", name)
        self.assertNotRegex(example, r"(?i)secret|password|token=\w")

    def test_secrets_are_ignored_by_git(self):
        self.assertRegex(read(ROOT / ".gitignore"), r"(?m)^\.env$")


class FrontendFiles(unittest.TestCase):
    def test_local_references_exist(self):
        html = read(DOCS / "index.html")
        for ref in re.findall(r'(?:src|href)="([^"#:]+)"', html):
            self.assertTrue((DOCS / ref).exists(), ref)
        for ref in re.findall(r'from "(\./[^"]+)"', read(DOCS / "app.js")):
            self.assertTrue((DOCS / ref).exists(), ref)

    def test_service_worker_shell_and_manifest(self):
        for ref in re.findall(r'"((?:js|assets)/[^"]+|index\.html|style\.css|app\.js|config\.js|manifest\.webmanifest)"', read(DOCS / "sw.js")):
            self.assertTrue((DOCS / ref).exists(), ref)
        manifest = json.loads(read(DOCS / "manifest.webmanifest"))
        self.assertEqual(manifest["share_target"]["method"], "GET")
        for icon in manifest["icons"]:
            self.assertTrue((DOCS / icon["src"]).exists(), icon["src"])

    def test_every_icon_used_is_in_the_sprite(self):
        sprite = set(re.findall(r'<symbol id="([a-z]+)"', read(DOCS / "assets/icons.svg")))
        html, js = read(DOCS / "index.html"), read(DOCS / "app.js")
        used = set(re.findall(r'data-icon="([a-z]+)"', html)) | set(re.findall(r'(?:setIcon\([^,]+,|icon\()\s*"([a-z]+)"', js))
        used |= set(re.findall(r'\["([a-z]+)", "[A-Z][^"]*"\]', js))   # BUTTON state table
        self.assertLessEqual(used, sprite, used - sprite)

    def test_no_emoji_or_symbol_characters_in_ui_files(self):
        for name in ("index.html", "app.js", "style.css", "js/api.js", "js/format.js", "js/store.js", "js/icons.js"):
            bad = [c for c in read(DOCS / name) if ord(c) > 0x2000]
            self.assertFalse(bad, f"{name}: {bad[:5]}")

    def test_no_settings_button(self):
        self.assertNotRegex(read(DOCS / "index.html").lower(), r"settings")


if __name__ == "__main__":
    unittest.main()
