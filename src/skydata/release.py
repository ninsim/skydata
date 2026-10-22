"""The release record: which skydata, Swiss Ephemeris and ephemeris files answered.

`skydata release --ephe-path DIR` writes RELEASE.json once at install time,
including a sha256 fingerprint of every file under DIR. Every response carries
the versions and that fingerprint, so a caller can key a cache on them.

Hashing the files takes a second or more, so it is not repeated per call.
Instead each call checks the cheap parts: the running versions, and the path,
size and modification time of every file under DIR. A mismatch means
RELEASE.json is stale and the call fails until it is regenerated. A file
rewritten with the same size and the same modification time would slip past
this check, so treat the ephemeris directory as read-only once released.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

from skydata import SCHEMA_VERSION, __version__, ephem
from skydata.errors import DataError

RELEASE_ENV = "SKYDATA_RELEASE"
PUBLIC_KEYS = ("skydata_version", "schema_version", "swisseph_version", "ephemeris_fingerprint")
REQUIRED = {"skydata_version": str, "schema_version": int, "swisseph_version": str,
            "pyswisseph_build": str, "ephemeris_fingerprint": str, "ephe_path": str,
            "file_signature": str}
FINGERPRINT_RE = re.compile(r"sha256:[0-9a-f]{64}")


def default_path() -> Path:
    """RELEASE.json beside the virtual environment skydata runs from."""
    return Path(os.environ.get(RELEASE_ENV) or Path(sys.prefix).parent / "RELEASE.json")


def build(ephe_path: str) -> dict:
    root = Path(ephe_path).resolve()
    if not root.is_dir():
        raise DataError(f"ephemeris directory not found: {root}")
    digest = hashlib.sha256()
    count = 0
    for relative, full in _files(root):
        file_hash = hashlib.sha256()
        with open(full, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                file_hash.update(block)
        digest.update(f"{relative}\0{os.stat(full).st_size}\0{file_hash.hexdigest()}\n".encode())
        count += 1
    if not count:
        raise DataError(f"no files in ephemeris directory {root}")
    return {
        "skydata_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "swisseph_version": ephem.swisseph_version(),
        "pyswisseph_version": _pyswisseph_version(),
        "pyswisseph_build": ephem.pyswisseph_build(),
        "ephemeris_fingerprint": f"sha256:{digest.hexdigest()}",
        "ephemeris_files": count,
        "ephe_path": str(root),
        "file_signature": _file_signature(root),
    }


def load(path: Path) -> dict:
    try:
        release = json.loads(Path(path).read_text())
    except FileNotFoundError:
        raise DataError(f"release record not found at {path}, run 'skydata release "
                        "--ephe-path DIR' first") from None
    except (OSError, ValueError) as exc:
        raise DataError(f"release record unreadable at {path}: {exc}") from None
    if not isinstance(release, dict):
        raise DataError(f"release record malformed at {path}")
    for key, kind in REQUIRED.items():
        if type(release.get(key)) is not kind:
            raise DataError(f"release record malformed at {path}: {key} missing or not a "
                            f"{kind.__name__}, rerun 'skydata release'")
    if not FINGERPRINT_RE.fullmatch(release["ephemeris_fingerprint"]):
        raise DataError(f"release record malformed at {path}: bad ephemeris_fingerprint")
    expected = {"skydata_version": __version__, "schema_version": SCHEMA_VERSION,
                "swisseph_version": ephem.swisseph_version(),
                "pyswisseph_build": ephem.pyswisseph_build()}
    for key, value in expected.items():
        if release[key] != value:
            raise DataError(f"release record at {path} is stale ({key} is {release[key]!r}, "
                            f"running {value!r}), rerun 'skydata release'")
    root = Path(release["ephe_path"])
    if not root.is_dir():
        raise DataError(f"ephemeris directory not found: {root}")
    if _file_signature(root) != release["file_signature"]:
        raise DataError(f"ephemeris files in {root} changed since the release record was "
                        "written, rerun 'skydata release'")
    return release


def public(release: dict) -> dict:
    return {key: release[key] for key in PUBLIC_KEYS}


def _files(root: Path):
    """(relative path, full path) for every file under root, in a fixed order."""
    found = []
    for directory, subdirs, files in os.walk(root):
        for name in files:
            full = os.path.join(directory, name)
            found.append((Path(os.path.relpath(full, root)).as_posix(), full))
    return sorted(found)


def _file_signature(root: Path) -> str:
    """Hash of every file's relative path, size and modification time under root."""
    entries = []
    for relative, full in _files(root):
        info = os.stat(full)
        entries.append((relative, info.st_size, info.st_mtime_ns))
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def _pyswisseph_version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("pyswisseph")
    except PackageNotFoundError:
        return "unknown"
