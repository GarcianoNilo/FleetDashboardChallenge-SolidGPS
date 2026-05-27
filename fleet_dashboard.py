"""
fleet_dashboard.py
──────────────────
Reads fleet_status.csv and writes a self-contained fleet_dashboard.html.

Data-cleaning rules applied:
  • Skip rows with missing / non-numeric lat or lon
  • Clamp battery_pct to [0, 100]; default to 0 on parse failure
  • Map unknown status values to "unknown"
  • Parse last_seen as UTC-naive datetime; compute human-readable "time ago"
  • Gracefully skip any row that raises an unexpected exception

Python standard-library only (csv, json, datetime, pathlib).
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

INPUT_FILE  = "fleet_status.csv"
OUTPUT_FILE = "fleet_dashboard.html"

VALID_STATUSES = {"active", "idle", "offline", "low_battery"}

LAST_SEEN_FMT = "%Y-%m-%d %H:%M:%S"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 – DATA CLEANING
# ─────────────────────────────────────────────────────────────────────────────

def time_ago(dt: datetime) -> str:
    """Return a human-readable relative time string for a past datetime.
    Clamps to 'just now' for future timestamps (bad data).
    """
    now   = datetime.now()
    delta = now - dt
    total = int(delta.total_seconds())

    if total < 0:
        return "future timestamp"
    if total < 60:
        return "just now"
    if total < 3600:
        mins = total // 60
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    if total < 86400:
        hrs = total // 3600
        return f"{hrs} hour{'s' if hrs != 1 else ''} ago"
    days = total // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def clean_row(row: dict, row_index: int) -> dict | None:
    """Validate and clean a single CSV row.
    Returns a cleaned dict, or None if the row must be skipped.
    """
    # ── lat / lon: must exist and be castable to float ──────────────────────
    try:
        lat = float(row.get("lat", "").strip())
        lon = float(row.get("lon", "").strip())
    except (ValueError, AttributeError):
        print(f"  [row {row_index}] SKIPPED – invalid lat/lon "
              f"({row.get('lat')!r}, {row.get('lon')!r})")
        return None

    # ── battery_pct: clamp to [0, 100], default 0 on failure ────────────────
    try:
        battery = float(row.get("battery_pct", "0").strip())
        battery = max(0.0, min(100.0, battery))
    except (ValueError, AttributeError):
        battery = 0.0

    # ── status: accept known values, map anything else to "unknown" ──────────
    raw_status = row.get("status", "").strip().lower()
    status = raw_status if raw_status in VALID_STATUSES else "unknown"
    if status == "unknown":
        print(f"  [row {row_index}] status {raw_status!r} mapped to 'unknown'")

    # ── last_seen: parse timestamp, compute time-ago string ─────────────────
    raw_ts = row.get("last_seen", "").strip()
    try:
        last_seen_dt  = datetime.strptime(raw_ts, LAST_SEEN_FMT)
        last_seen_str = last_seen_dt.strftime("%-d %b %Y, %H:%M")
        time_ago_str  = time_ago(last_seen_dt)
    except ValueError:
        last_seen_str = "Unknown"
        time_ago_str  = "Unknown"

    # ── name / device_id: use fallback if blank ──────────────────────────────
    device_id = row.get("device_id", "").strip() or "UNKNOWN"
    name      = row.get("name", "").strip()       or device_id
    location  = row.get("location", "").strip()   or "Unknown"

    return {
        "id":           device_id,
        "name":         name,
        "status":       status,
        "battery":      round(battery, 1),
        "lat":          lat,
        "lon":          lon,
        "location":     location,
        "last_seen":    last_seen_str,
        "time_ago":     time_ago_str,
    }


def load_devices(path: str) -> list[dict]:
    """Read the CSV, clean each row, and return the list of valid devices."""
    devices = []
    input_path = Path(path)

    if not input_path.exists():
        sys.exit(f"ERROR: '{path}' not found. "
                 "Make sure the CSV is in the same directory as this script.")

    with input_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=2):       # row 1 = header
            try:
                cleaned = clean_row(row, i)
                if cleaned:
                    devices.append(cleaned)
            except Exception as exc:                    # catch-all safety net
                print(f"  [row {i}] SKIPPED – unexpected error: {exc}")

    return devices


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – COMPUTE SUMMARY COUNTS
# ─────────────────────────────────────────────────────────────────────────────

def compute_summary(devices: list[dict]) -> dict:
    """Return count per status category."""
    summary = {"active": 0, "idle": 0, "offline": 0, "low_battery": 0, "unknown": 0}
    for d in devices:
        summary[d["status"]] = summary.get(d["status"], 0) + 1
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – HTML TEMPLATE
# ─────────────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>SolidGPS — Fleet Dashboard</title>

  <!-- Leaflet CSS -->
  <link rel="stylesheet"
        href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        crossorigin="" />

  <!-- Google Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=JetBrains+Mono:wght@400;600&display=swap"
        rel="stylesheet" />

  <style>
    /* ── Reset & Tokens ──────────────────────────────────────────────── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:           #0d1117;
      --surface:      #161b22;
      --surface2:     #1c2330;
      --border:       #30363d;
      --text:         #e6edf3;
      --muted:        #8b949e;
      --accent:       #58a6ff;

      --active:       #3fb950;
      --idle:         #f0a83a;
      --offline:      #6e7681;
      --low-battery:  #f85149;
      --unknown:      #a371f7;

      --active-bg:    rgba(63,185,80,.12);
      --idle-bg:      rgba(240,168,58,.12);
      --offline-bg:   rgba(110,118,129,.12);
      --low-battery-bg: rgba(248,81,73,.12);
      --unknown-bg:   rgba(163,113,247,.12);

      --radius:       10px;
      --sidebar-w:    340px;
      --header-h:     58px;
      --font:         'DM Sans', sans-serif;
      --mono:         'JetBrains Mono', monospace;
    }

    html, body { height: 100%; overflow: hidden; background: var(--bg); color: var(--text); font-family: var(--font); }

    /* ── Layout ──────────────────────────────────────────────────────── */
    .app {
      display: grid;
      grid-template-rows: var(--header-h) 1fr;
      grid-template-columns: var(--sidebar-w) 1fr;
      grid-template-areas:
        "header header"
        "sidebar map";
      height: 100vh;
    }

    /* ── Header ──────────────────────────────────────────────────────── */
    header {
      grid-area: header;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 20px;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      gap: 16px;
    }

    .logo {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 15px;
      font-weight: 600;
      letter-spacing: -.3px;
      white-space: nowrap;
    }

    .logo svg { flex-shrink: 0; }

    /* Summary pills in header */
    .summary-pills {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .pill {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px 4px 8px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 500;
      border: 1px solid transparent;
      cursor: pointer;
      transition: filter .15s;
    }
    .pill:hover { filter: brightness(1.15); }
    .pill .dot  { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
    .pill .count{ font-family: var(--mono); font-weight: 600; font-size: 13px; }

    .pill.active      { background: var(--active-bg);      border-color: rgba(63,185,80,.3);    color: var(--active); }
    .pill.idle        { background: var(--idle-bg);        border-color: rgba(240,168,58,.3);   color: var(--idle); }
    .pill.offline     { background: var(--offline-bg);     border-color: rgba(110,118,129,.3);  color: var(--offline); }
    .pill.low_battery { background: var(--low-battery-bg); border-color: rgba(248,81,73,.3);    color: var(--low-battery); }
    .pill.unknown     { background: var(--unknown-bg);     border-color: rgba(163,113,247,.3);  color: var(--unknown); }

    .pill.active      .dot { background: var(--active); }
    .pill.idle        .dot { background: var(--idle); }
    .pill.offline     .dot { background: var(--offline); }
    .pill.low_battery .dot { background: var(--low-battery); }
    .pill.unknown     .dot { background: var(--unknown); }

    .header-right {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-shrink: 0;
    }

    .generated-at {
      font-size: 11px;
      color: var(--muted);
      font-family: var(--mono);
      white-space: nowrap;
    }

    /* ── Sidebar ─────────────────────────────────────────────────────── */
    aside {
      grid-area: sidebar;
      display: flex;
      flex-direction: column;
      background: var(--surface);
      border-right: 1px solid var(--border);
      overflow: hidden;
    }

    .sidebar-header {
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
    }

    .sidebar-title {
      font-size: 12px;
      font-weight: 600;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: var(--muted);
    }

    .device-count {
      font-family: var(--mono);
      font-size: 11px;
      color: var(--muted);
    }

    /* Search */
    .search-wrap {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }

    .search-wrap input {
      width: 100%;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 7px 10px 7px 30px;
      font-size: 13px;
      font-family: var(--font);
      color: var(--text);
      outline: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%238b949e' stroke-width='2'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.35-4.35'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: 9px center;
      transition: border-color .15s;
    }
    .search-wrap input:focus { border-color: var(--accent); }
    .search-wrap input::placeholder { color: var(--muted); }

    /* Filter tabs */
    .filter-tabs {
      display: flex;
      padding: 8px 12px;
      gap: 4px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
      overflow-x: auto;
    }
    .filter-tabs::-webkit-scrollbar { display: none; }

    .tab-btn {
      flex-shrink: 0;
      padding: 4px 10px;
      border-radius: 6px;
      border: 1px solid transparent;
      font-size: 11px;
      font-weight: 500;
      cursor: pointer;
      background: transparent;
      color: var(--muted);
      transition: all .15s;
    }
    .tab-btn:hover { background: var(--surface2); color: var(--text); }
    .tab-btn.active-tab { background: var(--accent); color: #0d1117; border-color: var(--accent); }

    /* Device list */
    .device-list {
      flex: 1;
      overflow-y: auto;
      padding: 8px;
    }
    .device-list::-webkit-scrollbar { width: 4px; }
    .device-list::-webkit-scrollbar-track { background: transparent; }
    .device-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

    .device-card {
      padding: 11px 12px;
      border-radius: var(--radius);
      border: 1px solid var(--border);
      margin-bottom: 6px;
      background: var(--surface2);
      cursor: pointer;
      transition: border-color .15s, background .15s;
    }
    .device-card:hover   { border-color: var(--accent); background: rgba(88,166,255,.06); }
    .device-card.focused { border-color: var(--accent); background: rgba(88,166,255,.1); }

    .card-top {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 7px;
    }

    .card-name {
      font-size: 13px;
      font-weight: 500;
      line-height: 1.3;
    }

    .status-badge {
      flex-shrink: 0;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 8px;
      border-radius: 20px;
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: .05em;
    }
    .status-badge .dot { width: 5px; height: 5px; border-radius: 50%; }

    .badge-active      { background: var(--active-bg);      color: var(--active);      }
    .badge-idle        { background: var(--idle-bg);        color: var(--idle);        }
    .badge-offline     { background: var(--offline-bg);     color: var(--offline);     }
    .badge-low_battery { background: var(--low-battery-bg); color: var(--low-battery); }
    .badge-unknown     { background: var(--unknown-bg);     color: var(--unknown);     }

    .badge-active      .dot { background: var(--active);      }
    .badge-idle        .dot { background: var(--idle);         }
    .badge-offline     .dot { background: var(--offline);      }
    .badge-low_battery .dot { background: var(--low-battery);  }
    .badge-unknown     .dot { background: var(--unknown);      }

    .card-meta {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .meta-item {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 11px;
      color: var(--muted);
    }

    .battery-bar-wrap {
      display: flex;
      align-items: center;
      gap: 5px;
    }
    .battery-bar {
      width: 36px;
      height: 5px;
      background: var(--border);
      border-radius: 3px;
      overflow: hidden;
    }
    .battery-fill {
      height: 100%;
      border-radius: 3px;
      transition: width .3s;
    }
    .battery-pct { font-family: var(--mono); font-size: 10px; }

    .no-results {
      text-align: center;
      padding: 40px 16px;
      color: var(--muted);
      font-size: 13px;
    }

    /* ── Map ─────────────────────────────────────────────────────────── */
    #map {
      grid-area: map;
      width: 100%;
      height: 100%;
      background: var(--bg);
    }

    /* Leaflet popup overrides */
    .leaflet-popup-content-wrapper {
      background: var(--surface2) !important;
      color: var(--text) !important;
      border: 1px solid var(--border) !important;
      border-radius: var(--radius) !important;
      box-shadow: 0 8px 24px rgba(0,0,0,.5) !important;
    }
    .leaflet-popup-tip { background: var(--surface2) !important; }
    .leaflet-popup-content { margin: 14px 16px !important; min-width: 200px; }

    .popup-title   { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
    .popup-row     { display: flex; justify-content: space-between; font-size: 12px; gap: 12px; margin-bottom: 4px; }
    .popup-label   { color: var(--muted); }
    .popup-val     { font-family: var(--mono); font-size: 11px; }

    /* Custom SVG markers */
    .marker-svg { filter: drop-shadow(0 2px 4px rgba(0,0,0,.5)); }
  </style>
</head>
<body>
<div class="app">

  <!-- ── HEADER ─────────────────────────────────────────────────────── -->
  <header>
    <div class="logo">
      <svg width="22" height="22" viewBox="0 0 22 22" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect width="22" height="22" rx="6" fill="#58a6ff"/>
        <path d="M11 4C8.24 4 6 6.24 6 9c0 3.75 5 9 5 9s5-5.25 5-9c0-2.76-2.24-5-5-5zm0 6.5a1.5 1.5 0 110-3 1.5 1.5 0 010 3z" fill="#0d1117"/>
      </svg>
      SolidGPS Fleet
    </div>

    <div class="summary-pills" id="summaryPills"></div>

    <div class="header-right">
      <span class="generated-at" id="generatedAt"></span>
    </div>
  </header>

  <!-- ── SIDEBAR ────────────────────────────────────────────────────── -->
  <aside>
    <div class="sidebar-header">
      <span class="sidebar-title">Vehicles</span>
      <span class="device-count" id="visibleCount"></span>
    </div>

    <div class="search-wrap">
      <input type="text" id="searchInput" placeholder="Search by name or location…" autocomplete="off" />
    </div>

    <div class="filter-tabs" id="filterTabs"></div>

    <div class="device-list" id="deviceList"></div>
  </aside>

  <!-- ── MAP ───────────────────────────────────────────────────────── -->
  <div id="map"></div>
</div>

<!-- Leaflet JS -->
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>

<script>
// ═══════════════════════════════════════════════════════════════════════
// DATA — injected by fleet_dashboard.py
// ═══════════════════════════════════════════════════════════════════════
const DEVICES  = /*__DEVICES__*/[];
const SUMMARY  = /*__SUMMARY__*/{};
const GEN_TIME = /*__GEN_TIME__*/"";

// ═══════════════════════════════════════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════════════════════════════════════
const STATUS_CONFIG = {
  active:      { color: "#3fb950", label: "Active"      },
  idle:        { color: "#f0a83a", label: "Idle"        },
  offline:     { color: "#6e7681", label: "Offline"     },
  low_battery: { color: "#f85149", label: "Low Battery" },
  unknown:     { color: "#a371f7", label: "Unknown"     },
};

const STATUS_ORDER = ["active", "idle", "offline", "low_battery", "unknown"];

// ═══════════════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════════════
let activeFilter  = "all";
let searchQuery   = "";
let focusedId     = null;
const markerMap   = {};   // device_id → Leaflet marker

// ═══════════════════════════════════════════════════════════════════════
// MAP SETUP
// ═══════════════════════════════════════════════════════════════════════
const map = L.map("map", { zoomControl: false }).setView([-28, 134], 5);

L.tileLayer(
  "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  { attribution: "© OpenStreetMap © CARTO", maxZoom: 19 }
).addTo(map);

L.control.zoom({ position: "bottomright" }).addTo(map);

function makeSvgIcon(color) {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="28" height="36" viewBox="0 0 28 36" class="marker-svg">
      <path d="M14 0C6.27 0 0 6.27 0 14c0 9.75 14 22 14 22S28 23.75 28 14C28 6.27 21.73 0 14 0z" fill="${color}"/>
      <circle cx="14" cy="14" r="6" fill="white" fill-opacity="0.9"/>
    </svg>`;
  return L.divIcon({
    html: svg,
    iconSize:   [28, 36],
    iconAnchor: [14, 36],
    popupAnchor:[0, -36],
    className:  "",
  });
}

function buildPopup(d) {
  const cfg = STATUS_CONFIG[d.status] || STATUS_CONFIG.unknown;
  return `
    <div class="popup-title">${d.name}</div>
    <div class="popup-row"><span class="popup-label">ID</span>      <span class="popup-val">${d.id}</span></div>
    <div class="popup-row"><span class="popup-label">Status</span>  <span class="popup-val" style="color:${cfg.color}">${cfg.label}</span></div>
    <div class="popup-row"><span class="popup-label">Battery</span> <span class="popup-val">${d.battery}%</span></div>
    <div class="popup-row"><span class="popup-label">Location</span><span class="popup-val">${d.location}</span></div>
    <div class="popup-row"><span class="popup-label">Last seen</span><span class="popup-val">${d.time_ago}</span></div>
    <div class="popup-row"><span class="popup-label">Coords</span>  <span class="popup-val">${d.lat.toFixed(4)}, ${d.lon.toFixed(4)}</span></div>`;
}

// Plot all markers
DEVICES.forEach(d => {
  const cfg    = STATUS_CONFIG[d.status] || STATUS_CONFIG.unknown;
  const marker = L.marker([d.lat, d.lon], { icon: makeSvgIcon(cfg.color) })
                  .bindPopup(buildPopup(d), { maxWidth: 260 })
                  .addTo(map);

  marker.on("click", () => focusDevice(d.id));
  markerMap[d.id] = marker;
});

// ═══════════════════════════════════════════════════════════════════════
// SIDEBAR RENDER
// ═══════════════════════════════════════════════════════════════════════
function batteryColor(pct) {
  if (pct >= 50) return "#3fb950";
  if (pct >= 20) return "#f0a83a";
  return "#f85149";
}

function renderList() {
  const q   = searchQuery.toLowerCase();
  const list = document.getElementById("deviceList");
  const cnt  = document.getElementById("visibleCount");

  const filtered = DEVICES.filter(d => {
    const matchFilter = activeFilter === "all" || d.status === activeFilter;
    const matchSearch = !q || d.name.toLowerCase().includes(q) || d.location.toLowerCase().includes(q) || d.id.toLowerCase().includes(q);
    return matchFilter && matchSearch;
  });

  cnt.textContent = `${filtered.length} / ${DEVICES.length}`;

  if (!filtered.length) {
    list.innerHTML = `<div class="no-results">No vehicles match your filter.</div>`;
    return;
  }

  list.innerHTML = filtered.map(d => {
    const cfg      = STATUS_CONFIG[d.status] || STATUS_CONFIG.unknown;
    const bColor   = batteryColor(d.battery);
    const focused  = d.id === focusedId ? " focused" : "";
    const label    = d.status === "low_battery" ? "Low Bat" : cfg.label;

    return `
    <div class="device-card${focused}" data-id="${d.id}" onclick="focusDevice('${d.id}')">
      <div class="card-top">
        <span class="card-name">${d.name}</span>
        <span class="status-badge badge-${d.status}">
          <span class="dot"></span>${label}
        </span>
      </div>
      <div class="card-meta">
        <div class="meta-item battery-bar-wrap">
          <div class="battery-bar">
            <div class="battery-fill" style="width:${d.battery}%;background:${bColor}"></div>
          </div>
          <span class="battery-pct" style="color:${bColor}">${d.battery}%</span>
        </div>
        <div class="meta-item">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          ${d.time_ago}
        </div>
        <div class="meta-item">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>
          ${d.location}
        </div>
      </div>
    </div>`;
  }).join("");
}

function focusDevice(id) {
  focusedId = id;
  const d = DEVICES.find(x => x.id === id);
  if (d) {
    map.flyTo([d.lat, d.lon], 14, { duration: 0.8 });
    markerMap[id]?.openPopup();
  }
  renderList();
  // Scroll card into view
  const card = document.querySelector(`.device-card[data-id="${id}"]`);
  card?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ═══════════════════════════════════════════════════════════════════════
// SUMMARY PILLS
// ═══════════════════════════════════════════════════════════════════════
function renderPills() {
  const wrap = document.getElementById("summaryPills");
  wrap.innerHTML = STATUS_ORDER
    .filter(s => SUMMARY[s] > 0)
    .map(s => {
      const cfg = STATUS_CONFIG[s];
      return `
      <button class="pill ${s}" onclick="setFilter('${s}')">
        <span class="dot"></span>
        ${cfg.label}
        <span class="count">${SUMMARY[s]}</span>
      </button>`;
    }).join("");
}

// ═══════════════════════════════════════════════════════════════════════
// FILTER TABS
// ═══════════════════════════════════════════════════════════════════════
function renderTabs() {
  const wrap = document.getElementById("filterTabs");
  const tabs  = [
    { key: "all", label: "All" },
    ...STATUS_ORDER.filter(s => SUMMARY[s] > 0).map(s => ({
      key: s, label: STATUS_CONFIG[s].label
    }))
  ];
  wrap.innerHTML = tabs.map(t => `
    <button class="tab-btn${activeFilter === t.key ? " active-tab" : ""}"
            onclick="setFilter('${t.key}')">${t.label}</button>`
  ).join("");
}

function setFilter(status) {
  activeFilter = status;
  renderTabs();
  renderList();
}

// ═══════════════════════════════════════════════════════════════════════
// SEARCH
// ═══════════════════════════════════════════════════════════════════════
document.getElementById("searchInput").addEventListener("input", e => {
  searchQuery = e.target.value;
  renderList();
});

// ═══════════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════════
document.getElementById("generatedAt").textContent = "Generated " + GEN_TIME;
renderPills();
renderTabs();
renderList();
</script>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 – INJECT DATA & WRITE OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

def build_html(devices: list[dict], summary: dict) -> str:
    """Inject the cleaned JSON payload into the HTML template."""
    gen_time = datetime.now().strftime("%-d %b %Y, %H:%M")

    html = HTML_TEMPLATE
    html = html.replace("/*__DEVICES__*/[]",  json.dumps(devices,  separators=(",", ":")))
    html = html.replace("/*__SUMMARY__*/{}",  json.dumps(summary,  separators=(",", ":")))
    html = html.replace('/*__GEN_TIME__*/"" ', f'"{gen_time}" ')
    html = html.replace('/*__GEN_TIME__*/"";', f'"{gen_time}";')
    return html


def main() -> None:
    print(f"Reading '{INPUT_FILE}'…")
    devices = load_devices(INPUT_FILE)

    if not devices:
        sys.exit("ERROR: No valid devices found after cleaning. Aborting.")

    summary = compute_summary(devices)
    print(f"\nLoaded {len(devices)} valid device(s).")
    for status, count in summary.items():
        if count:
            print(f"  {status:<12}: {count}")

    print(f"\nBuilding '{OUTPUT_FILE}'…")
    html = build_html(devices, summary)

    output_path = Path(OUTPUT_FILE)
    output_path.write_text(html, encoding="utf-8")
    print(f"Done! Open '{output_path.resolve()}' in any browser.")


if __name__ == "__main__":
    main()
