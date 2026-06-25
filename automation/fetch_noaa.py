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
import os, sys, csv, io, datetime, tempfile, re
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

# coast.noaa.gov is fronted by a CDN (Akamai) that 403s the default python-requests
# user-agent. Present a normal browser UA so probes and downloads are accepted.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 SaintNAV/1.0"),
    "Accept": "*/*",
}

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
        # Probe with a 1-byte ranged GET (more reliable than HEAD through the CDN).
        h = {**HEADERS, "Range": "bytes=0-0"}
        r = requests.get(cand, headers=h, stream=True, timeout=30, allow_redirects=True)
        code = r.status_code
        r.close()
        if code in (200, 206):
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
with requests.get(url, headers=HEADERS, stream=True, timeout=1800) as r:
    r.raise_for_status()
    for chunk in r.iter_content(1 << 20):
        tmp.write(chunk); got += len(chunk)
        if got % (50 << 20) < (1 << 20): print(f"  downloaded {got//(1<<20)} MB...")
tmp.close()
print(f"Downloaded {got//(1<<20)} MB. Decompressing + filtering to East Coast yachts...")

# 3) stream-decompress the Zstandard CSV and filter
# read_across_frames=True is REQUIRED: NOAA's daily .csv.zst can be multi-frame, and
# the default reader stops after the first frame (silently yielding almost no rows).
out = os.path.join(INC, f"AIS_EC_{found_date.year}_{found_date.month:02d}_{found_date.day:02d}.csv")
kept = total = 0
header_seen = None
dctx = zstd.ZstdDecompressor()
with open(tmp.name, "rb") as fh, \
     dctx.stream_reader(fh, read_across_frames=True) as reader, \
     open(out, "w", newline="") as o:
    text = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
    rd = csv.DictReader(text)
    header_seen = rd.fieldnames or []
    # Resolve the columns we filter on case-insensitively, with known aliases, so a
    # capitalization change in the feed can't silently zero out the result.
    # Resolve headers by NORMALIZING away case, spaces, underscores and punctuation, so
    # "BaseDateTime" / "base_date_time" / "Base Date Time" / "BASEDATETIME" all match.
    # BUGFIX 2026-06-22: the writer used canonical KEEP names directly (row.get(k)); a
    # recased NOAA feed made every written field blank -> 1.28M empty rows.
    # BUGFIX 2026-06-24: a case-only resolver still left 5 multi-word columns
    # (BaseDateTime, VesselName, CallSign, VesselType, TransceiverClass) unmatched and
    # blank, dropping all timestamps. Normalizing separators matches them regardless of
    # NOAA's naming style (camelCase / snake_case / spaced).
    def _norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())
    lut = {_norm(c): c for c in header_seen}
    # Aliases for columns NOAA may name with genuinely different words.
    ALIASES = {
        "LAT": ("Latitude",), "LON": ("Longitude",),
        "VesselType": ("VesselTypeCode", "ShipType"), "Length": ("LOA",),
        "BaseDateTime": ("BaseDateTimeUTC", "Timestamp", "DateTime"),
        "VesselName": ("Name", "ShipName"), "CallSign": ("Callsign",),
    }
    def col(*names):
        for n in names:
            if _norm(n) in lut: return lut[_norm(n)]
        return names[0]
    # Resolve EVERY output column to the source file's ACTUAL header (separator/case/alias-robust).
    SRC = {k: col(k, *ALIASES.get(k, ())) for k in KEEP}
    C_LAT, C_LON, C_VT, C_LEN = SRC["LAT"], SRC["LON"], SRC["VesselType"], SRC["Length"]
    print("  detected source columns:", header_seen)
    print("  resolved mapping:", {k: SRC[k] for k in KEEP})
    unresolved = [k for k in KEEP if SRC[k] not in header_seen]
    if unresolved: print("  WARNING unresolved output columns (will be blank):", unresolved)
    wr = csv.DictWriter(o, fieldnames=KEEP); wr.writeheader()
    samples = []
    nonblank = 0
    for row in rd:
        total += 1
        if len(samples) < 3:
            samples.append(dict(row))
        lat, lon = fnum(row.get(C_LAT)), fnum(row.get(C_LON))
        if lat is None or lon is None: continue
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX): continue
        vt = int(fnum(row.get(C_VT)) or 0); loa = fnum(row.get(C_LEN))
        if not (vt in YACHT_TYPES or (loa and loa >= MIN_LOA)): continue
        vals = {k: row.get(SRC[k], "") for k in KEEP}
        wr.writerow(vals); kept += 1
        if (vals.get("MMSI") or "").strip(): nonblank += 1
os.unlink(tmp.name)
print(f"Scanned {total:,} rows -> kept {kept:,} East Coast yacht fixes "
      f"({nonblank:,} with a non-blank MMSI)")
if kept == 0 or nonblank == 0:
    # Self-diagnostic: a zero-row OR all-blank result writes a committed file we can
    # inspect remotely, so we never have to dig through Action logs to learn why.
    # (all-blank == the recased-header bug that produced 1.28M empty rows.)
    print(f"WARNING: kept {kept:,} rows but {nonblank:,} had real data — writing diagnostic.")
    print("  Detected columns:", header_seen)
    print(f"  Filter used -> LAT='{C_LAT}' LON='{C_LON}' VesselType='{C_VT}' Length='{C_LEN}'")
    print(f"  Scanned {total:,} total rows (if this is 0, decompression returned no data).")
    diag = os.path.join(INC, "AIS_EC_DIAGNOSTIC.csv")
    with open(diag, "w", newline="") as df:
        df.write("# fetch_noaa.py diagnostic — kept 0 rows\n")
        df.write(f"# source_url,{url}\n")
        df.write(f"# scanned_rows,{total}\n")
        df.write(f"# detected_columns,{'|'.join(header_seen)}\n")
        df.write(f"# resolved_filter_cols,LAT={C_LAT};LON={C_LON};VesselType={C_VT};Length={C_LEN}\n")
        df.write("# --- up to 3 raw sample rows below ---\n")
        if samples:
            w = csv.DictWriter(df, fieldnames=list(samples[0].keys()))
            w.writeheader()
            for s in samples: w.writerow(s)
    print("  Wrote diagnostic:", diag)
    # Remove the blank/garbage output so it can NEVER be committed or ingested as "real".
    # The committed diagnostic (AIS_EC_DIAGNOSTIC.csv) still surfaces the failure remotely.
    try:
        if os.path.exists(out):
            os.unlink(out); print("  Removed blank output so it is not presented as real:", out)
    except Exception as e:
        print("  WARN could not remove blank output:", e)
    sys.exit("fetch_noaa.py: no real rows extracted — see diagnostic above.")
print(f"Wrote {out}  ({round(os.path.getsize(out)/1e6,2)} MB)")
print("Done. Tell Claude 'process the new data', or wait for the Monday refresh.")
