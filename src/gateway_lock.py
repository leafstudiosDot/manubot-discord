"""Cross-process lock ensuring a single Discord Gateway connection."""

from __future__ import annotations

import os
from pathlib import Path

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None


class GatewayLock:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle: int | None = None

    def acquire(self) -> bool:
        if self._handle is not None:
            return True

        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if msvcrt is not None:
                if os.fstat(handle).st_size == 0:
                    os.write(handle, b"\0")
                os.lseek(handle, 0, os.SEEK_SET)
                msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
            elif fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:  # pragma: no cover - unsupported platform
                raise OSError("No supported file locking implementation")
        except OSError:
            os.close(handle)
            return False
        except Exception:
            os.close(handle)
            raise

        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None:
            return

        try:
            if msvcrt is not None:
                os.lseek(self._handle, 0, os.SEEK_SET)
                msvcrt.locking(self._handle, msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(self._handle, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(self._handle)
            self._handle = None
