---
name: hk-transport
description: >
  Use when the user asks, in Chinese or English, about Hong Kong MTR (港鐵):
  next train (下一班), fare (車費), route (路線), journey and interchange
  (轉車), ride time (幾耐), Light Rail (輕鐵), MTR bus (港鐵巴士), a station
  exit (出口), barrier-free facilities (無障礙設施), an address (地址), or a
  traffic disruption (交通消息). Also use for franchised buses (巴士, 九巴,
  城巴): which route (搭咩車), stops (巴士站), fare (車費), next bus (下一班),
  or whether a route is disrupted (改道). Also green minibus (小巴, 綠巴,
  專線小巴): which route, stops, fare, next minibus. Also tram (電車) and
  ferry (渡輪, 船): route, piers, fare.
  Not high-speed rail, cross-boundary rail, or taxi.
compatibility: Requires uv and Python >=3.13. $SKILL_DIR is the directory that contains mtr.sh, bus.sh and minibus.sh.
---

# hk-transport（港交寶）

Answer a Hong Kong transport question by running one of this skill's scripts. Do not write a fetcher. Do not invent a figure a command did not return.

**Scope: one journey search over MTR, franchised buses (KMB, LWB, Citybus, NLB, MTR feeder buses), green minibuses and the Lands Department pedestrian network; plus per-mode route, fare, stop and arrival commands, address lookup, the heavy-rail exit snapshot, and the two Transport Department feeds.** Out of scope today: taxi, cross-boundary rail and high-speed rail.

> If the request is out of scope, say 「這個問題超出 hk-transport（港交寶）的範圍。」 Leave KMB and ferry programs in hkdata. Do not copy them.

## Choose a command from the manual

Two entry points, one contract each:

```bash
bash ${SKILL_DIR}/journey.sh  # any point-to-point journey, all modes together
bash ${SKILL_DIR}/mtr.sh      # MTR and its feeders, plus place search
bash ${SKILL_DIR}/bus.sh      # franchised buses
bash ${SKILL_DIR}/minibus.sh  # green minibuses
bash ${SKILL_DIR}/tram.sh     # Hong Kong Tramways and the Peak Tram
bash ${SKILL_DIR}/ferry.sh    # every ferry route the TD lists
```

No arguments and `help` print the same page: a short introduction, then one line per command. Read `help <command>` when its arguments are not obvious. stdout of a command is JSON.

If you do not know a station, stop, line or place name, look it up first. `bash ${SKILL_DIR}/mtr.sh place_search <name>` turns a place or facility name into a point. MTR: `mtr_lines --line` or `--station`. Bus: `bus_stops_near` for stops near a place, `bus_route` for the stops on a route. Names must match the official spelling exactly — the MTR file spells 茘枝角 with 茘, not 荔. A station id (`2`) or code (`ADM`) also works for MTR; a stop id works for buses.

## When a name does not match

A command may answer 「找不到車站：…」, 「找不到路線：…」, 「400 米內沒有九巴／龍運站。最近的是…」, or 「這個站不在這條線上。」 That means the input did not match the published name — not that the place has no service.

- Do not guess a similar place, and do not re-run the same input expecting a different result.
- Look the name up with `mtr_lines` or `bus_stops_near`, then run the command again.
- Check the line as well as the station: a correct station on the wrong line fails the same way.
- Common traps: 茘枝角 is spelled with 茘; the command also accepts 荔枝角 as an alias. English names use the published form (`Tsim Sha Tsui`, `AsiaWorld-Expo`); 中環, 香港 and 機場快線香港站 are names for one interchange area.
- If it still does not resolve, say the skill cannot find it. Do not substitute a nearby place.

Place names are resolved by the Lands Department place search, which knows places and facilities, not just buildings. Three consequences:

- A **coordinate pair** (`22.31930,114.16940`) is accepted anywhere a place name is, and is the only way to pin both ends to an exact point. Use it when the caller already has coordinates, and when comparing two planners, because a place name resolves to a different spot in each one.
- A **district name** (`屯門`, `沙田`, `西貢`) is one point inside the district, not the district. The answer says so and prints the point. Do not treat it as "the whole district", and do not use it as an origin or destination when the question needs a precise place.
- A large facility (`香港國際機場`) may resolve to a label point kilometres from its entrances. When nothing is inside the walking radius, the answer falls back to a stop whose own name appears in the query and says which stop it used.
- When the answer names the nearest stop and a straight-line distance, that means **no bus stop is inside the walking radius**. Report it as it stands: the place has no bus stop that close, and the nearest one is that far away. Never quietly use the further stop.

## When a name matches more than one station

A few names are two stations: 香港 has an Airport Express id and a Tung Chung line id. A command may answer with `matches` (or `origin_matches` and `destination_matches`), with one entry per matching station, or with one fare pair per station, and says so in `note`.

- Do not choose one yourself. Say which stations matched, and ask which one the person means.
- Or run the command again with the station id or code, which settles it.
- Never add up, average, or subset the answer across those stations.

## Border control points (HK-side edge cases)

This skill covers **Hong Kong–side** public transport only. Do not plan rides on the Mainland network, cross-boundary coaches as a product, co-located Mainland halls, or high-speed rail through 西九龍. If the person asks to cross the boundary or ride 高鐵／跨境鐵路, say 「這個問題超出 hk-transport（港交寶）的範圍。」

Place search and stop names often collide with Mainland port names (福田、羅湖、皇崗、蓮塘、深圳灣). When the origin or destination is clearly one of the ports below (or a close alias), **do not** trust the first `place_search` hit blindly. Prefer the **journey input name** in the table (official stop or station wording). Pass the WGS84 pair from the table as the origin or destination (both `journey.sh` and `place` accept `lat,lng`); that settles the ambiguity exactly. If you pass a name instead, choose the hit nearest the listed point and say which port point you used.

Coordinates are from Lands Department place search, MTR exit snapshot, or TD `JSON_BUS` stop geometry (retrieved 2026-10-31 HKT unless noted). Round-trip checks: lat/lon are Hong Kong side unless marked avoid.

| User intent (aliases) | Prefer `journey` / stop input | lat | lon | Notes |
| --- | --- | --- | --- | --- |
| 羅湖、羅湖站、羅湖管制站、羅湖口岸（港方） | `羅湖` (MTR) or `港鐵羅湖站` | 22.527639 | 114.113235 | MTR only to the control point. Exit A ≈ 22.529048, 114.113419; ImmD hall place `羅湖出入境管制站` ≈ 22.529477, 114.113664. |
| 落馬洲支線、落馬洲站、福田口岸（港方過關）、落馬洲站福田口岸 | `落馬洲站 ‧ 福田口岸` | 22.515513 | 114.066528 | KMB/TD stop id `12729` (B1 terminus). **Preferred** over bare `落馬洲站` (place ≈ 22.515034, 114.065624), which can enter via bus loops. MTR `落馬洲` / exit A ≈ 22.514899, 114.066198 (`mtr:78`). Spur-line CP reporting centre ≈ 22.514953, 114.065663. |
| 落馬洲管制站、落馬洲道路口岸（舊皇崗道路過境） | `落馬洲管制站` | 22.509242 | 114.074162 | 舊道路過境點，**唔係**新皇崗口岸港方口岸區，亦唔係落馬洲支線站。新田運輸交匯處 ≈ 22.503179, 114.081932。 |
| 皇崗口岸、新皇崗口岸、皇崗管制站（港方口岸區） | `皇崗口岸` (TD stop `10000421`) | 22.523199 | 114.067601 | 新皇崗口岸港方口岸區：KMB B10/B11/NB73、CTB B13/B14/B15、NLB B12。Place `皇崗管制站` ≈ 22.523179, 114.067682。 |
| 皇崗、皇崗穿梭巴士（只有跨境巴士） | 唔好用 TD stop `皇崗` (`12743`) | 22.522901 | 114.067095 | 只有 `companyCode` XB 的跨境巴士；XB 唔入 `journey`。去新口岸請用上面的 `皇崗口岸`。 |
| 深圳灣、深圳灣口岸、深圳灣管制站 | `深圳灣口岸` (bus stop) | 22.501407 | 113.945805 | TD stop id `12728` (e.g. B3). ImmD `深圳灣出入境管制站` ≈ 22.493822, 113.945433. Closed area. |
| 文錦渡、文錦渡管制站 | `文錦渡管制站` | 22.537416 | 114.128813 | Nearest KMB often `文錦渡(新屋嶺村)` ≈ 22.534554, 114.131760. |
| 沙頭角、沙頭角管制站 | `沙頭角管制站` | 22.549083 | 114.223287 | ImmD: passenger/cargo clearance **suspended** (as of 2026-10-31). Bus `沙頭角總站` ≈ 22.545561, 114.223655. |
| 香園圍、香園圍管制站、蓮塘（港方） | `香園圍管制站` or bus `香園圍口岸` | 22.552296 / 22.552023 | 114.153809 / 114.154115 | Mainland name is 蓮塘; keep HK wording for search. |
| 港珠澳、港珠澳大橋、港珠澳大橋香港口岸 | `港珠澳大橋香港口岸` | 22.316145 | 113.950624 | TD stop `13345` (PTI). 旅檢大樓 / stop `13346` ≈ 22.317291, 113.950292. Place search pin ≈ 22.317343, 113.955271. |
| 高鐵西九龍、西九龍站（過關／高鐵） | Out of scope for cross-boundary rail | — | — | Local buses to the building are OK (`西九龍站` ≈ 22.304021, 114.166529; place `香港西九龍站` ≈ 22.303298, 114.165180) but do not sell a 高鐵 journey. |
| 中國客運碼頭 | `中國客運碼頭` | 22.299460 | 114.165840 | Ferry control point; sailings to Mainland ports are not a graph product beyond pier access. |
| 港澳客輪碼頭 | `港澳客輪碼頭出入境管制站` | 22.288839 | 114.152303 | |

When substituting, tell the user the canonical name and coordinates you used. If road vs Spur Line (落馬洲／皇崗／福田) is ambiguous, ask once before searching.

## Answer

Answer the person in Traditional Chinese.

- Name a direction by its destination station, for example 往中環. Do not say a direction code.
- Cite `dataset_id` and the endpoint you actually called. Both can be lists when one command reads several files; name them, do not read every URL aloud. `sources` keeps each source's own timestamp.
- Give the time of the data. Use `data_at` in Hong Kong time. When `data_at` is null, cite `update_frequency` instead: it says how fresh the source is, and a source with no timestamp has no better answer. If both are missing, say what `note` says about the time.
- If `data` is null, say `note`. Do not fill the gap.
- Quote `note`. Do not rewrite it into a stronger claim.
- A distance you compute from coordinates is straight-line, not walking time.

### One journey

Any point-to-point question goes to `journey.sh journey`. It searches the railway, the buses and the green minibuses as **one graph**, with walking at both ends and between stops.

- **Ranking is a policy, not a measurement.** Bus/minibus/tram/ferry waits use the TD GTFS headway when it exists (`1.5 × min(H/2, 20)` minutes) and routes outside service hours are removed. MTR first/last comes from the MTR website snapshot; MTR headway is a per-line policy estimate because MTR does not publish it as open data. MTR adds a per-line speed and a per-stop dwell, while bus/minibus use the operator's published whole-route time pro rata. Every boarding also adds a 4-minute transfer penalty. Walking is 15 minutes per kilometre. Rail has the cheapest board and the highest speed, so a long rail ride can outrank a short bus loop. The command's `note` repeats the current values; say they are assumptions, not measurements. `score` is a policy weight, not minutes — never quote it as a journey time.
- **Pass `--time` when the person gives a departure time.** `HH:MM` uses today; a full `YYYY-MM-DD HH:MM` is also accepted. Without it, the current Hong Kong time is used.
- **Walking is real, not straight-line.** Metres and minutes come from the Lands Department pedestrian network. A leg marked `estimated: true` means that network had no route and the figure is straight-line — say which it is.
- **Night routes are marked and ranked last.** A route code starting with `N` gets `overnight_hint: true` and sorts after every day option. Say so when it appears — there is no service-hours data, so the flag is a warning, not a timetable.
- **There is no riding time.** Never add up a total duration. The walk minutes are the only minutes the answer contains.
- **Scope: MTR, KMB/LWB, Citybus, NLB, MTR feeder buses, green minibus, tram, ferry, plus a few outlying-island and cross-boundary routes.** The Peak Tram, taxi and high-speed rail are **not** in the graph — the Peak Tram deliberately, because its queue is the real cost and we have no data for it. When the answer looks short, that may be why.
- No fares are included; use the per-mode fare commands.

### Buses

- Single-mode lists still exist (`mtr_fare`, `bus_route`, `minibus_route`), but journeys are answered by `journey.sh` only.
- Options, not one best route. Present them as alternatives and let the person choose. Never call one 最快 or 最好: cost is transfers then stops, not minutes.
- A bus fare is the **adult full fare** for boarding that route. It is not a section fare, and it excludes concessions and transfer discounts. Several legs mean several boardings; say the total is the sum of adult fares, not the amount the person will pay.
- `journey_time_minutes` is the whole route's published running time, not the segment ridden. Never present it as the trip time.
- Bus answers cover **KMB and LWB**. Journeys are answered by `journey.sh`, which does include Citybus, NLB and minibus; the per-mode bus commands do not.
- Service hours, headway and low-floor access have no data. The commands answer `null` and say why; do not estimate them.
- A disruption match is a keyword hit in Transport Department notices. No match does not mean no disruption, and notices do not always name routes.

### Trams and ferries

- Tram lines have **names, not numbers** (「筲箕灣 - 跑馬地線」). Search with a word from the name.
- **Eastbound and westbound tram stops are different stops.** Do not merge them.
- The tram fare is **flat**; boarding again after alighting costs another fare.
- **Ferry data carries no operator.** Answer with the route and the piers, never 「新渡輪」 or 「天星」 — the file does not say.
- Ferry fares are adult full fares, not section fares.
- There is **no tram arrival data, no ferry timetable and no next boat**. Those commands answer `null` and say why; do not estimate a sailing from memory.

### Minibuses

- **A route code is unique only inside a district.** `37` exists in more than one of `HKI`, `KLN`, `NT`. When a code matches several, the answer lists all of them — say which district, and never narrow it to one yourself.
- The per-mode minibus commands never include buses or the railway. Journeys across modes go through `journey.sh`.
- The fare is the **adult full fare** for boarding that route. It is not a section fare, and it excludes every concession.
- `journey_time_minutes` is the whole route's published time, not the segment ridden.
- Real-time arrivals need **a stop**. There is no whole-route next-bus endpoint, so a route alone cannot be answered; ask for the stop.
- Service hours, headway and low-floor access have no data. Those commands answer `null` and say why; do not estimate.
- **Red minibuses have no fixed routes, no published stops and no fares.** `red_minibus` answers that and nothing more.

### Everywhere else

- An accessibility answer says what the file says. A lift is 「閘外區域」(outside the paid area) or 「已付車費區域」(inside it), and the exit it serves. Do not upgrade that to "goes to the street" — the file never states a level. A lift marked 非港鐵管理 is not maintained by MTR but is still there; say so. An exit written 「A 和 D 出口」 covers both exits and cannot be split.
- The nearest-station combination (`mtr_exits` plus a walking radius) has no public command. For a point-to-point question use `journey`; for one named station use `mtr_exits`. Do not widen `mtr_exits` to answer「最近邊個站」.
- If no command covers the question, say this skill has no data for it.
- If the script exits with an error, report that message. Do not guess a train, a bus or a fare.
- Run a command once per question. Do not poll, and never loop on the traffic feeds.
