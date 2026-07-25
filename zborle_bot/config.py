"""Static configuration: paths, board geometry and the zborle.mk color palette."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

ANSWERS_PATH = BASE_DIR / 'data' / 'wordlist.txt'
GUESSES_PATH = BASE_DIR / 'data' / 'valid-guesses.txt'
FONT_PATH = BASE_DIR / 'fonts' / 'NotoSans-Bold.ttf'
DB_PATH = Path(os.getenv('ZBORLE_DB_PATH', BASE_DIR / 'db' / 'zborle.db'))

WORD_LENGTH = 5
MAX_GUESSES = 6

# Macedonian Cyrillic keyboard, same three rows as zborle.mk's on-screen keyboard.
KEYBOARD_ROWS = ('ЉЊЕРТЅУИОПШЃЖ', 'АСДФГХЈКЛЧЌ', 'ЗЏЦВБНМ')
MK_ALPHABET = frozenset(''.join(KEYBOARD_ROWS))

# Tailwind *-500 shades, matching zborle.mk's light theme.
COLOR_CORRECT = '#22c55e'   # green-500
COLOR_PRESENT = '#eab308'   # yellow-500
COLOR_ABSENT = '#64748b'    # slate-500
COLOR_UNUSED = '#e2e8f0'    # slate-200, for untouched keyboard keys
COLOR_EMPTY_BORDER = '#cbd5e1'  # slate-300
COLOR_BACKGROUND = '#ffffff'
COLOR_TILE_TEXT = '#ffffff'
COLOR_UNUSED_TEXT = '#1e293b'  # slate-800

# Board geometry, in pixels.
CELL_SIZE = 96
CELL_GAP = 10
CELL_RADIUS = 8
BOARD_PAD = 16
TILE_FONT_SIZE = 56

KEY_WIDTH = 36
KEY_HEIGHT = 46
KEY_GAP = 5
KEY_RADIUS = 5
KEY_FONT_SIZE = 20
KEYBOARD_MARGIN_TOP = 22

BOARD_WIDTH = WORD_LENGTH * CELL_SIZE + (WORD_LENGTH - 1) * CELL_GAP + 2 * BOARD_PAD
GRID_HEIGHT = MAX_GUESSES * CELL_SIZE + (MAX_GUESSES - 1) * CELL_GAP
KEYBOARD_HEIGHT = len(KEYBOARD_ROWS) * KEY_HEIGHT + (len(KEYBOARD_ROWS) - 1) * KEY_GAP
BOARD_HEIGHT = BOARD_PAD + GRID_HEIGHT + KEYBOARD_MARGIN_TOP + KEYBOARD_HEIGHT + BOARD_PAD
