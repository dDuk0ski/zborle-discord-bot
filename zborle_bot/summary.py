"""Group board rendering for channel messages.

Draws several players' boards side by side as colour-only grids, the way official
Wordle's session and daily-summary messages do. Letters are never drawn: these messages
are public, and rendering letters would leak the answer to anyone who has not played.
"""

import io
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

from . import config
from .board import Status

CARD_PAD = 16
CARD_RADIUS = 14
CARD_GAP = 14

MINI_CELL = 22
MINI_GAP = 4

AVATAR_SIZE = 56
AVATAR_GAP = 12

NAME_FONT_SIZE = 15
TITLE_FONT_SIZE = 22
TITLE_GAP = 18

# Darker surface than the in-game board: these render inside Discord's dark chrome.
COLOR_BACKGROUND = '#2b2d31'
COLOR_CARD = '#1e1f22'
COLOR_CARD_EDGE = '#3f4147'
COLOR_EMPTY = '#3a3c41'
COLOR_TITLE = '#f2f3f5'
COLOR_NAME = '#b5bac1'

TILE_COLORS = {
    Status.ABSENT: '#4b4d52',
    Status.PRESENT: '#c8b653',
    Status.CORRECT: '#6ca965',
}


@dataclass
class PlayerBoard:
    display_name: str
    rows: list[list[Status]] = field(default_factory=list)
    avatar: bytes | None = None


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(config.FONT_PATH), size)


def _circular_avatar(data: bytes | None) -> Image.Image | None:
    if not data:
        return None
    try:
        source = Image.open(io.BytesIO(data)).convert('RGBA')
    except Exception:
        # A broken or unfetchable avatar must not take down the whole render.
        return None

    source = source.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    mask = Image.new('L', (AVATAR_SIZE, AVATAR_SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, AVATAR_SIZE - 1, AVATAR_SIZE - 1), fill=255)
    source.putalpha(mask)
    return source


def _grid_size() -> tuple[int, int]:
    width = config.WORD_LENGTH * MINI_CELL + (config.WORD_LENGTH - 1) * MINI_GAP
    height = config.MAX_GUESSES * MINI_CELL + (config.MAX_GUESSES - 1) * MINI_GAP
    return width, height


def render_group_board(boards: list[PlayerBoard], puzzle_index: int) -> bytes:
    """Render every player's grid as one image, one card per player."""
    if not boards:
        raise ValueError('Нема играчи за прикажување.')

    grid_w, grid_h = _grid_size()
    card_w = max(grid_w, AVATAR_SIZE) + CARD_PAD * 2
    card_h = CARD_PAD + AVATAR_SIZE + AVATAR_GAP + grid_h + AVATAR_GAP + NAME_FONT_SIZE + CARD_PAD

    title_font = _font(TITLE_FONT_SIZE)
    name_font = _font(NAME_FONT_SIZE)

    width = CARD_PAD + len(boards) * (card_w + CARD_GAP) - CARD_GAP + CARD_PAD
    title_h = TITLE_FONT_SIZE + TITLE_GAP
    height = CARD_PAD + title_h + card_h + CARD_PAD

    image = Image.new('RGB', (width, height), COLOR_BACKGROUND)
    draw = ImageDraw.Draw(image)

    draw.text(
        (width / 2, CARD_PAD + TITLE_FONT_SIZE / 2),
        f'Зборле #{puzzle_index}',
        font=title_font,
        fill=COLOR_TITLE,
        anchor='mm',
    )

    top = CARD_PAD + title_h
    for index, board in enumerate(boards):
        left = CARD_PAD + index * (card_w + CARD_GAP)
        draw.rounded_rectangle(
            (left, top, left + card_w, top + card_h),
            CARD_RADIUS,
            fill=COLOR_CARD,
            outline=COLOR_CARD_EDGE,
            width=1,
        )

        avatar = _circular_avatar(board.avatar)
        avatar_x = int(left + (card_w - AVATAR_SIZE) / 2)
        avatar_y = top + CARD_PAD
        if avatar is not None:
            image.paste(avatar, (avatar_x, avatar_y), avatar)
        else:
            draw.ellipse(
                (avatar_x, avatar_y, avatar_x + AVATAR_SIZE, avatar_y + AVATAR_SIZE),
                fill=COLOR_EMPTY,
            )

        grid_x = left + (card_w - grid_w) / 2
        grid_y = avatar_y + AVATAR_SIZE + AVATAR_GAP
        for row in range(config.MAX_GUESSES):
            for column in range(config.WORD_LENGTH):
                x = grid_x + column * (MINI_CELL + MINI_GAP)
                y = grid_y + row * (MINI_CELL + MINI_GAP)
                played = row < len(board.rows) and column < len(board.rows[row])
                fill = TILE_COLORS[board.rows[row][column]] if played else COLOR_EMPTY
                draw.rounded_rectangle((x, y, x + MINI_CELL, y + MINI_CELL), 3, fill=fill)

        name = board.display_name
        while name and draw.textlength(name, font=name_font) > card_w - CARD_PAD:
            name = name[:-1]
        draw.text(
            (left + card_w / 2, grid_y + grid_h + AVATAR_GAP + NAME_FONT_SIZE / 2),
            name or '?',
            font=name_font,
            fill=COLOR_NAME,
            anchor='mm',
        )

    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()
