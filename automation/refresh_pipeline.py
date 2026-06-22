#!/usr/bin/env python3
"""Weekly refresh job (run by the Cowork scheduled task).

Processes any REAL NOAA AIS files in automation/incoming/ (files named like
AIS_YYYY_MM_DD.zip / .csv). Builds in a /tmp scratch dir (the synced folder
disallows in-place sqlite + deletes), then copies the refreshed database,
tracker_data.json and tracker HTML back. Files whose names contain 'sample' or
'test' are ignored so synthetic data is never presented as fresh.

Last line prints  ARTIFACT_HTML=<path>  (or REFRESH_STATUS=no_data) so the agent
running the schedule knows whether to push an update_artifact.
"""
import os, sys, glob, re, shutil, subprocess, sqlite3, datetime, tempfile
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INC=os.environ.get("FLEETVIEW_INCOMING", os.path.join(ROOT,"automation","incoming"))
ENV=dict(os.environ, PYTHONPYCACHEPREFIX="/tmp/pyc")
def run(a): subprocess.run([sys.executable]+a, check=True, env=ENV)
def real(f): return not re.search(r"(?i)(sample|test)", os.path.basename(f))

files=[f for f in sorted(glob.glob(os.path.join(INC,"*.csv"))+glob.glob(os.path.join(INC,"*.zip"))) if real(f)]
if not files:
    print("no new real AIS files in automation/incoming/ — nothing to refresh")
    print("REFRESH_STATUS=no_data"); sys.exit(0)

work=tempfile.mkdtemp(prefix="fv_refresh_"); wdb=os.path.join(work,"yacht_intel.db")
con=sqlite3.connect(wdb)
for fn in ("schema.sql","schema_v2_features.sql","schema_v3_scheduling.sql","seed_eastcoast_marinas.sql"):
    con.executescript(open(os.path.join(ROOT,"database",fn)).read())
con.commit(); con.close()
print(f"rebuilt scratch DB; ingesting {len(files)} real file(s): {[os.path.basename(f) for f in files]}")
for fp in files:
    run([os.path.join(ROOT,"ingestion","noaa_ingest.py"),"--infile",fp,"--all","--db",wdb])
run([os.path.join(ROOT,"ingestion","build_features.py"),"--db",wdb,"--asof",datetime.date.today().isoformat()])
wjson=os.path.join(work,"tracker_data.json"); whtml=os.path.join(work,"tracker_latest.html")
run([os.path.join(ROOT,"tools","export_artifact_data.py"),wdb,wjson])
run([os.path.join(ROOT,"tools","build_tracker.py"),wjson,whtml])

# copy outputs back to the synced folder (overwrite-in-place is allowed; delete is not)
def put(src,dst):
    try: shutil.copyfile(src,dst); print("updated",os.path.relpath(dst,ROOT))
    except Exception as e: print("WARN could not update",dst,e)
put(wjson, os.path.join(ROOT,"database","tracker_data.json"))
put(whtml, os.path.join(ROOT,"automation","tracker_latest.html"))
put(whtml, os.path.join(ROOT,"us-megayacht-arrival-tracker.html"))
put(wdb,   os.path.join(ROOT,"database","yacht_intel.db"))
print("REFRESH_STATUS=updated")
print("ARTIFACT_HTML="+os.path.join(ROOT,"automation","tracker_latest.html"))
