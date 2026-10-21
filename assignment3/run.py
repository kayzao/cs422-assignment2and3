#!/usr/bin/env python3
"""Run Assignment 3's four-algorithm, ten-second comparison with Assignment 2."""
from pathlib import Path
import subprocess
import sys

command = sys.argv[1:]
if command[0] in ("plan", "run"):
    command += ["--duration", "10", "--algorithms", "cubic", "reno", "bbr", "rttgood"]
raise SystemExit(subprocess.call([sys.executable, str(Path(__file__).resolve().parents[1] / "run.py"), *command]))
