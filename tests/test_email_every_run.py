from unittest.mock import AsyncMock, Mock

import pytest

import checkin


@pytest.mark.asyncio
async def test_success_without_balance_change_still_sends_email(monkeypatch):
	account = Mock()
	account.get_display_name.return_value = '测试账号'
	user_info = {'success': True, 'quota': 75.0, 'used_quota': 0.0, 'display': '余额: $75.00'}
	unchanged_hash = checkin.generate_balance_hash({'account_1': {'quota': 75.0, 'used': 0.0}})

	monkeypatch.setattr(checkin, 'is_debug_enabled', lambda: False)
	monkeypatch.setattr(checkin.AppConfig, 'load_from_env', lambda: Mock(providers={}))
	monkeypatch.setattr(checkin, 'load_accounts_config', lambda: [account])
	monkeypatch.setattr(checkin, 'load_balance_hash', lambda: unchanged_hash)
	monkeypatch.setattr(checkin, 'save_balance_hash', lambda _: None)
	monkeypatch.setattr(checkin, 'check_in_account', AsyncMock(return_value=(True, user_info, user_info)))

	send_email = Mock()
	push_message = Mock()
	monkeypatch.setattr(checkin.notify, 'send_email', send_email)
	monkeypatch.setattr(checkin.notify, 'push_message', push_message)

	with pytest.raises(SystemExit) as result:
		await checkin.main()

	assert result.value.code == 0
	send_email.assert_called_once()
	assert '今日已签到，无变化' in send_email.call_args.args[1]
	push_message.assert_not_called()
