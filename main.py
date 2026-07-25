"""Entry point. Loads .env before anything reads configuration from the environment."""

from dotenv import load_dotenv

load_dotenv()

from zborle_bot.bot import run  # noqa: E402  -- must follow load_dotenv

if __name__ == '__main__':
    run()
