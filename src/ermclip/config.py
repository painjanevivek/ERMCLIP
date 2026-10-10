from pathlib import Path
from typing import Literal
import json

from pydantic import Field, model_validator
from .models import Profile, Schema, Layout


ROOT = Path(__file__).resolve().parents[2]


class Settings(Schema):
    root: str = str(ROOT)
    allowed_inputs: list[str] = Field(default_factory=lambda: [str(ROOT / "input")])
    podcast_sources: list[str] = Field(default_factory=list, max_length=512)
    watch_folders: list[str] = Field(default_factory=list)
    stable_seconds: float = Field(default=10, ge=0, le=600)
    poll_seconds: float = Field(default=5, ge=0.1, le=3600)
    retries: int = Field(default=2, ge=0, le=5)
    revisions: int = Field(default=2, ge=0, le=2)
    process_timeout: int = Field(default=7200, ge=10, le=86400)
    min_free_gb: float = Field(default=2, ge=0)
    min_gpu_free_mb: int = Field(default=2000, ge=0)
    encoder: Literal["auto", "cpu", "nvenc"] = "auto"
    whisper_model: str = "base"
    whisper_device: Literal["auto", "cpu", "cuda"] = "auto"
    allow_model_download: bool = False
    scene_analysis: bool = True
    semantic_model: str | None = None
    local_llm_url: str | None = None
    director_model: str | None = None
    critic_model: str | None = None
    managed_local_model: bool = False
    local_context_tokens: int = Field(default=32768, ge=16384, le=65536)
    max_model_calls: int = Field(default=8, ge=0, le=40)
    cache_days: int = Field(default=30, ge=1, le=365)
    hermes_home: str | None = None
    telegram_enabled: bool = False
    telegram_chat_id: str | None = None
    telegram_allowed_users: list[str] = Field(default_factory=list)
    telegram_send_media: bool = False
    defaults: list[Profile] = Field(default_factory=lambda: [Profile()])
    podcast_layout: Layout = Field(default_factory=lambda: Layout(preset='podcast_hero', auto_highlight=True))
    podcast_caption_preset: str = 'short_yellow'
    additional_paid_api_budget: float = Field(default=0, ge=0, le=0)

    @model_validator(mode="after")
    def local_model(self):
        from .caption_styles import PRESET_IDS
        if self.podcast_caption_preset not in PRESET_IDS:
            raise ValueError('Unknown podcast caption preset')
        if self.local_llm_url:
            from urllib.parse import urlparse
            url = urlparse(self.local_llm_url)
            if url.scheme not in ("http", "https") or url.hostname not in ("127.0.0.1", "localhost", "::1") or url.username or url.password:
                raise ValueError("Only loopback model endpoints are supported. Cloud adapters remain disabled.")
        if self.managed_local_model and (self.local_llm_url != "http://127.0.0.1:8088/v1" or self.director_model not in ("ermclip-qwen3-4b", "ermclip-qwen35-9b") or self.critic_model != self.director_model):
            raise ValueError("The managed runtime requires the pinned loopback endpoint and model alias")
        return self

    @property
    def path(self):
        return Path(self.root).resolve()

    def prepare(self):
        for name in ("input", "output", "cache", "state", "logs"):
            (self.path / name).mkdir(parents=True, exist_ok=True)


def load(path: str | Path | None = None) -> Settings:
    path = Path(path) if path else ROOT / "config" / "local.json"
    settings = Settings.model_validate(json.loads(path.read_text(encoding="utf-8-sig"))) if path.exists() else Settings()
    settings.prepare()
    return settings
