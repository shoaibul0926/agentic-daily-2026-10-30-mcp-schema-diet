import json, os, subprocess, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from mcp_schema_diet import core

HERE = os.path.dirname(__file__)
EX = os.path.join(HERE, "..", "examples", "github_like_tools.json")


def tools():
    return core.load_tools(json.load(open(EX)))


class T(unittest.TestCase):
    def test_load_shapes(self):
        t = [{"name": "a"}]
        self.assertEqual(core.load_tools(t), t)
        self.assertEqual(core.load_tools({"tools": t}), t)
        self.assertEqual(core.load_tools({"jsonrpc": "2.0", "id": 1, "result": {"tools": t}}), t)
        with self.assertRaises(ValueError):
            core.load_tools({"nope": 1})
        with self.assertRaises(ValueError):
            core.load_tools([{"no_name": 1}])

    def test_shared_owner_repo_found(self):
        names = {s["property"] for s in core.shared_properties(tools())}
        self.assertTrue({"owner", "repo"} <= names)

    def test_waste_detected(self):
        w = core.find_waste(tools()[0])
        self.assertIn("$schema", w)
        self.assertIn("auto-generated title", w)
        self.assertIn("additionalProperties:false", w)

    def test_lossless_is_smaller_and_preserves_semantics(self):
        orig = tools()
        s = core.slim(orig, "lossless")
        self.assertLess(core.tokens(s), core.tokens(orig))
        for a, b in zip(orig, s):
            self.assertEqual(a["description"], b["description"])
            self.assertEqual(a["inputSchema"].get("required"), b["inputSchema"].get("required"))
            self.assertEqual(set(a["inputSchema"]["properties"]), set(b["inputSchema"]["properties"]))
            self.assertNotIn("$schema", b["inputSchema"])
            if a["name"] != "ping": self.assertIn("additionalProperties", b["inputSchema"])

    def test_slim_does_not_mutate_input(self):
        orig = tools(); snap = json.dumps(orig)
        core.slim(orig, "aggressive"); core.slim(orig, "discovery")
        self.assertEqual(snap, json.dumps(orig))

    def test_tier_ordering(self):
        o = tools()
        a, b, c = (core.tokens(core.slim(o, l)) for l in ("lossless", "aggressive", "discovery"))
        self.assertLessEqual(b, a); self.assertLess(c, b)

    def test_discovery_marks_optional(self):
        d = {x["name"]: x for x in core.slim(tools(), "discovery")}
        self.assertEqual(d["get_issue"]["params"]["issue_number"], "integer")
        self.assertEqual(d["list_issues"]["params"]["state"], "string?")

    def test_first_sentence_trim(self):
        self.assertEqual(core._first_sentence("One. Two.", 50), "One.")
        self.assertTrue(core._first_sentence("x" * 300, 20).endswith("…"))

    def test_budget_flags(self):
        r = core.analyse(tools(), budget=50)
        self.assertTrue(any(x["over_budget"] for x in r["tools"]))
        self.assertFalse([x for x in r["tools"] if x["name"] == "ping"][0]["over_budget"])

    def test_cli_exit_codes(self):
        run = lambda *a: subprocess.run([sys.executable, "-m", "mcp_schema_diet", *a],
                                        cwd=os.path.join(HERE, ".."), capture_output=True, text=True)
        self.assertEqual(run("audit", EX).returncode, 0)
        r = run("audit", EX, "--budget", "10"); self.assertEqual(r.returncode, 1); self.assertIn("OVER BUDGET", r.stdout)
        self.assertEqual(run("audit", "missing.json").returncode, 2)
        r = run("slim", EX, "--level", "discovery"); self.assertEqual(r.returncode, 0)
        json.loads(r.stdout)


if __name__ == "__main__":
    unittest.main()
