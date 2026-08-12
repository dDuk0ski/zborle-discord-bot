/**
 * Backend client.
 *
 * Every request goes through `/.proxy/`. Discord serves Activities from a sandboxed
 * iframe whose CSP blocks any request to a host that is not declared as a URL Mapping,
 * and the proxy strips the `/.proxy` prefix before forwarding to our own origin.
 */

import type { CharStatus } from './statuses'

const API_BASE = '/.proxy/api'

let accessToken: string | null = null

export const setAccessToken = (token: string) => {
    accessToken = token
}

export type GameState = {
    puzzleIndex: number
    guesses: string[]
    statuses: CharStatus[][]
    isWon: boolean
    isLost: boolean
    /** Only ever populated once the game is over. */
    solution: string | null
    secondsUntilNext: number
}

export type GuessResult =
    | { ok: true; statuses: CharStatus[]; isWon: boolean; isLost: boolean; solution: string | null }
    | { ok: false; error: 'not_a_word' | 'wrong_length' | 'duplicate' | 'game_over'; message: string }

export type LeaderboardRow = {
    userId: string
    displayName: string
    avatarUrl: string | null
    played: number
    won: number
    currentStreak: number
    maxStreak: number
    averageGuesses: number | null
}

export type Participant = {
    userId: string
    displayName: string
    avatarUrl: string | null
    guessCount: number
    isWon: boolean
    isLost: boolean
    /** Per-row colours only. Letters are never broadcast, so nobody can leak answers. */
    rows: CharStatus[][]
}

class ApiError extends Error {}

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
        throw new ApiError(`${init.method ?? 'GET'} ${path} failed: ${response.status}`)
    }
    return (await response.json()) as T
}

/** Exchanges the OAuth2 code for an access token. The client secret stays server-side. */
export const exchangeToken = (code: string) => request<{ access_token: string }>('/token', { method: 'POST', body: JSON.stringify({ code }) })

export const fetchState = (instanceId: string | null) =>
    request<GameState>(`/state${instanceId ? `?instance_id=${encodeURIComponent(instanceId)}` : ''}`)

export const submitGuess = (guess: string, instanceId: string | null) =>
    request<GuessResult>('/guess', { method: 'POST', body: JSON.stringify({ guess, instance_id: instanceId }) })

export const fetchLeaderboard = (guildId: string | null) =>
    request<{ rows: LeaderboardRow[] }>(`/leaderboard${guildId ? `?guild_id=${encodeURIComponent(guildId)}` : ''}`)

export const fetchParticipants = (instanceId: string) =>
    request<{ participants: Participant[] }>(`/participants?instance_id=${encodeURIComponent(instanceId)}`)
