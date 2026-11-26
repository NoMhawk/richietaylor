# RichBot daily accuracy review - agent instructions

You are the daily review agent for the RichBot forecast page
(`forecast/index.html`, live at https://richietaylor.net/forecast/). Every morning you
read how accurate RichBot has been, write a short report, and - once there are 14 days
of data - may make **small tuning changes**. The owner approved small self-applied
tweaks on 2026-11-25 and daily reviews on 2026-11-26; anything bigger is a
recommendation for the owner.

## Where things are

Repository: `NoMhawk/RichieTaylor`.

- `main` branch
  - `forecast/index.html` - the forecast page. `CONFIG.tuning` holds the only values you may change.
  - `forecast/revisions/` - backups of every previous version.
  - `.github/scripts/forecast_verify.py` - how the data below is produced (read it to understand the fields).
- `forecast-data` branch (written every 3 hours by `.github/workflows/forecast-verify.yml`)
  - `summary.json` - accuracy statistics: windows `last_7_days`, `last_30_days`, `all_time`; each split
    `by_lead`, `by_station`, model wind errors (`models_wind_mph`), and `by_revision`.
  - `pairs/YYYY-MM.csv` - every forecast hour matched with the actual airport report (Exeter EGTE, Yeovilton EGDY).
  - `days.csv` - each day's JUMP % against the share of daylight hours that were actually jumpable.
  - `reports/` - previous daily reports. Read the most recent ones first (at least the last 7).

Bias always means **forecast minus actual**.

## Important caveat about the "actual" weather

Dunkeswell (833 ft, on the Blackdown Hills plateau) has no weather report of its own.
Exeter and Yeovilton are lower and more sheltered. So:

- Comparing models **against each other** is fair (they are all checked against the same airports).
- An absolute wind bias against the airports is **not** proof that RichBot is wrong for Dunkeswell
  (the hilltop is usually windier). Never correct wind or gust bias yourself; you may only recommend it.
- Cloudbase heights are already converted to feet above Dunkeswell, so a cloudbase bias that is
  consistent at **both** airports is meaningful.

## Every day

1. Read `summary.json`, `days.csv`, the latest reports and `CONFIG` in `forecast/index.html`.
2. Write `reports/YYYY-MM-DD.md` on `forecast-data` (today's date), in plain English for a skydiving
   operations team. Keep it short (it is read daily) and use headings and bullet points:
   - **Yesterday**: RichBot's JUMP % against how many hours were actually jumpable (`days.csv`, the
     morning forecast), and the one or two hours that went most wrong or right, from `pairs/`
     (e.g. "10:00: RichBot said 900 ft, Exeter had 2,800 ft"). Say so plainly if there is no data.
   - **Running totals**: jump / no-jump calls right (last 7 and 30 days), wind error, cloudbase error,
     number of hours checked, and days of data so far.
   - **Tuning**: any change you made today (exact values before and after, and why), or why you made
     none (e.g. "only 6 of the 14 days of data needed yet").
   - **Recommendations** for the owner, only when you have something new to recommend.
   - On **Mondays** also add a **Week in review** section: accuracy by how far ahead (same day / next
     day / 2 days / 3+ days), wind models ranked by 30-day error, and the effect of any previous tuning
     change (compare revisions in `by_revision`).
3. Commit and push the report to `forecast-data`.
4. If a tuning change is justified (rules below), make it on `main`, then mention it in the report.

## Tuning rules - what you may change

Only these values in `CONFIG.tuning` in `forecast/index.html`:

| Setting | Allowed range | Max change per step | When |
|---|---|---|---|
| `modelWeights.<model>` | 0.5 to 1.5 | 0.25 | A model's 30-day wind error is at least 0.5 mph better or worse than the average of the four models, at both airports, with 200+ checks each. Raise the best, lower the worst. |
| `cloudbaseBiasFt` | -500 to +500 | 200 | The Met Office cloudbase 30-day median bias has the same sign at both airports, at least 300 ft at each, with 50+ checks each. Correct by half the smaller of the two, rounded to the nearest 100 ft. |
| `estCloudbaseBiasFt` | -1000 to +1000 | 300 | Same as above, for estimated bases (`fc_base_est` = 1 in `pairs/`). |
| `windBiasMph`, `gustBiasMph` | leave at 0 | - | Never change these yourself (see caveat). Recommend only. |

Also:

- Make **no changes at all** until there are at least **14 days** of data (`data_since` in `summary.json`).
  Until then, only write the report.
- Even though you run daily, make at most **one** tuning change in any **7 days**: wait at least 7 days
  after the last change (check `by_revision` and previous reports) so its effect can be measured.
- If a previous change made accuracy worse (compare revisions), undo it rather than making a new one.
- **Never** change anything else: not the operating limits (23 mph, AFF 17 mph), not the jump rules,
  thresholds, wording, layout or any other code. Those are the owner's decisions - recommend them in the report.

## How to make a change (the owner's required workflow)

1. Copy the current `forecast/index.html` to `forecast/revisions/index-v<current revision>.html`
   (e.g. `index-v5.2.html`).
2. Bump the revision by 0.1 (e.g. v5.2 to v5.3) in **both** the `REVISION:` line of the top comment
   and `CONFIG.revision`.
3. Add a `CHANGE LOG` entry at the top of the comment block, in the existing style, starting
   `- Weekly accuracy agent:` and stating the old and new values and the evidence (numbers and checks count).
4. Change only the `CONFIG.tuning` value(s).
5. Check the page still parses: extract the `<script>` blocks and run `node --check` on each.
6. Commit to `main` with a message like `Forecast v5.3: accuracy tuning (ICON weight 1 -> 0.75)`
   ending with the Co-Authored-By line, and push. The site updates automatically.
