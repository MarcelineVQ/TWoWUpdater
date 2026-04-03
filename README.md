# TWoWUpdater

Launcherless TurtleWoW updating. Fetches and compiles new MPQ changes.

## Requirements

- Python 3.10+
- Linux (x64) or Windows (x64)

StormLib is automatically downloaded (if needed) on first run.

## Quick Start

### Windows

1. Install [Python 3](https://www.python.org/downloads/) (check **Add Python to PATH** during install)
2. [Download](https://github.com/MarcelineVQ/TWoWUpdater/archive/refs/heads/master.zip) or clone this repo
3. Double-click **update.bat**
4. Paste your TurtleWoW game directory when prompted

### Linux

```bash
git clone https://github.com/MarcelineVQ/TWoWUpdater.git
cd TWoWUpdater
python3 twow_updater.py update
```

You'll be prompted for your game directory if you don't pass `--game-dir`.

## Usage

```bash
# Update your game (check, download, build, install)
python twow_updater.py update
python twow_updater.py update -g /path/to/TurtleWoW/

# Update and strip redundant files from MPQs to save disk space
python twow_updater.py update --strip

# Restore full MPQs (remove strip, then re-download originals)
python twow_updater.py update --unstrip

# Just check what needs updating
python twow_updater.py check

# Run steps separately
python twow_updater.py download
python twow_updater.py build

# Clean up downloads and built MPQs
python twow_updater.py clean
```

The game directory path can be in Linux or Windows format, with or without a trailing `Data/` directory.

### Options

```
--game-dir, -g    TurtleWoW game directory (prompted if not set)
--region, -r      Server region: EU, SEA, SA (default: EU)
--download-dir    Download directory (default: ./downloads)
--mirror, -m      CDN mirror: r2eu, bunny, linode, r2, tc (default: r2eu)
```

### Update options

```
--strip           Strip redundant files from MPQs after updating
--unstrip         Restore full MPQs before updating (removes strip markers)
--force, -f       Force MPQ rebuild even if no changes detected
--no-verify       Skip hash verification (use if CDN is out of sync)
--workers, -w     Parallel downloads (default: 10)
```

### Download options

```
--all             Download all manifest files, not just outdated
--include-mpq     Include .mpq files when using --all
--no-verify       Skip hash verification (use if CDN is out of sync)
--workers, -w     Parallel downloads (default: 10)
```

### Build options

```
--force, -f       Force rebuild even if no changes detected
```

## Commands

| Command | Description |
|---------|-------------|
| `update` | Full pipeline: check, download, build MPQs, install to game dir |
| `check` | Verify game files against manifest |
| `download` | Download outdated files (auto-runs check if needed) |
| `build` | Build/update MPQs from downloaded files |
| `clean` | Remove downloads and built MPQs |

## How it works

1. Fetches the official TurtleWoW manifest for your region
2. Compares your game files against the manifest (client files by hash, patch files inside MPQs)
3. Downloads changed/missing files from TurtleWoW CDN
4. Builds updated patch MPQs, only modifying files that actually differ
5. Installs updated files to your game directory

Stale downloads from previous manifest versions are automatically cleaned. Files already matching the manifest are skipped during both download and build.

## Stripping

WoW 1.12's MPQ system loads files by priority: `patch-9` overrides `patch-8`, which overrides `patch-7`, and so on down to the base archives. Many files exist in multiple MPQs but only the highest-priority copy is ever loaded.

`update --strip` removes these redundant copies and compacts the archives, typically saving 2+ GB of disk space. A `.stripped` marker is added to each modified MPQ so the updater knows the hash mismatch is intentional.

`update --unstrip` removes the markers, causing the next update to re-download the original full MPQs. Both flags can be combined: `update --unstrip --strip` restores originals then re-strips after updating.

## License

MIT
