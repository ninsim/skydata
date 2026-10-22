"""The release record: which skydata, Swiss Ephemeris and ephemeris files answered.

`skydata release --ephe-path DIR` writes RELEASE.json once at install time,
including a sha256 fingerprint of every file under DIR. Every response carries
the versions and that fingerprint, so a caller can key a cache on them.

Hashing the files takes a second or more, so it is not repeated per call.
Instead each call checks the cheap parts: the running versions, and the names
and sizes of the files at the top of DIR. A mismatch means RELEASE.json is
stale and the call fails until it is regenerated.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from skydata import SCHEMA_VERSION, __version__, ephem
from skydata.errors import DataError

RELEASE_ENV = "SKYDATA_RELEASE"
PUBLIC_KEYS = ("skydata_version", "schema_version", "swisseph_version", "ephemeris_fingerprint")


def default_path() -> Path:
    """RELEASE.json beside the virtual environment skydata runs from."""
    return Path(os.environ.get(RELEASE_ENV) or Path(sys.prefix).parent / "RELEASE.json")


def build(ephe_path: str) -> dict:
    root = Path(ephe_path).resolve()
    if not root.is_dir():
        raise DataError(f"ephemeris directory not found: {root}")
    digest = hashlib.sha256()
    count = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        file_hash = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                file_hash.update(block)
        digest.update(f"{path.relative_to(root).as_posix()}\0{path.stat().st_size}\0"
                      f"{file_hash.hexdigest()}\n".encode())
        count += 1
    if not count:
        raise DataError(f"no files in ephemeris directory {root}")
    return {
        "skydata_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "swisseph_version": ephem.swisseph_version(),
        "pyswisseph_version": _pyswisseph_version(),
        "ephemeris_fingerprint": f"sha256:{digest.hexdigest()}",
        "ephemeris_files": count,
        "ephe_path": str(root),
        "top_level_signature": _top_level_signature(root),
    }


def load(path: Path) -> dict:
    try:
        release = json.loads(Path(path).read_text())
    except FileNotFoundError:
        raise DataError(f"release record not found at {path}; run 'skydata release "
                        "--ephe-path DIR' first") from None
    except (OSError, ValueError) as exc:
        raise DataError(f"release record unreadable at {path}: {exc}") from None
    if not isinstance(release, dict):
        raise DataError(f"release record malformed at {path}")
    expected = {"skydata_version": __version__, "schema_version": SCHEMA_VERSION,
                "swisseph_version": ephem.swisseph_version()}
    for key, value in expected.items():
        if release.get(key) != value:
            raise DataError(f"release record at {path} is stale ({key} is {release.get(key)!r}, "
                            f"running {value!r}); rerun 'skydata release'")
    root = Path(release.get("ephe_path", ""))
    if not root.is_dir():
        raise DataError(f"ephemeris directory not found: {root}")
    if _top_level_signature(root) != release.get("top_level_signature"):
        raise DataError(f"ephemeris files in {root} changed since the release record was "
                        "written; rerun 'skydata release'")
    return release


def public(release: dict) -> dict:
    return {key: release[key] for key in PUBLIC_KEYS}


def _top_level_signature(root: Path) -> str:
    entries = sorted((entry.name, entry.stat().st_size) for entry in os.scandir(root)
                     if entry.is_file())
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def _pyswisseph_version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("pyswisseph")
    except PackageNotFoundError:
        return "unknown"
