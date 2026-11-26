#!/usr/bin/env python3
"""RichBot forecast verification.

Checks what the RichBot forecast page (richietaylor.net/forecast/) predicted against
what actually happened at the nearest airports with weather reports (METARs):
Exeter (EGTE) and Yeovilton (EGDY). Dunkeswell has no METAR of its own.

Run by .github/workflows/forecast-verify.yml every 3 hours. Each run:
  1. Snapshot  - at about 06:00 and 18:00 UTC, opens the live page in a headless
                 browser and saves window.richbotSnapshot() (exactly what staff see).
  2. Observe   - downloads the last 30 hours of METARs for both airports.
  3. Pair      - matches every forecast hour that is now in the past with the
                 nearest METAR (within 30 min), per airport.
  4. Summarise - writes summary.json, read by richietaylor.net/forecast/accuracy/
                 and by the weekly review agent.

All data lives on the `forecast-data` branch (checked out into --data).
"""
import argparse
import csv
import json
import math
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

PAGE_URL = "https://richietaylor.net/forecast/"
STATIONS = {"EGTE": "Exeter", "EGDY": "Yeovilton"}
AIRFIELD_ELEV_FT = 833          # Dunkeswell, 254 m
LOCAL_TZ = ZoneInfo("Europe/London")
SNAPSHOT_SLOTS_UTC = (6, 18)    # morning-of and evening-before forecasts
SLOT_GRACE_HOURS = 3            # GitHub's scheduler can run late
KEEP_SNAPSHOT_DAYS = 10         # a 7-day forecast is fully verified after 8 days
MATCH_WINDOW_MIN = 30
LAT, LON = 50.880, -3.230

# Same operating rules as assessHour() in forecast/index.html
OPS_WIND_MPH = 23
LOW_BASE_FT = 2000
POOR_VIS_KM = 3
HEAVY_CLOUD_PCT = 90
RAIN_PROB_PCT = 50

COVER_PCT = {"SKC": 0, "CLR": 0, "NSC": 0, "NCD": 0, "CAVOK": 0,
             "FEW": 19, "SCT": 44, "BKN": 75, "OVC": 100, "OVX": 100, "VV": 100}
CEILING_COVERS = {"BKN", "OVC", "OVX", "VV"}
BASE_COVERS = {"SCT", "BKN", "OVC", "OVX", "VV"}   # 3+ oktas: what a forecast "cloudbase" means
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "meteofrance_seamless"]
LEAD_BUCKETS = [("same_day", 0, 14), ("next_day", 14, 38), ("day_2", 38, 62), ("day_3_plus", 62, 10_000)]

PAIR_FIELDS = [
    "issued", "revision", "lead_h", "valid", "station",
    "fc_ws", "ob_ws", "fc_wg", "ob_wg", "fc_dir", "ob_dir",
    "fc_base_state", "fc_base_ft", "fc_base_est", "ob_base_ft", "ob_ceiling_ft", "ob_lowest_ft",
    "fc_cloud", "ob_cloud", "fc_rain_prob", "ob_rain", "fc_vis", "ob_vis", "fc_fog", "ob_fog",
    "fc_score", "fc_issues", "ob_issues", "fc_jumpable", "ob_jumpable", "ob_raw",
] + [f"m_{m}_{f}" for m in MODELS for f in ("ws", "wg")]
DAY_FIELDS = ["issued", "revision", "date", "lead_days", "station", "fc_likelihood", "ob_pct", "ob_hours"]


# ----------------------------------------------------------------------------- helpers
def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "richbot-forecast-verify"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")


def read_csv(path):
    if not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def local_to_utc(t):
    """'2026-11-25T11:00' (Europe/London) -> aware UTC datetime."""
    return datetime.fromisoformat(t).replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)


def kt_to_mph(kt):
    return None if kt is None else round(kt * 1.15078)


def angle_diff(a, b):
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


# ----------------------------------------------------------------------------- 1. snapshot
def snapshot_slot(now, force):
    if force:
        return now.hour
    for slot in SNAPSHOT_SLOTS_UTC:
        if slot <= now.hour < slot + SLOT_GRACE_HOURS:
            return slot
    return None


def take_snapshot(data_dir, now, force=False):
    slot = snapshot_slot(now, force)
    if slot is None:
        print("snapshot: not a snapshot slot, skipping")
        return
    out = data_dir / "snapshots" / f"{now:%Y-%m-%d}T{slot:02d}Z.json"
    if out.exists():
        print(f"snapshot: {out.name} already taken")
        return
    from playwright.sync_api import sync_playwright  # only needed for snapshots
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{PAGE_URL}?verify={int(now.timestamp())}", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_function("window.richbotReady === true", timeout=120_000)
        snap = page.evaluate("window.richbotSnapshot()")
        browser.close()
    write_json(out, snap)
    print(f"snapshot: saved {out.name} ({snap['revision']}, {len(snap['hours'])} hours)")


# ----------------------------------------------------------------------------- 2. observe
def parse_metar(m):
    station = m["icaoId"]
    raw = m.get("rawOb", "")
    t = datetime.fromisoformat(m["reportTime"].replace("Z", "+00:00"))
    elev_ft = (m.get("elev") or 0) * 3.28084
    cavok = "CAVOK" in raw

    wdir = m.get("wdir")
    wdir = wdir if isinstance(wdir, (int, float)) else None      # 'VRB' -> None
    ws = kt_to_mph(m.get("wspd"))
    wg = kt_to_mph(m.get("wgst")) if m.get("wgst") else None     # only reported when gusty

    vis = m.get("visib")
    if cavok:
        vis_km = 10.0
    elif isinstance(vis, str):
        vis_km = min(10.0, float(vis.rstrip("+")) * 1.609)
    elif isinstance(vis, (int, float)):
        vis_km = min(10.0, vis * 1.609)
    else:
        vis_km = None

    ceiling = lowest = base_sct = None
    cloud_pct = 0
    for layer in ([] if cavok else (m.get("clouds") or [])):
        cover, base = layer.get("cover"), layer.get("base")
        cloud_pct = max(cloud_pct, COVER_PCT.get(cover, 0))
        if base is None:
            continue
        agl = max(0, round(base + elev_ft - AIRFIELD_ELEV_FT))   # height above Dunkeswell
        lowest = agl if lowest is None else min(lowest, agl)
        if cover in BASE_COVERS:
            base_sct = agl if base_sct is None else min(base_sct, agl)
        if cover in CEILING_COVERS:
            ceiling = agl if ceiling is None else min(ceiling, agl)

    # present weather, ignoring "in the vicinity" (VC) and "recent" (RE) groups
    wx = [tok for tok in (m.get("wxString") or "").split() if not tok.startswith(("VC", "RE"))]
    wx_s = " ".join(wx)
    rain = bool(re.search(r"RA|DZ|SN|GR|GS|PL|TS|SH", wx_s))
    fog = ("FG" in wx_s) or (vis_km is not None and vis_km < 1) or ("BR" in wx_s and vis_km is not None and vis_km < 5)

    issues = []
    if (ws or 0) > OPS_WIND_MPH or (wg or 0) > OPS_WIND_MPH:
        issues.append("wind")
    if rain:
        issues.append("rain")
    if fog:
        issues.append("fog")
    elif vis_km is not None and vis_km < POOR_VIS_KM:
        issues.append("vis")
    if ceiling is not None and ceiling < LOW_BASE_FT:
        issues.append("lowbase")
    if cloud_pct >= HEAVY_CLOUD_PCT:
        issues.append("cloud")

    return {
        "station": station, "time": t.strftime("%Y-%m-%dT%H:%MZ"),
        "ws": ws, "wg": wg, "dir": wdir, "vis": None if vis_km is None else round(vis_km, 1),
        "base": base_sct, "ceiling": ceiling, "lowest": lowest, "cloud": cloud_pct,
        "rain": rain, "fog": fog, "issues": issues, "raw": raw,
    }


def collect_observations(data_dir):
    url = f"https://aviationweather.gov/api/data/metar?ids={','.join(STATIONS)}&hours=30&format=json"
    added = 0
    by_day = {}
    for m in http_json(url):
        try:
            ob = parse_metar(m)
        except Exception as e:  # one bad report must not stop the run
            print(f"observe: skipped report ({e}): {m.get('rawOb')}")
            continue
        by_day.setdefault(ob["time"][:10], []).append(ob)
    for day, obs in by_day.items():
        path = data_dir / "observations" / f"{day}.json"
        store = read_json(path, {})
        for ob in obs:
            st = store.setdefault(ob["station"], {})
            if ob["time"] not in st:
                added += 1
            st[ob["time"]] = ob
        write_json(path, store)
    print(f"observe: {added} new reports")


def load_observations(data_dir):
    obs = {s: [] for s in STATIONS}
    for path in sorted((data_dir / "observations").glob("*.json")):
        for station, reports in read_json(path, {}).items():
            for ob in reports.values():
                ob["_t"] = datetime.strptime(ob["time"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
                obs.setdefault(station, []).append(ob)
    return obs


def nearest(reports, when):
    best = None
    for ob in reports:
        gap = abs((ob["_t"] - when).total_seconds()) / 60
        if gap <= MATCH_WINDOW_MIN and (best is None or gap < best[0]):
            best = (gap, ob)
    return best[1] if best else None


# ----------------------------------------------------------------------------- 3. pair
def fetch_sunset_hours():
    """Local sunset hour per date for the last two weeks (the page scores 08:00 to the sunset hour)."""
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
           f"&daily=sunset&timezone=Europe/London&past_days=14&forecast_days=1")
    d = http_json(url)["daily"]
    return {date: int(s[11:13]) for date, s in zip(d["time"], d["sunset"])}


def build_pairs(data_dir, now):
    obs = load_observations(data_dir)
    sunset = fetch_sunset_hours()
    pairs_dir = data_dir / "pairs"
    existing = {}
    for path in pairs_dir.glob("*.csv"):
        for row in read_csv(path):
            existing[(row["issued"], row["valid"], row["station"])] = row
    days_existing = {(r["issued"], r["date"], r["station"]): r for r in read_csv(data_dir / "days.csv")}

    new = 0
    for snap_path in sorted((data_dir / "snapshots").glob("*.json")):
        snap = read_json(snap_path, None)
        if not snap:
            continue
        issued = snap["issued"]
        issued_dt = datetime.fromisoformat(issued.replace("Z", "+00:00"))
        for h in snap["hours"]:
            valid_utc = local_to_utc(h["t"])
            if valid_utc > now - timedelta(minutes=40) or valid_utc < issued_dt:
                continue   # not happened yet, or already past when the forecast was taken
            for station in STATIONS:
                key = (issued, h["t"], station)
                if key in existing:
                    continue
                ob = nearest(obs.get(station, []), valid_utc)
                if not ob:
                    continue
                row = {
                    "issued": issued, "revision": snap["revision"],
                    "lead_h": round((valid_utc - issued_dt).total_seconds() / 3600, 1),
                    "valid": h["t"], "station": station,
                    "fc_ws": h["ws"], "ob_ws": ob["ws"], "fc_wg": h["wg"], "ob_wg": ob["wg"],
                    "fc_dir": h["dir"], "ob_dir": ob["dir"],
                    "fc_base_state": h["baseState"], "fc_base_ft": h["baseFt"], "fc_base_est": int(bool(h["baseEstimated"])),
                    "ob_base_ft": ob.get("base"), "ob_ceiling_ft": ob["ceiling"], "ob_lowest_ft": ob["lowest"],
                    "fc_cloud": h.get("cloud", max(h["low"], h["mid"])), "ob_cloud": ob["cloud"],
                    "fc_rain_prob": h["rain"], "ob_rain": int(ob["rain"]),
                    "fc_vis": h["vis"], "ob_vis": ob["vis"], "fc_fog": int(bool(h["fog"])), "ob_fog": int(ob["fog"]),
                    "fc_score": h["score"], "fc_issues": "/".join(h["issues"]), "ob_issues": "/".join(ob["issues"]),
                    "fc_jumpable": int(h["score"] > 0), "ob_jumpable": int(not ob["issues"]),
                    "ob_raw": ob["raw"],
                }
                for m in MODELS:
                    mv = (h.get("models") or {}).get(m)
                    row[f"m_{m}_ws"] = mv["ws"] if mv else ""
                    row[f"m_{m}_wg"] = mv["wg"] if mv else ""
                existing[key] = row
                new += 1

        # day level: JUMP % shown vs share of daylight hours that were actually jumpable
        today_local = now.astimezone(LOCAL_TZ).date().isoformat()
        issued_local_date = issued_dt.astimezone(LOCAL_TZ).date()
        for day in snap.get("days", []):
            date = day["date"]
            if date >= today_local or date not in sunset:
                continue
            for station in STATIONS:
                key = (issued, date, station)
                if key in days_existing:
                    continue
                hours = [existing.get((issued, f"{date}T{hh:02d}:00", station)) for hh in range(8, min(18, sunset[date]) + 1)]
                hours = [r for r in hours if r]
                if len(hours) < 5:
                    continue
                days_existing[key] = {
                    "issued": issued, "revision": snap["revision"], "date": date,
                    "lead_days": (datetime.fromisoformat(date).date() - issued_local_date).days,
                    "station": station, "fc_likelihood": day["likelihood"],
                    "ob_pct": round(100 * sum(int(r["ob_jumpable"]) for r in hours) / len(hours)),
                    "ob_hours": len(hours),
                }

    by_month = {}
    for row in existing.values():
        by_month.setdefault(row["valid"][:7], []).append(row)
    for month, rows in by_month.items():
        rows.sort(key=lambda r: (r["valid"], r["issued"], r["station"]))
        write_csv(pairs_dir / f"{month}.csv", PAIR_FIELDS, rows)
    write_csv(data_dir / "days.csv", DAY_FIELDS,
              sorted(days_existing.values(), key=lambda r: (r["date"], r["issued"], r["station"])))
    print(f"pair: {new} new hour pairs, {len(existing)} total; {len(days_existing)} day pairs")
    return list(existing.values()), list(days_existing.values())


# ----------------------------------------------------------------------------- 4. summarise
def err_stats(pairs, digits=1):
    """pairs of (forecast, observed) -> n, mean absolute error, bias (forecast minus observed)."""
    pairs = [(f, o) for f, o in pairs if f is not None and o is not None]
    if not pairs:
        return {"n": 0}
    errs = [f - o for f, o in pairs]
    r = (lambda v: round(v)) if digits == 0 else (lambda v: round(v, digits))
    return {"n": len(errs), "mae": r(mean(abs(e) for e in errs)),
            "bias": r(mean(errs)), "median_bias": r(median(errs))}


def verdict_stats(pairs):
    """pairs of (forecast_yes, observed_yes) booleans."""
    n = len(pairs)
    if not n:
        return {"n": 0}
    both = sum(1 for f, o in pairs if f and o)
    neither = sum(1 for f, o in pairs if not f and not o)
    said_yes_wasnt = sum(1 for f, o in pairs if f and not o)
    said_no_was = sum(1 for f, o in pairs if not f and o)
    return {"n": n, "accuracy_pct": round(100 * (both + neither) / n),
            "both_yes": both, "both_no": neither,
            "said_yes_but_no": said_yes_wasnt, "said_no_but_yes": said_no_was}


def summarise_rows(rows):
    f = lambda r, k: num(r.get(k))
    s = {
        "hours": len(rows),
        "jumpable": verdict_stats([(r["fc_jumpable"] == "1" or r["fc_jumpable"] == 1,
                                    r["ob_jumpable"] == "1" or r["ob_jumpable"] == 1) for r in rows]),
        "wind_mph": err_stats([(f(r, "fc_ws"), f(r, "ob_ws")) for r in rows]),
        "gust_mph_when_reported": err_stats([(f(r, "fc_wg"), f(r, "ob_wg")) for r in rows]),
        "wind_dir_deg_mae": None,
        # forecast base vs the airport's lowest layer of scattered (3+ oktas) or more
        "cloudbase_ft": err_stats([(f(r, "fc_base_ft"), f(r, "ob_base_ft")) for r in rows
                                   if r["fc_base_state"] == "ft" and r.get("ob_base_ft") not in ("", None)], digits=0),
        "low_base_under_2000": verdict_stats([
            (r["fc_base_state"] == "ft" and (f(r, "fc_base_ft") or 9e9) < LOW_BASE_FT,
             r.get("ob_ceiling_ft") not in ("", None) and f(r, "ob_ceiling_ft") < LOW_BASE_FT) for r in rows]),
        "cloud_pct": err_stats([(f(r, "fc_cloud"), f(r, "ob_cloud")) for r in rows], digits=0),
        "rain": verdict_stats([((f(r, "fc_rain_prob") or 0) >= RAIN_PROB_PCT, str(r["ob_rain"]) == "1") for r in rows]),
        "models_wind_mph": {m: err_stats([(f(r, f"m_{m}_ws"), f(r, "ob_ws")) for r in rows]) for m in MODELS},
        "models_gust_mph_when_reported": {m: err_stats([(f(r, f"m_{m}_wg"), f(r, "ob_wg")) for r in rows]) for m in MODELS},
    }
    dirs = [angle_diff(f(r, "fc_dir"), f(r, "ob_dir")) for r in rows
            if f(r, "fc_dir") is not None and f(r, "ob_dir") is not None and (f(r, "ob_ws") or 0) >= 5]
    if dirs:
        s["wind_dir_deg_mae"] = round(mean(dirs))
    return s


def summarise_days(rows):
    pct = err_stats([(num(r["fc_likelihood"]), num(r["ob_pct"])) for r in rows])
    verdict = verdict_stats([(num(r["fc_likelihood"]) >= 50, num(r["ob_pct"]) >= 50) for r in rows])
    return {"jump_pct": pct, "day_verdict_50pct": verdict}


def bucket_of(lead_h):
    for name, lo, hi in LEAD_BUCKETS:
        if lo <= lead_h < hi:
            return name
    return None


def build_summary(data_dir, now, pair_rows, day_rows):
    windows = {"last_7_days": 7, "last_30_days": 30, "all_time": None}
    today = now.astimezone(LOCAL_TZ).date()
    out = {"generated": now.strftime("%Y-%m-%dT%H:%MZ"), "stations": STATIONS,
           "airfield_elev_ft": AIRFIELD_ELEV_FT, "rules": {
               "ops_wind_mph": OPS_WIND_MPH, "low_base_ft": LOW_BASE_FT, "poor_vis_km": POOR_VIS_KM,
               "heavy_cloud_pct": HEAVY_CLOUD_PCT, "rain_prob_pct": RAIN_PROB_PCT},
           "windows": {}}
    for wname, days in windows.items():
        since = None if days is None else (today - timedelta(days=days)).isoformat()
        rows = [r for r in pair_rows if since is None or r["valid"][:10] > since]
        drows = [r for r in day_rows if since is None or r["date"] > since]
        w = {"overall": summarise_rows(rows), "by_lead": {}, "by_station": {}, "days": {}}
        for name, _, _ in LEAD_BUCKETS:
            w["by_lead"][name] = summarise_rows([r for r in rows if bucket_of(float(r["lead_h"])) == name])
        for st in STATIONS:
            w["by_station"][st] = summarise_rows([r for r in rows if r["station"] == st])
        w["days"]["overall"] = summarise_days(drows)
        for ld in sorted({int(r["lead_days"]) for r in drows}):
            w["days"][f"lead_{ld}_days"] = summarise_days([r for r in drows if int(r["lead_days"]) == ld])
        out["windows"][wname] = w

    out["by_revision"] = {}
    for rev in sorted({r["revision"] for r in pair_rows}):
        rr = [r for r in pair_rows if r["revision"] == rev]
        s = summarise_rows(rr)
        out["by_revision"][rev] = {"hours": s["hours"], "jumpable": s["jumpable"], "wind_mph": s["wind_mph"],
                                   "cloudbase_ft": s["cloudbase_ft"],
                                   "first_valid": min(r["valid"] for r in rr), "last_valid": max(r["valid"] for r in rr)}

    snaps = sorted((data_dir / "snapshots").glob("*.json"))
    latest = read_json(snaps[-1], {}) if snaps else {}
    out["current_revision"] = latest.get("revision")
    out["current_tuning"] = latest.get("tuning")
    out["data_since"] = min((r["valid"] for r in pair_rows), default=None)
    out["reports"] = sorted(p.name for p in (data_dir / "reports").glob("*.md"))
    write_json(data_dir / "summary.json", out)
    print(f"summary: written ({len(pair_rows)} hour pairs, {len(day_rows)} day pairs)")


def prune_snapshots(data_dir, now):
    cutoff = (now - timedelta(days=KEEP_SNAPSHOT_DAYS)).strftime("%Y-%m-%d")
    for p in (data_dir / "snapshots").glob("*.json"):
        if p.name[:10] < cutoff:
            p.unlink()
            print(f"prune: removed {p.name}")


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="checkout of the forecast-data branch")
    ap.add_argument("--force-snapshot", action="store_true", help="take a snapshot now, whatever the time")
    ap.add_argument("--no-snapshot", action="store_true")
    args = ap.parse_args()

    data_dir = Path(args.data)
    now = datetime.now(timezone.utc)
    ok = True
    if not args.no_snapshot:
        try:
            take_snapshot(data_dir, now, force=args.force_snapshot)
        except Exception as e:
            ok = False
            print(f"snapshot FAILED: {e}", file=sys.stderr)
    try:
        collect_observations(data_dir)
    except Exception as e:
        ok = False
        print(f"observe FAILED: {e}", file=sys.stderr)
    pair_rows, day_rows = build_pairs(data_dir, now)
    build_summary(data_dir, now, pair_rows, day_rows)
    prune_snapshots(data_dir, now)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
