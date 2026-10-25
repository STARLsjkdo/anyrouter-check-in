import httpx

from checkin import get_user_info


def test_agentrouter_uses_official_backup_when_primary_returns_html():
	requests = []

	def respond(request):
		requests.append(request)
		if request.url.host == 'agentrouter.org':
			return httpx.Response(200, text='<html>Service challenge</html>')
		return httpx.Response(200, json={'success': True, 'data': {'quota': 500000, 'used_quota': 0}})

	with httpx.Client(transport=httpx.MockTransport(respond)) as client:
		result = get_user_info(client, {'new-api-user': '12345'}, 'https://agentrouter.org/api/user/self')

	assert result['success'] is True
	assert result['quota'] == 1.0
	assert len(requests) == 2
	assert requests[1].url == 'https://ps.air-outer.com/api/user/self'
	assert requests[1].headers['new-api-user'] == '12345'
	assert requests[1].headers['origin'] == 'https://ps.air-outer.com'


def test_agentrouter_reports_non_json_backup_without_looping_or_logging_body(capsys):
	requests = []

	def respond(request):
		requests.append(request)
		return httpx.Response(403, text='<html>private response body</html>')

	with httpx.Client(transport=httpx.MockTransport(respond)) as client:
		result = get_user_info(client, {}, 'https://agentrouter.org/api/user/self')

	assert result['success'] is False
	assert result['error'] == 'Failed to get user info: HTTP 403, non-JSON response'
	assert len(requests) == 2
	assert 'private response body' not in capsys.readouterr().out


def test_authentication_failure_does_not_retry_backup():
	requests = []

	def respond(request):
		requests.append(request)
		return httpx.Response(401, json={'success': False, 'message': 'Invalid session'})

	with httpx.Client(transport=httpx.MockTransport(respond)) as client:
		result = get_user_info(client, {}, 'https://agentrouter.org/api/user/self')

	assert result['success'] is False
	assert len(requests) == 1


def test_other_provider_never_sends_credentials_to_agentrouter_backup():
	requests = []

	def respond(request):
		requests.append(request)
		return httpx.Response(200, text='<html>Service challenge</html>')

	with httpx.Client(transport=httpx.MockTransport(respond)) as client:
		result = get_user_info(client, {}, 'https://anyrouter.top/api/user/self')

	assert result['success'] is False
	assert len(requests) == 1
