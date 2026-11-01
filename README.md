# 🚇 hk-transport · 港交寶

![Python](https://img.shields.io/badge/python-3.13%2B-blue)
![uv](https://img.shields.io/badge/managed%20by-uv-261230)
![data](https://img.shields.io/badge/data-data.gov.hk-0b7285)
![MIT](https://img.shields.io/badge/licence-MIT-green)

**An AI agent skill for Hong Kong public transport — MTR first.**

A skill an AI agent loads when someone asks how to get around Hong Kong. The agent talks to the person; the skill supplies the facts through 14 commands. Every command returns one JSON envelope with its own source: the dataset, the endpoint actually called, and the time the data describes.

English · [繁體中文](README.zh.md)

---

## What this is

`hk-transport` is a skill, not an app and not a chatbot. It ships as a small command set (`mtr.sh`) that an AI agent runs to answer one kind of citizen question at a time — which stations a line has, where to change trains, what a fare costs, when the next train arrives.

The split is deliberate:

- **The agent speaks; the skill states.** Commands return facts. They do not chat, do not choose a "best route" for anyone, and never fill a gap with a plausible number.
- **Absence is an answer.** When the published data cannot support a reply, `data` is `null` and `note` says why.
- **Every figure is traceable.** A missing field stays empty and is explained — never replaced from another ticket type, another file, or a guess.

It is the transport-focused sibling of [`hkdata`](https://github.com/gnokit/hkdata): `hkdata` covers all of data.gov.hk, this project covers public transport only, one command per question a citizen actually asks.

### Roadmap

Phase 1 ships one entry script, `mtr.sh`. Every later phase adds a sibling script built the same way — `bus.sh`, `minibus.sh`, `tram.sh` — so an agent learns the pattern once and the modes stay independent.

| Phase | Modes | Entry script | Status |
|---|---|---|---|
| 1 | MTR heavy rail, Airport Express, Disneyland Resort Line, Light Rail, feeder buses | `mtr.sh` | ✅ 14 commands |
| 2 | Franchised buses | `bus.sh` | built, under test |
| 3 | Green minibus, red minibus | `minibus.sh` | built, under test |
| — | One journey across every built mode | `journey.sh` | built, under test |
| 4 | Tram, Peak Tram, ferry | `tram.sh`, `ferry.sh` | built, under test |
| 5 | Taxi, cross-boundary and high-speed rail | — | **cancelled** — no usable open data |

Every phase ships the same five things:

1. **A scope section in [docs/TASKS.md](docs/TASKS.md)** — written before any code.
2. **A core module** — one function per dataset, whole tables, no filtering.
3. **An answer module** — one function per citizen question, no URL, no cache.
4. **An entry script `<mode>.sh`** — same manual: no arguments lists commands, `help <command>` explains one, stdout is JSON.
5. **Tests** — offline by default, plus `live`-marked checks that never gate CI.

What phase 1 built stays shared rather than copied: the result envelope (`_result`), the 30-day fetch cache (`_http`), cell reading (`_values`), address lookup (`als`), and the two Transport Department feeds (`notices`).

Two honest caveats: phases 1–4 are built and phase 5 is cancelled for lack of open data, and the order above was a plan, not a commitment. Phase 3 also has its ten target questions and data sources written down. Phase 2 is the exception in having code — its ten target citizen questions and the implementation tasks are written in [docs/TASKS.md](docs/TASKS.md), chosen from the questions people ask rather than from the datasets available. Its journey search returns several options with their cost, and lets the person choose; cost is transfers and stops, not minutes. Open questions and known gaps are kept in [docs/BACKLOG.md](docs/BACKLOG.md). KMB and ferry code already lives in [`hkdata`](https://github.com/gnokit/hkdata); those phases decide whether to move it or wrap it.

## Quick start

```bash
git clone https://github.com/gnokit/hk-transport.git && cd hk-transport
bash mtr.sh                                          # the manual: one line per command
bash mtr.sh help mtr_next_train                      # that command's arguments
bash mtr.sh mtr_next_train 港島線 金鐘                # ask a question
```

`mtr.sh` prints one JSON envelope. Trimmed, from a real call:

```json
{
  "dataset_id": ["mtr-data-routes-fares-barrier-free-facilities", "mtr-data2-nexttrain-data"],
  "endpoint": ["…/mtr_lines_and_stations.csv", "…/getSchedule.php?line=ISL&sta=ADM&lang=tc"],
  "data_at": "2026-10-29T12:58:16+08:00",
  "update_frequency": "10s",
  "data": {
    "line_zh": "港島線",
    "station": { "id": "2", "code": "ADM", "name_zh": "金鐘", "name_en": "Admiralty" },
    "directions": [{ "direction": "UP", "trains": [{ "dest": { "name_zh": "柴灣" }, "platform": "3", "ttnt": "2" }] }]
  },
  "note": "這次回應沒有特別安排"
}
```

`data_at` is the time the data describes, in Hong Kong time — kept separate from `retrieved_at`, when it was fetched. A monthly file has no timestamp, so `data_at` is `null` and `update_frequency` carries the truth instead.

## What you can ask

Each command answers one kind of question. These are phase 1.

**Any journey, every mode**

| Command | Answers |
|---|---|
| `journey` | Which lines to ride and where to transfer, across MTR, every franchised bus operator and green minibus, with real walking legs |

**Heavy rail**

| Command | Answers |
|---|---|
| `mtr_lines` | Which stations a line has, or which lines serve a station |
| `mtr_fare` | Octopus and single-journey fare, every ticket type in the file |
| `mtr_airport_express_fare` | Airport Express fare — adult and child only |
| `mtr_next_train` | Next trains, terminus, platform, and any service alert |
| `mtr_ride_estimate` | In-vehicle minutes, estimated from live arrivals |
| `mtr_barrier_free` | Which barrier-free facilities a station has, and at which exit |
| `mtr_exits` | Exit coordinates for one station |

**Light Rail and feeders**

| Command | Answers |
|---|---|
| `light_rail` | Stop order on a route, or the fare between two stops |
| `light_rail_next` | Next departures from one stop, special departures marked |
| `mtr_bus` | Feeder-bus stops, per-route fare, and next arrivals |

**Tram and ferry**

| Command | Answers |
|---|---|
| `tram_route` | Stop order of one tram line, or whether it serves a place |
| `tram_stops_near` | Tram stops near a place |
| `tram_fare` | Adult tram fare |
| `peak_tram` | Peak Tram stops and fare |
| `tram_disruption` | TD notices that mention a line |
| `ferry_route` | Pier order of one ferry route |
| `ferry_piers_near` | Ferry piers near a place |
| `ferry_fare` | Adult ferry fare |
| `ferry_disruption` | TD notices that mention a route |
| `tram_service_hours`, `tram_eta`, `ferry_timetable`, `ferry_eta` | No data; say so |

Ferry data carries no operator, so answers name the route and piers, never the company.

**Green minibus**

| Command | Answers |
|---|---|
| `minibus_route` | Stop order of one route, or whether it serves a place |
| `minibus_stops_near` | Minibus stops near a place, with straight-line distance |
| `minibus_direct` | One-ride routes between two places |
| `minibus_fare` | Adult full fare and published whole-route time |
| `minibus_eta` | Next minibuses at a stop |
| `minibus_service_hours` | No data; says so |
| `minibus_frequency` | No data; says so |
| `minibus_disruption` | Transport Department notices that mention a route |
| `minibus_accessibility` | No data; says so |
| `red_minibus` | No data; red minibuses have no fixed routes |

A minibus route code is unique only inside a district (`HKI`, `KLN`, `NT`), so commands take `--region` when the code exists in more than one.

**Location and traffic**

| Command | Answers |
|---|---|
| `place_search` | Find a place, building or facility on the map, with coordinates |
| `address_lookup` | Match a place name or address, with coordinates |
| `special_traffic_news` | Current territory-wide traffic incidents |
| `special_traffic_arrangements` | Traffic arrangements published in advance |

Station input accepts a Chinese name, an English name, a station id (`2`), or a code (`ADM`). Names must be spelled as published. If a name matches more than one station, the commands say so rather than picking one.

## Design rules

These are the reason the project exists, not decoration.

- ✅ **Never invent a figure.** No published trip time exists, so `mtr_ride_estimate` derives minutes from live arrivals — and returns `null` for the whole trip when any link's trains don't agree.
- ✅ **Every answer is auditable.** `dataset_id`, the endpoint called, `data_at`, `update_frequency`, and per-source detail in `sources`.
- ✅ **Absence is stated, not smoothed over.** No alert becomes 「這次回應沒有特別安排」 — never "all services normal".
- ✅ **Caching is explicit.** Monthly CSVs live 30 days in `.cache/`; live APIs and the traffic feeds are never cached; the exit snapshot is reused for about a year.
- ✅ **Straight-line is not walking time.** A distance computed from coordinates is labelled as what it is.
- 🚫 **No politeness, no itinerary.** A command returns facts; the agent writes the sentence.

## Architecture

```mermaid
graph LR
  A[AI agent] --> B[mtr.sh<br/>skill entry point]
  B --> C[mtr.py<br/>one function per question]
  C --> D[mtr_core.py<br/>one function per dataset]
  C --> E[als.py · exits.py · notices.py]
  D --> F[(data.gov.hk · MTR)]
  E --> G[(Lands Department · Transport Department)]
```

Two layers, plus small shared modules (`_result` envelope, `_http` fetch, `_values` cell reading). `mtr.py` holds no URL and no cache; it only composes core functions. A new question reuses existing core functions — only a new data source adds one.

Scope is specified in [docs/TASKS.md](docs/TASKS.md); agent-facing instructions are in [SKILL.md](SKILL.md).

## Scope

| Covered in phase 1 | Not yet |
|---|---|
| MTR heavy rail, Airport Express, Disneyland Resort Line | Franchised bus, green minibus, red minibus, tram, ferry, taxi |
| Light Rail and MTR feeder buses | Cross-boundary rail, high-speed rail, intercity services |
| Address lookup, station exits, barrier-free facilities | Which exit serves a particular building |
| Territory-wide traffic news and advance arrangements | Crowding levels, first and last trains |

## Data sources & licence

Data comes from [DATA.GOV.HK](https://data.gov.hk): four MTR datasets, the Transport Department's GTFS headway feed and traffic feeds, plus the Lands Department address lookup, location search and coordinate transform. The MTR website's public service-hours pages are read once to build the first/last-train snapshot. Use is subject to the [data.gov.hk terms](https://data.gov.hk/tc/terms-and-conditions) and the MTR website terms.

This project's own code is [MIT licensed](LICENSE). That licence covers the code only: the bundled exit snapshot in `src/hk_transport/data/mtr_exits.json` and the MTR service-hours snapshot in `src/hk_transport/data/mtr_service_hours.json` are derived from third-party data and remain subject to their source terms — see [NOTICE](NOTICE).

## Development

```bash
uv run ruff check .                    # lint
uv run pytest                          # offline tests
uv run pytest -m live -o addopts=      # live checks against the real endpoints
uv run python scripts/check_od_benchmark.py   # journey cost against the 40-pair OD benchmark
```

CI runs `ruff check` and the offline suite. The OD benchmark is opt-in as well: it needs the MTR, bus, minibus, tram and ferry tables, and compares the planner's own minutes with Google Maps durations taken on 2026-11-01. Live tests call data.gov.hk, so they are opt-in and never gate a build.

## Status

Phase 1 is complete. The skill answers MTR questions — heavy rail, Airport Express, Disneyland Resort Line, Light Rail, feeder buses, addresses, exits, and the two Transport Department feeds — through 14 commands. Later transport modes are listed in the roadmap above and in [docs/TASKS.md](docs/TASKS.md).
