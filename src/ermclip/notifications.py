"""Existing Hermes credentials are read locally. Never run a second Telegram poller."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


def hermes_telegram(home: str | None):
    token=os.environ.get("TELEGRAM_BOT_TOKEN")
    chat=os.environ.get("TELEGRAM_HOME_CHANNEL")
    users=os.environ.get("TELEGRAM_ALLOWED_USERS","").split(",")
    if home:
        env_path=Path(home)/".env"
        if env_path.exists():
            # Parse only the three known keys. Do not evaluate shell interpolation.
            for line in env_path.read_text(encoding="utf-8-sig").splitlines():
                key,sep,value=line.partition("=")
                key=key.strip().removeprefix("export ")
                value=value.strip().strip('"').strip("'")
                if not sep or not value:
                    continue
                if key=="TELEGRAM_BOT_TOKEN": token=token or value
                elif key=="TELEGRAM_HOME_CHANNEL": chat=chat or value
                elif key=="TELEGRAM_ALLOWED_USERS" and not any(users): users=value.split(",")
    return token,chat,[u.strip() for u in users if u.strip()]


def authorised_sender(sender: str, settings):
    _,_,inherited=hermes_telegram(settings.hermes_home)
    return str(sender) in (settings.telegram_allowed_users or inherited)


def bot_identity(settings):
    token, _, _ = hermes_telegram(settings.hermes_home)
    if not token:
        raise RuntimeError("Add the Telegram bot token in Hermes first")
    request = Request(f"https://api.telegram.org/bot{token}/getMe")
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read())
        if not result.get('ok'):
            raise RuntimeError('Bot verification failed')
        return {key: result['result'][key] for key in ('id', 'username')}
    except Exception as exc:
        raise RuntimeError(f"Telegram bot verification failed ({type(exc).__name__})") from None


def begin_delivery(store):
    """Record a baseline without deleting history or claiming that old events were sent."""
    with store.connect() as db:
        baseline = db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
        db.execute("INSERT INTO controls VALUES ('telegram_event_baseline',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(baseline),))
    return baseline


def send(settings,text):
    token,chat,users=hermes_telegram(settings.hermes_home)
    chat=settings.telegram_chat_id or chat
    allowed=settings.telegram_allowed_users or users
    if not settings.telegram_enabled or not token or not chat or not allowed:
        raise RuntimeError("Telegram requires an existing bot token, destination, and authorised-user list")
    # Direct outbound messages use the existing bot. Hermes keeps ownership of incoming updates.
    request=Request(f"https://api.telegram.org/bot{token}/sendMessage",data=json.dumps({"chat_id":chat,"text":text[:4000]}).encode(),headers={"Content-Type":"application/json"})
    try:
        with urlopen(request,timeout=30) as response:
            result=json.loads(response.read())
        if not result.get("ok"):
            raise RuntimeError("Telegram rejected the notification")
    except Exception as exc:
        # urllib error messages can contain the bot token in the request URL.
        raise RuntimeError(f"Telegram delivery failed ({type(exc).__name__})") from None


def flush(settings,store):
    if not settings.telegram_enabled:
        return
    with store.connect() as db:
        baseline = int(store.control('telegram_event_baseline') or 0)
        rows=db.execute("SELECT * FROM events WHERE id>? AND delivered=0 AND delivery_attempts<3 ORDER BY id LIMIT 10", (baseline,)).fetchall()
    for row in rows:
        payload=json.loads(row["payload"])
        text=f"ERMCLIP {row['kind']}\nJob: {row['job_id']}\n"+"\n".join(f"{key}: {value}" for key,value in payload.items())
        try:
            send(settings,text)
        except RuntimeError:
            with store.connect() as db:
                db.execute("UPDATE events SET delivery_attempts=delivery_attempts+1 WHERE id=?",(row["id"],))
            break
        with store.connect() as db:
            db.execute("UPDATE events SET delivered=1 WHERE id=?",(row["id"],))
