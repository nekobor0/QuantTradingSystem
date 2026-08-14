"""Content-addressed immutable storage for source bytes."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .errors import RepositoryConflict


class RawFileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes, suffix: str = ".bin") -> tuple[str, str]:
        checksum = hashlib.sha256(content).hexdigest()
        path = self.root / f"{checksum}{suffix}"
        if path.exists() and path.read_bytes() != content:
            raise RepositoryConflict("content-address collision")
        if not path.exists():
            path.write_bytes(content)
        return checksum, path.as_uri()

