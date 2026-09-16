from pathlib import Path
from typing import Protocol

from .config import settings


class Storage(Protocol):
    def put(self, key: str, content: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def path(self, key: str) -> Path: ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        resolved = (self.root / key).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("Invalid storage key")
        return resolved

    def put(self, key: str, content: bytes) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    def read(self, key: str) -> bytes:
        return self.path(key).read_bytes()


def storage() -> Storage:
    return LocalStorage(settings().storage_root)
