import io
import json
import os
from pathlib import Path

import pytest

from skydata import cli
from skydata import release as release_record

EPHE = os.environ.get("SKYDATA_TEST_EPHE")
REFERENCE = json.loads((Path(__file__).parent / "reference" / "swisseph-2.10.03.json").read_text())


@pytest.fixture(scope="session")
def release_path(tmp_path_factory):
    """A release record for the ephemeris files named by SKYDATA_TEST_EPHE."""
    if not EPHE:
        pytest.skip("set SKYDATA_TEST_EPHE to a directory holding sepl_18.se1, semo_18.se1 "
                    "and seas_18.se1 (and the _12 files for the 1750 case)")
    path = tmp_path_factory.mktemp("release") / "RELEASE.json"
    path.write_text(json.dumps(release_record.build(EPHE)))
    return path


def run(request, release_path, *args, raw=None):
    """Run the CLI in process. Returns (exit code, stdout bytes, stderr text)."""
    stdin = io.BytesIO(raw if raw is not None else json.dumps(request).encode())
    stdout, stderr = io.BytesIO(), io.StringIO()
    code = cli.main(["--release", str(release_path), *args], stdin, stdout, stderr)
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def ask(release_path):
    """Run a request that must succeed and return its parsed response."""
    def ask(request):
        code, out, err = run(request, release_path)
        assert code == 0, err
        return json.loads(out)
    return ask
