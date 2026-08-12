/**
 * Tile colours.
 *
 * Upstream zborle derives these in the browser by comparing each guess against the
 * solution. That cannot work here: the solution is never sent to the client, because a
 * leaderboard built on client-reported results is trivially forged. Instead the server
 * scores every guess and we cache what it returns, keyed by the guess.
 *
 * The exported signatures are unchanged from upstream so Grid, CompletedRow,
 * MiniCompletedRow, Keyboard and share.ts work against this file untouched.
 */

export type CharStatus = 'absent' | 'present' | 'correct'

export type CharValue =
    | 'Љ'
    | 'Њ'
    | 'Е'
    | 'Р'
    | 'Т'
    | 'Ѕ'
    | 'У'
    | 'И'
    | 'О'
    | 'П'
    | 'Ш'
    | 'Ѓ'
    | 'Ж'
    | 'А'
    | 'С'
    | 'Д'
    | 'Ф'
    | 'Г'
    | 'Х'
    | 'Ј'
    | 'К'
    | 'Л'
    | 'Ч'
    | 'Ќ'
    | 'З'
    | 'Џ'
    | 'Ц'
    | 'В'
    | 'Б'
    | 'Н'
    | 'М'

const RANK: Record<CharStatus, number> = { absent: 0, present: 1, correct: 2 }

const scored = new Map<string, CharStatus[]>()

/** Cache the server's verdict for a single guess. */
export const recordGuessStatuses = (guess: string, statuses: CharStatus[]) => {
    scored.set(guess, statuses)
}

/** Replace the whole cache, e.g. when loading state or rolling over to a new day. */
export const replaceGuessStatuses = (guesses: string[], statuses: CharStatus[][]) => {
    scored.clear()
    guesses.forEach((guess, i) => {
        if (statuses[i]) {
            scored.set(guess, statuses[i])
        }
    })
}

export const getGuessStatuses = (guess: string): CharStatus[] => scored.get(guess) ?? []

export const getStatuses = (guesses: string[]): { [key: string]: CharStatus } => {
    const charObj: { [key: string]: CharStatus } = {}

    guesses.forEach((word) => {
        const statuses = scored.get(word)
        if (!statuses) {
            return
        }
        word.split('').forEach((letter, i) => {
            const status = statuses[i]
            if (!status) {
                return
            }
            const existing = charObj[letter]
            // Best-known status wins, so a letter marked absent in one guess is never
            // downgraded from a correct hit in another.
            if (existing === undefined || RANK[status] > RANK[existing]) {
                charObj[letter] = status
            }
        })
    })

    return charObj
}
