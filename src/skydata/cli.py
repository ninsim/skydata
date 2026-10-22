"""Command line: a JSON request on stdin, JSON facts on stdout.

    skydata [--out PATH] [--release PATH] < request.json
    skydata release --ephe-path DIR [--release PATH]
    skydata --version

Exit codes: 0 success, 1 failure worth one retry (crash, write error),
2 invalid request, 3 ephemeris data or release record problem. On failure
stderr carries one line and any existing file at PATH is left untouched.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from skydata import SCHEMA_VERSION, __version__, ephem, release as release_record, spec
from skydata.errors import RequestError, SkydataError
from skydata.events import events
from skydata.sky import sky


def compute(request, release: dict) -> dict:
    normalized = spec.normalize(request)
    ephem.set_ephe_path(release["ephe_path"])
    results = sky(normalized) if normalized["op"] == "sky" else events(normalized)
    return {"skydata": {"version": __version__, "schema": SCHEMA_VERSION},
            "release": release_record.public(release),
            "request": normalized,
            "results": results}


def encode(response: dict) -> bytes:
    return (json.dumps(response, separators=(",", ":"), allow_nan=False) + "\n").encode()


def main(argv=None, stdin=None, stdout=None, stderr=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    stdin = sys.stdin.buffer if stdin is None else stdin
    stdout = sys.stdout.buffer if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    try:
        if argv[:1] == ["release"]:
            return _release_command(argv[1:], stdout)
        return _request_command(argv, stdin, stdout)
    except SkydataError as exc:
        print(f"skydata: {exc}", file=stderr)
        return exc.exit_code
    except Exception as exc:  # anything unforeseen is a crash, worth one retry
        print(f"skydata: internal error: {type(exc).__name__}: {exc}", file=stderr)
        return 1


def _request_command(argv, stdin, stdout) -> int:
    parser = argparse.ArgumentParser(prog="skydata", description="Astronomical facts as JSON.")
    parser.add_argument("--version", action="version", version=f"skydata {__version__}")
    parser.add_argument("--out", help="also write the response to PATH, atomically")
    parser.add_argument("--release", help="release record (default: $SKYDATA_RELEASE, "
                                          "else RELEASE.json beside the virtualenv)")
    args = parser.parse_args(argv)
    try:
        request = json.loads(stdin.read())
    except ValueError as exc:
        raise RequestError(f"request is not valid JSON: {exc}") from None
    spec.normalize(request)  # reject a bad request before touching the installation
    release = release_record.load(Path(args.release) if args.release else release_record.default_path())
    data = encode(compute(request, release))
    _emit(data, stdout, args.out)
    return 0


def _release_command(argv, stdout) -> int:
    parser = argparse.ArgumentParser(prog="skydata release",
                                     description="Fingerprint the ephemeris files and write RELEASE.json.")
    parser.add_argument("--ephe-path", required=True, help="directory holding the .se1 files")
    parser.add_argument("--release", help="where to write it (default: as for requests)")
    args = parser.parse_args(argv)
    target = Path(args.release) if args.release else release_record.default_path()
    data = (json.dumps(release_record.build(args.ephe_path), indent=2) + "\n").encode()
    _emit(data, stdout, str(target))
    return 0


def _emit(data: bytes, stdout, out_path) -> None:
    """Write stdout, and PATH when given, so a failure leaves any old PATH intact.

    Order: write and fsync a temp file beside PATH, write stdout, then rename the
    temp file over PATH. A failure before the rename removes the temp file. Exit
    0 therefore means both writes completed.
    """
    temp = _write_temp(Path(out_path), data) if out_path else None
    try:
        try:
            _write_all(stdout, data)
        except OSError as exc:
            _silence(stdout)
            raise SkydataError(f"could not write stdout: {exc}") from None
        if temp:
            try:
                os.replace(temp, out_path)
            except OSError as exc:
                raise SkydataError(f"could not write {out_path}: {exc}") from None
            temp = None
            _fsync_dir(Path(out_path).parent)
    finally:
        if temp:
            os.unlink(temp)


def _write_all(stream, data: bytes) -> None:
    """Write every byte. A raw or non-blocking stream may accept only part of a write."""
    view = memoryview(data)
    while view:
        written = stream.write(view)
        if not written:
            raise OSError(f"stdout took no more bytes after {len(data) - len(view)} of {len(data)}")
        view = view[written:]
    stream.flush()


def _write_temp(path: Path, data: bytes) -> str:
    import tempfile  # only needed with --out; keeps plain calls quick to start
    try:
        handle, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    except OSError as exc:
        raise SkydataError(f"could not write {path}: {exc}") from None
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(temp, 0o666 & ~umask)
    except OSError as exc:
        os.unlink(temp)
        raise SkydataError(f"could not write {path}: {exc}") from None
    return temp


def _fsync_dir(directory: Path) -> None:
    try:
        handle = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)


def _silence(stream) -> None:
    """Point a broken stdout at /dev/null so interpreter shutdown does not fail on it again."""
    try:
        fileno = stream.fileno()
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, fileno)
        os.close(devnull)
    except (OSError, ValueError, AttributeError):
        pass
