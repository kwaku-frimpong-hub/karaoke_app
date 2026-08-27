"""Pydantic schemas for the YouTube song preview (M6).

``YouTubeVideoData`` is the service-layer metadata snapshot returned by the
YouTube Data API fetch; ``SongPreviewResponse`` is the API boundary shape
(metadata + the long-video warning, decision D34).
"""

from pydantic import BaseModel, Field

#: Maximum accepted length of a pasted URL.
MAX_YOUTUBE_URL_LENGTH = 2048


class SongPreviewRequest(BaseModel):
    """Request body for ``POST /api/v1/sessions/{id}/entries/preview``."""

    youtube_url: str = Field(max_length=MAX_YOUTUBE_URL_LENGTH)


class YouTubeVideoData(BaseModel):
    """Metadata snapshot of a YouTube video (service layer, M6)."""

    video_id: str
    youtube_url: str
    title: str
    channel: str
    duration_seconds: int
    thumbnail_url: str


class SongPreviewResponse(BaseModel):
    """Preview shown to a participant before they add a song (E3/E4/B6)."""

    youtube_url: str
    video_id: str
    title: str
    channel: str
    duration_seconds: int
    thumbnail_url: str
    #: True when the video is longer than ``youtube_long_video_seconds``.
    is_long: bool
    #: Human-readable warning (None when the video is not unusually long).
    warning: str | None
