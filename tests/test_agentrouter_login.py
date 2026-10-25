import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import checkin
from utils.browser import BrowserLoginResult
from utils.config import AccountConfig, AppConfig


@pytest.fixture
def app_config(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)
	return AppConfig.load_from_env()


@pytest.mark.asyncio
async def test_cookie_only_agentrouter_fails_without_browser_or_network(app_config, monkeypatch):
	prepare = AsyncMock()
	login = AsyncMock()
	run_requests = MagicMock()
	monkeypatch.setattr(checkin, 'prepare_cookies', prepare)
	monkeypatch.setattr(checkin, 'login_with_credentials', login)
	monkeypatch.setattr(checkin, 'run_check_in_requests', run_requests)
	account = AccountConfig(cookies={'session': 'private-session'}, api_user='123', provider='agentrouter')

	success, before, after = await checkin.check_in_account(account, 0, app_config)

	assert success is False
	assert before is None
	assert after['success'] is False
	assert 'fresh username/password login' in after['error']
	prepare.assert_not_called()
	login.assert_not_called()
	run_requests.assert_not_called()


@pytest.fixture
def browser_login(monkeypatch):
	settings = SimpleNamespace(
		wait_timeout_ms=100,
		profile_dir='unused-profile',
		persist_profile=False,
		headless=True,
		humanize=False,
	)
	load_settings = MagicMock(return_value=settings)
	context = SimpleNamespace(
		new_page=AsyncMock(),
		cookies=AsyncMock(return_value=[{'name': 'session', 'value': 'private-session'}]),
		close=AsyncMock(),
	)
	page = SimpleNamespace(url='https://agentrouter.org/console', expect_response=MagicMock())
	context.new_page.return_value = page
	monkeypatch.setattr(checkin, 'load_browser_login_settings', load_settings)
	monkeypatch.setattr(checkin, 'launch_login_context', AsyncMock(return_value=context))
	monkeypatch.setattr(checkin, 'prepare_browser_page', AsyncMock())
	monkeypatch.setattr(checkin, 'navigate_login_page', AsyncMock())
	monkeypatch.setattr(checkin, 'is_logged_in', AsyncMock(return_value=False))
	monkeypatch.setattr(checkin, 'has_session_cookie', AsyncMock(return_value=False))
	monkeypatch.setattr(checkin, 'save_login_screenshot', AsyncMock())
	login_form = AsyncMock()
	verify_login = AsyncMock(return_value={'id': 123})
	monkeypatch.setattr(checkin, 'login_with_email_form', login_form)
	monkeypatch.setattr(checkin, 'verify_browser_login', verify_login)
	return SimpleNamespace(
		page=page, context=context, load_settings=load_settings, login_form=login_form, verify_login=verify_login
	)


def set_login_response(browser_login, payload, status=200):
	response = SimpleNamespace(
		url='https://agentrouter.org/api/user/login?turnstile=token',
		request=SimpleNamespace(method='POST'),
		status=status,
		json=AsyncMock(return_value=payload),
	)
	if isinstance(payload, Exception):
		response.json.side_effect = payload
	response_value = asyncio.get_running_loop().create_future()
	response_value.set_result(response)
	response_context = MagicMock()
	response_context.__aenter__ = AsyncMock(return_value=SimpleNamespace(value=response_value))
	response_context.__aexit__ = AsyncMock(return_value=False)
	browser_login.page.expect_response.return_value = response_context
	return response


@pytest.mark.asyncio
@pytest.mark.parametrize(
	'payload,status',
	[
		(ValueError('private-response-body'), 200),
		({'success': False, 'data': {'checked_in': True}}, 200),
		({'success': 1, 'data': {'checked_in': True}}, 200),
		({'success': True, 'data': {}}, 200),
		({'success': True, 'data': {'checked_in': 'true'}}, 200),
		({'success': True, 'data': {'checked_in': 1}}, 200),
		({'success': True, 'data': {'checked_in': True}}, 403),
		([], 200),
	],
)
async def test_agentrouter_login_rejects_unverified_credit_response(app_config, browser_login, payload, status, capsys):
	set_login_response(browser_login, payload, status)
	result = await checkin.login_with_credentials(
		'AgentRouter', app_config.providers['agentrouter'], 'agentrouter', 'username', 'private-password'
	)

	assert result is None
	browser_login.verify_login.assert_not_awaited()
	assert 'private-response-body' not in capsys.readouterr().out
	browser_login.context.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('checked_in', [True, False])
async def test_agentrouter_login_carries_verified_boolean_and_captures_exact_endpoint(
	app_config, browser_login, checked_in
):
	response = set_login_response(browser_login, {'success': True, 'data': {'checked_in': checked_in}})
	app_config.providers['agentrouter'].persist_profile = True
	result = await checkin.login_with_credentials(
		'AgentRouter', app_config.providers['agentrouter'], 'agentrouter', 'username', 'private-password'
	)

	assert result == BrowserLoginResult({'session': 'private-session'}, '123', checked_in)
	assert browser_login.load_settings.call_args.kwargs['persist_profile'] is False
	predicate = browser_login.page.expect_response.call_args.args[0]
	assert predicate(response) is True
	assert predicate(SimpleNamespace(url=response.url, request=SimpleNamespace(method='GET'))) is False
	assert (
		predicate(
			SimpleNamespace(
				url='https://agentrouter.org.evil.invalid/api/user/login', request=SimpleNamespace(method='POST')
			)
		)
		is False
	)
	assert (
		predicate(SimpleNamespace(url='https://other.invalid/api/user/login', request=SimpleNamespace(method='POST')))
		is False
	)


@pytest.mark.asyncio
async def test_agentrouter_existing_browser_session_is_not_a_fresh_claim(app_config, browser_login, monkeypatch):
	monkeypatch.setattr(checkin, 'is_logged_in', AsyncMock(return_value=True))
	result = await checkin.login_with_credentials(
		'AgentRouter', app_config.providers['agentrouter'], 'agentrouter', 'username', 'private-password'
	)

	assert result is None
	browser_login.page.expect_response.assert_not_called()
	browser_login.verify_login.assert_not_awaited()


@pytest.mark.asyncio
async def test_agentrouter_passes_login_credit_result_to_requests(app_config, monkeypatch):
	monkeypatch.setattr(
		checkin,
		'login_with_credentials',
		AsyncMock(return_value=BrowserLoginResult({'session': 'new-session'}, '123', True)),
	)
	run_requests = MagicMock(return_value=(True, None, {'success': True}))
	monkeypatch.setattr(checkin, 'run_check_in_requests', run_requests)
	account = AccountConfig(cookies=None, provider='agentrouter', email='username', password='private-password')

	assert (await checkin.check_in_account(account, 0, app_config))[0] is True
	assert run_requests.call_args.kwargs['login_checked_in'] is True
	assert run_requests.call_args.kwargs['api_user_override'] == '123'


@pytest.mark.parametrize('checked_in', [True, False])
def test_agentrouter_success_depends_on_login_credit_and_reads_balance_once(
	app_config, monkeypatch, checked_in, capsys
):
	requests = []
	real_client = httpx.Client

	def respond(request):
		requests.append(request)
		return httpx.Response(200, json={'success': True, 'data': {'quota': 500000, 'used_quota': 0}})

	monkeypatch.setattr(checkin.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(respond)))
	account = AccountConfig(cookies=None, provider='agentrouter')
	success, before, after = checkin.run_check_in_requests(
		{'session': 'private-session'},
		account,
		'AgentRouter',
		app_config.providers['agentrouter'],
		login_checked_in=checked_in,
	)

	assert success is checked_in
	assert before is None
	assert len(requests) == 1
	assert requests[0].method == 'GET'
	assert after is not None
	if checked_in:
		assert after['quota'] == 1.0
		assert 'daily credit was granted' in capsys.readouterr().out
	else:
		assert after['success'] is False
		assert 'daily claim unconfirmed' in after['error']
		assert 'Already checked' not in capsys.readouterr().out


def test_agentrouter_missing_login_credit_never_queries_profile(app_config, monkeypatch):
	client = MagicMock()
	monkeypatch.setattr(checkin.httpx, 'Client', client)
	account = AccountConfig(cookies=None, provider='agentrouter')
	result = checkin.run_check_in_requests({}, account, 'AgentRouter', app_config.providers['agentrouter'])

	assert result[0] is False
	assert result[1] is None
	client.assert_not_called()


def test_anyrouter_keeps_profile_sign_in_profile_sequence(app_config, monkeypatch):
	requests = []
	real_client = httpx.Client

	def respond(request):
		requests.append(request)
		if request.method == 'POST':
			return httpx.Response(200, json={'success': True})
		return httpx.Response(200, json={'success': True, 'data': {'quota': 500000, 'used_quota': 0}})

	monkeypatch.setattr(checkin.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(respond)))
	account = AccountConfig(cookies=None)
	success, before, after = checkin.run_check_in_requests({}, account, 'AnyRouter', app_config.providers['anyrouter'])

	assert success is True
	assert before is not None
	assert after is not None
	assert before['success'] is True
	assert after['success'] is True
	assert [(request.method, request.url.path) for request in requests] == [
		('GET', '/api/user/self'),
		('POST', '/api/user/sign_in'),
		('GET', '/api/user/self'),
	]


@pytest.mark.asyncio
async def test_anyrouter_browser_login_does_not_require_agentrouter_response(app_config, browser_login):
	result = await checkin.login_with_credentials(
		'AnyRouter', app_config.providers['anyrouter'], 'anyrouter', 'username', 'private-password'
	)

	assert result == BrowserLoginResult({'session': 'private-session'}, '123')
	browser_login.page.expect_response.assert_not_called()
	browser_login.login_form.assert_awaited_once()
