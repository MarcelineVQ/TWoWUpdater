# TWoWUpdater

Launcherless TurtleWoW updating. Fetches and compiles new MPQ changes.

## Requirements

- Python 3.10+
- Linux (x64) or Windows (x64)

StormLib is automatically downloaded on first run.

## Installation

```bash
git clone https://github.com/youruser/TWoWUpdater.git
cd TWoWUpdater
```

## Usage

```bash
# Check what needs updating
python twow_updater.py check

# Download updates and build MPQs in one step
python twow_updater.py update
python twow_updater.py --game-dir /games_drive/twmoa_1180/ update

# Or run steps separately:
python twow_updater.py download    # Download outdated files
python twow_updater.py build-mpq   # Build MPQs from downloads

# Clean up downloads and built MPQs
python twow_updater.py clean
```
You need to copy the built mpqs yourself, also no exe or dlls are replaced for safety.  
When you want these updated you must copy them from the downloads/ folder.  

### Options

```
--game-dir, -g    Game directory
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

## Output

- Downloaded files go to `downloads/`
- Built MPQs go to `mpqs/`

After building, copy the MPQs from `mpqs/` to your game's `Data/` directory.

## How it works

1. Fetches the official TurtleWoW manifest
2. Compares your game files against the manifest
3. Downloads changed/missing files from TurtleWoW CDN
4. Updates your patch MPQs with the new files

## License

MIT
