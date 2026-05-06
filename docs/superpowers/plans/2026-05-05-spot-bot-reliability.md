# Spot Bot Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Spot Bot accurately track image-based campus spottings, including multi-person photos, edits, deletes, and safe backfills.

**Architecture:** Extract message parsing into a small testable module, store one row per spotted person per Discord message, and compute leaderboards from those rows. Keep SQLite for the current scale, with Docker Compose mounting a persistent `/data` directory for VPS hosting.

**Tech Stack:** Python 3, discord.py, aiosqlite, pytest, pytest-asyncio, Docker Compose.

---

### Task 1: Message Parsing

**Files:**
- Create: `spotting.py`
- Create: `tests/test_spotting.py`
- Modify: `requirements.txt`

- [ ] Write tests for image attachment detection, unique non-bot mentions, and spotter count equal to number of spotted users.
- [ ] Run the tests and verify they fail because `spotting.py` does not exist.
- [ ] Implement `parse_spotting_message(message)` and supporting dataclass.
- [ ] Run the tests and verify they pass.
- [ ] Commit with message `feat: validate spotting messages`.

### Task 2: Event-Based Storage

**Files:**
- Modify: `database.py`
- Create: `tests/test_database.py`

- [ ] Write tests proving one message with three mentioned users gives the poster three spots and each mentioned user one spotted count.
- [ ] Run the tests and verify they fail against the aggregate counter schema.
- [ ] Replace aggregate tables with `spot_messages` and `spottings`, preserving config storage and adding idempotent upsert/delete helpers.
- [ ] Run the database tests and verify they pass.
- [ ] Commit with message `feat: store individual spottings`.

### Task 3: Bot Reconciliation

**Files:**
- Modify: `bot.py`
- Modify: `tests/test_spotting.py`

- [ ] Write tests for edit/delete reconciliation using parser/database functions where practical.
- [ ] Run the tests and verify they fail before bot handlers are wired.
- [ ] Update `on_message`, `on_message_edit`, `on_message_delete`, and `/backfill` to use idempotent message replacement instead of incrementing counters.
- [ ] Run all tests and Python compilation.
- [ ] Commit with message `fix: reconcile spotting message changes`.

### Task 4: Guild-Scoped Config

**Files:**
- Modify: `database.py`
- Modify: `bot.py`
- Modify: `tests/test_database.py`

- [ ] Write tests proving config values are isolated by guild.
- [ ] Run the tests and verify they fail with global config.
- [ ] Add `guild_id` to config operations while retaining simple legacy migration.
- [ ] Run all tests.
- [ ] Commit with message `fix: scope config by guild`.

### Task 5: Deployment

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `ARCHITECTURE.md`

- [ ] Add container files using `/data/spot_bot.db`.
- [ ] Document Discord intents, persistent SQLite storage, backups, and VPS run commands.
- [ ] Run final verification.
- [ ] Commit with message `chore: add docker deployment setup`.
