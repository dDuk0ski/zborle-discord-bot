/**
 * Live progress socket.
 *
 * Connects through the same `/.proxy/` path as the REST calls, so Discord's CSP allows
 * it under the existing URL mapping. The access token is sent in the first message
 * rather than the query string: URLs end up in logs and history, tokens should not.
 */

import type { CharStatus } from './statuses'

export type Participant = {
    userId: string
    displayName: string
    avatarUrl: string | null
    guessCount: number
    isWon: boolean
    isLost: boolean
    /** Colours only. Letters are never sent, so a spectator cannot derive the answer. */
    rows: CharStatus[][]
}

type Handlers = {
    onParticipants: (players: Participant[]) => void
}

const RECONNECT_MS = 3000

export class LiveConnection {
    private socket: WebSocket | null = null
    private closed = false
    private retry: number | null = null

    constructor(
        private readonly instanceId: string,
        private readonly token: string,
        private readonly handlers: Handlers,
    ) {}

    connect(): void {
        if (this.closed) return

        const url = `wss://${window.location.host}/.proxy/api/ws`
        const socket = new WebSocket(url)
        this.socket = socket

        socket.onopen = () => {
            socket.send(JSON.stringify({ token: this.token, instance_id: this.instanceId }))
        }

        socket.onmessage = (event) => {
            try {
                const payload = JSON.parse(event.data)
                if (payload.type === 'participants') {
                    this.handlers.onParticipants(payload.players as Participant[])
                }
            } catch {
                // Ignore malformed frames rather than tearing down a working session.
            }
        }

        socket.onclose = () => {
            this.socket = null
            if (!this.closed) {
                // Discord suspends iframes when backgrounded, so drops are routine.
                this.retry = window.setTimeout(() => this.connect(), RECONNECT_MS)
            }
        }

        socket.onerror = () => socket.close()
    }

    close(): void {
        this.closed = true
        if (this.retry !== null) window.clearTimeout(this.retry)
        this.socket?.close()
        this.socket = null
    }
}
