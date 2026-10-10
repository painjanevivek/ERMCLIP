import json

import pytest

from ermclip import notifications, telegram_setup
from ermclip.store import Store


@pytest.fixture
def telegram_home(settings, monkeypatch):
    for key in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_HOME_CHANNEL', 'TELEGRAM_ALLOWED_USERS'):
        monkeypatch.delenv(key, raising=False)
    home = settings.path / 'hermes'
    home.mkdir()
    (home / '.env').write_text('TELEGRAM_BOT_TOKEN=private-test-token\nTELEGRAM_ALLOWED_USERS=42\n', encoding='utf8')
    settings.hermes_home = str(home)
    return home


def test_connect_owner_without_replaying_history(settings, telegram_home, monkeypatch):
    store = Store(settings.path / 'state/test.sqlite3')
    store.event('old-job', 'finished', {'output': 'old-private-path'})
    config = settings.path / 'config.json'
    config.write_text(settings.model_dump_json(), encoding='utf8')
    sent = []
    monkeypatch.setattr(telegram_setup, 'bot_identity', lambda _: {'id': 123, 'username': 'expected_bot'})
    monkeypatch.setattr(telegram_setup, 'send', lambda cfg, text: sent.append((cfg.telegram_chat_id, text)))
    result = telegram_setup.connect(settings, store, config, '42', '@expected_bot')
    assert result['connected'] and result['event_baseline'] == 1
    saved = json.loads(config.read_text())
    assert saved['telegram_allowed_users'] == ['42'] and saved['telegram_enabled']
    assert not saved['telegram_send_media'] and 'private-test-token' not in config.read_text()
    settings.telegram_enabled = True
    monkeypatch.setattr(notifications, 'send', lambda _, text: sent.append(('42', text)))
    store.event('new-job', 'finished', {'status': 'review_required'})
    notifications.flush(settings, store)
    assert len(sent) == 2 and 'new-job' in sent[1][1]
    with store.connect() as db:
        assert db.execute('SELECT delivered FROM events WHERE id=1').fetchone()[0] == 0


@pytest.mark.parametrize('user_id', ['@owner', '-42', '0', '99'])
def test_connect_rejects_unknown_owner(settings, telegram_home, monkeypatch, user_id):
    monkeypatch.setattr(telegram_setup, 'bot_identity', lambda _: pytest.fail('Must reject before network call'))
    with pytest.raises(ValueError):
        telegram_setup.connect(settings, Store(settings.path/'state/test.sqlite3'), settings.path/'unused', user_id, 'expected_bot')


def test_wrong_bot_cannot_send_or_enable(settings, telegram_home, monkeypatch):
    monkeypatch.setattr(telegram_setup, 'bot_identity', lambda _: {'id': 123, 'username': 'wrong_bot'})
    monkeypatch.setattr(telegram_setup, 'send', lambda *_: pytest.fail('Must not send to a wrong bot'))
    with pytest.raises(ValueError, match='different Telegram bot'):
        telegram_setup.connect(settings, Store(settings.path/'state/test.sqlite3'), settings.path/'unused', '42', 'expected_bot')
    assert not settings.telegram_enabled


def test_failed_delivery_does_not_enable(settings, telegram_home, monkeypatch):
    monkeypatch.setattr(telegram_setup, 'bot_identity', lambda _: {'id': 123, 'username': 'expected_bot'})
    def fail(*_):
        raise RuntimeError('Owner must start bot first')
    monkeypatch.setattr(telegram_setup, 'send', fail)
    config = settings.path/'config.json'
    config.write_text(settings.model_dump_json(), encoding='utf8')
    store = Store(settings.path/'state/test.sqlite3')
    with pytest.raises(RuntimeError):
        telegram_setup.connect(settings, store, config, '42', 'expected_bot')
    assert not json.loads(config.read_text())['telegram_enabled']
    assert store.control('telegram_event_baseline') is None


def test_bot_verification_masks_url_token(settings, telegram_home, monkeypatch):
    def fail(request, timeout):
        raise OSError(request.full_url)
    monkeypatch.setattr(notifications, 'urlopen', fail)
    with pytest.raises(RuntimeError) as error:
        notifications.bot_identity(settings)
    assert 'private-test-token' not in str(error.value)
    assert 'private-test-token' not in json.dumps(telegram_setup.status(settings))
