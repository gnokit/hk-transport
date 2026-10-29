# 🚇 hk-transport · 港交寶

![Python](https://img.shields.io/badge/python-3.13%2B-blue)
![uv](https://img.shields.io/badge/managed%20by-uv-261230)
![data](https://img.shields.io/badge/data-data.gov.hk-0b7285)
![MIT](https://img.shields.io/badge/licence-MIT-green)
![tests](https://github.com/gnokit/hk-transport/actions/workflows/tests.yml/badge.svg)

**An AI skill that answers Hong Kong MTR questions — built for an agent, not for a chat window.**

Every tool answers one kind of citizen question, and every answer carries its own source: the dataset, the endpoint actually called, and the time the data describes.

English · [繁體中文](README.zh.md)

---

## What this is

`hk-transport` gives an AI agent tools for Hong Kong's MTR. The agent talks to the person; the tools supply facts. That split is deliberate:

- The tools **do not chat**, do not choose a "best route" for anyone, and never fill a gap with a plausible number.
- When the published data cannot support an answer, `data` is `null` and `note` says why.
- A missing field stays empty and is explained — it is never replaced from a different ticket type, a different file, or a guess.

It is the transport-focused sibling of [`hkdata`](https://github.com/gnokit/hkdata): `hkdata` covers all of data.gov.hk, this repo is only transport, with one tool per question a citizen actually asks.

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

**Heavy rail**

| Command | Answers |
|---|---|
| `mtr_lines` | Which stations a line has, or which lines serve a station |
| `mtr_journey` | Which line to ride, where to transfer, stations in between |
| `mtr_fare` | Octopus and single-journey fare, every ticket type in the file |
| `mtr_airport_express_fare` | Airport Express fare — adult and child only |
| `mtr_next_train` | Next trains, terminus, platform, and any service alert |
| `mtr_ride_estimate` | In-vehicle minutes, estimated from live arrivals |
| `mtr_barrier_free` | Which barrier-free facilities a station has, and at which exit |
| `mtr_exits` | Exit coordinates — all stations, or one |

**Light Rail and feeders**

| Command | Answers |
|---|---|
| `light_rail` | Stop order on a route, or the fare between two stops |
| `light_rail_next` | Next departures from one stop, special departures marked |
| `mtr_bus` | Feeder-bus stops, per-route fare, and next arrivals |

**Location and traffic**

| Command | Answers |
|---|---|
| `address_lookup` | Match a place name or address, with coordinates |
| `special_traffic_news` | Current territory-wide traffic incidents |
| `special_traffic_arrangements` | Traffic arrangements published in advance |

Station input accepts a Chinese name, an English name, a station id (`2`), or a code (`ADM`). Names must be spelled as published. If a name matches more than one station, the tools say so rather than picking one.

## Design rules

These are the reason the repo exists, not decoration.

- ✅ **Never invent a figure.** No published trip time exists, so `mtr_ride_estimate` derives minutes from live arrivals — and returns `null` for the whole trip when any link's trains don't agree.
- ✅ **Every answer is auditable.** `dataset_id`, the endpoint called, `data_at`, `update_frequency`, and per-source detail in `sources`.
- ✅ **Absence is stated, not smoothed over.** No alert becomes 「這次回應沒有特別安排」 — never "all services normal".
- ✅ **Caching is explicit.** Monthly CSVs live 30 days in `.cache/`; live APIs and the traffic feeds are never cached; the exit snapshot is reused for about a year.
- ✅ **Straight-line is not walking time.** A distance computed from coordinates is labelled as what it is.
- 🚫 **No politeness, no itinerary.** The tool returns facts; the agent writes the sentence.

## Architecture

```mermaid
graph LR
  A[Agent] --> B[mtr.sh<br/>manual + CLI]
  B --> C[mtr.py<br/>one function per question]
  C --> D[mtr_core.py<br/>one function per dataset]
  C --> E[als.py · exits.py · notices.py]
  D --> F[(data.gov.hk · MTR)]
  E --> G[(Lands Department · Transport Department)]
```

Two layers, plus small shared modules (`_result` envelope, `_http` fetch, `_values` cell reading). `mtr.py` holds no URL and no cache; it only composes core functions. A new question reuses existing core functions — only a new data source adds one.

Scope is specified in [docs/TASKS.md](docs/TASKS.md); agent-facing instructions are in [SKILL.md](SKILL.md).

## Scope

| In | Out |
|---|---|
| MTR heavy rail, Airport Express, Disneyland Resort Line | Franchised bus, green minibus, red minibus, tram, ferry, taxi |
| Light Rail and MTR feeder buses | High-speed rail, cross-boundary rail, intercity services |
| Address lookup, station exits, barrier-free facilities | Which exit serves a particular building |
| Territory-wide traffic news and advance arrangements | Crowding levels, first and last trains |

## Data sources & licence

Data comes from [DATA.GOV.HK](https://data.gov.hk): four MTR datasets, plus the Lands Department address lookup, location search and coordinate transform, and the Transport Department's traffic news and advance arrangements. Use is subject to the [data.gov.hk terms](https://data.gov.hk/tc/terms-and-conditions).

This repository's own code is [MIT licensed](LICENSE). That licence covers the code only: the bundled exit snapshot in `src/hk_transport/data/mtr_exits.json` is derived from Lands Department data and stays subject to the data.gov.hk terms — see [NOTICE](NOTICE).

## Development

```bash
uv run pytest                          # 66 offline tests
uv run pytest -m live -o addopts=      # 8 live checks against the real endpoints
```

The offline suite is what CI runs. Live tests call data.gov.hk, so they are opt-in and never gate a build.

## Status

Phase 1 is complete: 14 commands covering heavy rail, Airport Express, Disneyland Resort Line, Light Rail, feeder buses, addresses, exits, and the two Transport Department feeds. Later phases are undecided — see [docs/TASKS.md](docs/TASKS.md).
