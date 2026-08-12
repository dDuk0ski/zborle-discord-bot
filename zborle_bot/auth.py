"""Discord OAuth2 for the Activity.

The browser can only ever hand us an access token. We resolve it to a user id by asking
Discord, and cache that mapping briefly. Nothing the client claims about its own identity
is trusted: a client-supplied user id would let anyone write to anyone's leaderboard row.
"""

import os
import time
from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException

DISCORD_API = 'https://discord.com/api/v10'
# Short enough that a revoked token stops working quickly, long enough that a six-guess
# game does not make six identity round-trips to Discord.
CACHE_TTL_SECONDS = 300


@dataclass(frozen=True)
class DiscordUser:
    id: str
    username: str
    display_name: str
    avatar_url: str | None


_cache: dict[str, tuple[float, DiscordUser]] = {}


def _avatar_url(user: dict) -> str | None:
    if not user.get('avatar'):
        return None
    return f'https://cdn.discordapp.com/avatars/{user["id"]}/{user["avatar"]}.png'


async def exchange_code(code: str) -> str:
    """Trade an OAuth2 code for an access token. The client secret never leaves the server."""
    client_id = os.getenv('DISCORD_CLIENT_ID')
    client_secret = os.getenv('DISCORD_CLIENT_SECRET')
    if not client_id or not client_secret:
        raise HTTPException(500, 'DISCORD_CLIENT_ID/DISCORD_CLIENT_SECRET не се поставени на серверот.')

    async with httpx.AsyncClient(timeout=10) as http:
        response = await http.post(
            f'{DISCORD_API}/oauth2/token',
            data={
                'client_id': client_id,
                'client_secret': client_secret,
                'grant_type': 'authorization_code',
                'code': code,
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )

    if response.status_code != 200:
        raise HTTPException(401, f'Размената на кодот не успеа: {response.status_code}')

    token = response.json().get('access_token')
    if not token:
        raise HTTPException(401, 'Одговорот од Discord не содржи access_token.')
    return token


async def resolve_user(access_token: str) -> DiscordUser:
    cached = _cache.get(access_token)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    async with httpx.AsyncClient(timeout=10) as http:
        response = await http.get(
            f'{DISCORD_API}/users/@me',
            headers={'Authorization': f'Bearer {access_token}'},
        )

    if response.status_code != 200:
        raise HTTPException(401, 'Невалиден или истечен токен.')

    payload = response.json()
    user = DiscordUser(
        id=str(payload['id']),
        username=payload.get('username', ''),
        display_name=payload.get('global_name') or payload.get('username', ''),
        avatar_url=_avatar_url(payload),
    )
    _cache[access_token] = (time.monotonic() + CACHE_TTL_SECONDS, user)
    return user


async def current_user(authorization: str = Header(default='')) -> DiscordUser:
    """FastAPI dependency: turns the Authorization header into a verified identity."""
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise HTTPException(401, 'Недостасува Bearer токен.')
    return await resolve_user(token)
