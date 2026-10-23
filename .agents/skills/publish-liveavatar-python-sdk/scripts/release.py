"""Prepare and verify releases. Never uploads; uses only Python's standard library."""

import argparse
import email
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

PACKAGE = "liveavatar-channel-sdk"


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def metadata(path):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = [
                n
                for n in archive.namelist()
                if n.count("/") == 1 and n.endswith(".dist-info/METADATA")
            ]
            if len(names) != 1:
                raise ValueError("Expected one wheel METADATA")
            raw = archive.read(names[0])
    else:
        with tarfile.open(path, "r:gz") as archive:
            names = [n for n in archive.getnames() if n.count("/") == 1 and n.endswith("/PKG-INFO")]
            if len(names) != 1:
                raise ValueError("Expected one sdist PKG-INFO")
            raw = archive.extractfile(names[0]).read()
    info = email.message_from_bytes(raw)
    return info["Name"], info["Version"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remote(version):
    if not re.fullmatch(r"[A-Za-z0-9.!+_-]+", version):
        raise ValueError("Invalid version URL component")
    url = "https://pypi.org/pypi/{}/{}/json".format(PACKAGE, version)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def run(*args, cwd):
    subprocess.run([sys.executable, "-m", *args], cwd=cwd, check=True)


def prepare(args):
    root = Path(args.repo or Path.cwd()).resolve()
    if not args.repo:
        while not (root / "pyproject.toml").is_file() and root != root.parent:
            root = root.parent
    if not (root / "pyproject.toml").is_file():
        raise ValueError("No pyproject.toml; provide --repo")
    # Built metadata supports both static and dynamic project versions.
    run("pytest", cwd=root)
    output = Path(tempfile.mkdtemp(prefix="liveavatar-release-"))
    run("build", "--outdir", str(output), cwd=root)
    wheels = list(output.glob("*.whl"))
    sources = list(output.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Expected exactly one wheel and one sdist")
    files = wheels + sources
    name, version = metadata(files[0])
    if normalized(name) != PACKAGE or any(metadata(p) != (name, version) for p in files):
        raise ValueError("Unexpected package name or inconsistent artifact metadata")
    if args.version and version != args.version:
        raise ValueError("Built version differs from requested version")
    run("twine", "check", *(str(p) for p in files), cwd=root)
    if remote(version) is not None:
        raise ValueError("Version already exists on PyPI; do not upload")
    manifest = {
        "name": name,
        "version": version,
        "repository": "https://upload.pypi.org/legacy/",
        "tests": "pytest passed",
        "files": [
            {"filename": p.name, "size": p.stat().st_size, "sha256": digest(p)} for p in files
        ],
    }
    target = output / "release.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(target)
    print(json.dumps(manifest, indent=2))
    print("Prepared only. User confirmation is required before upload.")


def check(args):
    path = Path(args.manifest).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        normalized(manifest["name"]) != PACKAGE
        or manifest["repository"] != "https://upload.pypi.org/legacy/"
    ):
        raise ValueError("Unexpected package or destination")
    entries = manifest["files"]
    names = [e["filename"] for e in entries]
    if (
        len(names) != 2
        or len(set(names)) != 2
        or sum(n.endswith(".whl") for n in names) != 1
        or sum(n.endswith(".tar.gz") for n in names) != 1
    ):
        raise ValueError("Expected one wheel and one sdist")
    for entry in entries:
        name = entry["filename"]
        if Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Invalid artifact filename")
        artifact = path.parent / name
        if (
            artifact.is_symlink()
            or digest(artifact) != entry["sha256"]
            or artifact.stat().st_size != entry["size"]
        ):
            raise ValueError("Artifact changed: " + name)
        if metadata(artifact) != (manifest["name"], manifest["version"]):
            raise ValueError("Artifact metadata changed: " + name)
    if args.command == "verify":
        data = remote(manifest["version"])
        if data is None:
            raise ValueError("Version not visible on PyPI; do not blindly re-upload")
        if (
            normalized(data["info"]["name"]) != PACKAGE
            or data["info"]["version"] != manifest["version"]
        ):
            raise ValueError("Remote metadata mismatch")
        actual = {f["filename"]: f["digests"]["sha256"] for f in data["urls"]}
        for entry in entries:
            if actual.get(entry["filename"]) != entry["sha256"]:
                raise ValueError("Remote artifact missing or hash mismatch: " + entry["filename"])
        print("Verified: https://pypi.org/project/{}/{}/".format(PACKAGE, manifest["version"]))
    else:
        print(json.dumps(manifest, indent=2))
        print("Local artifacts match manifest. Compare manifest SHA-256 with the approved value:")
        print(digest(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser(
        "prepare", help="Run tests, build, check metadata and PyPI availability"
    )
    prepare_parser.add_argument(
        "--repo", help="Repository path; otherwise discover from current directory"
    )
    prepare_parser.add_argument("--version", help="Expected version, checked without changing it")
    for command in ("check", "verify"):
        commands.add_parser(command).add_argument("manifest")
    args = parser.parse_args()
    try:
        prepare(args) if args.command == "prepare" else check(args)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, "{}: {}\n".format(type(error).__name__, error))


if __name__ == "__main__":
    main()
