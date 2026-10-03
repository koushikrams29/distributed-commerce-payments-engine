"""Regenerate the pinned requirement locks from the requirements*.in files.

    python scripts/lock_requirements.py            # after editing a .in file
    python scripts/lock_requirements.py --upgrade  # move every pin to the newest allowed version

Existing pins are kept unless --upgrade is given, so an edit to one .in file
changes only what that edit requires. Locks are universal: the same file
installs on the Linux images and CI and on Windows or macOS dev machines.

Needs uv (`pip install uv`). CI regenerates the locks with the uv version
pinned in .github/workflows/ci.yml and fails if anything changed; other uv
versions may format the files differently.
"""

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Matches the service images and CI.
PYTHON_VERSION = "3.11"
# Runtime locks first: each dev lock is constrained by its runtime lock.
LOCKS = ("requirements", "requirements-dev")


def uv_command() -> list[str]:
    if executable := shutil.which("uv"):
        return [executable]
    if importlib.util.find_spec("uv") is not None:
        return [sys.executable, "-m", "uv"]
    sys.exit("uv is not installed: run `pip install uv` first.")


def projects() -> list[Path]:
    services = sorted(p for p in (ROOT / "services").iterdir() if p.is_dir())
    return [ROOT / "libs" / "common", ROOT / "scripts", *services]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--upgrade", action="store_true", help="ignore existing pins and take the newest versions"
    )
    args = parser.parse_args()

    uv = uv_command()
    for project in projects():
        for name in LOCKS:
            source = project / f"{name}.in"
            if not source.exists():
                continue
            print(f"Locking {source.relative_to(ROOT).as_posix()}")
            subprocess.run(
                [
                    *uv, "pip", "compile", source.name,
                    "--output-file", f"{name}.txt",
                    "--universal",
                    "--python-version", PYTHON_VERSION,
                    "--custom-compile-command", "python scripts/lock_requirements.py",
                    "--quiet",
                    *(["--upgrade"] if args.upgrade else []),
                ],
                cwd=project,
                check=True,
            )


if __name__ == "__main__":
    main()
