#!/usr/bin/env python3
"""East Coast NOAA AIS downloader.

Finds the most recent NOAA Marine Cadastre national daily AIS file, streams it to
disk, keeps only U.S. EAST COAST yacht rows (Atlantic bbox + pleasure/sailing types
or LOA>=24m), and writes a compact CSV to automation/incoming/ for the tracker.

Updated 2026-06-22: NOAA changed the daily file format. Files are now named
`ais-YYYY-MM-DD.csv.zst` (lowercase, hyphenated, Zstandard-compressed) instead of
the old `AIS_YYYY_MM_DD.zip`. We also widen the lookback so we bridge to whatever
the latest published day actually is (NOAA publishes on a multi-week-to-months lag).

  pip install requests zstandard
  python fetch_noaa.py
"""
import os, sys, csv, io, datetime, tempfile
try:
    import requests
except ImportError:
    sys.exit("Run:  pip install requests zstandard")
try:
    import zstandard as zstd
except ImportError:
    sys.exit("Run:  pip install zstandard   (NOAA files are now .csv.zst)")

LAT_MIN, LAT_MAX = 24.0, 45.6          # East Coast (Atlantic): S. Florida -> Maine
LON_MIN, LON_MAX = -82.0, -66.5
YACHT_TYPES = {36, 37}                  # sailing, pleasure craft
MIN_LOA = 24.0
KEEP = ["MMSI","BaseDateTime","LAT","LON","SOG","COG","Heading","VesselName","IMO",
        "CallSign","VesselType","Status","Length","Width","Draft","Cargo","TransceiverClass"]
INC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "incoming")
os.makedirs(INC, exist_ok=True)
BASE = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler"

# How many days back to scan. Start a little behind "today" (publishing lag) and
# search far enough back to cross a year boundary if the current year isn't up yet.
START_LAG_DAYS = 10
MAX_LOOKBACK_DAYS = 400

def fnum(v):
    try: return float(v)
    except: return None

def url_for(d):
    # New NOAA format: .../<year>/ais-YYYY-MM-DD.csv.zst
    return f"{BASE}/{d.year}/ais-{d.year}-{d.month:02d}-{d.day:02d}.csv.zst"

# 1) find the most recent available daily file (NOAA publishes on a lag)
d = datetime.date.today() - datetime.timedelta(days=START_LAG_DAYS)
url = None
found_date = None
print("Looking for the latest available NOAA daily file...")
for _ in range(MAX_LOOKBACK_DAYS):
    cand = url_for(d)
    try:
        r = requests.head(cand, timeout=30, allow_redirects=True)
        if r.status_code == 200:
            url = cand; found_date = d; break
    except Exception:
        pass
    d -= datetime.timedelta(days=1)
if not url:
    sys.exit("Could not find a NOAA daily file via the bulk URL in the last "
             f"{MAX_LOOKBACK_DAYS} days. As a fallback, order an East Coast extract at\n"
             "https://marinecadastre.gov/accessais/ and place the CSV/zst in this\n"
             "'incoming' folder.")
print("Found:", url)

# 2) stream the .zst to a temp file (avoids loading hundreds of MB into memory)
tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv.zst")
got = 0
with requests.get(url, stream=True, timeout=1800) as r:
    r.raise_for_status()
    for chunk in r.iter_content(1 << 20):
        tmp.write(chunk); got += len(chunk)
        if got % (50 << 20) < (1 << 20): print(f"  downloaded {got//(1<<20)} MB...")
tmp.close()
print(f"Downloaded {got//(1<<20)} MB. Decompressing + filtering to East Coast yachts...")

# 3) stream-decompress the Zstandard CSV and filter
out = os.path.join(INC, f"AIS_EC_{found_date.year}_{found_date.month:02d}_{found_date.day:02d}.csv")
kept = total = 0
dctx = zstd.ZstdDecompressor()
with open(tmp.name, "rb") as fh, dctx.stream_reader(fh) as reader, \
     open(out, "w", newline="") as o:
    text = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
    rd = csv.DictReader(text)
    wr = csv.DictWriter(o, fieldnames=KEEP); wr.writeheader()
    for row in rd:
        total += 1
        lat, lon = fnum(row.get("LAT")), fnum(row.get("LON"))
        if lat is None or lon is None: continue
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX): continue
        vt = int(fnum(row.get("VesselType")) or 0); loa = fnum(row.get("Length"))
        if not (vt in YACHT_TYPES or (loa and loa >= MIN_LOA)): continue
        wr.writerow({k: row.get(k, "") for k in KEEP}); kept += 1
os.unlink(tmp.name)
print(f"Scanned {total:,} rows -> kept {kept:,} East Coast yacht fixes")
print(f"Wrote {out}  ({round(os.path.getsize(out)/1e6,2)} MB)")
print("Done. Tell Claude 'process the new data', or wait for the Monday refresh.")
