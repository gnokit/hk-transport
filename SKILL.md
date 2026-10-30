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
  專線小巴): which route, stops, fare, next minibus. Also /hk-transport.
  Not tram, ferry, or high-speed rail.
compatibility: Requires uv and Python >=3.13. $SKILL_DIR is the directory that contains mtr.sh, bus.sh and minibus.sh.
---

# hk-transport（港交寶）

Answer a Hong Kong transport question by running one of this skill's scripts. Do not write a fetcher. Do not invent a figure a command did not return.

**Scope: MTR heavy rail, Airport Express, Disneyland Resort Line, Light Rail, MTR feeder buses, address lookup, the heavy-rail exit snapshot, and the two Transport Department feeds — live special-traffic news and advance arrangements. Plus franchised buses (KMB and LWB) and green minibuses.** Out of scope today: Citybus and New Lantao Bus answers, tram, ferry, taxi, cross-boundary rail and high-speed rail.

> If the request is out of scope, say 「這個問題超出 hk-transport（港交寶）的範圍。」 Leave KMB and ferry programs in hkdata. Do not copy them.

## Choose a command from the manual

Two entry points, one contract each:

```bash
bash ${SKILL_DIR}/mtr.sh      # MTR and its feeders, plus place search
bash ${SKILL_DIR}/bus.sh      # franchised buses
bash ${SKILL_DIR}/minibus.sh  # green minibuses
```

No arguments and `help` print the same page: a short introduction, then one line per command. Read `help <command>` when its arguments are not obvious. stdout of a command is JSON.

If you do not know a station, stop, line or place name, look it up first. `bash ${SKILL_DIR}/mtr.sh place_search <name>` turns a place or facility name into a point. MTR: `mtr_lines --line` or `--station`. Bus: `bus_stops_near` for stops near a place, `bus_route` for the stops on a route. Names must match the official spelling exactly — the MTR file spells 茘枝角 with 茘, not 荔. A station id (`2`) or code (`ADM`) also works for MTR; a stop id works for buses.

## When a name does not match

A command may answer 「找不到車站：…」, 「找不到路線：…」, 「400 米內沒有九巴／龍運站。最近的是…」, or 「這個站不在這條線上。」 That means the input did not match the published name — not that the place has no service.

- Do not guess a similar place, and do not re-run the same input expecting a different result.
- Look the name up with `mtr_lines` or `bus_stops_near`, then run the command again.
- Check the line as well as the station: a correct station on the wrong line fails the same way.
- Common traps: 茘枝角 is spelled with 茘; English names use the published form (`Tsim Sha Tsui`, `AsiaWorld-Expo`); 中環, 香港 and 機場快線香港站 are names for one interchange area.
- If it still does not resolve, say the skill cannot find it. Do not substitute a nearby place.

Place names are resolved by the Lands Department place search, which knows places and facilities, not just buildings. Two consequences:

- A district name (元朗, 尖沙咀) becomes **one point**, not the whole district. Say which point was used, and do not treat it as covering the district.
- When the answer names the nearest stop and a straight-line distance, that means **no bus stop is inside the walking radius**. Report it as it stands: the place has no bus stop that close, and the nearest one is that far away. Never quietly use the further stop.

## When a name matches more than one station

A few names are two stations: 香港 has an Airport Express id and a Tung Chung line id. A command may answer with `matches` (or `origin_matches` and `destination_matches`), with one entry per matching station, or with one fare pair per station, and says so in `note`.

- Do not choose one yourself. Say which stations matched, and ask which one the person means.
- Or run the command again with the station id or code, which settles it.
- Never add up, average, or subset the answer across those stations.

## Answer

Answer the person in Traditional Chinese.

- Name a direction by its destination station, for example 往中環. Do not say a direction code.
- Cite `dataset_id` and the endpoint you actually called. Both can be lists when one command reads several files; name them, do not read every URL aloud. `sources` keeps each source's own timestamp.
- Give the time of the data. Use `data_at` in Hong Kong time. When `data_at` is null, cite `update_frequency` instead: it says how fresh the source is, and a source with no timestamp has no better answer. If both are missing, say what `note` says about the time.
- If `data` is null, say `note`. Do not fill the gap.
- Quote `note`. Do not rewrite it into a stronger claim.
- A distance you compute from coordinates is straight-line, not walking time.

### Buses

- A bus journey answers with **options**, not one best route. Present them as alternatives and let the person choose. Never call one 最快 or 最好: cost is transfers then stops, not minutes.
- A bus fare is the **adult full fare** for boarding that route. It is not a section fare, and it excludes concessions and transfer discounts. Several legs mean several boardings; say the total is the sum of adult fares, not the amount the person will pay.
- `journey_time_minutes` is the whole route's published running time, not the segment ridden. Never present it as the trip time.
- Bus answers cover **KMB and LWB**. A journey will not include Citybus, NLB or minibuses, and cannot transfer between operators — say so when it changes the answer.
- Service hours, headway and low-floor access have no data. The commands answer `null` and say why; do not estimate them.
- A disruption match is a keyword hit in Transport Department notices. No match does not mean no disruption, and notices do not always name routes.

### Minibuses

- **A route code is unique only inside a district.** `37` exists in more than one of `HKI`, `KLN`, `NT`. When a code matches several, the answer lists all of them — say which district, and never narrow it to one yourself.
- A minibus journey is green minibus only. It cannot use a bus or the railway, and cannot transfer between operators. Say so when it changes the answer.
- The fare is the **adult full fare** for boarding that route. It is not a section fare, and it excludes every concession.
- `journey_time_minutes` is the whole route's published time, not the segment ridden.
- Real-time arrivals need **a stop**. There is no whole-route next-bus endpoint, so a route alone cannot be answered; ask for the stop.
- Service hours, headway and low-floor access have no data. Those commands answer `null` and say why; do not estimate.
- **Red minibuses have no fixed routes, no published stops and no fares.** `red_minibus` answers that and nothing more.

### Everywhere else

- An accessibility answer says what the file says. A lift is 「閘外區域」(outside the paid area) or 「已付車費區域」(inside it), and the exit it serves. Do not upgrade that to "goes to the street" — the file never states a level. A lift marked 非港鐵管理 is not maintained by MTR but is still there; say so. An exit written 「A 和 D 出口」 covers both exits and cannot be split.
- If no command covers the question, say this skill has no data for it.
- If the script exits with an error, report that message. Do not guess a train, a bus or a fare.
- Run a command once per question. Do not poll, and never loop on the traffic feeds.
