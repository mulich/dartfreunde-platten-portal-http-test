import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.recovery import observe_account, token_subject


def token(subject):
    payload = base64.urlsafe_b64encode(json.dumps({'sub':subject}).encode()).decode().rstrip('=')
    return 'header.' + payload + '.signature'


def test_identity_observer_stores_only_subject_and_ignores_other_origins():
    handlers = {}
    identities = {}
    context = SimpleNamespace(on=lambda name, callback: handlers.update({name:callback}))
    observe_account(context, 'session', identities)
    bearer = token('real-user')
    async def check():
        await handlers['request'](SimpleNamespace(url='https://other.example/',all_headers=AsyncMock(return_value={'authorization':'Bearer '+bearer})))
        assert identities == {}
        await handlers['request'](SimpleNamespace(url='https://api.autodarts.com/as/v0/friends',all_headers=AsyncMock(return_value={'authorization':'Bearer '+bearer})))
        assert identities == {'session':'real-user'}
        await handlers['response'](SimpleNamespace(url='https://api.autodarts.com/auth/v1/refresh',status=200,json=AsyncMock(return_value={'access_token':token('new-user'),'refresh_token':'never-store'})))
        assert identities == {'session':'new-user'}
    asyncio.run(check())
    assert token_subject('bad') is None
    assert token_subject(token(None)) is None
