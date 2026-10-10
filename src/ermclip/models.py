from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .caption_styles import CaptionPreset


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


def seconds(value: str | float | int) -> float:
    if isinstance(value, str):
        if ":" in value:
            parts = value.split(":")
            if len(parts) != 3 or not all(re.fullmatch(r"\d+(?:\.\d+)?", p) for p in parts):
                raise ValueError("Use seconds or HH:MM:SS")
            h, m, s = map(float, parts)
            if m >= 60 or s >= 60:
                raise ValueError("Minutes and seconds must be below 60")
            value = h * 3600 + m * 60 + s
        else:
            match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(s|sec(?:onds?)?|m|min(?:utes?)?)?\s*", value, re.I)
            if not match:
                raise ValueError("Use seconds, minutes, or HH:MM:SS")
            value = float(match[1]) * (60 if (match[2] or "s").lower().startswith("m") else 1)
    value = float(value)
    if not math.isfinite(value) or not 0 < value <= 900:
        raise ValueError("Each output duration must be greater than 0 and at most 900 seconds")
    return value


class Duration(Schema):
    target: float = 60
    minimum: float = 15
    maximum: float = 90
    strict: bool = False

    @field_validator("target", "minimum", "maximum", mode="before")
    @classmethod
    def parse(cls, value):
        return seconds(value)

    @model_validator(mode="after")
    def bounds(self):
        if not self.minimum <= self.target <= self.maximum:
            raise ValueError("Require minimum <= target <= maximum <= 900")
        return self


class Captions(Schema):
    burn: bool = True
    srt: bool = True
    preset: CaptionPreset = "highlight"
    font: str = "Arial"
    size: int = Field(default=52, ge=12, le=180)
    color: str = "FFFFFF"
    highlight: str = "00D7FF"
    max_chars: int = Field(default=36, ge=12, le=100)
    position: Literal["bottom", "top", "middle"] = "bottom"

    @field_validator("color", "highlight")
    @classmethod
    def hex_color(cls, value):
        if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
            raise ValueError("Caption colours must be six hex digits")
        return value.upper()

    @field_validator("font")
    @classmethod
    def safe_font(cls, value):
        if not re.fullmatch(r"[\w -]{1,80}", value):
            raise ValueError("Invalid font name")
        return value


class Layout(Schema):
    preset: Literal["plain", "reference_window", "podcast_hero"] = "plain"
    headline: str | None = Field(default=None, min_length=1, max_length=100)
    highlight: str | None = Field(default=None, min_length=1, max_length=40)
    credit: str | None = Field(default=None, min_length=1, max_length=100)
    auto_highlight: bool = False


class Profile(Schema):
    name: str = "shorts_9x16"
    ratio: str = "9:16"
    width: int = Field(default=1080, ge=64, le=7680)
    height: int = Field(default=1920, ge=64, le=7680)
    duration: Duration = Field(default_factory=Duration)
    count: int | None = Field(default=None, ge=1, le=100)
    total_duration: float | None = Field(default=None, gt=0, le=90000)
    strategy: Literal["continuous", "compilation"] = "continuous"
    framing: Literal["smart", "center", "pad", "blur", "original", "speaker"] = "smart"
    captions: Captions = Field(default_factory=Captions)
    layout: Layout = Field(default_factory=Layout)
    inherit_podcast_style: bool = True
    normalize_audio: bool = True
    fades: bool = True
    trim_silence: bool = False

    @field_validator("name")
    @classmethod
    def safe_name(cls, value):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", value):
            raise ValueError("Profile name must contain letters, digits, underscores, or hyphens")
        return value

    @model_validator(mode="after")
    def geometry(self):
        match = re.fullmatch(r"([1-9]\d{0,3}):([1-9]\d{0,3})", self.ratio)
        if not match:
            raise ValueError("Aspect ratio must use positive integers, for example 9:16")
        if self.width % 2 or self.height % 2:
            raise ValueError("H.264 output dimensions must be even")
        ratio = int(match[1]) / int(match[2])
        if abs(self.width / self.height - ratio) / ratio > 0.015:
            raise ValueError("Dimensions do not match the selected aspect ratio")
        if self.layout.preset != "plain":
            if abs(ratio-9/16) > .001 or self.framing == "original":
                raise ValueError("Podcast layouts require a 9:16 canvas and crop or padded framing")
            if self.captions.position != "bottom":
                raise ValueError("Podcast layouts place speech captions at the bottom of the speaker window")
            if self.layout.highlight and self.layout.headline and self.layout.highlight.casefold() not in self.layout.headline.casefold():
                raise ValueError("Highlighted words must occur in the headline")
        return self


class Conditions(Schema):
    keywords: list[str] = Field(default_factory=list, max_length=40)
    all_keywords: bool = False
    topics: list[str] = Field(default_factory=list, max_length=20)
    exclude: list[str] = Field(default_factory=list, max_length=40)
    speaker: str | None = None
    visual_events: list[str] = Field(default_factory=list, max_length=20)


class JobSpec(Schema):
    source: str
    instruction: str = Field(default="Create the best clips from this video.", max_length=10000)
    mode: Literal["AUTO", "TARGETED"] = "AUTO"
    conditions: Conditions = Field(default_factory=Conditions)
    profiles: list[Profile] = Field(default_factory=lambda: [Profile()], min_length=1, max_length=12)
    transcript: str | None = None
    transcript_language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")
    approved_plan: str | None = None
    revision_of: str | None = None
    podcast_mode: Literal["auto", "on", "off"] = "auto"

    @model_validator(mode="after")
    def unique_names(self):
        # User context supplies the content type. We do not infer podcast identity
        # from face size or claim general video classification.
        from pathlib import PureWindowsPath
        context = self.instruction + " " + PureWindowsPath(self.source).stem
        requested = self.podcast_mode == "on" or (self.podcast_mode == "auto" and
            bool(re.search(r"\b(podcasts?|interviews?|active speaker|person who is talking)\b", context, re.I)))
        preserve = bool(re.search(r"\b(keep|preserve|show)\b.{0,30}\b(full|whole|original)\s+(frame|video)\b", self.instruction, re.I))
        if requested and not preserve:
            for i, profile in enumerate(self.profiles):
                if profile.framing != "original":
                    self.profiles[i] = profile.model_copy(update={"framing":"speaker"})
        if len({p.name for p in self.profiles}) != len(self.profiles):
            raise ValueError("Profile names must be unique")
        if self.mode == "TARGETED" and not any(self.conditions.model_dump().get(k) for k in ("keywords", "topics", "speaker", "visual_events")):
            raise ValueError("TARGETED requires at least one inclusion condition")
        return self


class Word(Schema):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str

    @model_validator(mode="after")
    def bounds(self):
        if self.end <= self.start:
            raise ValueError("Word end must be after start")
        return self


class Passage(Schema):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str
    words: list[Word] = Field(default_factory=list)
    speaker: str | None = None

    @model_validator(mode="after")
    def bounds(self):
        if self.end <= self.start:
            raise ValueError("Passage end must be after start")
        if any(w.start < self.start - 0.1 or w.end > self.end + 0.1 for w in self.words):
            raise ValueError("Word timestamps are outside their passage")
        return self


class Transcript(Schema):
    language: str = "und"
    engine: str
    passages: list[Passage]
    warnings: list[str] = Field(default_factory=list)


class Segment(Schema):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    reason: str

    @model_validator(mode="after")
    def bounds(self):
        if self.end <= self.start:
            raise ValueError("Segment end must be after start")
        return self


class Candidate(Schema):
    id: str = Field(pattern=r"^clip_[0-9]{3}$")
    profile: str
    title: str = Field(max_length=100)
    segments: list[Segment] = Field(min_length=1, max_length=80)
    reason: str
    narrative: list[str] = Field(default_factory=list)
    score: float = Field(default=0, ge=0, le=100)
    framing: str | None = None
    revision: int = Field(default=0, ge=0, le=2)

    @field_validator("id")
    @classmethod
    def safe_id(cls, value):
        if not re.fullmatch(r"clip_\d{3}", value):
            raise ValueError("Candidate ID must use clip_001 format")
        return value

    @property
    def duration(self):
        return sum(s.end - s.start for s in self.segments)


class EditingPlan(Schema):
    version: int = 1
    instruction: str
    source: str
    fingerprint: str
    source_duration: float
    mode: Literal["AUTO", "TARGETED"]
    profiles: list[Profile]
    candidates: list[Candidate]
    director: str
    warnings: list[str] = Field(default_factory=list)
    evaluation_criteria: dict[str, int] = Field(default_factory=lambda: {"relevance":25, "coherence":25, "hook_pacing":15, "value":15, "visual":10, "audio_subtitles":10})
    constraints: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_timeline(self):
        profiles = {p.name:p for p in self.profiles}
        identifiers = set()
        for c in self.candidates:
            key = (c.profile, c.id)
            if key in identifiers or c.profile not in profiles:
                raise ValueError("Duplicate candidate or unknown output profile")
            identifiers.add(key)
            p = profiles[c.profile]
            if c.duration > min(900, p.duration.maximum) + 0.001 or c.duration < p.duration.minimum - 0.001:
                raise ValueError("Candidate duration is outside output limits")
            if p.duration.strict and abs(c.duration - p.duration.target) > 0.05:
                raise ValueError("Candidate does not meet strict duration")
            if p.strategy == "continuous" and len(c.segments) != 1:
                raise ValueError("Continuous profiles must use one source segment")
            if any(s.end > self.source_duration + 0.01 for s in c.segments):
                raise ValueError("Candidate timestamps exceed the source")
            if c.framing is not None and c.framing not in ("smart", "center", "pad", "blur", "original", "speaker"):
                raise ValueError("Unsupported candidate framing")
            if p.framing == "speaker" and c.framing not in (None, "speaker", "pad", "blur"):
                raise ValueError("Podcast framing cannot be replaced by an unverified static face crop")
            for i, segment in enumerate(c.segments):
                if any(segment.start < other.end and segment.end > other.start for other in c.segments[:i]):
                    raise ValueError("A compilation cannot repeat overlapping source footage")
        for name,p in profiles.items():
            outputs=[c for c in self.candidates if c.profile==name]
            if p.count and len(outputs)>p.count:
                raise ValueError("Plan exceeds the requested output count")
            if p.total_duration and sum(c.duration for c in outputs)>p.total_duration+0.01:
                raise ValueError("Plan exceeds the requested total duration")
        return self
