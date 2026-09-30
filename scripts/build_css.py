"""Build web/app.css from web/src/app.css with the Tailwind CSS standalone CLI (no Node.js needed).

The CLI binary is downloaded once into .tools/, pinned to one release and checked against its published SHA-256.
The Docker build runs this script too, so the image always carries a stylesheet built from the current templates.

    python scripts/build_css.py            # build once, minified
    python scripts/build_css.py --watch    # rebuild on every change while working on the front end
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

VERSION = "v4.3.3"
# from the release's sha256sums.txt
SHA256 = {
    "tailwindcss-linux-x64": "dc61b3ac6b8c9ca874c0cc4c57b2409791a64c5540404ca5f5367360babc313a",
    "tailwindcss-linux-arm64": "55fd0b241214eff3de1e8ee4f22796662f2d2e7a49bcfca7477cfd0bac398195",
    "tailwindcss-windows-x64.exe": "e0e260ce048014e9268f6237ff18f8ccf02cef521cbd0ae04e82c2cdf7aa3955",
}
ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / ".tools"
SRC = ROOT / "web" / "src" / "app.css"
OUT = ROOT / "web" / "app.css"


def _asset() -> str:
    system, machine = platform.system().lower(), platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    name = f"tailwindcss-{system}-{arch}" + (".exe" if system == "windows" else "")
    if name not in SHA256:
        sys.exit(f"no pinned Tailwind CLI for {system}/{machine}; add its checksum to scripts/build_css.py")
    return name


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cli() -> Path:
    name = _asset()
    path = TOOLS / f"{VERSION}-{name}"
    if not path.exists() or _sha256(path) != SHA256[name]:
        TOOLS.mkdir(exist_ok=True)
        url = f"https://github.com/tailwindlabs/tailwindcss/releases/download/{VERSION}/{name}"
        print(f"downloading {url}", file=sys.stderr)
        tmp = path.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 (fixed https URL)
            tmp.write_bytes(r.read())
        if _sha256(tmp) != SHA256[name]:
            tmp.unlink()
            sys.exit(f"checksum mismatch for {name}; refusing to run it")
        tmp.replace(path)
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--watch", action="store_true", help="rebuild whenever a template or the source file changes")
    args = ap.parse_args()
    cmd = [str(cli()), "--input", str(SRC), "--output", str(OUT)]
    cmd += ["--watch"] if args.watch else ["--minify"]
    subprocess.run(cmd, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
