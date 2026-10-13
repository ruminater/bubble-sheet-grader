"""Shared on a network: one password, and each person sees only their own runs."""

import pathlib
import unittest

from bubblegrader import app as appmod
from bubblegrader.app import app, configure

SAMPLE = pathlib.Path(__file__).parent.parent / "samples" / "sample-key-and-students.pdf"
PASSWORD = "correct horse battery"


class AccessTest(unittest.TestCase):
    def setUp(self):
        configure(password=PASSWORD)
        appmod._tries.clear()

    def tearDown(self):
        configure(password="")
        appmod._tries.clear()

    def signed_in(self):
        c = app.test_client()
        r = c.post("/login", data={"password": PASSWORD, "next": "/"})
        self.assertEqual(r.status_code, 302)
        return c

    def upload(self, c):
        r = c.post("/grade", data={"students": (open(SAMPLE, "rb"), "s.pdf")},
                   content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        return r.location

    def test_everything_needs_the_password(self):
        c = app.test_client()
        for path in ("/", "/r/anything", "/r/anything/download/csv"):
            r = c.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn("/login", r.location)
        r = c.post("/grade", data={})
        self.assertIn("/login", r.location)

    def test_wrong_password(self):
        r = app.test_client().post("/login", data={"password": "nope"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("not right", r.get_data(as_text=True))

    def test_attempts_are_limited(self):
        c = app.test_client()
        for _ in range(appmod.LOGIN_TRIES):
            c.post("/login", data={"password": "nope"})
        r = c.post("/login", data={"password": PASSWORD})
        self.assertIn("Too many attempts", r.get_data(as_text=True))

    def test_results_are_private_to_the_uploader(self):
        mine = self.signed_in()
        url = self.upload(mine)
        self.assertEqual(mine.get(url).status_code, 200)
        other = self.signed_in()
        for suffix in ("", "/download/xlsx", "/sheet/1", "/sheet/1/side1.png"):
            self.assertEqual(other.get(url + suffix).status_code, 404, suffix)

    def test_pages_are_never_cached(self):
        c = self.signed_in()
        self.assertEqual(c.get(self.upload(c)).headers["Cache-Control"], "no-store")

    def test_open_redirect_refused(self):
        r = app.test_client().post("/login", data={"password": PASSWORD, "next": "//evil.example"})
        self.assertEqual(r.location, "/")

    def test_not_a_pdf(self):
        c = self.signed_in()
        r = c.post("/grade", data={"students": (__import__("io").BytesIO(b"hello"), "notes.txt")},
                   content_type="multipart/form-data")
        self.assertIn("error", r.location)


if __name__ == "__main__":
    unittest.main()
