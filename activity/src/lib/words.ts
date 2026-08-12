/**
 * Puzzle schedule.
 *
 * Upstream zborle computes the daily index in the browser from a 2022-01-01 epoch and
 * looks the answer up in a bundled word list. Neither the list nor the index lives here:
 * the server owns both, pins the timezone to Europe/Skopje so every player gets the same
 * word, and hands us only the index plus a countdown.
 *
 * `getWordOfDayIndex`, `getTimeUntilNextWord`, `Time` and `formatTime` keep their upstream
 * signatures so share.ts and the modals are unchanged.
 */

let puzzleIndex = 0
/** Wall-clock ms at which the current word expires, derived from the server countdown. */
let rolloverAt = 0

export const setSchedule = (index: number, secondsUntilNext: number) => {
    puzzleIndex = index
    rolloverAt = Date.now() + secondsUntilNext * 1000
}

export const getWordOfDayIndex = () => puzzleIndex

export const getTimeUntilNextWord = () => {
    const remaining = Math.max(0, rolloverAt - Date.now())
    return {
        hours: Math.floor(remaining / 3600000),
        minutes: Math.floor((remaining % 3600000) / 60000),
        seconds: Math.floor((remaining % 60000) / 1000),
        solutionIndex: puzzleIndex,
    }
}

/** True once the countdown has elapsed, so the app can refetch instead of guessing. */
export const hasRolledOver = () => rolloverAt > 0 && Date.now() >= rolloverAt

export type Time = {
    hours: number
    minutes: number
    seconds: number
}

export const formatTime = (time: number) => (time >= 10 ? `${time}` : `0${time}`)
