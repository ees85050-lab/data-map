# Data seed for the homelab box

The human half of `datamap.md`: one row per data file. `datamap --write` measures the rest and writes the page.
When you add, move or retire a data file, change its row here; `datamap --check` names anything that drifted.

## Ground rules

- Every JSONL file here is one JSON object per line, appended. Nothing rewrites old rows unless its Gotchas say so.
- Each data file's Time line says how to read its time key in DuckDB. Don't assume UTC: the writers disagree.
- Query the files where they are, with DuckDB. Don't copy them into a database.

## Scan

| Dir | Suffixes | Depth |
|---|---|---|
| data | jsonl, json | 2 |

## Data

| Group | Name | Path | Writer | Row | Cadence | Fresh | Time key | Gotchas |
|---|---|---|---|---|---|---|---|---|
| Sensors | Weather station | data/weather/readings.jsonl | weather-poll (cron) | one reading from the backyard station: temp_c, humidity | every 10 min | 30m | ts | temp_c is -999 when the sensor drops out; filter it |
| Sensors | Office plug power | data/power/*.jsonl | plug-logger (systemd service) | one reading: watts, plug | hourly; a new file at each local midnight | 2h | t | watts is the reading at that moment, not an hourly average |
| Apps | To-do export | data/todo/export.json | todo-export (cron) | the whole file: meta, and items[] with list, title, done | nightly, 03:20 UTC | 2d | meta.exported_at | replaced every night, so there's no history; done items drop out after 30 days |
| Apps | Bookmark clicks | data/bookmarks/clicks.jsonl | the browser extension | one click: url | whenever a bookmark is clicked | - | ts_ms | private windows aren't logged |
| Retired | Old energy feed | data/legacy/feed.jsonl | the old utility scraper (removed) | one hourly kWh total | - | retired | when | times are the scraper's local time (Europe/Berlin); superseded by the office plug |

## Ignored

| Path | Why |
|---|---|
| data/todo/dedupe-ids.json | the exporter's own bookkeeping, not data |

## Queries

Every block runs with `datamap --sql`, from this folder.

```sql
-- Hourly mean temperature, without sensor dropouts
SELECT date_trunc('hour', to_timestamp(ts)) AS hour, round(avg(temp_c), 1) AS temp_c
FROM read_json_auto('data/weather/readings.jsonl')
WHERE temp_c > -100
GROUP BY hour ORDER BY hour;
```

```sql
-- The office plug's five highest readings, in UTC
SELECT timezone('UTC', t) AS at_utc, watts
FROM read_json_auto('data/power/*.jsonl')
ORDER BY watts DESC LIMIT 5;
```

```sql
-- Open to-dos per list
SELECT item.list, count(*) AS open
FROM (SELECT unnest(items) AS item FROM read_json_auto('data/todo/export.json'))
WHERE NOT item.done
GROUP BY ALL ORDER BY open DESC;
```

```sql
-- Most-clicked bookmarks, with the last click
SELECT url, count(*) AS clicks, max(to_timestamp(ts_ms / 1000)) AS last_click
FROM read_json_auto('data/bookmarks/clicks.jsonl')
GROUP BY url ORDER BY clicks DESC;
```
