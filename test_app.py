import os, tempfile, unittest
os.environ["JARVIS_DB"] = os.path.join(tempfile.mkdtemp(), "t.db"); os.environ["AI_API_KEY"] = ""
import app as A

class T(unittest.TestCase):
    def setUp(self): self.c = A.app.test_client()
    def say(self, m): return self.c.post("/api/chat", json={"message": m})
    def test_empty(self): self.assertEqual(self.say("  ").status_code, 400)
    def test_calc(self): self.assertIn("= 84", self.say("12*(3+4)").json["reply"])
    def test_calc_safe(self): self.assertNotIn("=", self.say("__import__('os')").json["reply"])
    def test_div0(self): self.assertIn("zero", self.say("1/0").json["reply"])
    def test_tasks(self):
        self.say("add task buy milk"); self.assertIn("buy milk", self.say("list tasks").json["reply"])
        self.say("complete task 1"); self.assertTrue(self.c.get("/api/state").json["tasks"][-1]["done"])
    def test_note_reminder(self):
        self.assertIn("saved", self.say("note call mom").json["reply"])
        self.assertIn("Reminder", self.say("remind me to stretch in 10 minutes").json["reply"])
    def test_due(self):
        self.c.post("/api/reminders", json={"text": "x in 0 minutes"})
        self.assertEqual(len(self.c.get("/api/reminders/due").json["due"]), 1)
        self.assertEqual(len(self.c.get("/api/reminders/due").json["due"]), 0)
    def test_fallback_honest(self):
        r = self.say("tell me a story"); self.assertIn("not connected", r.json["reply"]); self.assertEqual(r.json["source"], "rules")
    def test_clear(self):
        self.say("hi"); self.c.post("/api/chat/clear"); self.assertEqual(self.c.get("/api/state").json["history"], [])
    def test_page(self): self.assertEqual(self.c.get("/").status_code, 200)
if __name__ == "__main__": unittest.main()
