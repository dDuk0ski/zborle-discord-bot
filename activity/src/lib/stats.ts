import { GameStats, emptyStats } from './localStorage'

/**
 * Stats come from the server, which computes them from the same games table the Discord
 * bot writes to. Upstream recomputed them in the browser and saved to localStorage;
 * doing that here would let anyone hand themselves a 100% win rate on the leaderboard.
 */

export type ServerStats = {
    played: number
    won: number
    currentStreak: number
    maxStreak: number
    distribution: Record<string, number>
}

export const toGameStats = (server: ServerStats): GameStats => {
    // Upstream indexes winDistribution by guess count, 1..6 -> slots 0..5.
    const winDistribution = [0, 0, 0, 0, 0, 0]
    for (const [score, count] of Object.entries(server.distribution)) {
        const index = Number(score) - 1
        if (index >= 0 && index < winDistribution.length) {
            winDistribution[index] = count
        }
    }

    return {
        winDistribution,
        gamesFailed: server.played - server.won,
        currentStreak: server.currentStreak,
        bestStreak: server.maxStreak,
        totalGames: server.played,
        successRate: server.played ? Math.round((100 * server.won) / server.played) : 0,
    }
}

export const loadStats = (): GameStats => emptyStats
