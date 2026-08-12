# AGENTS.md

## Cursor Cloud specific instructions

Зборле is a single Python product: a Macedonian Wordle bot for Discord. There is no web
server, no port to expose, and no external database server — it is one long-running
Discord gateway worker plus an embedded SQLite file. Standard setup/run/test commands
live in `README.md`; only the non-obvious cloud caveats are captured here.

### Environment
- Dependencies are installed into a project virtualenv at `.venv/` (created by the
  startup update script). Run everything through it, e.g. `.venv/bin/python`,
  `.venv/bin/pytest`.
- `pytest` is a dev-only dependency and is intentionally **not** in `requirements.txt`;
  the update script installs it separately. Do not add it to `requirements.txt`.
- The system package `python3.12-venv` is required to create the venv and is already
  baked into the VM snapshot (installed via apt). It is not part of the update script.

### Running / testing
- Tests: `.venv/bin/python -m pytest tests/ -q` — fully offline, no token or network
  needed. This is the fastest way to validate changes.
- Lint: the repo has **no** configured linter (no ruff/flake8/pyproject). Use
  `.venv/bin/python -m compileall main.py zborle_bot tests` as a syntax check.
- Run the bot: `.venv/bin/python main.py`.

### Discord token caveat (important)
- The bot **requires a real `BOT_TOKEN`** (Discord developer application token) to run
  end-to-end. Without it, `main.py` exits immediately with a Macedonian message asking
  you to set it. With an invalid token it boots the discord.py client and fails Discord
  login with `401 Unauthorized` — so a valid token is the only missing piece to go live.
- A real token cannot be fabricated here. To fully exercise the live Discord flow, add
  `BOT_TOKEN` (and optionally `DEV_GUILD_ID` for instant slash-command registration in a
  test server) as a secret / in a local `.env` (copy `.env.example`).
- The **core game engine is fully testable offline** without Discord: `zborle_bot.words`
  (daily word), `zborle_bot.board.Game` (scoring + PNG board rendering), and
  `zborle_bot.db.ZborleDB` (SQLite persistence + stats) are exactly what the slash
  commands call internally. Import and drive these directly to verify behavior and to
  render the same board PNG the bot uploads.

### Data / state
- SQLite state lives at `db/zborle.db` by default (override with `ZBORLE_DB_PATH`). The
  `db/` directory is auto-created on first run and is gitignored.
- `data/wordlist.txt` order is load-bearing (the daily word is looked up by index). Never
  sort or dedupe it. `data/valid-guesses.txt` is order-independent.
