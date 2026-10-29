---
name: hk-transport
description: >
  Use when the user asks, in Chinese or English, about Hong Kong MTR (港鐵):
  next train (下一班), fare (車費), route (路線), journey and interchange
  (轉車), ride time (幾耐), Light Rail (輕鐵), MTR bus (港鐵巴士), a station
  exit (出口), barrier-free facilities (無障礙設施), an address (地址), or a
  traffic disruption (交通消息). Also /hk-transport. Not franchised bus,
  minibus, tram, ferry, or high-speed rail.
compatibility: Requires uv and Python >=3.13. $SKILL_DIR is the directory that contains mtr.sh.
---

# hk-transport（港交寶）

Answer a Hong Kong MTR question by running `mtr.sh`. This skill is phase 1 of hk-transport: it covers MTR and its feeders. Do not write a fetcher. Do not invent a figure the command did not return.

**Scope: MTR heavy rail, Airport Express, Disneyland Resort Line, Light Rail, MTR feeder buses, address lookup, the heavy-rail exit snapshot, and the two Transport Department feeds — live special-traffic news and advance special-traffic arrangements.** Franchised bus, green minibus, tram, ferry, taxi, red minibus, and cross-boundary rail are out of scope.

> If the request is out of scope, say 「這個問題超出 hk-transport（港交寶）的範圍。」 Leave KMB and ferry programs in hkdata. Do not copy them.

## Choose a command from the manual

`$SKILL_DIR` is the directory where this skill is installed. The command list grows. This file does not list commands.

```bash
bash ${SKILL_DIR}/mtr.sh
bash ${SKILL_DIR}/mtr.sh help <command>
```

No arguments and `help` print the same page: a short introduction, then one line per command. Read `help <command>` when its arguments are not obvious. stdout of a command is JSON.

If you do not know a station, stop, or line name, run `mtr_lines` first. `mtr_lines --line 東鐵線` lists the stations on one line; `mtr_lines --station 金鐘` lists the lines through one station. The name must match the official spelling exactly — the file spells 茘枝角 with 茘, not 荔. A station id (`2`) or code (`ADM`) also works, and is never ambiguous.

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
- If no command covers the question, say this skill has no data for it.
- If the script exits with an error, report that message. Do not guess a train or a fare.
- Run a command once per question. Do not poll, and never loop on the traffic feeds.
