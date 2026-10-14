#!/usr/bin/env bash
# Runs datamap on this example: sets each file's modification time as if it were DATAMAP_NOW (default: now),
# writes datamap.md, then runs the seed's queries. The committed datamap.md came from
#   TZ=UTC DATAMAP_NOW=1791964800 ./demo.sh
set -euo pipefail
cd "$(dirname "$0")"
now=${DATAMAP_NOW:-$(date +%s)}
python3 - "$now" <<'EOF'
import os, sys
now = int(sys.argv[1])
ages = {  # seconds since each file was last written
    "data/weather/readings.jsonl": 240,
    "data/power/2026-10-13.jsonl": 36600,
    "data/power/2026-10-14.jsonl": 600,
    "data/todo/export.json": 276000,
    "data/todo/dedupe-ids.json": 276000,
    "data/bookmarks/clicks.jsonl": 5000,
    "data/legacy/feed.jsonl": 1872000,
    "data/scratch/test-run.jsonl": 7200,
}
for path, age in ages.items():
    os.utime(path, (now - age, now - age))
EOF
export DATAMAP_ROOT=$PWD DATAMAP_NOW=$now
../../datamap --write
if command -v "${DATAMAP_DUCKDB:-duckdb}" >/dev/null; then
    ../../datamap --sql
else
    echo "duckdb isn't installed; skipping the queries"
fi
