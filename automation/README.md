# Automating the refresh (no daily work from you)

The Cowork sandbox can't reach the internet, so data can't be pulled from *inside*
Claude. The fix splits the job in two:

```
[ downloader, runs where there IS internet ]        [ Cowork, weekly ]
 fetch_noaa.py -> automation/incoming/AIS_EC_*.csv  ->  refresh_pipeline.py -> tracker
 (your PC / cloud / free GitHub Action)               (the scheduled task = me)
```

### Half 1 — the downloader (set up ONCE)
`fetch_noaa.py` downloads the national NOAA daily file, filters it to the **U.S. East Coast** (Atlantic bbox lat 24-45.6, lon -82 to -66.5) and yacht types, and writes a **small** CSV to `automation/incoming/`.
Run it anywhere with internet:
- **Free + hands-off:** put `github-action-weekly.yml` at `.github/workflows/` in a
  GitHub repo whose `automation/incoming/` syncs to this folder. It runs every
  Monday and commits the new file. Zero ongoing effort.
- **Or** a cron line on any always-on machine: `0 11 * * 1 python fetch_noaa.py`.

Prefer NOAA AccessAIS? Order an East Coast box there and drop the CSV/zip in
`automation/incoming/` instead — the pipeline tags it to the right region either way.

### Half 2 — the weekly Cowork task (already set up)
The scheduled task **fleetview-weekly-refresh** runs every Monday 8am. It executes
`refresh_pipeline.py`, which rebuilds the database from any real files in
`automation/incoming/`, recomputes predictions, and updates the live artifact.
Files named *sample*/*test* are ignored, so synthetic data is never shown as fresh.
If no new files arrived, it reports "no new data" and changes nothing.

### Paid alternative (no downloader needed)
Authenticate the **Kpler** connector (or wrap Datalastic as a custom MCP). Then the
weekly task — or the artifact itself — pulls live with no external machine. Cost is
the tradeoff (Kpler enterprise; Datalastic ~$200/mo).
