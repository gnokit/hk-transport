# Contributing

Thanks for helping with `hk-transport`（港交寶）. This repository is an AI agent
skill: the agent talks to the person, and the scripts return facts. Keep that
split in every change.

## Setup

```bash
uv sync
uv run pytest
uv run pytest -m live -o addopts=   # live endpoints; opt-in, never gates CI
uv run ruff check .
```

Python 3.13+ and [uv](https://docs.astral.sh/uv/) are required.

## Before you start

- Read [AGENTS.md](AGENTS.md) for the repo rules and the per-mode traps.
- Read [docs/TASKS.md](docs/TASKS.md) for the agreed scope.
- Check [docs/BACKLOG.md](docs/BACKLOG.md) for known gaps. Do not add a mode or
  command that is not in scope.

## What a change should contain

- **One function does one thing.** Core modules wrap one dataset per function;
  answer modules wrap one citizen question and hold no URL or cache.
- **Every envelope is auditable.** Keep `dataset_id`, the endpoint called,
  `data_at`/`update_frequency`, and per-source detail.
- **Absence is an answer.** Do not fill a missing field with a plausible value.
- **Tests.** Add offline tests for new behaviour. Live checks are marked `live`
  and must not gate CI.
- **Docs.** Update `SKILL.md` when agent-facing instructions change, and
  `docs/TASKS.md` or `docs/BACKLOG.md` when scope or a known gap changes.

## Pull requests

Fill in `.github/pull_request_template.md`. In particular:

- run `uv run pytest` and `uv run ruff check .`;
- run `uv run pytest -m live -o addopts=` if the change touches an endpoint;
- say which citizen question the change answers and which dataset it reads.

GitHub may not report checks for a pull request opened from a fork. Maintainers
should run the full suite locally before merging; contributors should paste the
commands and results in the PR description.

## Data and licensing

Data comes from DATA.GOV.HK and is subject to its terms. The bundled exit
snapshot is derived from Lands Department data and is covered by [NOTICE](NOTICE),
not by the MIT licence that covers the code.

## Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).
