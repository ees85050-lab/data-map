#!/usr/bin/env python3
"""Tests for datamap: reconciliation, freshness, time hints, and a broken seed. Run: python3 tests/test_datamap.py"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from importlib.machinery import SourceFileLoader

os.environ["TZ"] = "UTC"
time.tzset()

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "datamap")
DUCKDB = os.environ.get("DATAMAP_DUCKDB") or "duckdb"
NOW = 1791671600          # 2026-10-10 22:33:20 UTC

_loader = SourceFileLoader("datamap", SCRIPT)
dm = importlib.util.module_from_spec(importlib.util.spec_from_loader("datamap", _loader))
_loader.exec_module(dm)

SEED = """# Seed for the tests

## Ground rules

Every time on this box is UTC unless a row says otherwise.

## Scan

| Dir | Suffixes | Depth |
|---|---|---|
| d | jsonl, json | {depth} |

## Data

| Group | Name | Path | Writer | Row | Cadence | Fresh | Time key | Gotchas |
|---|---|---|---|---|---|---|---|---|
| A | a | d/a.jsonl | the test | one event | every minute | 30m | t | don't trust mtime (test) |
{extra}

## Ignored

| Path | Why |
|---|---|
| d/ids.json | a lookup table, not data |{ignored}

## Queries

```sql
SELECT 1;
```
"""
ROW_B = "| A | b | d/b.jsonl | the test | one event | every 5 min | 10m | at | - |"


class Datamap(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="datamap-test.")
        self.addCleanup(shutil.rmtree, self.root)
        self.put("d/a.jsonl", {"t": "2026-10-11T00:30:00+02:00"})
        self.put("d/b.jsonl", {"at": "2026-10-11 00:31:00"})
        self.put("d/ids.json", {"x": 1})
        # none of these may show up as unregistered: a backup, a hidden file, one level too deep
        self.put("d/a.bak-20261010.jsonl", {"t": 0})
        self.put("d/.b.jsonl", {"at": 0})
        self.put("d/sub/deep.jsonl", {"t": 0})

    def put(self, rel, obj, age=60):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(json.dumps(obj) + "\n")
        os.utime(p, (NOW - age, NOW - age))

    def seed(self, extra="", depth=0, ignored=""):
        with open(os.path.join(self.root, "datamap-seed.md"), "w") as f:
            f.write(SEED.replace("{extra}", extra).replace("{depth}", str(depth)).replace("{ignored}", ignored))

    def run_dm(self, *args):
        env = dict(os.environ, DATAMAP_ROOT=self.root, DATAMAP_NOW=str(NOW))
        for k in ("DATAMAP_SEED", "DATAMAP_OUT", "DATAMAP_HOME"):
            env.pop(k, None)
        return subprocess.run([sys.executable, SCRIPT, *args], env=env, capture_output=True, text=True)

    def page(self):
        with open(os.path.join(self.root, "datamap.md")) as f:
            return f.read()

    def test_unregistered_file_is_named(self):
        self.seed()
        r = self.run_dm("--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unregistered: d/b.jsonl", r.stdout)
        self.assertNotIn("bak", r.stdout)
        self.assertNotIn(".b.jsonl", r.stdout)
        self.assertNotIn("deep", r.stdout)
        self.assertEqual(self.run_dm("--write").returncode, 0)
        page = self.page()
        self.assertIn("On disk but not in the seed: 1", page)
        self.assertIn("- d/b.jsonl", page)

    def test_everything_registered_is_clean(self):
        self.seed(ROW_B)
        r = self.run_dm("--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("2 registered", r.stdout)
        self.assertIn("0 unregistered, 0 missing", r.stdout)
        self.run_dm("--write")
        self.assertIn("- On disk but not in the seed: none", self.page())
        self.assertIn("- In the seed but not on disk: none", self.page())

    def test_scan_depth_and_ignored_directories(self):
        self.seed(ROW_B, depth=1)
        r = self.run_dm("--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unregistered: d/sub/deep.jsonl", r.stdout)
        self.seed(ROW_B, depth=1, ignored="\n| d/sub | scratch space |")
        r = self.run_dm("--check")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_registered_but_missing(self):
        self.seed(ROW_B + "\n| A | c | d/c.jsonl | the test | one event | hourly | 2h | t | - |")
        r = self.run_dm("--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing: d/c.jsonl", r.stdout)
        self.run_dm("--write")
        self.assertIn("In the seed but not on disk: 1", self.page())
        self.assertIn("| A | c | d/c.jsonl | ✗ missing |", self.page())

    def test_freshness_hints_and_seed_text(self):
        self.seed(ROW_B)
        self.put("d/b.jsonl", {"at": "2026-10-11 00:31:00"}, age=3600)
        r = self.run_dm()
        self.assertEqual(r.returncode, 0, r.stderr)
        page = r.stdout
        self.assertIn("| A | a | d/a.jsonl | ✓ 1 min ago | 1 row, ", page)
        self.assertIn("fresh within 10m; now ✗ 1.0 h ago", page)
        self.assertIn("`timezone('UTC', \"t\")`", page)
        self.assertIn("off by the offset", page)
        self.assertIn("In DuckDB: `\"at\"` (use as is", page)
        self.assertIn("- Gotchas: don't trust mtime (test)", page)
        self.assertNotIn("- Gotchas: -", page)
        self.assertIn("Every time on this box is UTC", page)
        self.assertIn("SELECT 1;", page)
        self.assertIn("| A | a | d/a.jsonl | ✓ 1 min ago | 1 row, 35B | 2026-10-10 22:30 |", page)
        r = self.run_dm("--check")
        self.assertIn("1 stale", r.stdout)

    def test_dated_files_retired_rows_and_json_documents(self):
        self.put("d/p/2026-10-09.jsonl", {"t": "2026-10-09 10:00:00"}, age=86400)
        self.put("d/p/2026-10-10.jsonl", {"t": "2026-10-10T10:00:00.5"})
        self.put("d/old.jsonl", {"when": "2026-10-10 21:00:00"}, age=3600)
        self.put("d/state.json", {"meta": {"saved_at": "2026-10-10T22:00:00Z"}})
        self.seed(ROW_B + "\n| B | p | d/p/*.jsonl | the test | a reading | daily file | 1d | t | - |"
                  "\n| B | old | d/old.jsonl | nobody now | one event | - | retired | when | - |"
                  "\n| B | state | d/state.json | the test | the whole file | on change | - | meta.saved_at | - |")
        page = self.run_dm().stdout
        self.assertIn("- Path: `d/p/*.jsonl` (2 files)", page)
        self.assertIn("one format in the first row (2026-10-09 10:00:00) and another in the last (2026-10-10T10:00:00.5)",
                      page)
        self.assertIn("⚠ retired but still written, last at 2026-10-10 21:33", page)
        self.assertIn("`timezone('UTC', meta.saved_at)`", page)
        r = self.run_dm("--check")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("1 retired but still written", r.stdout)

    def test_a_broken_seed_row_fails_loudly(self):
        self.seed("| A | short | d/b.jsonl |")
        r = self.run_dm("--check")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("has 3 cells, needs 9", r.stderr)


BASE = 1791678600          # 2026-10-11 00:30:00 UTC
SAMPLES = [
    (BASE, BASE), (BASE * 1000 + 123, BASE + 0.123), ("2026-10-11", BASE - 1800), ("2026-10-11 00:30", BASE),
    ("2026-10-11T00:30:00", BASE), ("2026-10-11 00:30:00", BASE), ("2026-10-11T00:30:00.5", BASE + 0.5),
    ("2026-10-11 00:30:00.123", BASE + 0.123), ("2026-10-11T00:30:00Z", BASE),
    ("2026-10-11T00:30:00.123456Z", BASE + 0.123456), ("2026-10-11 00:30:00Z", BASE),
    ("2026-10-11T00:30:00+02:00", BASE - 7200), ("2026-10-11T00:30:00.5-0530", BASE + 19800.5),
    ("2026-10-11 00:30:00+02:00", BASE - 7200), ("2026-10-11 00:30:00.123+0200", BASE - 7199.877),
    ("2026-10-11 00:30:00 +0200", BASE - 7200), ("2026-10-11T00:30:00.5 -05:30", BASE + 19800.5),
]


class TimeFormats(unittest.TestCase):
    def test_every_sample_is_recognised_and_converted(self):
        for v, want in SAMPLES:
            with self.subTest(v=v):
                self.assertIsNotNone(dm.tfmt(v))
                self.assertAlmostEqual(dm.to_epoch(v), want, places=4)
        for v in (True, None, 42, "yesterday", "2026-10-11T00:30", {"t": 1}):
            self.assertIsNone(dm.tfmt(v), v)

    @unittest.skipUnless(shutil.which(DUCKDB), "duckdb isn't installed")
    def test_every_hint_gives_the_right_instant_in_duckdb(self):
        d = tempfile.mkdtemp(prefix="datamap-duckdb.")
        self.addCleanup(shutil.rmtree, d)
        for i, (v, want) in enumerate(SAMPLES):
            with self.subTest(v=v):
                p = os.path.join(d, f"s{i}.jsonl")
                with open(p, "w") as f:
                    f.write(json.dumps({"k": v}) + "\n" + json.dumps({"k": v}) + "\n")
                expr = dm.tfmt(v)[1].format(k="k")
                r = subprocess.run([DUCKDB, "-noheader", "-csv", "-c",
                                    f"SET TimeZone='UTC'; SELECT epoch({expr}) FROM read_json_auto('{p}') LIMIT 1"],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{expr}: {r.stderr}")
                self.assertAlmostEqual(float(r.stdout), want, places=4, msg=expr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
