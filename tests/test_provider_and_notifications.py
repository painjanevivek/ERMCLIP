import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading
import pytest

from ermclip.models import Candidate,Duration,Profile,Segment
from ermclip.notifications import authorised_sender,hermes_telegram,send
from ermclip.provider import LocalModel


def test_local_provider_isolation_and_budget(settings):
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body=json.dumps({"choices":[{"message":{"content":"{\"result\":true}"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self,*_): pass
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        settings.local_llm_url=f"http://127.0.0.1:{server.server_port}/v1"
        settings.director_model="test-director"
        settings.critic_model="test-critic"
        settings.max_model_calls=2
        model=LocalModel(settings)
        assert model.json("director",{"text":"untrusted"},{})["result"]
        assert model.json("critic",{"text":"evidence"},{})["result"]
        assert received[0]["model"]=="test-director" and received[1]["model"]=="test-critic"
        assert len(received[1]["messages"])==2
        assert received[0]["response_format"]=={"type":"json_object", "schema":{}}
        assert [entry["role"] for entry in model.usage]==["director","critic"]
        assert all(entry["paid_cost"]==0 for entry in model.usage)
        with pytest.raises(RuntimeError): model.json("critic",{},{})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_telegram_reads_only_expected_keys(settings,monkeypatch):
    for key in ("TELEGRAM_BOT_TOKEN","TELEGRAM_HOME_CHANNEL","TELEGRAM_ALLOWED_USERS"):
        monkeypatch.delenv(key,raising=False)
    home=settings.path/"fake-hermes"
    home.mkdir()
    (home/".env").write_text("TELEGRAM_BOT_TOKEN=fake-token\nTELEGRAM_HOME_CHANNEL=42\nTELEGRAM_ALLOWED_USERS=42,84\nUNRELATED_SECRET=do-not-load\n",encoding="utf-8")
    settings.hermes_home=str(home)
    token,chat,users=hermes_telegram(str(home))
    assert token=="fake-token" and chat=="42" and users==["42","84"]
    assert authorised_sender("42",settings) and not authorised_sender("999",settings)
    with pytest.raises(RuntimeError): send(settings,"disabled")


def test_telegram_notification_mock(settings,monkeypatch):
    import ermclip.notifications as notifications
    settings.telegram_enabled=True
    settings.telegram_chat_id="42"
    settings.telegram_allowed_users=["42"]
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN","fake-token")
    requests=[]
    class Response:
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def read(self): return b'{"ok":true}'
    def fake(request,timeout):
        requests.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr(notifications,"urlopen",fake)
    send(settings,"done")
    assert requests==[{"chat_id":"42","text":"done"}]
