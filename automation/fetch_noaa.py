#!/usr/bin/env python3
"""East Coast NOAA AIS downloader — RUN ON A PC WITH INTERNET (double-click
pull_real_data.bat, or `python fetch_noaa.py`). It does NOT run inside Claude.

Finds a recent NOAA Marine Cadastre national daily AIS zip, streams it to disk,
keeps only U.S. EAST COAST yacht rows (Atlantic bbox + pleasure/sailing types or
LOA>=24m), and writes a compact CSV to automation/incoming/ for the tracker.

  pip install requests
  python fetch_noaa.py
"""
import os, sys, csv, io, zipfile, datetime, tempfile
try: import requests
except ImportError: sys.exit("Run:  pip install requests")

LAT_MIN, LAT_MAX = 24.0, 45.6          # East Coast (Atlantic): S. Florida -> Maine
LON_MIN, LON_MAX = -82.0, -66.5
YACHT_TYPES = {36, 37}                  # sailing, pleasure craft
MIN_LOA = 24.0
KEEP = ["MMSI","BaseDateTime","LAT","LON","SOG","COG","Heading","VesselName","IMO",
        "CallSign","VesselType","Status","Length","Width","Draft","Cargo","TransceiverClass"]
INC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "incoming")
os.makedirs(INC, exist_ok=True)
BASE = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler"

def fnum(v):
    try: return float(v)
    except: return None

# 1) find the most recent available daily file (NOAA publishes on a lag)
d = datetime.date.today() - datetime.timedelta(days=18)
url = None
print("Looking for the latest available NOAA daily file...")
for _ in range(60):
    cand = f"{BASE}/{d.year}/AIS_{d.year}_{d.month:02d}_{d.day:02d}.zip"
    try:
        if requests.head(cand, timeout=30).status_code == 200:
            url = cand; break
    except Exception:
        pass
    d -= datetime.timedelta(days=1)
if not url:
    sys.exit("Could not find a NOAA daily file via the bulk URL. As a fallback, order an\n"
             "East Coast extract at https://marinecadastre.gov/accessais/ and place the\n"
             "CSV/zip in this 'incoming' folder.")
print("Found:", url)

# 2) stream the zip to a temp file (avoids loading hundreds of MB into memory)
tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
got = 0
with requests.get(url, stream=True, timeout=1200) as r:
    r.raise_for_status()
    for chunk in r.iter_content(1 << 20):
        tmp.write(chunk); got += len(chunk)
        if got % (50 << 20) < (1 << 20): print(f"  downloaded {got//(1<<20)} MB...")
tmp.close()
print(f"Downloaded {got//(1<<20)} MB. Filtering to East Coast yachts...")

# 3) filter
out = os.path.join(INC, f"AIS_EC_{d.year}_{d.month:02d}_{d.day:02d}.csv")
kept = total = 0
with zipfile.ZipFile(tmp.name) as z:
    name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
    with z.open(name) as f, open(out, "w", newline="") as o:
        rd = csv.DictReader(io.TextIOWrapper(f, "utf-8"))
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
