import unittest

from app.errors import AppError
from app.urls import check_syntax, is_public_address, validate_url
from . import helpers  # noqa: F401


class UrlValidation(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_bad_input(self):
        for bad in ["", "   ", "ftp://8.8.8.8/x", "javascript:alert(1)", "file:///etc/passwd", "http://",
                    "http://user:pw@8.8.8.8/", "http://8.8.8.8:22/", "http://8.8.8.8/a b", "x" * 3000]:
            with self.assertRaises(AppError, msg=bad) as ctx:
                await validate_url(bad)
            self.assertEqual(ctx.exception.code, "invalid_url", bad)

    async def test_blocks_private_and_local_addresses(self):
        for blocked in ["http://127.0.0.1/", "http://localhost/", "http://10.0.0.5/", "http://192.168.1.1/",
                        "http://169.254.169.254/latest/meta-data", "http://[::1]/", "http://0.0.0.0/"]:
            with self.assertRaises(AppError, msg=blocked) as ctx:
                await validate_url(blocked)
            self.assertIn(ctx.exception.code, ("blocked_address", "unresolvable", "invalid_url"), blocked)

    async def test_accepts_public_address(self):
        self.assertEqual(await validate_url(" https://8.8.8.8/watch?v=1 "), "https://8.8.8.8/watch?v=1")

    def test_address_classification(self):
        self.assertFalse(is_public_address("127.0.0.1"))
        self.assertFalse(is_public_address("fe80::1%eth0"))
        self.assertTrue(is_public_address("8.8.8.8"))
        self.assertEqual(check_syntax("http://8.8.8.8:80/a")[2], 80)


if __name__ == "__main__":
    unittest.main()
