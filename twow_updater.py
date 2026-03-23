#!/usr/bin/env python3
"""
TurtleWoW Update Checker & Downloader

Checks game files against the official manifest and downloads updates.
Supports both full MPQ verification (patch through patch-7) and
individual file verification inside patch-8/patch-9.

Usage:
    # Activate venv first: source .venv/bin/activate
    python twow_updater.py check          # Check what needs updating
    python twow_updater.py download       # Download outdated files
    python twow_updater.py build-mpq      # Build MPQs from downloaded files (requires Wine+MPQEditor)
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Import our StormLib wrapper
try:
    import stormlib
    HAS_STORMLIB = True
except ImportError:
    HAS_STORMLIB = False
    print("Warning: StormLib not available. Run 'make' to build it.")

LAUNCHER_API = "https://launcher.turtlecraft.gg/api"
DEFAULT_REGION = "EU"
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_GAME_DIR = None
DEFAULT_DOWNLOAD_DIR = SCRIPT_DIR / "downloads"
DEFAULT_MIRROR = "r2eu"
MIRROR_ORDER = ["r2eu", "bunny", "linode", "r2", "tc"]

# MPQEditor path for building MPQs
MPQEDITOR_PATH = Path("/home/august/projects/wtools-Tools/MPQEditor 3.5.0.733/MPQEditor.exe")


@dataclass
class FileStatus:
    """Status of a file check."""
    name: str
    expected_hash: str
    expected_size: int
    actual_hash: Optional[str] = None
    actual_size: Optional[int] = None
    status: str = "unknown"  # "ok", "missing", "hash_mismatch", "size_mismatch"
    category: str = ""  # "client", "patch-8", "patch-9"
    mirrors: dict = field(default_factory=dict)


def normalize_path(path_str: str) -> Path:
    """Clean up a user-provided path: strip quotes, trailing Data/, expand ~."""
    # Strip quotes and whitespace
    while len(path_str) > 1 and (path_str[0] in '"\'') and path_str[-1] == path_str[0]:
        path_str = path_str[1:-1]
    path_str = path_str.strip()
    # Strip trailing Data/ - user may have pointed at the Data subdirectory
    stripped = path_str.rstrip('/').rstrip('\\')
    if stripped.lower().endswith(('/data', '\\data')):
        stripped = stripped[:-5]
    return Path(stripped or path_str).expanduser()


def find_wow_exe(game_dir: Path) -> Optional[Path]:
    """Find WoW.exe in a directory. Tries case-insensitive name match first,
    then falls back to scanning .exe files for the TurtleWoW version string."""
    import re
    try:
        exe_files = [f for f in game_dir.iterdir() if f.suffix.lower() == '.exe' and f.is_file()]
    except OSError:
        return None

    # First pass: case-insensitive name match
    for f in exe_files:
        if f.name.lower() == "wow.exe":
            return f

    # Second pass: scan .exe files for the TurtleWoW version signature
    for f in exe_files:
        try:
            data = f.read_bytes()
            if re.search(rb'\d{4,5}\x00+\d+\.\d+\.\d+\x00+RELEASE_BUILD', data):
                return f
        except OSError:
            continue

    return None


def validate_game_dir(game_dir: Optional[Path]) -> Path:
    """Validate that game_dir contains WoW.exe. Returns resolved path or prompts if not found."""
    if game_dir is not None:
        game_dir = game_dir.resolve()

    while game_dir is None or find_wow_exe(game_dir) is None:
        if game_dir is not None:
            print(f"WoW.exe not found in {game_dir}")
        try:
            user_input = input("Enter your TurtleWoW game directory: ")
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        game_dir = normalize_path(user_input).resolve()

    return game_dir


def resolve_region(region: str) -> str:
    """Validate region against the API's region list, returning the canonical casing."""
    url = f"{LAUNCHER_API}/versions"
    req = urllib.request.Request(url, headers={"User-Agent": "TurtleWoW-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=10) as response:
        versions = json.loads(response.read().decode())
    lookup = {v.upper(): v for v in versions}
    canonical = lookup.get(region.upper())
    if canonical is None:
        print(f"Error: Unknown region '{region}'. Available: {', '.join(versions)}", file=sys.stderr)
        sys.exit(1)
    return canonical


def fetch_manifest(region: str) -> dict:
    """Fetch the manifest from the launcher API."""
    url = f"{LAUNCHER_API}/manifest/{region}"
    print(f"Fetching manifest from {url}...")
    req = urllib.request.Request(url, headers={"User-Agent": "TurtleWoW-Updater/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def sha256_file(filepath: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest().upper()


def sha256_bytes(data: bytes) -> str:
    """Calculate SHA256 hash of bytes."""
    return hashlib.sha256(data).hexdigest().upper()


def check_client_files(manifest: dict, game_dir: Path) -> list[FileStatus]:
    """Check client files (full MPQ hashes)."""
    results = []

    for item in manifest.get("client", []):
        if item.get("type") != "file" or not item.get("hash"):
            continue

        name = item["name"]
        filepath = game_dir / name

        status = FileStatus(
            name=name,
            expected_hash=item["hash"].upper(),
            expected_size=item["size"],
            category="client",
            mirrors=item.get("mirrors", {})
        )

        if not filepath.exists():
            status.status = "missing"
        else:
            status.actual_size = filepath.stat().st_size
            if status.actual_size != status.expected_size:
                status.status = "size_mismatch"
            else:
                print(f"  Hashing {name}...", end="", flush=True)
                status.actual_hash = sha256_file(filepath)
                if status.actual_hash == status.expected_hash:
                    status.status = "ok"
                    print(" OK")
                else:
                    status.status = "hash_mismatch"
                    print(" MISMATCH")

        results.append(status)

    return results


def check_patch_files(manifest: dict, game_dir: Path) -> list[FileStatus]:
    """Check files inside patch-8 and patch-9 MPQs using StormLib."""
    if not HAS_STORMLIB:
        print("Warning: StormLib not available, skipping patch-8/9 verification")
        print("         Run 'make' to build StormLib support")
        return []

    results = []

    for patch in manifest.get("patches", []):
        patch_key = patch["key"]
        patch_name = f"patch-{patch_key}"
        mpq_path = game_dir / "Data" / f"{patch_name}.mpq"

        files_in_patch = [f for f in patch.get("files", []) if f.get("type") == "file"]
        if not files_in_patch:
            continue  # Skip empty patches like patch-Z

        if not mpq_path.exists():
            print(f"  {mpq_path.name}: MISSING")
            for item in files_in_patch:
                results.append(FileStatus(
                    name=item["name"],
                    expected_hash=item["hash"].upper(),
                    expected_size=item["size"],
                    status="missing",
                    category=patch_name,
                    mirrors=item.get("mirrors", {})
                ))
            continue

        print(f"  Checking {mpq_path.name} ({len(files_in_patch)} files)...")

        try:
            archive = stormlib.MPQArchive(mpq_path, mode='r')
        except Exception as e:
            print(f"    Error opening {mpq_path}: {e}")
            continue

        checked = 0

        for item in files_in_patch:
            name = item["name"]

            status = FileStatus(
                name=name,
                expected_hash=item["hash"].upper(),
                expected_size=item["size"],
                category=patch_name,
                mirrors=item.get("mirrors", {})
            )

            try:
                if not archive.has_file(name):
                    status.status = "missing"
                else:
                    # Read and hash the file
                    data = archive.read_file(name)

                    status.actual_size = len(data)
                    status.actual_hash = sha256_bytes(data)

                    if status.actual_hash == status.expected_hash:
                        status.status = "ok"
                    else:
                        status.status = "hash_mismatch"
            except Exception as e:
                status.status = "error"

            results.append(status)
            checked += 1
            if checked % 500 == 0:
                print(f"    Checked {checked}/{len(files_in_patch)} files...")

        archive.close()
        print(f"    Checked {checked} files")

    return results


def print_status_summary(results: list[FileStatus]):
    """Print a summary of file statuses."""
    by_category = {}
    for r in results:
        if r.category not in by_category:
            by_category[r.category] = {"ok": 0, "missing": 0, "hash_mismatch": 0, "size_mismatch": 0, "error": 0}
        by_category[r.category][r.status] = by_category[r.category].get(r.status, 0) + 1

    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)

    total_ok = 0
    total_outdated = 0

    for category, counts in sorted(by_category.items()):
        ok = counts.get("ok", 0)
        outdated = counts.get("missing", 0) + counts.get("hash_mismatch", 0) + counts.get("size_mismatch", 0)
        total_ok += ok
        total_outdated += outdated

        status_str = "✓ UP TO DATE" if outdated == 0 else f"✗ {outdated} OUTDATED"
        print(f"  {category}: {ok} ok, {status_str}")

    print("-" * 60)
    print(f"  TOTAL: {total_ok} files OK, {total_outdated} files need updating")

    return total_outdated


def get_outdated_files(results: list[FileStatus]) -> list[FileStatus]:
    """Get list of files that need updating."""
    return [r for r in results if r.status in ("missing", "hash_mismatch", "size_mismatch")]


def download_file(url: str, dest_path: Path, expected_hash: str = None, expected_size: int = None,
                  verify: bool = True, quiet: bool = False) -> bool:
    """Download a file with optional progress indication."""
    from urllib.parse import quote, urlparse, urlunparse

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")

    # URL-encode the path component (handles spaces and special chars)
    parsed = urlparse(url)
    encoded_path = quote(parsed.path, safe='/')
    url = urlunparse(parsed._replace(path=encoded_path))

    req = urllib.request.Request(url, headers={"User-Agent": "TurtleWoW-Updater/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0

            with open(temp_path, "wb") as f:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

            if not quiet:
                size_mb = downloaded / (1024*1024)
                print(f"    Downloaded {size_mb:.1f} MB")

        # Verify hash (unless verify=False)
        if expected_hash and verify:
            actual_hash = sha256_file(temp_path)
            if actual_hash.upper() != expected_hash.upper():
                temp_path.unlink()
                raise ValueError(f"Hash mismatch: expected {expected_hash[:16]}..., got {actual_hash[:16]}...")

        temp_path.rename(dest_path)
        return True

    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise


def _download_single_file(args: tuple, max_retries: int = 3, base_delay: float = 1.0) -> tuple[str, bool, str]:
    """Download a single file with exponential backoff retry. Returns (name, success, error_msg)."""
    import time
    import random

    f, download_dir, mirror, verify = args

    dest = download_dir / f.category / f.name

    # Check if already downloaded
    if dest.exists():
        try:
            existing_hash = sha256_file(dest)
            if existing_hash.upper() == f.expected_hash.upper():
                return (f.name, True, "already downloaded")
        except:
            pass

    # Try mirrors in order, with retries per mirror
    mirrors_to_try = [mirror] + [m for m in MIRROR_ORDER if m != mirror]
    last_error = "no mirrors"

    for m in mirrors_to_try:
        if m not in f.mirrors:
            continue

        url = f.mirrors[m]

        for attempt in range(max_retries):
            try:
                download_file(url, dest, f.expected_hash, f.expected_size, verify=verify, quiet=True)
                return (f.name, True, m)
            except Exception as e:
                last_error = str(e)

                # Don't retry on hash mismatch - that's a server issue, try next mirror
                if "Hash mismatch" in last_error:
                    break

                # Exponential backoff with jitter
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)

    return (f.name, False, last_error)


def download_outdated(outdated: list[FileStatus], download_dir: Path, mirror: str = DEFAULT_MIRROR,
                      verify: bool = True, workers: int = 10):
    """Download outdated files using parallel downloads."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    print(f"\nDownloading {len(outdated)} files to {download_dir}")
    print(f"Using mirror: {mirror} with {workers} parallel downloads")
    if not verify:
        print("WARNING: Hash verification disabled!")

    # Calculate total size
    total_size = sum(f.expected_size for f in outdated)
    print(f"Total download size: {total_size / (1024*1024*1024):.2f} GB\n")

    failed = []  # List of (name, reason) tuples
    succeeded = 0
    skipped = 0
    lock = threading.Lock()
    completed = [0]  # Use list for mutable counter in closure

    def update_progress(name: str, success: bool, msg: str):
        nonlocal succeeded, skipped
        with lock:
            completed[0] += 1
            pct = (completed[0] / len(outdated)) * 100
            if success:
                if msg == "already downloaded":
                    skipped += 1
                    print(f"[{completed[0]}/{len(outdated)}] {pct:5.1f}% ⊘ {name} (cached)")
                else:
                    succeeded += 1
                    print(f"[{completed[0]}/{len(outdated)}] {pct:5.1f}% ✓ {name}")
            else:
                failed.append((name, msg))
                print(f"[{completed[0]}/{len(outdated)}] {pct:5.1f}% ✗ {name} ({msg})")

    # Prepare download args
    download_args = [(f, download_dir, mirror, verify) for f in outdated]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_download_single_file, args): args[0] for args in download_args}

        for future in as_completed(futures):
            name, success, msg = future.result()
            update_progress(name, success, msg)

            # Update download state for successful downloads
            if success and msg != "already downloaded":
                f = futures[future]
                update_download_state_for_file(download_dir, f.category, f.name, f.expected_hash)

    print(f"\n{'=' * 60}")
    print(f"Download complete: {succeeded} downloaded, {skipped} cached, {len(failed)} failed")

    if failed:
        print("\nFailed files:")
        for name, reason in failed[:20]:
            print(f"  - {name}: {reason}")
        if len(failed) > 20:
            print(f"  ... and {len(failed) - 20} more")

        # Check if any failures were hash mismatches
        hash_mismatches = [name for name, reason in failed if "Hash mismatch" in reason]
        if hash_mismatches:
            print(f"\n⚠ {len(hash_mismatches)} file(s) failed due to hash mismatch.")
            print("  This usually means the CDN has different files than the downloaded manifest expects.")
            print("  To download anyway, use: --no-verify")

    return len(failed) == 0


def build_mpq(patch_key: str, download_dir: Path, output_path: Path):
    """Build an MPQ from downloaded files using MPQEditor via Wine."""
    if not MPQEDITOR_PATH.exists():
        print(f"Error: MPQEditor not found at {MPQEDITOR_PATH}")
        return False

    source_dir = download_dir / f"patch-{patch_key}"
    if not source_dir.exists():
        print(f"Error: Source directory not found: {source_dir}")
        return False

    print(f"Building {output_path.name} from {source_dir}...")

    # Use MPQEditor command line via Wine
    # MPQEditor.exe /new archive.mpq /add folder\ * /c /r
    cmd = [
        "wine", str(MPQEDITOR_PATH),
        "/new", str(output_path),
        "/add", str(source_dir) + "\\", "*",
        "/c", "/r"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print(f"  ✓ Built {output_path.name}")
            return True
        else:
            print(f"  ✗ Failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


def cmd_check(args):
    """Check command - verify game files."""
    args.game_dir = validate_game_dir(args.game_dir)
    region = resolve_region(args.region)
    manifest = fetch_manifest(region)

    print(f"\nGame directory: {args.game_dir}")
    print("\n" + "=" * 60)
    print("CHECKING CLIENT FILES (full MPQ verification)")
    print("=" * 60)

    client_results = check_client_files(manifest, args.game_dir)

    print("\n" + "=" * 60)
    print("CHECKING PATCH FILES (inside patch-8/patch-9)")
    print("=" * 60)

    patch_results = check_patch_files(manifest, args.game_dir)

    all_results = client_results + patch_results
    outdated_count = print_status_summary(all_results)

    if outdated_count > 0:
        outdated = get_outdated_files(all_results)
        print("\nOutdated files:")
        by_cat = {}
        for f in outdated:
            if f.category not in by_cat:
                by_cat[f.category] = []
            by_cat[f.category].append(f)

        for cat, files in sorted(by_cat.items()):
            total_size = sum(f.expected_size for f in files)
            print(f"\n  {cat}: {len(files)} files ({total_size/(1024*1024):.1f} MB)")
            # Sort: mismatches first, then missing
            status_order = {"hash_mismatch": 0, "size_mismatch": 1, "missing": 2}
            sorted_files = sorted(files, key=lambda f: (status_order.get(f.status, 3), f.name))
            for f in sorted_files:
                print(f"    - {f.name} ({f.status})")

    # Save results for download command
    args.download_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.download_dir / "check_results.json"
    with open(results_path, "w") as f:
        json.dump([{
            "name": r.name,
            "expected_hash": r.expected_hash,
            "expected_size": r.expected_size,
            "status": r.status,
            "category": r.category,
            "mirrors": r.mirrors
        } for r in all_results], f, indent=2)
    print(f"\nResults saved to {results_path}")

    return outdated_count == 0


def merge_dlls_txt(new_file: Path, existing_file: Path):
    """Merge new dlls.txt entries into the existing one.

    Adds entries from new_file that aren't already present in existing_file.
    Respects commented-out entries -- if a DLL is commented out (e.g. #nampower.dll)
    it's treated as intentionally disabled and won't be re-added."""
    new_lines = new_file.read_text().splitlines()
    new_entries = set()
    for line in new_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            new_entries.add(stripped.lower())

    if not existing_file.exists():
        # No existing file, just copy
        import shutil
        existing_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(new_file, existing_file)
        print(f"  {existing_file.name} (created)")
        return

    existing_text = existing_file.read_text()
    existing_lines = existing_text.splitlines()

    # Build set of all DLL names present in existing file (active or commented)
    existing_names = set()
    for line in existing_lines:
        # Strip any leading # characters and whitespace to get the bare name
        name = line.lstrip('#').strip().lower()
        if name:
            existing_names.add(name)

    # Find entries in new that aren't in existing at all (not even commented)
    to_add = []
    for entry in sorted(new_entries):
        if entry not in existing_names:
            to_add.append(entry)

    if not to_add:
        return

    # Append new entries
    content = existing_text
    if not content.endswith('\n'):
        content += '\n'
    for entry in to_add:
        content += entry + '\n'

    existing_file.write_text(content)
    print(f"  {existing_file.name} (added {len(to_add)} entries: {', '.join(to_add)})")


def cmd_update(args):
    """Update command - check, download, build MPQs, and install to game directory."""
    import shutil

    # Clear downloads to avoid stale files from previous runs
    if args.download_dir.exists():
        shutil.rmtree(args.download_dir)
        args.download_dir.mkdir(parents=True)

    # First check
    print("=" * 60)
    print("STEP 1: CHECKING FOR UPDATES")
    print("=" * 60)

    all_up_to_date = cmd_check(args)
    if all_up_to_date:
        print("\nEverything is up to date, nothing to do.")
        return True

    # Then download
    print("\n" + "=" * 60)
    print("STEP 2: DOWNLOADING UPDATES")
    print("=" * 60)

    download_success = cmd_download(args)

    # Build MPQs only if there are outdated patch files
    results_path = args.download_dir / "check_results.json"
    with open(results_path) as f:
        results = [FileStatus(**r) for r in json.load(f)]
    patch_outdated = [r for r in get_outdated_files(results) if r.category.startswith("patch-")]

    build_success = True
    if patch_outdated:
        print("\n" + "=" * 60)
        print("STEP 3: BUILDING MPQs")
        print("=" * 60)

        args.force = True
        build_success = cmd_build_mpq(args)

    # Install files that differ by absence or hash
    print("\n" + "=" * 60)
    print("STEP 4: INSTALLING TO GAME DIRECTORY")
    print("=" * 60)

    installed = 0

    def install_if_changed(src: Path, dest: Path):
        """Copy src to dest only if dest is missing or has a different hash."""
        nonlocal installed
        if dest.exists():
            if sha256_file(src) == sha256_file(dest):
                return
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"  {dest.relative_to(args.game_dir)}")
        shutil.copy2(src, dest)
        installed += 1

    # Install built MPQs (patch-8, patch-9)
    mpq_dir = SCRIPT_DIR / "mpqs"
    game_data_dir = args.game_dir / "Data"
    for mpq_file in sorted(mpq_dir.glob("*.mpq")):
        install_if_changed(mpq_file, game_data_dir / mpq_file.name)

    # Install client files (full MPQs, DLLs, etc.)
    client_dir = args.download_dir / "client"
    if client_dir.exists():
        for f in client_dir.rglob('*'):
            if not f.is_file():
                continue
            rel = f.relative_to(client_dir)
            dest = args.game_dir / rel
            if f.name.lower() == "dlls.txt":
                merge_dlls_txt(f, dest)
                installed += 1
            else:
                install_if_changed(f, dest)

    if installed:
        print(f"\nInstalled {installed} file(s)")
    else:
        print("\nNothing to install, game files already match")

    return download_success and build_success


def clean_stale_downloads(manifest: dict, download_dir: Path):
    """Remove downloaded files that aren't in the manifest or have wrong hashes."""
    # Build map of expected files per category: name -> hash
    expected = {}
    for patch in manifest.get("patches", []):
        category = f"patch-{patch['key']}"
        expected[category] = {}
        for item in patch.get("files", []):
            if item.get("type") == "file" and item.get("hash"):
                expected[category][item["name"]] = item["hash"].upper()

    removed = 0
    for category, expected_files in expected.items():
        cat_dir = download_dir / category
        if not cat_dir.exists():
            continue
        for f in list(cat_dir.rglob('*')):
            if not f.is_file():
                continue
            rel = str(f.relative_to(cat_dir))
            if rel not in expected_files:
                f.unlink()
                removed += 1
            else:
                # Check hash matches
                actual_hash = sha256_file(f)
                if actual_hash != expected_files[rel]:
                    print(f"  Removing stale: {rel}")
                    f.unlink()
                    removed += 1
        # Clean empty dirs
        for d in sorted(cat_dir.rglob('*'), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()

    if removed:
        print(f"Cleaned {removed} stale file(s) from downloads")


def cmd_download(args):
    """Download command - download outdated files or all manifest files."""

    if getattr(args, 'all', False):
        # Download all manifest files mode
        region = resolve_region(args.region)
        print("Fetching manifest...")
        try:
            manifest = fetch_manifest(region)
        except Exception as e:
            print(f"Error fetching manifest: {e}")
            return False

        clean_stale_downloads(manifest, args.download_dir)

        # Collect all files from manifest
        files_to_download = []

        # Client files
        for item in manifest.get("client", []):
            if item.get("type") != "file" or not item.get("hash"):
                continue
            name = item["name"]
            # Skip .mpq files unless --include-mpq
            if name.lower().endswith('.mpq') and not getattr(args, 'include_mpq', False):
                continue
            files_to_download.append(FileStatus(
                name=name,
                expected_hash=item["hash"].upper(),
                expected_size=item["size"],
                status="download_all",
                category="client",
                mirrors=item.get("mirrors", {})
            ))

        # Patch files
        for patch in manifest.get("patches", []):
            patch_key = patch["key"]
            for item in patch.get("files", []):
                if item.get("type") != "file" or not item.get("hash"):
                    continue
                files_to_download.append(FileStatus(
                    name=item["name"],
                    expected_hash=item["hash"].upper(),
                    expected_size=item["size"],
                    status="download_all",
                    category=f"patch-{patch_key}",
                    mirrors=item.get("mirrors", {})
                ))

        if not files_to_download:
            print("No files found in manifest!")
            return False

        mpq_note = " (excluding .mpq files)" if not getattr(args, 'include_mpq', False) else ""
        print(f"Found {len(files_to_download)} files in manifest{mpq_note}")

        return download_outdated(files_to_download, args.download_dir, args.mirror,
                                  verify=not args.no_verify, workers=args.workers)

    # Normal mode - download outdated files, auto-run check if needed
    results_path = args.download_dir / "check_results.json"

    if not results_path.exists():
        print("No check results found, running check first...\n")
        cmd_check(args)

    with open(results_path) as f:
        results_data = json.load(f)

    results = [FileStatus(**r) for r in results_data]
    outdated = get_outdated_files(results)

    if not outdated:
        print("All files are up to date!")
        return True

    # Clean stale downloads using the manifest
    region = resolve_region(args.region)
    manifest = fetch_manifest(region)
    clean_stale_downloads(manifest, args.download_dir)

    return download_outdated(outdated, args.download_dir, args.mirror, verify=not args.no_verify, workers=args.workers)


def get_download_state_path(download_dir: Path) -> Path:
    """Get path to download state file."""
    return download_dir / ".download_state.json"


def load_download_state(download_dir: Path) -> dict:
    """Load the download state (tracks what's been downloaded and when)."""
    state_path = get_download_state_path(download_dir)
    if state_path.exists():
        with open(state_path) as f:
            return json.load(f)
    return {"files": {}, "mpq_builds": {}}


def save_download_state(download_dir: Path, state: dict):
    """Save the download state."""
    state_path = get_download_state_path(download_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def update_download_state_for_file(download_dir: Path, category: str, filename: str, file_hash: str):
    """Update state after downloading a file."""
    state = load_download_state(download_dir)
    if category not in state["files"]:
        state["files"][category] = {}
    state["files"][category][filename] = {
        "hash": file_hash,
        "downloaded_at": str(Path(download_dir / category / filename).stat().st_mtime)
    }
    save_download_state(download_dir, state)


def needs_mpq_rebuild(download_dir: Path, patch_key: str) -> bool:
    """Check if an MPQ needs to be rebuilt based on download state."""
    state = load_download_state(download_dir)
    category = f"patch-{patch_key}"

    # Get current files in download directory
    source_dir = download_dir / category
    if not source_dir.exists():
        return False

    current_files = {}
    for f in source_dir.rglob('*'):
        if f.is_file():
            rel_path = str(f.relative_to(source_dir))
            current_files[rel_path] = f.stat().st_mtime

    # Check if we have a build record
    if category not in state.get("mpq_builds", {}):
        return True

    last_build = state["mpq_builds"][category]
    last_build_files = last_build.get("files", {})

    # Compare file sets
    if set(current_files.keys()) != set(last_build_files.keys()):
        return True

    # Compare modification times
    for filename, mtime in current_files.items():
        if filename not in last_build_files:
            return True
        if mtime > last_build_files[filename]:
            return True

    return False


def record_mpq_build(download_dir: Path, patch_key: str, output_dir: Path = None):
    """Record that an MPQ was built."""
    if output_dir is None:
        output_dir = SCRIPT_DIR / "mpqs"

    state = load_download_state(download_dir)
    category = f"patch-{patch_key}"
    source_dir = download_dir / category
    mpq_path = output_dir / f"{category}.mpq"

    files = {}
    for f in source_dir.rglob('*'):
        if f.is_file():
            rel_path = str(f.relative_to(source_dir))
            files[rel_path] = f.stat().st_mtime

    if "mpq_builds" not in state:
        state["mpq_builds"] = {}

    state["mpq_builds"][category] = {
        "built_at": str(os.path.getmtime(mpq_path)) if mpq_path.exists() else None,
        "files": files
    }
    save_download_state(download_dir, state)


def cmd_clean(args):
    """Clean command - remove build MPQs and downloaded files."""
    import shutil

    download_dir = args.download_dir
    mpq_dir = SCRIPT_DIR / "mpqs"
    removed_files = 0
    removed_dirs = 0

    # Remove built MPQ directory
    if mpq_dir.exists() and mpq_dir.is_dir():
        mpq_files = list(mpq_dir.glob('*.mpq'))
        if mpq_files:
            print(f"Removing built MPQs:")
            for mpq_file in mpq_files:
                print(f"  - {mpq_file.name}")
                removed_files += 1
        shutil.rmtree(mpq_dir)
        removed_dirs += 1

    # Remove download state file
    state_path = get_download_state_path(download_dir)
    if state_path.exists():
        print(f"Removing {state_path}")
        state_path.unlink()
        removed_files += 1

    # Remove check results
    results_path = download_dir / "check_results.json"
    if results_path.exists():
        print(f"Removing {results_path}")
        results_path.unlink()
        removed_files += 1

    # Remove downloaded file directories (patch-8, patch-9, client)
    for subdir in ["patch-8", "patch-9", "client"]:
        subdir_path = download_dir / subdir
        if subdir_path.exists() and subdir_path.is_dir():
            import shutil
            file_count = sum(1 for _ in subdir_path.rglob('*') if _.is_file())
            print(f"Removing {subdir_path} ({file_count} files)")
            shutil.rmtree(subdir_path)
            removed_files += file_count
            removed_dirs += 1

    # Remove downloads dir itself if empty
    if download_dir.exists() and not any(download_dir.iterdir()):
        print(f"Removing empty {download_dir}")
        download_dir.rmdir()
        removed_dirs += 1

    print(f"\nClean complete: removed {removed_files} files, {removed_dirs} directories")
    return True


def get_expected_patch_files(manifest: dict, patch_key: str) -> dict[str, str]:
    """Get expected files for a patch from the manifest. Returns {name: hash}."""
    expected = {}
    for patch in manifest.get("patches", []):
        if patch["key"] == patch_key:
            for item in patch.get("files", []):
                if item.get("type") == "file":
                    # Normalize to backslashes for MPQ comparison
                    name = item["name"].replace("/", "\\")
                    expected[name] = item.get("hash", "").upper()
            break
    return expected


def cmd_build_mpq(args):
    """Build MPQ command - update existing MPQs with downloaded files."""
    if not HAS_STORMLIB:
        print("Error: StormLib not available. Run 'make' to build it.")
        return False

    import shutil

    args.game_dir = validate_game_dir(args.game_dir)
    region = resolve_region(args.region)
    download_dir = args.download_dir
    output_dir = SCRIPT_DIR / "mpqs"  # Built MPQs go here
    output_dir.mkdir(parents=True, exist_ok=True)
    game_data_dir = args.game_dir / "Data"

    # Fetch manifest to know which files should exist
    print("Fetching manifest to determine expected files...")
    try:
        manifest = fetch_manifest(region)
    except Exception as e:
        print(f"Error fetching manifest: {e}")
        return False

    built_any = False

    for patch_key in ["8", "9"]:
        category = f"patch-{patch_key}"
        source_dir = download_dir / category
        output_path = output_dir / f"{category}.mpq"
        game_mpq_path = game_data_dir / f"{category}.mpq"

        # Get expected files from manifest
        expected_files = get_expected_patch_files(manifest, patch_key)
        if not expected_files:
            print(f"{category}: No files defined in manifest, skipping")
            continue

        # Check if we have downloaded files to add
        downloaded_files = []
        if source_dir.exists():
            downloaded_files = [f for f in source_dir.rglob('*') if f.is_file()]

        # Check if rebuild needed
        if not args.force and not needs_mpq_rebuild(download_dir, patch_key):
            print(f"{category}: Up to date, skipping (use --force to rebuild)")
            continue

        # Copy existing MPQ from game directory if we don't have one yet
        if not output_path.exists():
            if game_mpq_path.exists():
                print(f"\nCopying {game_mpq_path} to {output_path}...")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(game_mpq_path, output_path)
            else:
                print(f"\n{category}: No existing MPQ found at {game_mpq_path}, will create new")

        print(f"\nProcessing {output_path.name}...")
        print(f"  Expected files in manifest: {len(expected_files)}")

        try:
            needs_rebuild = False
            current_files = set()

            if output_path.exists():
                # Check current MPQ capacity
                archive = stormlib.MPQArchive(output_path, mode='a')
                current_files = set(archive.list_files())
                print(f"  Current files in MPQ: {len(current_files)}")

                # If MPQ is nearly empty but we need many files, rebuild from scratch
                if len(current_files) < 100 and len(expected_files) > 1000:
                    print(f"  MPQ too small for {len(expected_files)} files, will rebuild...")
                    archive.close()
                    needs_rebuild = True

            if output_path.exists() and not needs_rebuild:
                archive = stormlib.MPQArchive(output_path, mode='a')
                current_files = set(archive.list_files())

                # Find files to remove (in MPQ but not in manifest)
                to_remove = current_files - set(expected_files.keys())
                if to_remove:
                    print(f"  Removing {len(to_remove)} obsolete files...")
                    removed = 0
                    for filename in to_remove:
                        try:
                            archive.remove_file(filename)
                            removed += 1
                        except Exception as e:
                            print(f"    Warning: Could not remove {filename}: {e}")
                    print(f"    Removed {removed} files")

                # Add/update downloaded files only if MPQ copy differs
                added = 0
                updated = 0
                skipped = 0
                if downloaded_files:
                    for file_path in downloaded_files:
                        rel_path = file_path.relative_to(source_dir)
                        archive_name = str(rel_path).replace('/', '\\')
                        expected_hash = expected_files.get(archive_name, "")

                        existed = archive.has_file(archive_name)
                        if existed and expected_hash:
                            # Check if MPQ already has the right version
                            try:
                                mpq_data = archive.read_file(archive_name)
                                if sha256_bytes(mpq_data) == expected_hash:
                                    skipped += 1
                                    continue
                            except Exception:
                                pass

                        archive.add_file(file_path, archive_name)
                        if existed:
                            updated += 1
                        else:
                            added += 1

                archive.close()
                if added or updated or to_remove:
                    print(f"  ✓ Updated {output_path.name}: {added} added, {updated} replaced, {len(to_remove)} removed")
                else:
                    print(f"  ✓ {output_path.name}: up to date")
            else:
                # Create new MPQ from downloaded files (rebuild case or no existing MPQ)
                if downloaded_files:
                    if output_path.exists():
                        output_path.unlink()  # Remove small/corrupt MPQ
                    count = stormlib.create_mpq_from_directory(output_path, source_dir)
                    print(f"  ✓ Created {output_path.name} with {count} files")
                else:
                    print(f"  ✗ Cannot create MPQ without downloaded files")
                    continue

            if downloaded_files:
                record_mpq_build(download_dir, patch_key, output_dir)
            built_any = True

        except Exception as e:
            print(f"  ✗ Failed to update {output_path.name}: {e}")
            import traceback
            traceback.print_exc()

    if built_any:
        print(f"\nMPQ files ready in: {output_dir}")
    else:
        print("\nNo MPQs were built")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="TurtleWoW Update Checker & Downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("--game-dir", "-g", type=normalize_path, default=DEFAULT_GAME_DIR,
                        help="TurtleWoW game directory (will prompt if not set)")
    parser.add_argument("--download-dir", "-d", type=Path, default=DEFAULT_DOWNLOAD_DIR,
                        help=f"Download directory (default: {DEFAULT_DOWNLOAD_DIR})")
    parser.add_argument("--mirror", "-m", choices=MIRROR_ORDER, default=DEFAULT_MIRROR,
                        help=f"CDN mirror (default: {DEFAULT_MIRROR})")
    parser.add_argument("--region", "-r", default=DEFAULT_REGION,
                        help=f"Server region (default: {DEFAULT_REGION})")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Update command (most common operation) - listed first
    update_parser = subparsers.add_parser("update", help="Check, download, build, and install updates")
    update_parser.add_argument("--no-verify", action="store_true",
                                help="Skip hash verification (use if CDN and manifest are out of sync)")
    update_parser.add_argument("--workers", "-w", type=int, default=10,
                                help="Number of parallel downloads (default: 10)")
    update_parser.add_argument("--force", "-f", action="store_true",
                                help="Force MPQ rebuild even if no changes detected")

    check_parser = subparsers.add_parser("check", help="Check game files for updates")
    download_parser = subparsers.add_parser("download", help="Download outdated files")
    download_parser.add_argument("--no-verify", action="store_true",
                                  help="Skip hash verification (use if CDN and manifest are out of sync)")
    download_parser.add_argument("--workers", "-w", type=int, default=10,
                                  help="Number of parallel downloads (default: 10)")
    download_parser.add_argument("--all", "-a", action="store_true",
                                  help="Download all manifest files, not just outdated ones")
    download_parser.add_argument("--include-mpq", action="store_true",
                                  help="Include .mpq files when using --all (excluded by default)")
    build_parser = subparsers.add_parser("build", help="Build MPQs from downloaded files")
    clean_parser = subparsers.add_parser("clean", help="Remove build MPQs and downloaded files")
    build_parser.add_argument("--force", "-f", action="store_true",
                              help="Force rebuild even if no changes detected")

    args = parser.parse_args()

    # Ensure StormLib is available for commands that need it (not for clean or help)
    if args.command and args.command not in ("clean",):
        try:
            import stormlib
            global HAS_STORMLIB
            HAS_STORMLIB = True
        except ImportError as e:
            print(f"StormLib not available: {e}")
            print("Some features (MPQ verification/building) will be disabled.")
            HAS_STORMLIB = False

    if args.command == "update":
        success = cmd_update(args)
        sys.exit(0 if success else 1)
    elif args.command == "check":
        success = cmd_check(args)
        sys.exit(0 if success else 1)
    elif args.command == "download":
        success = cmd_download(args)
        sys.exit(0 if success else 1)
    elif args.command == "build":
        cmd_build_mpq(args)
    elif args.command == "clean":
        cmd_clean(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
