"""Smoke tests for runnable examples."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


EXAMPLES = [
    "examples/dynamic_topic_switching_demo.py",
    "examples/ezmsg_toy_session.py",
    "examples/processor_chain_showcase.py",
    "examples/simple_demo.py",
    "examples/processor_chain_demo.py",
]


@pytest.mark.parametrize("example", EXAMPLES)
def test_example_runs_headless(example: str) -> None:
    root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["EZMSG_QT_DEMO_AUTOCLOSE_MS"] = "1500"

    completed = subprocess.run(
        [sys.executable, example],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=25,
    )

    assert completed.returncode == 0, (
        f"example failed: {example}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
