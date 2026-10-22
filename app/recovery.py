"""Match portal sessions by observed account ID; never retain authentication tokens."""
import base64
import json
from urllib.parse import urlsplit


def token_subject(token):
    try:
        encoded = token.split('.')[1]
        subject = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))['sub']
        return subject if isinstance(subject, str) and subject else None
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def observe_account(context, ident, identities):
    async def request(event):
        if urlsplit(event.url).netloc != 'api.autodarts.com':
            return
        headers = await event.all_headers()
        value = headers.get('authorization', '')
        if value.lower().startswith('bearer '):
            subject = token_subject(value[7:])
            if subject:
                identities[ident] = subject

    async def response(event):
        url = urlsplit(event.url)
        if url.netloc != 'api.autodarts.com' or not url.path.startswith('/auth/v1/') or not 200 <= event.status < 300:
            return
        try:
            subject = token_subject((await event.json()).get('access_token', ''))
            if subject:
                identities[ident] = subject
        except Exception:
            pass

    context.on('request', request)
    context.on('response', response)
