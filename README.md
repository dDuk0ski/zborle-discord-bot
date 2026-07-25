# Зборле — Discord бот

Macedonian Wordle for Discord. Each player gets their own private board, and the daily
word is the same one [zborle.mk](https://zborle.mk) is showing.

Word lists and the daily-word schedule come from [zborle/wordle](https://github.com/zborle/wordle);
the bot structure follows [JaredIsaacs/worlde-discord](https://github.com/JaredIsaacs/worlde-discord).

## Commands

| Command | What it does |
| --- | --- |
| `/зборле збор:<збор>` | Make a guess. Replies privately with your board. |
| `/табла` | Show your board for today. |
| `/сподели` | Post your emoji grid in the channel (only after you finish). |
| `/статистика` | Games played, win rate, streaks, guess distribution. |
| `/помош` | Rules and command list. |

Guesses must be five letters of Macedonian Cyrillic. Everything except `/сподели`
replies ephemerally, so nobody else in the channel sees your board.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Create an application at the [Discord Developer Portal](https://discord.com/developers/applications),
add a Bot, and copy its token:

```bash
cp .env.example .env
```

Put the token in `BOT_TOKEN`. While developing, also set `DEV_GUILD_ID` to your test
server's ID — guild-scoped commands register instantly, whereas global commands can take
up to an hour to appear.

Invite the bot with the `applications.commands` and `bot` scopes. It needs no privileged
intents: everything runs through slash commands, so Message Content stays off.

```bash
.venv/bin/python main.py
```

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

The suite checks scoring against a direct port of zborle.mk's own `getGuessStatuses`
over 20,000 random word pairs, and checks the daily-word index against a port of the
site's millisecond formula at hourly resolution across two years.

## How the daily word is chosen

zborle.mk computes:

```js
index = Math.floor((Date.now() - 1640995200000 - tzOffsetMs) / 86400000) % WORDS.length
```

Subtracting the timezone offset shifts the epoch millisecond count onto the local wall
clock, so this is just "whole local days elapsed since 2022-01-01, mod 964". The bot
computes it as a date difference instead, which is equivalent and stays correct across
daylight-saving transitions.

The site uses each visitor's own timezone. The bot pins it to `Europe/Skopje`, so the
word rolls over at Skopje midnight. Override with `ZBORLE_TIMEZONE` if needed.

**The answer is public.** The formula and the word list are both in a public repo, and
anyone can open zborle.mk to read today's word. This is inherent to matching the site.
If you would rather the bot be uncheatable, change `word_of_day` in
[words.py](zborle_bot/words.py) to draw from a shuffled ordering seeded with a private
value — the rest of the code needs no changes.

`data/wordlist.txt` order is load-bearing: the daily word is looked up by position.
Do not sort or dedupe it. `data/valid-guesses.txt` is order-independent.

## Layout

```
main.py               entry point
zborle_bot/
  config.py           paths, board geometry, zborle.mk color palette
  words.py            word lists, daily-word schedule, guess validation
  board.py            scoring, game state, PNG rendering
  db.py               SQLite persistence and stats
  bot.py              Discord client and slash commands
data/                 964 answers, 13,033 valid guesses
fonts/                Noto Sans Bold (SIL OFL), covers all 31 Macedonian letters
tests/
```

State lives in `db/zborle.db`, keyed by `(user_id, puzzle_index)` — one attempt per
person per day, shared across every server the bot is in. Only the guesses are stored;
colors, win state and stats are all derived.
