# TWoWUpdater

Launcherless TurtleWoW updating. Fetches and compiles new MPQ changes.

## Requirements

- Python 3.10+
- Linux (x64) or Windows (x64)

StormLib is automatically downloaded on first run.

## Installation

```bash
git clone https://github.com/MarcelineVQ/TWoWUpdater.git
cd TWoWUpdater
```

## Usage

```bash
# Update your game (check, download, build, install)
python twow_updater.py -g /path/to/TurtleWoW/ update

# Just check what needs updating
python twow_updater.py -g /path/to/TurtleWoW/ check

# Run steps separately:
python twow_updater.py -g /path/to/TurtleWoW/ download
python twow_updater.py -g /path/to/TurtleWoW/ build

# Clean up downloads and built MPQs
python twow_updater.py clean
```

If you don't provide `--game-dir`, you'll be prompted for it. The path can be in Linux or Windows format, with or without a trailing `Data/` directory.

### Options

```
--game-dir, -g    TurtleWoW game directory (prompted if not set)
--region, -r      Server region: EU, SEA, SA (default: EU)
--download-dir    Download directory (default: ./downloads)
--mirror, -m      CDN mirror: r2eu, bunny, linode, r2, tc (default: r2eu)
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

## License

MIT
