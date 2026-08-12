/**
 * Backend client.
 *
 * Every request goes through `/.proxy/`. Discord serves Activities from a sandboxed
 * iframe whose CSP blocks any request to a host that is not declared as a URL Mapping,
 * and the proxy strips the `/.proxy` prefix before forwarding to our own origin.
 *
 * Only endpoints that actually exist server-side live here; the leaderboard and
 * live-participant calls arrive with their endpoints.
 */

import type { CharStatus } from './statuses'
import type { ServerStats } from './stats'

const API_BASE = '/.proxy/api'

let accessToken: string | null = null

export const setAccessToken = (token: string) => {
    accessToken = token
}

export const getAccessToken = () => accessToken

export type GameState = {
    puzzleIndex: number
    guesses: string[]
    statuses: CharStatus[][]
    isWon: boolean
    isLost: boolean
    /** Null until the game is over. The answer is never sent to a winnable board. */
    solution: string | null
    secondsUntilNext: number
    maxGuesses: number
}

export type GuessResult =
    | { ok: true; statuses: CharStatus[]; isWon: boolean; isLost: boolean; solution: string | null }
    | {
          ok: false
          error: 'not_a_word' | 'not_cyrillic' | 'wrong_length' | 'duplicate' | 'game_over'
          message: string
      }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...((init.headers as Record<string, string>) ?? {}),
    }
    if (accessToken) {
        headers.Authorization = `Bearer ${accessToken}`
    }

    const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
    if (!response.ok) {
        throw new Error(`${init.method ?? 'GET'} ${path} -> ${response.status}`)
    }
    return (await response.json()) as T
}

/** Exchanges the OAuth2 code for an access token. The client secret stays server-side. */
export const exchangeToken = (code: string) =>
    request<{ access_token: string }>('/token', { method: 'POST', body: JSON.stringify({ code }) })

export type LeaderboardRow = {
    userId: string
    displayName: string
    avatarUrl: string | null
    played: number
    won: number
    winPercent: number
    currentStreak: number
    maxStreak: number
    averageGuesses: number | null
}

const withGuild = (path: string, guildId: string | null) =>
    guildId ? `${path}?guild_id=${encodeURIComponent(guildId)}` : path

export const fetchState = (
    guildId: string | null = null,
    channelId: string | null = null,
    instanceId: string | null = null,
) => {
    const params = new URLSearchParams()
    if (guildId) params.set('guild_id', guildId)
    // Lets the server post the daily summary where the game is actually played.
    if (channelId) params.set('channel_id', channelId)
    // Ties this player to the live session message for their activity instance.
    if (instanceId) params.set('instance_id', instanceId)
    const query = params.toString()
    return request<GameState>(query ? `/state?${query}` : '/state')
}

export const fetchLeaderboard = (guildId: string | null) =>
    request<{ rows: LeaderboardRow[]; scope: 'guild' | 'dm' }>(withGuild('/leaderboard', guildId))

export const submitGuess = (
    guess: string,
    context: { instanceId?: string | null; guildId?: string | null; channelId?: string | null } = {},
) =>
    request<GuessResult>('/guess', {
        method: 'POST',
        body: JSON.stringify({
            guess,
            instance_id: context.instanceId ?? null,
            guild_id: context.guildId ?? null,
            channel_id: context.channelId ?? null,
        }),
    })

export const fetchStats = () => request<ServerStats>('/stats')
