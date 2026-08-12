/**
 * Embedded App SDK bootstrap.
 *
 * Discord loads the Activity in a sandboxed iframe and hands it a `frame_id` and
 * `instance_id` on the query string. Nothing works until `ready()` resolves, and the
 * backend will not answer without an access token, so this runs once before React mounts.
 *
 * Outside Discord (`npm run dev` in a plain browser) there is no frame to talk to, so we
 * fall back to an unauthenticated standalone mode rather than hanging on `ready()`.
 */

import { DiscordSDK } from '@discord/embedded-app-sdk'

import { exchangeToken, setAccessToken } from './api'

export type Session = {
    /** False when running outside Discord, e.g. local `vite dev`. */
    embedded: boolean
    instanceId: string | null
    guildId: string | null
    channelId: string | null
}

const CLIENT_ID = import.meta.env.VITE_DISCORD_CLIENT_ID as string | undefined

let sdk: DiscordSDK | null = null

export const getSdk = () => sdk

/** True when the page is actually running inside a Discord Activity frame. */
const isEmbedded = () => new URLSearchParams(window.location.search).has('frame_id')

export async function startSession(): Promise<Session> {
    if (!isEmbedded()) {
        return { embedded: false, instanceId: null, guildId: null, channelId: null }
    }

    if (!CLIENT_ID) {
        throw new Error('VITE_DISCORD_CLIENT_ID не е поставен при билдот.')
    }

    sdk = new DiscordSDK(CLIENT_ID)
    await sdk.ready()

    // `prompt: 'none'` keeps returning users from seeing a consent screen every launch.
    const { code } = await sdk.commands.authorize({
        client_id: CLIENT_ID,
        response_type: 'code',
        state: '',
        prompt: 'none',
        scope: ['identify', 'guilds'],
    })

    // Only the backend holds the client secret, so it performs the exchange.
    const { access_token } = await exchangeToken(code)
    await sdk.commands.authenticate({ access_token })

    // Every later API call carries this; the server resolves it to a user id itself
    // rather than trusting anything the client claims about who it is.
    setAccessToken(access_token)

    return {
        embedded: true,
        instanceId: sdk.instanceId ?? null,
        guildId: sdk.guildId ?? null,
        channelId: sdk.channelId ?? null,
    }
}
