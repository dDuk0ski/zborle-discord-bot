import { getGuessStatuses } from './statuses'
import { getWordOfDayIndex } from './words'
import { shareToChannel } from './api'

export type ShareOutcome = 'posted' | 'copied' | 'failed'

export const buildShareText = (guesses: string[]) =>
    `Зборле ${getWordOfDayIndex()} ${guesses.length}/6\n\n${generateEmojiGrid(
        guesses,
    )}\n\nИграјте ЗБОРЛЕ https://zborle.mk`

/**
 * Discord's Activity iframe blocks clipboard writes through Permissions Policy, and the
 * upstream call neither awaited nor caught the rejection, so the button silently did
 * nothing. Inside Discord we post through the bot instead, which is what sharing is
 * actually for. Outside Discord we still copy, with a fallback for browsers that refuse
 * the async clipboard API.
 */
export const shareStatus = async (guesses: string[], instanceId: string | null): Promise<ShareOutcome> => {
    if (instanceId) {
        try {
            const result = await shareToChannel(instanceId)
            if (result.ok) {
                return 'posted'
            }
        } catch {
            // Fall through to the clipboard attempt below.
        }
    }

    const text = buildShareText(guesses)

    try {
        await navigator.clipboard.writeText(text)
        return 'copied'
    } catch {
        return copyViaTextarea(text) ? 'copied' : 'failed'
    }
}

/** Last resort for contexts where the async clipboard API is unavailable. */
function copyViaTextarea(text: string): boolean {
    try {
        const area = document.createElement('textarea')
        area.value = text
        area.setAttribute('readonly', '')
        area.style.position = 'fixed'
        area.style.opacity = '0'
        document.body.appendChild(area)
        area.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(area)
        return ok
    } catch {
        return false
    }
}

export const generateEmojiGrid = (guesses: string[]) => {
    return guesses
        .map((guess) => {
            const status = getGuessStatuses(guess)
            return guess
                .split('')
                .map((_, i) => {
                    switch (status[i]) {
                        case 'correct':
                            return '🟩'
                        case 'present':
                            return '🟨'
                        default:
                            return '⬜'
                    }
                })
                .join('')
        })
        .join('\n')
}
