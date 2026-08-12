/**
 * Upstream zborle persisted the board and stats in localStorage. Here the server is the
 * single source of truth, so that persistence is gone: stats are shared with the Discord
 * bot and feed the leaderboard, and a browser-owned copy would just drift.
 *
 * The `GameStats` shape survives unchanged because StatsModals, StatBar and Histogram
 * render against it, and keeping it lets those components stay identical to upstream.
 */

export type GameStats = {
    winDistribution: number[]
    gamesFailed: number
    currentStreak: number
    bestStreak: number
    totalGames: number
    successRate: number
}

export const emptyStats: GameStats = {
    winDistribution: [0, 0, 0, 0, 0, 0],
    gamesFailed: 0,
    currentStreak: 0,
    bestStreak: 0,
    totalGames: 0,
    successRate: 0,
}
