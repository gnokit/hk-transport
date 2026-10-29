---
name: hk-transport
description: >
  Use when the user asks, in Chinese or English, about Hong Kong MTR (港鐵):
  next train (下一班), fare (車費), route, Light Rail (輕鐵), MTR bus, a
  station exit, or a traffic disruption. Also /hk-transport. Not franchised
  bus, minibus, tram, ferry, or high-speed rail.
compatibility: Requires uv and Python >=3.13. $SKILL_DIR is the directory that contains mtr.sh.
---

# hk-transport（港交寶）

Answer a Hong Kong MTR question by running `mtr.sh`. Do not write a fetcher. Do not invent a figure the tool did not return.

**Scope: MTR heavy rail, Airport Express, Disneyland Resort Line, Light Rail, MTR feeder buses, address lookup, the heavy-rail exit snapshot, and territory-wide special-traffic notices.** Franchised bus, green minibus, tram, ferry, taxi, red minibus, and cross-boundary rail are out of scope.

> If the request is out of scope, say "This is outside hk-transport." Leave KMB and ferry programs in hkdata. Do not copy them.

## Choose a command from the manual

`$SKILL_DIR` is the directory where this skill is installed. The command list grows. This file does not list commands.

```bash
bash ${SKILL_DIR}/mtr.sh
bash ${SKILL_DIR}/mtr.sh help <command>
```

No arguments and `help` print the same page: a short introduction, then one line per command. Read `help <command>` before you run that command. stdout of a command is JSON.

## Answer

Answer the person in Traditional Chinese.

- Name a direction by its destination station, for example 往中環. Do not say a direction code.
- Cite `dataset_id`, `endpoint`, and `data_at` (Hong Kong time). If `data_at` is null, say what `note` says about the time.
- If `data` is null, say `note`. Do not fill the gap.
- Quote `note`. Do not rewrite it into a stronger claim.
- A distance you compute from coordinates is straight-line, not walking time.
- If no command covers the question, say this skill has no data for it.
- If the script exits with an error, report that message. Do not guess a train or a fare.
