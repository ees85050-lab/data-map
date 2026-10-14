# datamap

A catalog page for the JSON and JSONL data files on one machine, generated from a short hand-written seed. For each file it shows who writes it, what one row is, whether it's fresh, how big it is, and how to read its time key in DuckDB. It also names every data file on disk that the seed doesn't mention, so the page can't quietly fall behind.

```sh
cd examples/homelab && ./demo.sh
# unregistered: data/scratch/test-run.jsonl
# datamap: 5 registered, 1 stale; 1 unregistered, 0 missing; wrote datamap.md
# ok  block 1: -- Hourly mean temperature, without sensor dropouts
# ...
# queries: 4 blocks, 0 bad
```

The page from that run is [examples/homelab/datamap.md](examples/homelab/datamap.md). datamap is one Python script, standard library only, with a test suite.

## Why

A machine with a few cron jobs, loggers and exports collects JSONL files, and after a while nobody remembers all of them, AI agents included.

- **Every session rediscovers the data.** Which file has the power readings, what's in a row, is anything still writing it? An agent finds out by listing directories and reading the first lines of files, every time, and sometimes it guesses.
- **Timestamps come in a dozen formats, and DuckDB's `read_json_auto` treats them differently.** Given a `T` and an offset, it converts the value to UTC and drops the offset. Given a space instead of the `T`, it leaves the value as text. A query that uses the column as is can be off by hours without any error.
- **Hand-written docs rot.** A data catalog written once is wrong a month later: files move, new loggers appear, old ones stop.

## How it works

- **The seed** (`datamap-seed.md`) is the human half. It has one row per data file: its writer, what a row is, how often it's written, how stale is too stale, the key that holds its time, and its gotchas. It also lists the directories to scan, the files to leave out, some ground rules and example queries.
- **datamap measures the rest** every time it runs: whether the file is there, when it was last written, rows and size, the format of the time key in the first and last rows, and the DuckDB expression that reads that format correctly.
- **Reconciliation.** Every file under a scanned directory with a listed suffix must be claimed by a Data or Ignored row. Anything else is named at the end of the page and makes `datamap --check` exit 1. So does a Data row whose file is gone.

Run `datamap --write` from a timer so the page stays current, and point your agent at the page. For Claude Code that's one line in CLAUDE.md, such as "The data files on this machine and how to query them: datamap.md".

## Quick start

```sh
git clone https://github.com/ees85050-lab/data-map.git
cd data-map/examples/homelab
./demo.sh        # sets the example files' times, writes datamap.md, runs the queries
```

On your own machine, put `datamap` on your PATH and write `datamap-seed.md` in the directory your data paths are relative to (start from the example's seed). Then:

```sh
datamap --check  # lists the files the seed doesn't cover; add rows until it's clean
datamap --write  # writes datamap.md next to the seed
```

## Commands

| Command | What it does | Exit status |
|---|---|---|
| `datamap` | Prints the page. | 0 |
| `datamap --write` | Writes the page to `DATAMAP_OUT`, then lists unregistered and missing files and prints a summary. | 0 |
| `datamap --check` | Only the list and the summary. | 1 if anything is unregistered or missing |
| `datamap --sql` | Runs every `sql` code block in the seed's Queries section through duckdb. | 1 if any block fails |

A broken seed, such as a Data row with the wrong number of cells or a Fresh value datamap can't read, stops it with exit status 1 and a message that names the row.

## The seed

The seed is markdown with `## ` sections. datamap reads the five below (the case of the heading doesn't matter) and ignores any others. See [examples/homelab/datamap-seed.md](examples/homelab/datamap-seed.md).

- **Ground rules**: free text, copied to the top of the page.
- **Scan**: a table `Dir | Suffixes | Depth`. Depth 0 is the directory itself, 1 adds its subdirectories, and so on. datamap skips hidden files and directories; names containing `.bak` or ending in `.lock`, `.tmp` or `~`; and `__pycache__`, `.git`, `node_modules`, `fixtures` and `.venv`. A Scan directory that doesn't exist is reported on stderr.
- **Data**: a table with these nine columns, in this order:

  | Column | What goes in it |
  |---|---|
  | Group | A section heading on the page. |
  | Name | The file's name on the page. |
  | Path | A path or a glob (`*`, `**`), relative to `DATAMAP_ROOT` or starting with `~/`. |
  | Writer | What writes the file. |
  | Row | What one row is. |
  | Cadence | How often it's written, in words. |
  | Fresh | How old the last write may be before the file counts as stale: `30m`, `2h` or `2d`. `-` means no expectation, `retired` means nothing should write it anymore. |
  | Time key | The key that holds each row's time, dotted for nested keys (`meta.exported_at`), or `-`. |
  | Gotchas | Anything a reader would get wrong, or `-`. |

- **Ignored**: a table `Path | Why` for files under a scanned directory that aren't data. A directory listed here is ignored whole.
- **Queries**: free text with `sql` code blocks, copied to the end of the page. `--sql` runs each block from `DATAMAP_ROOT`, so a query that breaks when a file moves gets noticed.

Freshness compares the file's modification time with Fresh. A `retired` file that was written in the last two days is flagged as "retired but still written".

For a set of files whose names all contain a date (`2026-10-13.jsonl`), the first row is read from the oldest name and the last row from the newest. Otherwise both come from the most recently written file. A `.json` file is read as one document (up to 20 MB), and the time key is looked up in it.

## Time formats

This is what datamap says for each format it recognises, checked against DuckDB 1.5. `tests/test_datamap.py` runs every expression through the duckdb you have installed and fails if one doesn't give the right instant.

| Value in the file | What `read_json_auto` makes of it | Expression datamap gives |
|---|---|---|
| `1791964800` (epoch seconds) | a number | `to_timestamp(k)` |
| `1791964800000` (epoch milliseconds) | a number | `to_timestamp(k / 1000)` |
| `2026-10-14` | DATE | `k` |
| `2026-10-14 08:00` | text | `k::TIMESTAMP` |
| `2026-10-14T08:00:00`, `2026-10-14 08:00:00`, `2026-10-14 08:00:00.5` | TIMESTAMP | `k` |
| `2026-10-14T08:00:00.5` (a `T` and a fraction) | text | `k::TIMESTAMP` |
| `2026-10-14T08:00:00Z` | TIMESTAMP in UTC, without a zone | `timezone('UTC', k)` |
| `2026-10-14 08:00:00Z` | text | `k::TIMESTAMPTZ` |
| `2026-10-14T10:00:00+02:00` or `+0200` | TIMESTAMP converted to UTC, offset dropped | `timezone('UTC', k)` |
| `2026-10-14 10:00:00+02:00` | text | `k::TIMESTAMPTZ` (`::TIMESTAMP` would drop the offset) |
| `2026-10-14 10:00:00 +0200` | text that won't cast | `regexp_replace(k, ' ([+-])', '\1')::TIMESTAMPTZ` |

On the page, `k` is the key quoted for DuckDB, such as `"at"` or `"meta"."exported_at"`. Keys like `at` and `when` are SQL keywords, and a query that uses them bare fails with a syntax error.

A timestamp without an offset is in whatever clock its writer used, and the page says so. When the first and last rows need different expressions, the page says that instead and suggests checking the column's type with `DESCRIBE`. One common cause is Python's `isoformat()`, which leaves out the fraction when it's zero.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `DATAMAP_ROOT` | the current directory | Relative paths in the seed resolve against it, and `--sql` runs there. |
| `DATAMAP_SEED` | `$DATAMAP_ROOT/datamap-seed.md` | The seed. |
| `DATAMAP_OUT` | `$DATAMAP_ROOT/datamap.md` | Where `--write` puts the page. |
| `DATAMAP_HOME` | your home directory | What `~/` means in the seed. |
| `DATAMAP_NOW` | the current time | Epoch seconds. Pins the clock for tests and examples. |
| `DATAMAP_DUCKDB` | `duckdb` | The duckdb binary for `--sql`. |

Times on the page are in the local time zone; set `TZ` to change it.

## Requirements

Python 3.8 or newer, standard library only; tested on Linux with Python 3.12. duckdb is needed only for `--sql` and for the DuckDB test. datamap only reads your data. The one file it writes is the page, which it replaces atomically.

## Tests

```sh
python3 tests/test_datamap.py
```

9 tests, about a second. The DuckDB test is skipped if duckdb isn't installed.

## License

MIT

## 中文简介

datamap 给一台机器上的 JSON／JSONL 数据文件生成一页目录：每个文件谁写的、一行是什么、新不新鲜、多大、时间键是什么格式、在 DuckDB 里该怎么读。人写的部分只在种子文件里（一份 markdown 表），量出来的部分每次重新量。盘上有种子没登记的数据文件、或者种子登记了但盘上没有的，页面末尾会点名，`--check` 返回 1，所以这页目录不会悄悄过期。适合当 AI 代理查「这台机器上有哪些数据、怎么查」的唯一入口。
