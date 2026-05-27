# Fleet Dashboard Challenge — Nilo Garciano Jr.

A single Python script that reads `fleet_status.csv` and produces a fully self-contained `fleet_dashboard.html` a fleet manager can open in any browser with zero setup.

---

## Quick Start

```bash
# Place fleet_status.csv in the same directory, then:
python fleet_dashboard.py

# Open the output
open fleet_dashboard.html   # macOS
xdg-open fleet_dashboard.html  # Linux
```

**Requirements:** Python 3.10+ — standard library only. No pip installs.

---

## Files

| File | Description |
|------|-------------|
| `fleet_dashboard.py` | The script — reads CSV, cleans data, writes HTML |
| `fleet_dashboard.html` | Pre-built output (open directly in any browser) |
| `fleet_status.csv` | Input snapshot of 30 GPS tracking devices |

---

## My Approach

### How I used AI to complete this task

I treat AI as an **architectural partner, not an autocomplete tool**. Before writing a single line of code, I used Gemini to map out the overall system workflow — identifying the data pipeline stages (ingest → clean → transform → render), the edge cases in the CSV worth handling, and the right shape for the HTML template injection strategy.

Once I had a clear architectural plan, I worked with Claude to implement and iterate on the solution. I used it the same way I use a senior engineer on a pair-programming call: I'd describe the constraint (standard library only, single output file, corrupted rows in the data), review what it produced, push back where the logic was wrong or the UI was generic, and maintained full ownership of every decision — from the cleaning rules to the final design direction.

Concretely, AI helped me:
- Draft the data-cleaning skeleton and identify the five corrupted row patterns in the CSV
- Generate the HTML/CSS/JS template that I then refined for visual quality
- Debug a `L is not defined` Leaflet race condition that appeared during testing

Every output was reviewed, tested, and deliberately shaped. The AI accelerated the build; the logic and judgment were mine.

### Colour and status logic

| Status | Colour | Hex | Rationale |
|--------|--------|-----|-----------|
| `active` | Green | `#3fb950` | Universal "all clear" signal — no attention needed |
| `idle` | Amber | `#f0a83a` | Vehicle is on but stationary — worth monitoring, not urgent |
| `offline` | Grey | `#6e7681` | No signal — unknown state, deprioritised visually |
| `low_battery` | Red | `#f85149` | Requires immediate action before the device goes dark |
| `unknown` | Purple | `#a371f7` | Invalid/unexpected status value — flagged as a data quality issue |

The priority ordering is intentional: **red draws the eye first**, then amber, then the greens. A fleet manager scanning the map at 7 AM should immediately see which vehicles need intervention without reading a single label. Grey (offline) is visually suppressed because an offline device — while important — is a known unknown; low battery is actionable right now.

The battery bar in the sidebar reinforces the same colour logic independently of status: green above 50%, amber 20–49%, red below 20%.

### One thing I would add for a real product

**Server-Sent Events (SSE) or WebSocket live updates.**

This dashboard is a static snapshot. In production, the most valuable thing a fleet manager needs is to see a device *transition* from `active` to `offline` or `low_battery` in real time — not discover it 30 minutes later when they next refresh.

I'd add a lightweight backend endpoint that streams status deltas to the open browser tab. The marker on the map would animate its colour change, and a toast notification would surface critical events (`TRK009 battery critical — 5%`). The Python script already structures the data in a shape that makes this straightforward to extend: the JSON payload injected into the HTML could be replaced with a live WebSocket feed with minimal changes to the frontend logic.

---

## Data Cleaning

The script handles the following real-world data issues found in the CSV:

| Row | Issue | Handling |
|-----|-------|----------|
| TRK031 | Missing `lat`, `lon`, `name`, `battery_pct` | **Skipped** — coordinates are required to plot |
| TRK032 | Status `"maintenance"` (not a valid enum) | Loaded as **`unknown`** category, flagged visually |
| TRK033 | `battery_pct` of `150` | **Clamped** to `100` |
| TRK034 | `lat` value of `"not_a_lat"` | **Skipped** — float cast fails |
| TRK035 | `battery_pct` of `-5`, future `last_seen` timestamp | Battery clamped to `0`; time shown as `"future timestamp"` |

Result: **33 of 35 rows** loaded successfully.

---

*Built by [Nilo Garciano Jr.](https://github.com/GarcianoNilo) · github.com/GarcianoNilo*
