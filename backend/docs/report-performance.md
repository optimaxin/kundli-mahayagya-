# Excel report performance

How the Excel reports (`POST /reports/exports`, FINAL and DAILY) are generated, what made the full
report slow, what was changed, and the measured results. All numbers below come from runs of
`scripts/benchmark_report.py` or from the server's own `report_generated` log lines. Nothing here is
an estimate.

## Root cause

On Render Free (0.1 CPU, 512 MB), production `report_jobs` showed the FINAL report taking
**50.7 to 54.6 s** to generate, with only 0.5 s of queueing, and almost no registrations in the
database. The browser kept showing "Preparing report…" for the whole time.

The same code in a container capped to `--cpus=0.1 --memory=512m` took 50.69 s with an empty database.
The per-stage breakdown:

| Stage | Seconds | Share |
|---|---|---|
| Kund Allocation sheet: openpyxl `ws.append` (34,416 rows: 2,151 Kunds × 16 sessions) | 41.7 | 82 % |
| Database queries (all sheets) | 5.0 | 10 % |
| Python row building | 2.2 | 4 % |
| `wb.save` | 1.8 | 4 % |
| Peak memory | 94 MB | |

The bottleneck was CPU, not the database or memory. openpyxl builds every cell as a Python object
and serialises it through its XML layer. That costs about 1.2 ms of CPU per row at 0.1 CPU. The Kund
Allocation sheet always has 34,416 rows, even when nobody has registered, so even an empty report
took 50 seconds. The cost also grows with registrations: 800 families took 77 s, 8,000 families
took 266 s, and a sold-out event (34,416 families) took 108 s even on an unthrottled machine.

The daily report covers 2 of the 16 sessions, so it has one eighth of the rows. That is why it
appeared to work.

A second, smaller cause turned up after the writer was fixed. Report queries stream through a
server-side cursor (`yield_per`). PostgreSQL's default `cursor_tuple_fraction = 0.1` then picks
"fast first rows" nested-loop plans. For the No Shows query at event scale, that meant 5.44 s
instead of 0.80 s (measured in isolation). The plan itself is fine: an `EXPLAIN ANALYZE` of the
same query runs in 0.43 s, using hash joins and the existing indexes.

## Changes

* **`app/services/xlsx_stream.py`**: a small streaming writer for `.xlsx` files, used instead of
  openpyxl. Each row becomes one XML string, written in chunks into a zip entry (deflate level 1).
  The output has the same 7 sheets, headers, column widths, frozen header row, header style,
  date/datetime formats, IST conversion and formula-injection guard as before. Comparing the old
  and new files cell by cell on the small and medium datasets (FINAL and DAILY) found no
  differences. LibreOffice opens the files.
* **`app/services/reporting_service.py`**:
  * Queries select only the columns they need instead of ORM entities.
  * Family Bookings gets the sessions of each booking from one `string_agg` subquery.
  * Kund Allocation is one query that includes its family list.
  * The dashboard counts come from one query.
  * Large results stream with `yield_per=10_000`.
  * `SET LOCAL cursor_tuple_fraction = 1.0` is set for the report transaction. It is
    transaction-scoped, so it is safe behind the Supabase transaction pooler.
  * The workbook is written to `<job>.tmp` and renamed when complete. A failed run deletes the temp
    file.
  * Report files older than 1 hour are deleted whenever a new report is requested.
  * A missing file returns `410 REPORT_EXPIRED`.
  * A job still `PENDING` or `RUNNING` 15 minutes after it was created is reported as
    `FAILED / ABANDONED`.
* **Instrumentation.** Each report produces one `report_generated` (or `report_failed`) log line
  with request id, job id, type, total and queue seconds, seconds per stage
  (`<sheet>.db`, `<sheet>.write`, `<sheet>.total`), rows per sheet and file size.
  `report_download_sent` logs the bytes sent and how long sending took. The same timings are stored
  in the job's `summary.timings`. No names, phone numbers, emails, tokens or credentials are logged.
  Tests assert this.
* **Indexes.** None were added. The existing indexes cover the joins (`booking_sessions(session_id,
  status)`, `(session_id, kund_id)`, `(booking_id, session_id)`, `family_members(booking_id,
  member_number)`, `attendance_checkins(booking_session_id, member_id)`). The planner uses them, and
  server-side execution time is small next to row transfer and writing.
* **Frontend (`src/lib/db.js`, `src/pages/Admin.jsx`)**:
  * One report runs at a time. Clicking again joins the request already running, so no duplicate
    job is created.
  * Polling starts fast and backs off (1 s, then 2 s, then 4 s), and stops after 10 minutes rather
    than after a fixed number of polls.
  * Up to 3 failed polls in a row are tolerated.
  * The download is checked before it is saved: it must be an `.xlsx` content type with the full
    length.
  * The button shows elapsed seconds, and a Hindi "keep this page open" hint after 15 s.
  * Every failure has a Hindi message (`REPORT_FAILED`, `REPORT_TIMEOUT`, `REPORT_INVALID`,
    `REPORT_BUSY`, network). The button always returns to normal, and no success message appears
    after a failure.

## Results

Test datasets are synthetic, seeded only into local scratch databases. The script refuses
non-local hosts.

| Dataset | Families | Members | Session reservations |
|---|---|---|---|
| empty | 0 | 0 | 0 |
| small | 800 | 3,200 | 1,600 |
| medium | 8,000 | 32,000 | 16,000 |
| event scale (sold out) | 34,416 | 137,664 | 68,832 |

For the FINAL report, "Session Attendance" has one row per member per session: 275,328 rows at
event scale.

### Render Free emulation (`--cpus=0.1 --memory=512m`)

| Report | Dataset | Before | After | Peak memory after |
|---|---|---|---|---|
| FINAL | empty | 50.69 s | 4.7 – 6.2 s | ~90 MB |
| DAILY | empty | – | 0.8 – 2.0 s | ~90 MB |
| FINAL | small | 76.97 s | – | |
| FINAL | medium | 266.06 s | **33.70 s** | 98 MB |
| DAILY | medium | – | 7.28 s | 91 MB |
| FINAL | event scale | not run | 124.19 s (29.3 MB file) | 111 MB |
| DAILY | event scale | – | 27.90 s (4.5 MB file) | 98 MB |

"–" means that combination was not measured. After the change, writing is 75–80 % of the time and
the database is about 18 %.

### Unthrottled (development machine, local PostgreSQL)

| Report | Dataset | Before | After |
|---|---|---|---|
| FINAL | small | 7.16 s | 0.92 s |
| FINAL | medium | 27.05 s | 3.53 s (2.73 s generation through the real HTTP API) |
| DAILY | medium | 4.45 s | 0.70 s |
| FINAL | event scale | 108.15 s | 12.55 s (17.38 s before the cursor fix) |
| DAILY | event scale | – | 2.22 s |

Downloading the 6.5 MB medium file from a local server took 0.04 s server-side
(`report_download_sent.send_s`). Real download time depends on the user's connection.

## Remaining limitations

* **0.1 CPU is the ceiling.** On Render Free, the engineering targets (DAILY < 5 s, FINAL < 10 s)
  are met while registrations are few. They are not met at medium volume or above: FINAL took 34 s
  for 8,000 families and 124 s sold out. Almost all of that time is writing XML in Python. More CPU
  scales it almost linearly: the same event-scale FINAL took 12.6 s unthrottled. A paid instance
  (0.5 to 1 CPU) is the practical fix if large reports must be fast during the event.
* Report generation runs in the web process (FastAPI `BackgroundTasks`) and competes with
  registration and check-in traffic for the same 0.1 CPU. Avoid generating FINAL reports during
  registration peaks.
* Report files live on Render's ephemeral disk. They disappear on restart, deploy or sleep (the
  download then returns `410 REPORT_EXPIRED`) and are deleted after 1 hour. A job interrupted by a
  restart shows as `FAILED / ABANDONED` after 15 minutes. Exports are not backups.
* A free instance that has gone to sleep needs about a minute to wake up before the first request
  succeeds. The frontend shows a Hindi network message suggesting a retry.

## Reproducing

```bash
# local scratch DB only; refuses production hosts
DATABASE_URL=postgresql+psycopg://mahayagya:mahayagya@localhost:5432/bench_medium \
  python -m scripts.benchmark_report --scenario medium --kind full --runs 2 --after-event
# reuse already-seeded data (read-only):  --scenario none
# Render Free emulation: run the same command in a container with --cpus=0.1 --memory=512m
```
