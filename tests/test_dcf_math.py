"""The front-end DCF math is plain JavaScript; run its own checks in Node."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_dcf_math():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    script = Path(__file__).with_name("dcf_check.js")
    r = subprocess.run([node, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr or r.stdout
    assert "dcf ok" in r.stdout
