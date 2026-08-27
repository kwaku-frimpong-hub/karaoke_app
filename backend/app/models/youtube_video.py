"""SQLAlchemy model for a YouTube video metadata snapshot (M7).

One row per unique YouTube video ID (``youtube_video_id`` is unique): queue
entries reference it, and duplicate-song submissions reuse the existing row
(decision B16/D15 allows duplicates — they share the metadata snapshot).

The row is immutable after creation; a host editing an entry's URL (M7)
re-fetches metadata and points the entry at a new row.
"""

import uuid

from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class YouTubeVideo(Base):
    """Metadata snapshot of a submitted YouTube video."""

    __tablename__ = "youtube_videos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    youtube_video_id: Mapped[str] = mapped_column(
        String(11), unique=True, index=True, nullable=False
    )
    youtube_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(200), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(nullable=False)
    thumbnail_url: Mapped[str] = mapped_column(String(2048), nullable=False)
