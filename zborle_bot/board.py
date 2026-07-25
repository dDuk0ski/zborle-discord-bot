"""Game state, scoring, and PNG rendering of a player's board."""

import io
from enum import IntEnum
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from . import config
from .words import GuessError, clean_guess


class Status(IntEnum):
    ABSENT = 0
    PRESENT = 1
    CORRECT = 2


TILE_COLORS = {
    Status.ABSENT: config.COLOR_ABSENT,
    Status.PRESENT: config.COLOR_PRESENT,
    Status.CORRECT: config.COLOR_CORRECT,
}

EMOJI = {
    Status.ABSENT: '⬜',
    Status.PRESENT: '🟨',
    Status.CORRECT: '🟩',
}


def score_guess(guess: str, solution: str) -> list[Status]:
    """Wordle scoring: exact matches first, then present-letters against what's left over.

    The two passes matter for repeated letters -- a second 'А' in the guess is only
    yellow if the solution has an 'А' that no green tile already claimed.
    """
    statuses = [Status.ABSENT] * len(guess)
    remaining: dict[str, int] = {}

    for i, char in enumerate(guess):
        if char == solution[i]:
            statuses[i] = Status.CORRECT
        else:
            remaining[solution[i]] = remaining.get(solution[i], 0) + 1

    for i, char in enumerate(guess):
        if statuses[i] is Status.CORRECT:
            continue
        if remaining.get(char, 0) > 0:
            statuses[i] = Status.PRESENT
            remaining[char] -= 1

    return statuses


class Game:
    """One player's attempt at one day's word."""

    def __init__(self, solution: str, guesses: list[str] | None = None):
        self.solution = solution.upper()
        self.guesses = list(guesses or [])

    @property
    def rows(self) -> list[tuple[str, list[Status]]]:
        return [(guess, score_guess(guess, self.solution)) for guess in self.guesses]

    @property
    def is_won(self) -> bool:
        return bool(self.guesses) and self.guesses[-1] == self.solution

    @property
    def is_lost(self) -> bool:
        return not self.is_won and len(self.guesses) >= config.MAX_GUESSES

    @property
    def is_over(self) -> bool:
        return self.is_won or self.is_lost

    @property
    def guesses_left(self) -> int:
        return config.MAX_GUESSES - len(self.guesses)

    def add_guess(self, raw: str) -> list[Status]:
        if self.is_over:
            raise GuessError('Играта за денес е завршена.')

        guess = clean_guess(raw)
        if guess in self.guesses:
            raise GuessError(f'Веќе го проба „{guess}“.')

        self.guesses.append(guess)
        return score_guess(guess, self.solution)

    def letter_statuses(self) -> dict[str, Status]:
        """Best status seen so far per letter, for coloring the keyboard."""
        best: dict[str, Status] = {}
        for guess, statuses in self.rows:
            for char, status in zip(guess, statuses):
                if status > best.get(char, -1):
                    best[char] = status
        return best

    def emoji_grid(self) -> str:
        return '\n'.join(''.join(EMOJI[s] for s in statuses) for _, statuses in self.rows)

    def share_text(self, puzzle_index: int) -> str:
        score = len(self.guesses) if self.is_won else 'X'
        return (
            f'Зборле {puzzle_index} {score}/{config.MAX_GUESSES}\n\n'
            f'{self.emoji_grid()}\n\n'
            'Играјте ЗБОРЛЕ https://zborle.mk'
        )

    def render(self) -> bytes:
        """Draw the grid and keyboard, returning PNG bytes."""
        image = Image.new('RGB', (config.BOARD_WIDTH, config.BOARD_HEIGHT), config.COLOR_BACKGROUND)
        draw = ImageDraw.Draw(image)

        self._draw_grid(draw)
        self._draw_keyboard(draw)

        buffer = io.BytesIO()
        image.save(buffer, 'PNG')
        return buffer.getvalue()

    def _draw_grid(self, draw: ImageDraw.ImageDraw) -> None:
        font = _font(config.TILE_FONT_SIZE)
        rows = self.rows
        step = config.CELL_SIZE + config.CELL_GAP

        for row in range(config.MAX_GUESSES):
            y = config.BOARD_PAD + row * step
            for col in range(config.WORD_LENGTH):
                x = config.BOARD_PAD + col * step
                box = (x, y, x + config.CELL_SIZE, y + config.CELL_SIZE)

                if row < len(rows):
                    char, statuses = rows[row][0][col], rows[row][1][col]
                    draw.rounded_rectangle(box, config.CELL_RADIUS, fill=TILE_COLORS[statuses])
                    draw.text(
                        (x + config.CELL_SIZE / 2, y + config.CELL_SIZE / 2),
                        char,
                        font=font,
                        fill=config.COLOR_TILE_TEXT,
                        anchor='mm',
                    )
                else:
                    draw.rounded_rectangle(
                        box,
                        config.CELL_RADIUS,
                        fill=config.COLOR_BACKGROUND,
                        outline=config.COLOR_EMPTY_BORDER,
                        width=3,
                    )

    def _draw_keyboard(self, draw: ImageDraw.ImageDraw) -> None:
        font = _font(config.KEY_FONT_SIZE)
        statuses = self.letter_statuses()
        top = config.BOARD_PAD + config.GRID_HEIGHT + config.KEYBOARD_MARGIN_TOP
        step_x = config.KEY_WIDTH + config.KEY_GAP
        step_y = config.KEY_HEIGHT + config.KEY_GAP

        for row_index, row in enumerate(config.KEYBOARD_ROWS):
            row_width = len(row) * config.KEY_WIDTH + (len(row) - 1) * config.KEY_GAP
            left = (config.BOARD_WIDTH - row_width) / 2
            y = top + row_index * step_y

            for key_index, char in enumerate(row):
                x = left + key_index * step_x
                status = statuses.get(char)
                fill = TILE_COLORS[status] if status is not None else config.COLOR_UNUSED
                text_color = config.COLOR_TILE_TEXT if status is not None else config.COLOR_UNUSED_TEXT

                draw.rounded_rectangle(
                    (x, y, x + config.KEY_WIDTH, y + config.KEY_HEIGHT),
                    config.KEY_RADIUS,
                    fill=fill,
                )
                draw.text(
                    (x + config.KEY_WIDTH / 2, y + config.KEY_HEIGHT / 2),
                    char,
                    font=font,
                    fill=text_color,
                    anchor='mm',
                )


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(config.FONT_PATH), size)
