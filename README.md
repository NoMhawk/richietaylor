# RichBot forecast verification data

Written automatically by `.github/workflows/forecast-verify.yml` (on `main`) every 3 hours.
Results page: https://richietaylor.net/forecast/accuracy/

| Path | What it holds |
|---|---|
| `snapshots/` | What the live forecast page showed, taken ~06:00 and ~18:00 UTC (kept 10 days) |
| `observations/` | Parsed METARs for Exeter (EGTE) and Yeovilton (EGDY), one file per UTC day |
| `pairs/YYYY-MM.csv` | Every forecast hour (08:00-18:00) matched with the nearest METAR, per airport |
| `days.csv` | Each day's JUMP % against the share of daylight hours that were actually jumpable |
| `summary.json` | Accuracy statistics (7 days, 30 days, all time; by lead time, airport, model, revision) |
| `reports/` | Weekly review reports written by the accuracy agent |

Cloud heights from the airports are converted to feet above Dunkeswell (833 ft).
"Jumpable" uses the same rules as the page: wind or gusts over 23 mph, rain, fog,
visibility under 3 km, ceiling under 2,000 ft or overcast cloud = not jumpable.
