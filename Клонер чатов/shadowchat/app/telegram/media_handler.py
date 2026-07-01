import hashlib
from pathlib import Path

import structlog
from telethon.tl.types import (
    DocumentAttributeAnimated,
    DocumentAttributeAudio,
    DocumentAttributeSticker,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from app.config import get_settings

logger = structlog.get_logger()


class MediaHandler:
    def __init__(self, cache_dir: Path | None = None):
        self.settings = get_settings()
        self.cache_dir = cache_dir or self.settings.resolved_media_cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, message_id: int, suffix: str) -> Path:
        return self.cache_dir / f"{message_id}_{suffix}"

    async def download_media(self, message) -> tuple[Path | None, str]:
        """Download message media to cache. Returns (path, media_type)."""
        if not message.media:
            return None, "none"

        media_type = self._detect_media_type(message)
        suffix = self._suffix_for_type(media_type, message)
        dest = self._cache_path(message.id, suffix)

        try:
            path = await message.download_media(file=str(dest))
            if not path:
                return None, media_type

            file_path = Path(path)
            if file_path.stat().st_size > self.settings.max_media_size_bytes:
                logger.warning(
                    "media_too_large",
                    message_id=message.id,
                    size=file_path.stat().st_size,
                )
                file_path.unlink(missing_ok=True)
                return None, media_type

            return file_path, media_type
        except Exception as exc:
            logger.error("media_download_failed", message_id=message.id, error=str(exc))
            return None, media_type

    def cleanup(self, path: Path | None) -> None:
        if path and path.exists():
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("media_cleanup_failed", path=str(path), error=str(exc))

    def _detect_media_type(self, message) -> str:
        if isinstance(message.media, MessageMediaPhoto):
            return "photo"
        if isinstance(message.media, MessageMediaDocument):
            doc = message.media.document
            if not doc:
                return "document"
            for attr in doc.attributes:
                if isinstance(attr, DocumentAttributeSticker):
                    return "sticker"
                if isinstance(attr, DocumentAttributeAnimated):
                    return "gif"
                if isinstance(attr, DocumentAttributeAudio):
                    if attr.voice:
                        return "voice"
                    return "audio"
            mime = doc.mime_type or ""
            if mime.startswith("video/"):
                if "round" in mime or getattr(doc, "size", 0) < 10_000_000:
                    return "video_note"
                return "video"
            return "document"
        return "unknown"

    def _suffix_for_type(self, media_type: str, message) -> str:
        mapping = {
            "photo": "jpg",
            "video": "mp4",
            "video_note": "mp4",
            "voice": "ogg",
            "audio": "mp3",
            "sticker": "webp",
            "gif": "mp4",
            "document": "bin",
        }
        return mapping.get(media_type, "bin")

    @staticmethod
    def avatar_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()[:16]
