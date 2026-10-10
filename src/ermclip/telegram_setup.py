"""Local configuration for the existing Hermes bot; contains no inbound poller."""
import json
from pathlib import Path

from .notifications import begin_delivery, bot_identity, hermes_telegram, send
from .util import atomic_json


def status(settings):
    token, chat, users = hermes_telegram(settings.hermes_home)
    return {'hermes_home': settings.hermes_home, 'bot_token_present': bool(token),
            'notifications_enabled': settings.telegram_enabled,
            'destination': settings.telegram_chat_id or chat,
            'allowed_users': settings.telegram_allowed_users or users,
            'media_uploads_enabled': settings.telegram_send_media,
            'inbound_owner': 'Hermes gateway', 'paid_api_budget': 0}


def connect(settings, store, config_path: Path, user_id: str, expected_bot: str):
    if not user_id.isdecimal() or int(user_id) <= 0:
        raise ValueError('Use your positive numeric Telegram user ID')
    _, _, inherited = hermes_telegram(settings.hermes_home)
    # A local config write cannot override a different gateway allowlist silently.
    if user_id not in inherited:
        raise ValueError('Add this numeric user ID to Hermes Telegram allowed users first')
    bot = bot_identity(settings)
    if bot['username'].lower() != expected_bot.lstrip('@').lower():
        raise ValueError('The Hermes token belongs to a different Telegram bot')
    configured = settings.model_copy(update={'telegram_enabled': True, 'telegram_chat_id': user_id,
                                             'telegram_allowed_users': [user_id], 'telegram_send_media': False})
    # Send only a connection check to the authorised owner's private chat.
    send(configured, 'ERMCLIP connection check. Local Qwen3.5 9B. Paid API usage: 0. Media uploads: off.')
    baseline = begin_delivery(store)
    data = json.loads(config_path.read_text(encoding='utf-8-sig'))
    for field in ('telegram_enabled', 'telegram_chat_id', 'telegram_allowed_users', 'telegram_send_media'):
        data[field] = getattr(configured, field)
    atomic_json(config_path, data)
    return {'connected': True, 'bot': bot['username'], 'destination': user_id,
            'event_baseline': baseline, 'restart_worker': True, 'inbound_owner': 'Hermes gateway'}
