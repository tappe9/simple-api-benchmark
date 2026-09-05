"""Install only reviewed oha release assets; never execute an unverified download."""

import hashlib
import os
import platform
import tempfile
from pathlib import Path

from .process import ROOT, execute
from .results import BenchmarkFailure, require

VERSION = "1.16.0"
# Official release asset digests: https://github.com/hatoo/oha/releases/tag/v1.16.0
SHA256 = {
    "oha-linux-amd64": "620bb9e16fb53eabc9a3fc45f88bdb41fefa3fee5c05e75892011ce320391716",
    "oha-linux-arm64": "99a790eb8c3e0feaca974bd6b32f0f8d4426a0c5b289f39e833e5b2c7529cd39",
    "oha-macos-amd64": "5ecbfc5233e3f1d30384e142a9a8dd7ebf9d3298ab22476fabac44a8f2117e08",
    "oha-macos-arm64": "7dea53ecb8342a7a067e1976fd0aef44ac33d9cc6b1e65c53637ffb932da63c4",
}


def platform_asset() -> str:
    system = {"Linux": "linux", "Darwin": "macos"}.get(platform.system())
    architecture = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
    require(
        system is not None and architecture is not None,
        "oha installer requires Linux/macOS amd64/arm64",
    )
    return f"oha-{system}-{architecture}"


def verify(path: Path, checksum: str) -> None:
    require(path.is_file() and not path.is_symlink(), "oha must be a regular file, not a symlink")
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    require(
        digest.hexdigest() == checksum,
        f"oha checksum mismatch: remove {path} and inspect the download source",
    )
    require(
        execute([str(path), "--version"], timeout=10).strip() == "oha " + VERSION,
        "oha version mismatch",
    )


def ensure_oha(cache: Path = ROOT / ".cache" / "oha") -> Path:
    asset = platform_asset()
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / asset
    if destination.exists() or destination.is_symlink():
        verify(destination, SHA256[asset])
        return destination
    descriptor, name = tempfile.mkstemp(prefix=".oha-", dir=cache)
    os.close(descriptor)
    temporary = Path(name)
    try:
        execute(
            [
                "curl",
                "--fail",
                "--location",
                "--proto",
                "=https",
                "--tlsv1.2",
                "--connect-timeout",
                "10",
                "--max-time",
                "120",
                f"https://github.com/hatoo/oha/releases/download/v{VERSION}/{asset}",
                "--output",
                str(temporary),
            ],
            timeout=130,
        )
        temporary.chmod(0o755)
        verify(temporary, SHA256[asset])
        os.replace(temporary, destination)
    except OSError as error:
        raise BenchmarkFailure(f"oha installation failed: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)
    return destination
