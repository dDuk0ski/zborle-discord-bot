# Зборле - Discord бот

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
server's ID - guild-scoped commands register instantly, whereas global commands can take
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
value, the rest of the code needs no changes.

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

State lives in `db/zborle.db`, keyed by `(user_id, puzzle_index)` - one attempt per
person per day, shared across every server the bot is in. Only the guesses are stored;
colors, win state and stats are all derived.

## Deploying to Fly.io

```bash
brew install flyctl && fly auth login
```

Then, from the project directory:

```bash
fly launch --no-deploy
```

Answer no when it offers to overwrite `fly.toml`. If the app name is taken it will pick
another; that is fine. Create the volume for the SQLite file, in the same region as
`primary_region`:

```bash
fly volumes create zborle_data --size 1 --region fra
```

Set the token as a secret. It is encrypted at rest and never enters the image or git:

```bash
fly secrets set BOT_TOKEN=paste_your_token_here
```

Deploy, then pin it to exactly one machine:

```bash
fly deploy --remote-only && fly scale count 1
```

```bash
fly logs
```

You should see `Најавен како Zborle Bot#8244` and `Денешен збор: #NNN`.

### Two things that will bite you

**Run exactly one machine.** Fly likes to start two. Two machines means two gateway
connections, and the bot answers every command twice. `fly scale count 1` is not
optional. Check with `fly status`.

**Commands are registered globally in production.** `DEV_GUILD_ID` is deliberately not
set in `fly.toml`, so the deployed bot registers global commands that work in every
server it joins. Global commands can take up to an hour to appear. If you previously ran
the bot locally with `DEV_GUILD_ID` set, that server still has guild-scoped copies
registered and you will see each command listed twice. Clear them once:

```bash
curl -X PUT -H "Authorization: Bot $BOT_TOKEN" -H "Content-Type: application/json" -d '[]' "https://discord.com/api/v10/applications/YOUR_APP_ID/guilds/YOUR_GUILD_ID/commands"
```

### Updating

```bash
fly deploy --remote-only
```

The volume persists across deploys, so player stats and streaks survive.

## License

MIT, see [LICENSE](LICENSE).

The word lists and the daily-word schedule come from
[zborle/wordle](https://github.com/zborle/wordle), which is MIT licensed, and that
notice is carried in `LICENSE` as MIT requires. The bundled Noto Sans Bold is under the
SIL Open Font License 1.1, included at [fonts/LICENSE-NotoSans.txt](fonts/LICENSE-NotoSans.txt).

[JaredIsaacs/worlde-discord](https://github.com/JaredIsaacs/worlde-discord) inspired the
overall structure but publishes no license, so none of its code is reproduced here.
