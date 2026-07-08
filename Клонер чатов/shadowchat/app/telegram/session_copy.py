"""Копия .session для параллельного клиента без блокировки SQLite."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.config import get_settings

_AUX_ROOT: Path | None = None


def _aux_dir() -> Path:
    global _AUX_ROOT
    if _AUX_ROOT is None:
        settings = get_settings()
        _AUX_ROOT = settings.resolved_sessions_dir / f"_aux_{uuid.uuid4().hex[:8]}"
        _AUX_ROOT.mkdir(parents=True, exist_ok=True)
    return _AUX_ROOT


def copy_session_path(session_name: str, *, tag: str = "aux") -> str:
    """Возвращает путь к копии session-файла (str для Telethon)."""
    settings = get_settings()
    src = settings.resolved_sessions_dir / f"{session_name}.session"
    dst = _aux_dir() / f"{session_name}_{tag}.session"
    if src.exists():
        shutil.copy2(src, dst)
        journal = src.with_name(f"{session_name}.session-journal")
        if journal.exists():
            shutil.copy2(journal, dst.with_name(f"{dst.stem}.session-journal"))
    return str(dst.with_suffix(""))


def refresh_session_copy(session_name: str, *, tag: str = "aux") -> str:
    """Пересоздать копию (актуальные ключи после работы основного клиента)."""
    settings = get_settings()
    aux = _aux_dir()
    for old in aux.glob(f"{session_name}_{tag}*"):
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass
    return copy_session_path(session_name, tag=tag)
