import httpx
import pytest

import checkin
from utils.config import AccountConfig, AppConfig


@pytest.mark.parametrize('json_response', [True, False])
def test_unauthorized_profile_is_actionable_and_never_retries_backup(json_response, capsys):
	requests = []

	def respond(request):
		requests.append(request)
		if json_response:
			return httpx.Response(401, json={'success': False, 'message': 'private-response-message'})
		return httpx.Response(401, text='private-response-body')

	with httpx.Client(transport=httpx.MockTransport(respond)) as client:
		result = checkin.get_user_info(client, {}, 'https://agentrouter.org/api/user/self')

	assert result['success'] is False
	assert result['status_code'] == 401
	assert 'session may have expired or api_user may not match' in result['error']
	assert 'production Secret' in result['error']
	assert 'site password' in result['error']
	assert 'private-response' not in result['error']
	assert 'private-response' not in capsys.readouterr().out
	assert len(requests) == 1


def test_manual_sign_in_stops_after_rejected_authentication(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)
	requests = []
	real_client = httpx.Client

	def respond(request):
		requests.append(request)
		return httpx.Response(401, json={'success': False})

	monkeypatch.setattr(checkin.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(respond)))
	provider = AppConfig.load_from_env().providers['anyrouter']
	success, before, after = checkin.run_check_in_requests({}, AccountConfig(cookies=None), 'AnyRouter', provider)

	assert success is False
	assert before is not None
	assert after is not None
	assert before['status_code'] == 401
	assert after['status_code'] == 401
	assert [(request.method, request.url.path) for request in requests] == [('GET', '/api/user/self')]


def test_transient_profile_failure_does_not_prevent_manual_sign_in(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)
	requests = []
	real_client = httpx.Client

	def respond(request):
		requests.append(request)
		if len(requests) == 1:
			return httpx.Response(503, json={'success': False})
		if request.method == 'POST':
			return httpx.Response(200, json={'success': True})
		return httpx.Response(200, json={'success': True, 'data': {'quota': 500000, 'used_quota': 0}})

	monkeypatch.setattr(checkin.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(respond)))
	provider = AppConfig.load_from_env().providers['anyrouter']
	success, before, after = checkin.run_check_in_requests({}, AccountConfig(cookies=None), 'AnyRouter', provider)

	assert success is True
	assert before is not None and before['success'] is False
	assert after is not None and after['success'] is True
	assert [(request.method, request.url.path) for request in requests] == [
		('GET', '/api/user/self'),
		('POST', '/api/user/sign_in'),
		('GET', '/api/user/self'),
	]
