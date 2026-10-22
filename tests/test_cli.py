import io
import json
import os
import subprocess
import sys

import pytest

from conftest import run
from skydata import __version__, cli

SKY = {"op": "sky", "times": ["2027-03-20T12:00:00Z"], "bodies": ["sun"]}


def test_response_carries_versions_fingerprint_and_request(ask):
    response = ask(SKY)
    assert response["skydata"] == {"version": __version__, "schema": 1}
    assert set(response["release"]) == {"skydata_version", "schema_version", "swisseph_version",
                                        "ephemeris_fingerprint"}
    assert response["release"]["ephemeris_fingerprint"].startswith("sha256:")
    assert response["request"] == {**SKY, "equatorial": False}


def test_output_is_deterministic(release_path):
    first, second = run(SKY, release_path), run(SKY, release_path)
    assert first == second and first[0] == 0


@pytest.mark.parametrize("raw, message", [
    (b"not json", "not valid JSON"),
    (b"[]", "expected a JSON object"),
    (b'{"op": "orbit"}', "op:"),
    (b'{"op": "sky"}', "times: required"),
    (b'{"op": "sky", "times": ["2027-03-20T12:00:00Z"], "bodys": ["sun"]}', "bodys: unknown key"),
    (b'{"op": "sky", "times": ["2027-03-20T12:00:00-05:00"]}', "times[0]"),
    (b'{"op": "sky", "times": ["2027-03-20 12:00:00"]}', "times[0]"),
    (b'{"op": "sky", "times": ["2027-02-29T12:00:00Z"]}', "day is out of range"),
    (b'{"op": "sky", "times": ["2027-03-20T12:00:00Z"], "bodies": ["vulcan"]}', "unknown body"),
    (b'{"op": "sky", "times": ["2027-03-20T12:00:00Z"], "bodies": ["sun", "sun"]}', "duplicate"),
    (b'{"op": "sky", "times": ["2027-03-20T12:00:00Z"], "place": {"lat": 91, "lon": 0}}', "place.lat"),
    (b'{"op": "sky", "times": ["2027-03-20T12:00:00Z"], "place": {"lat": 0, "lon": 0, '
     b'"house_system": "Z"}}', "house_system"),
    (b'{"op": "events", "start": "2027-01-02T00:00:00Z", "end": "2027-01-01T00:00:00Z", '
     b'"find": [{"type": "station", "body": "mars"}]}', "later than start"),
    (b'{"op": "events", "start": "2027-01-01T00:00:00Z", "end": "2027-02-01T00:00:00Z", '
     b'"find": [{"type": "crossing", "body": "sun", "degrees": [360]}]}', "degrees[0]"),
    (b'{"op": "events", "start": "2027-01-01T00:00:00Z", "end": "2027-02-01T00:00:00Z", '
     b'"find": [{"type": "crossing", "body": "sun", "degrees": [0, 0.0]}]}', "duplicate"),
    (b'{"op": "events", "start": "2027-01-01T00:00:00Z", "end": "2027-02-01T00:00:00Z", '
     b'"find": [{"type": "separation", "a": "sun", "b": "sun", "angles": [0]}]}', "must differ"),
    (b'{"op": "events", "start": "2027-01-01T00:00:00Z", "end": "2027-02-01T00:00:00Z", '
     b'"find": [{"type": "eclipse", "kind": "planetary"}]}', "kind"),
])
def test_rejected_requests_exit_2_with_one_line(release_path, raw, message):
    code, out, err = run(None, release_path, raw=raw)
    assert code == 2 and out == b""
    assert message in err and err.count("\n") == 1 and err.startswith("skydata: ")


def test_invalid_request_wins_over_a_missing_release(tmp_path):
    code, _, _ = run(None, tmp_path / "missing.json", raw=b'{"op": "sky"}')
    assert code == 2


def test_missing_release_exits_3(tmp_path):
    code, out, err = run(SKY, tmp_path / "missing.json")
    assert code == 3 and out == b"" and "skydata release" in err


def test_stale_release_exits_3(release_path, tmp_path):
    record = json.loads(release_path.read_text())
    record["skydata_version"] = "0.0.0"
    stale = tmp_path / "RELEASE.json"
    stale.write_text(json.dumps(record))
    code, _, err = run(SKY, stale)
    assert code == 3 and "stale" in err


def test_changed_ephemeris_files_exit_3(release_path, tmp_path):
    record = json.loads(release_path.read_text())
    record["top_level_signature"] = "0" * 64
    changed = tmp_path / "RELEASE.json"
    changed.write_text(json.dumps(record))
    code, _, err = run(SKY, changed)
    assert code == 3 and "changed" in err


def test_no_silent_fallback_without_data_files(tmp_path):
    empty = tmp_path / "ephe"
    empty.mkdir()
    (empty / "README").write_text("no ephemeris files here")
    record = tmp_path / "RELEASE.json"
    assert cli.main(["release", "--ephe-path", str(empty), "--release", str(record)],
                    None, open(os.devnull, "wb"), None) == 0
    code, out, err = run(SKY, record)
    assert code == 3 and out == b"" and "Moshier" in err


def test_out_writes_the_same_bytes_as_stdout(release_path, tmp_path):
    target = tmp_path / "facts.json"
    target.write_text("old")
    code, out, _ = run(SKY, release_path, "--out", str(target))
    assert code == 0 and target.read_bytes() == out
    assert os.listdir(tmp_path) == ["facts.json"]


def test_out_keeps_old_file_on_rejected_request(release_path, tmp_path):
    target = tmp_path / "facts.json"
    target.write_text("old")
    code, _, _ = run(None, release_path, "--out", str(target), raw=b'{"op": "sky"}')
    assert code == 2 and target.read_text() == "old"
    assert os.listdir(tmp_path) == ["facts.json"]


def test_out_keeps_old_file_when_stdout_fails(release_path, tmp_path):
    class Broken:
        def write(self, data):
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self):
            pass

    target = tmp_path / "facts.json"
    target.write_text("old")
    stdin = io.BytesIO(json.dumps(SKY).encode())
    stderr = io.StringIO()
    code = cli.main(["--release", str(release_path), "--out", str(target)], stdin, Broken(), stderr)
    assert code == 1 and "stdout" in stderr.getvalue()
    assert target.read_text() == "old"
    assert os.listdir(tmp_path) == ["facts.json"]


def test_out_into_missing_directory_exits_1(release_path, tmp_path):
    code, out, err = run(SKY, release_path, "--out", str(tmp_path / "nope" / "facts.json"))
    assert code == 1 and out == b"" and "could not write" in err


def test_entry_point_and_exit_codes(release_path):
    env = {**os.environ, "SKYDATA_RELEASE": str(release_path)}
    ok = subprocess.run([sys.executable, "-m", "skydata"], input=json.dumps(SKY).encode(),
                        capture_output=True, env=env)
    assert ok.returncode == 0 and json.loads(ok.stdout)["results"][0]["jd_ut"] == 2461485.0
    bad = subprocess.run([sys.executable, "-m", "skydata"], input=b"{}", capture_output=True, env=env)
    assert bad.returncode == 2 and bad.stdout == b""
    version = subprocess.run([sys.executable, "-m", "skydata", "--version"], capture_output=True)
    assert version.returncode == 0 and version.stdout.decode().strip() == f"skydata {__version__}"
