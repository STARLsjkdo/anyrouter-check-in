import json
import os

import pytest

from utils.config import AccountConfig, load_accounts_config


@pytest.fixture(autouse=True)
def clear_account_environment(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)
	monkeypatch.delenv('AGENTROUTER_ACCOUNTS', raising=False)


def test_legacy_accounts_alone_keep_existing_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
	legacy_json = json.dumps([{'cookies': {'session': 'dummy-legacy-session'}, 'api_user': '12345'}])
	monkeypatch.setenv('ANYROUTER_ACCOUNTS', legacy_json)

	assert load_accounts_config() == [
		AccountConfig(cookies={'session': 'dummy-legacy-session'}, api_user='12345', name='Account 1')
	]
	assert os.environ['ANYROUTER_ACCOUNTS'] == legacy_json
	assert 'AGENTROUTER_ACCOUNTS' not in os.environ


def test_agentrouter_accounts_alone_default_to_agentrouter(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv(
		'AGENTROUTER_ACCOUNTS',
		json.dumps([{'email': 'agent@example.com', 'password': 'dummy-agent-password'}]),
	)

	assert load_accounts_config() == [
		AccountConfig(
			cookies=None,
			provider='agentrouter',
			name='Account 1',
			email='agent@example.com',
			password='dummy-agent-password',
		)
	]


def test_both_account_sources_merge_without_overwriting_environment(monkeypatch: pytest.MonkeyPatch) -> None:
	legacy_json = json.dumps([{'name': 'Legacy', 'cookies': {'session': 'dummy-session'}, 'api_user': '12345'}])
	agent_json = json.dumps([{'name': 'Agent', 'email': 'agent@example.com', 'password': 'dummy-agent-password'}])
	monkeypatch.setenv('ANYROUTER_ACCOUNTS', legacy_json)
	monkeypatch.setenv('AGENTROUTER_ACCOUNTS', agent_json)

	assert load_accounts_config() == [
		AccountConfig(cookies={'session': 'dummy-session'}, api_user='12345', name='Legacy'),
		AccountConfig(
			cookies=None,
			provider='agentrouter',
			name='Agent',
			email='agent@example.com',
			password='dummy-agent-password',
		),
	]
	assert os.environ['ANYROUTER_ACCOUNTS'] == legacy_json
	assert os.environ['AGENTROUTER_ACCOUNTS'] == agent_json


@pytest.mark.parametrize('source', ['ANYROUTER_ACCOUNTS', 'AGENTROUTER_ACCOUNTS'])
def test_explicit_account_provider_is_preserved(monkeypatch: pytest.MonkeyPatch, source: str) -> None:
	monkeypatch.setenv(
		source,
		json.dumps([{'provider': 'custom', 'email': 'custom@example.com', 'password': 'dummy-password'}]),
	)

	accounts = load_accounts_config()

	assert accounts is not None
	assert accounts[0].provider == 'custom'


def test_missing_both_account_sources_returns_none() -> None:
	assert load_accounts_config() is None


@pytest.mark.parametrize('source', ['ANYROUTER_ACCOUNTS', 'AGENTROUTER_ACCOUNTS'])
def test_invalid_json_rejects_all_accounts_without_logging_credentials(
	monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], source: str
) -> None:
	other_source = 'AGENTROUTER_ACCOUNTS' if source == 'ANYROUTER_ACCOUNTS' else 'ANYROUTER_ACCOUNTS'
	monkeypatch.setenv(other_source, json.dumps([{'email': 'valid@example.com', 'password': 'dummy-valid-password'}]))
	monkeypatch.setenv(
		source,
		'[{"email":"invalid@example.com","password":"dummy-secret-password",'
		'"cookies":{"session":"dummy-secret-session"}},]',
	)

	assert load_accounts_config() is None
	output = capsys.readouterr()
	assert 'dummy-secret-password' not in output.out + output.err
	assert 'dummy-secret-session' not in output.out + output.err
	assert 'dummy-valid-password' not in output.out + output.err


@pytest.mark.parametrize('payload', [{}, 'not-an-array', [None], ['not-an-account']])
def test_invalid_agentrouter_container_rejects_all_accounts(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
	monkeypatch.setenv(
		'ANYROUTER_ACCOUNTS', json.dumps([{'email': 'legacy@example.com', 'password': 'dummy-password'}])
	)
	monkeypatch.setenv('AGENTROUTER_ACCOUNTS', json.dumps(payload))

	assert load_accounts_config() is None


@pytest.mark.parametrize(
	'account',
	[
		{},
		{'api_user': '12345'},
		{'email': 'agent@example.com', 'password': ''},
		{'password': 'dummy-secret-password'},
		{'cookies': {'session': 'dummy-secret-session'}},
	],
)
def test_agentrouter_account_without_complete_auth_rejects_all_accounts_without_logging_credentials(
	monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], account: dict
) -> None:
	monkeypatch.setenv(
		'ANYROUTER_ACCOUNTS', json.dumps([{'email': 'legacy@example.com', 'password': 'dummy-legacy-password'}])
	)
	monkeypatch.setenv('AGENTROUTER_ACCOUNTS', json.dumps([account]))

	assert load_accounts_config() is None
	output = capsys.readouterr()
	assert 'dummy-secret-password' not in output.out + output.err
	assert 'dummy-secret-session' not in output.out + output.err
	assert 'dummy-legacy-password' not in output.out + output.err
