"""
StormLib ctypes wrapper for MPQ creation and modification.
Supplements python-mpq with missing create/write functions.

Auto-downloads prebuilt StormLib from GitHub releases if not found locally.
"""

import ctypes
from ctypes import c_bool, c_char_p, c_uint32, c_uint64, c_void_p, byref, POINTER
from pathlib import Path
import os
import platform
import sys

SCRIPT_DIR = Path(__file__).parent
LIB_DIR = SCRIPT_DIR / "lib"

# StormLib release info
STORMLIB_VERSION = "v9.31"
STORMLIB_RELEASE_URL = f"https://github.com/ladislav-zezula/StormLib/releases/download/{STORMLIB_VERSION}"
STORMLIB_LINUX_DEB = f"libstorm-dev_{STORMLIB_VERSION}_amd64.deb"
STORMLIB_WINDOWS_ZIP = "stormlib_dll.zip"


def _get_platform_lib_info():
    """Get library filename and download URL for current platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux" and machine in ("x86_64", "amd64"):
        return "libstorm.so", f"{STORMLIB_RELEASE_URL}/{STORMLIB_LINUX_DEB}", "deb"
    elif system == "windows" and machine in ("x86_64", "amd64", "amd64"):
        return "storm.dll", f"{STORMLIB_RELEASE_URL}/{STORMLIB_WINDOWS_ZIP}", "zip"
    else:
        return None, None, None


def _download_and_extract_stormlib():
    """Download and extract StormLib for the current platform."""
    import urllib.request
    import tempfile

    lib_name, url, pkg_type = _get_platform_lib_info()
    if not lib_name:
        raise ImportError(f"No prebuilt StormLib available for {platform.system()} {platform.machine()}")

    LIB_DIR.mkdir(parents=True, exist_ok=True)
    lib_path = LIB_DIR / lib_name

    print(f"Downloading StormLib {STORMLIB_VERSION} for {platform.system()}...")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        pkg_path = tmpdir / f"stormlib.{pkg_type}"

        # Download
        req = urllib.request.Request(url, headers={"User-Agent": "TurtleWoW-Updater/1.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            with open(pkg_path, "wb") as f:
                f.write(response.read())

        # Extract based on package type
        if pkg_type == "deb":
            import subprocess
            import shutil

            # Extract .deb (it's an ar archive containing data.tar)
            subprocess.run(["ar", "x", str(pkg_path)], cwd=tmpdir, check=True, capture_output=True)

            # Find and extract data.tar.*
            for data_tar in tmpdir.glob("data.tar.*"):
                subprocess.run(["tar", "xf", str(data_tar)], cwd=tmpdir, check=True, capture_output=True)
                break

            # Find libstorm.so
            for so_file in tmpdir.rglob("libstorm.so*"):
                if so_file.is_file() and not so_file.is_symlink():
                    shutil.copy2(so_file, lib_path)
                    print(f"Extracted {lib_name} to {lib_path}")
                    return lib_path

        elif pkg_type == "zip":
            import zipfile
            import shutil

            with zipfile.ZipFile(pkg_path, 'r') as zf:
                zf.extractall(tmpdir)

            # Find storm.dll (usually in x64 subfolder for 64-bit)
            for dll_file in tmpdir.rglob("storm.dll"):
                # Prefer x64 version
                if "x64" in str(dll_file.parent).lower() or "64" in str(dll_file.parent):
                    shutil.copy2(dll_file, lib_path)
                    print(f"Extracted {lib_name} to {lib_path}")
                    return lib_path

            # Fallback to any storm.dll found
            for dll_file in tmpdir.rglob("storm.dll"):
                shutil.copy2(dll_file, lib_path)
                print(f"Extracted {lib_name} to {lib_path}")
                return lib_path

    raise ImportError(f"Failed to extract StormLib from {url}")


def _load_stormlib():
    """Find and load the StormLib library."""
    system = platform.system().lower()

    if system == "linux":
        lib_name = "libstorm.so"
        search_paths = [
            LIB_DIR / lib_name,
            SCRIPT_DIR / "build" / "install" / "lib" / lib_name,
            Path("/usr/local/lib") / lib_name,
            Path("/usr/lib") / lib_name,
        ]
    elif system == "windows":
        lib_name = "storm.dll"
        search_paths = [
            LIB_DIR / lib_name,
            SCRIPT_DIR / lib_name,
        ]
    else:
        raise ImportError(f"Unsupported platform: {system}")

    # Try to find existing library
    for path in search_paths:
        if path.exists():
            try:
                return ctypes.CDLL(str(path))
            except OSError:
                continue

    # Not found - try to download
    try:
        lib_path = _download_and_extract_stormlib()
        return ctypes.CDLL(str(lib_path))
    except Exception as e:
        raise ImportError(
            f"Could not find or download StormLib.\n"
            f"Error: {e}\n"
            f"You can manually build it with 'make' or download from:\n"
            f"  https://github.com/ladislav-zezula/StormLib/releases"
        )


_lib = _load_stormlib()

# Type definitions
HANDLE = c_void_p
DWORD = c_uint32
LCID = c_uint32
ULONGLONG = c_uint64
TCHAR = c_char_p

# Constants for MPQ creation
MPQ_CREATE_LISTFILE = 0x00100000
MPQ_CREATE_ATTRIBUTES = 0x00200000
MPQ_CREATE_SIGNATURE = 0x00400000
MPQ_CREATE_ARCHIVE_V1 = 0x00000000
MPQ_CREATE_ARCHIVE_V2 = 0x01000000
MPQ_CREATE_ARCHIVE_V3 = 0x02000000
MPQ_CREATE_ARCHIVE_V4 = 0x03000000

# File flags
MPQ_FILE_IMPLODE = 0x00000100
MPQ_FILE_COMPRESS = 0x00000200
MPQ_FILE_ENCRYPTED = 0x00010000
MPQ_FILE_FIX_KEY = 0x00020000
MPQ_FILE_SINGLE_UNIT = 0x01000000
MPQ_FILE_DELETE_MARKER = 0x02000000
MPQ_FILE_SECTOR_CRC = 0x04000000
MPQ_FILE_REPLACEEXISTING = 0x80000000

# Compression types
MPQ_COMPRESSION_HUFFMANN = 0x01
MPQ_COMPRESSION_ZLIB = 0x02
MPQ_COMPRESSION_PKWARE = 0x08
MPQ_COMPRESSION_BZIP2 = 0x10
MPQ_COMPRESSION_SPARSE = 0x20
MPQ_COMPRESSION_ADPCM_MONO = 0x40
MPQ_COMPRESSION_ADPCM_STEREO = 0x80
MPQ_COMPRESSION_LZMA = 0x12

# Open flags
MPQ_OPEN_READ_ONLY = 0x00000100

# Define function signatures
_lib.SFileCreateArchive.argtypes = [TCHAR, DWORD, DWORD, POINTER(HANDLE)]
_lib.SFileCreateArchive.restype = c_bool

_lib.SFileAddFileEx.argtypes = [HANDLE, TCHAR, c_char_p, DWORD, DWORD, DWORD]
_lib.SFileAddFileEx.restype = c_bool

_lib.SFileAddFile.argtypes = [HANDLE, TCHAR, c_char_p, DWORD]
_lib.SFileAddFile.restype = c_bool

_lib.SFileCreateFile.argtypes = [HANDLE, c_char_p, ULONGLONG, DWORD, LCID, DWORD, POINTER(HANDLE)]
_lib.SFileCreateFile.restype = c_bool

_lib.SFileWriteFile.argtypes = [HANDLE, c_void_p, DWORD, DWORD]
_lib.SFileWriteFile.restype = c_bool

_lib.SFileFinishFile.argtypes = [HANDLE]
_lib.SFileFinishFile.restype = c_bool

_lib.SFileCloseArchive.argtypes = [HANDLE]
_lib.SFileCloseArchive.restype = c_bool

_lib.SFileOpenArchive.argtypes = [TCHAR, DWORD, DWORD, POINTER(HANDLE)]
_lib.SFileOpenArchive.restype = c_bool

_lib.SFileCompactArchive.argtypes = [HANDLE, TCHAR, c_bool]
_lib.SFileCompactArchive.restype = c_bool

_lib.SFileFlushArchive.argtypes = [HANDLE]
_lib.SFileFlushArchive.restype = c_bool

_lib.SFileHasFile.argtypes = [HANDLE, c_char_p]
_lib.SFileHasFile.restype = c_bool

_lib.SFileRemoveFile.argtypes = [HANDLE, c_char_p, DWORD]
_lib.SFileRemoveFile.restype = c_bool

_lib.SFileOpenFileEx.argtypes = [HANDLE, c_char_p, DWORD, POINTER(HANDLE)]
_lib.SFileOpenFileEx.restype = c_bool

_lib.SFileGetFileSize.argtypes = [HANDLE, POINTER(DWORD)]
_lib.SFileGetFileSize.restype = DWORD

_lib.SFileReadFile.argtypes = [HANDLE, c_void_p, DWORD, POINTER(DWORD), c_void_p]
_lib.SFileReadFile.restype = c_bool

_lib.SFileCloseFile.argtypes = [HANDLE]
_lib.SFileCloseFile.restype = c_bool

# File find structures
class SFILE_FIND_DATA(ctypes.Structure):
    _fields_ = [
        ("cFileName", ctypes.c_char * 1024),
        ("szPlainName", ctypes.c_char_p),
        ("dwHashIndex", DWORD),
        ("dwBlockIndex", DWORD),
        ("dwFileSize", DWORD),
        ("dwFileFlags", DWORD),
        ("dwCompSize", DWORD),
        ("dwFileTimeLo", DWORD),
        ("dwFileTimeHi", DWORD),
        ("lcLocale", LCID),
    ]

_lib.SFileFindFirstFile.argtypes = [HANDLE, c_char_p, POINTER(SFILE_FIND_DATA), c_char_p]
_lib.SFileFindFirstFile.restype = HANDLE

_lib.SFileFindNextFile.argtypes = [HANDLE, POINTER(SFILE_FIND_DATA)]
_lib.SFileFindNextFile.restype = c_bool

_lib.SFileFindClose.argtypes = [HANDLE]
_lib.SFileFindClose.restype = c_bool

# SFILE_OPEN_FROM_MPQ constant
SFILE_OPEN_FROM_MPQ = 0x00000000


class StormLibError(Exception):
    """StormLib operation failed."""
    pass


class MPQArchive:
    """Context manager for MPQ archive operations."""

    def __init__(self, path: str | Path, mode: str = 'r', max_files: int = 0):
        """
        Open or create an MPQ archive.

        Args:
            path: Path to the MPQ file
            mode: 'r' for read-only, 'w' for create new, 'a' for append/modify
            max_files: Maximum number of files (only for 'w' mode, 0 = auto)
        """
        self.path = Path(path)
        self.mode = mode
        self.handle = HANDLE()
        self._closed = False

        path_bytes = str(self.path).encode('utf-8')

        if mode == 'r':
            if not _lib.SFileOpenArchive(path_bytes, 0, MPQ_OPEN_READ_ONLY, byref(self.handle)):
                raise StormLibError(f"Failed to open archive: {path}")
        elif mode == 'w':
            if max_files == 0:
                max_files = 4096  # Default
            flags = MPQ_CREATE_LISTFILE | MPQ_CREATE_ATTRIBUTES | MPQ_CREATE_ARCHIVE_V1
            if not _lib.SFileCreateArchive(path_bytes, flags, max_files, byref(self.handle)):
                raise StormLibError(f"Failed to create archive: {path}")
        elif mode == 'a':
            if not _lib.SFileOpenArchive(path_bytes, 0, 0, byref(self.handle)):
                raise StormLibError(f"Failed to open archive for writing: {path}")
        else:
            raise ValueError(f"Invalid mode: {mode}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self):
        """Close the archive."""
        if not self._closed and self.handle:
            _lib.SFileFlushArchive(self.handle)
            _lib.SFileCloseArchive(self.handle)
            self._closed = True

    def add_file(self, source_path: str | Path, archive_name: str,
                 compression: int = MPQ_COMPRESSION_ZLIB,
                 flags: int = MPQ_FILE_COMPRESS | MPQ_FILE_REPLACEEXISTING):
        """
        Add a file from disk to the archive.

        Args:
            source_path: Path to the source file on disk
            archive_name: Name of the file inside the archive (use backslashes)
            compression: Compression type
            flags: File flags
        """
        if self.mode == 'r':
            raise StormLibError("Archive opened in read-only mode")

        source_bytes = str(source_path).encode('utf-8')
        # Convert forward slashes to backslashes for MPQ paths
        archive_bytes = archive_name.replace('/', '\\').encode('utf-8')

        if not _lib.SFileAddFileEx(self.handle, source_bytes, archive_bytes,
                                   flags, compression, compression):
            raise StormLibError(f"Failed to add file: {source_path} -> {archive_name}")

    def add_data(self, data: bytes, archive_name: str,
                 compression: int = MPQ_COMPRESSION_ZLIB,
                 flags: int = MPQ_FILE_COMPRESS | MPQ_FILE_REPLACEEXISTING):
        """
        Add data directly to the archive.

        Args:
            data: File contents as bytes
            archive_name: Name of the file inside the archive
            compression: Compression type
            flags: File flags
        """
        if self.mode == 'r':
            raise StormLibError("Archive opened in read-only mode")

        archive_bytes = archive_name.replace('/', '\\').encode('utf-8')
        file_handle = HANDLE()

        if not _lib.SFileCreateFile(self.handle, archive_bytes, 0, len(data), 0,
                                    flags, byref(file_handle)):
            raise StormLibError(f"Failed to create file in archive: {archive_name}")

        try:
            if not _lib.SFileWriteFile(file_handle, data, len(data), compression):
                raise StormLibError(f"Failed to write file data: {archive_name}")

            if not _lib.SFileFinishFile(file_handle):
                raise StormLibError(f"Failed to finish file: {archive_name}")
        except:
            _lib.SFileCloseFile(file_handle)
            raise

    def has_file(self, archive_name: str) -> bool:
        """Check if a file exists in the archive."""
        archive_bytes = archive_name.replace('/', '\\').encode('utf-8')
        return _lib.SFileHasFile(self.handle, archive_bytes)

    def remove_file(self, archive_name: str):
        """Remove a file from the archive."""
        if self.mode == 'r':
            raise StormLibError("Archive opened in read-only mode")

        archive_bytes = archive_name.replace('/', '\\').encode('utf-8')
        if not _lib.SFileRemoveFile(self.handle, archive_bytes, 0):
            raise StormLibError(f"Failed to remove file: {archive_name}")

    def read_file(self, archive_name: str) -> bytes:
        """Read a file from the archive."""
        archive_bytes = archive_name.replace('/', '\\').encode('utf-8')
        file_handle = HANDLE()

        if not _lib.SFileOpenFileEx(self.handle, archive_bytes, SFILE_OPEN_FROM_MPQ,
                                    byref(file_handle)):
            raise StormLibError(f"Failed to open file: {archive_name}")

        try:
            high_size = DWORD()
            size = _lib.SFileGetFileSize(file_handle, byref(high_size))
            if size == 0xFFFFFFFF:
                raise StormLibError(f"Failed to get file size: {archive_name}")

            buffer = ctypes.create_string_buffer(size)
            read_size = DWORD()

            if not _lib.SFileReadFile(file_handle, buffer, size, byref(read_size), None):
                raise StormLibError(f"Failed to read file: {archive_name}")

            return buffer.raw[:read_size.value]
        finally:
            _lib.SFileCloseFile(file_handle)

    def compact(self):
        """Compact the archive to reclaim space from deleted files."""
        if self.mode == 'r':
            raise StormLibError("Archive opened in read-only mode")

        if not _lib.SFileCompactArchive(self.handle, None, False):
            raise StormLibError("Failed to compact archive")

    def flush(self):
        """Flush changes to disk."""
        if not _lib.SFileFlushArchive(self.handle):
            raise StormLibError("Failed to flush archive")

    def list_files(self, pattern: str = "*") -> list[str]:
        """
        List all files in the archive matching a pattern.

        Args:
            pattern: Wildcard pattern (default "*" for all files)

        Returns:
            List of file names in the archive
        """
        files = []
        find_data = SFILE_FIND_DATA()
        pattern_bytes = pattern.encode('utf-8')

        find_handle = _lib.SFileFindFirstFile(self.handle, pattern_bytes,
                                               byref(find_data), None)
        if not find_handle:
            return files

        try:
            while True:
                filename = find_data.cFileName.decode('utf-8', errors='replace')
                if filename and not filename.startswith('('):  # Skip (listfile), (attributes)
                    files.append(filename)

                if not _lib.SFileFindNextFile(find_handle, byref(find_data)):
                    break
        finally:
            _lib.SFileFindClose(find_handle)

        return files

    def __iter__(self):
        """Iterate over all files in the archive."""
        return iter(self.list_files())


def create_mpq_from_directory(mpq_path: str | Path, source_dir: str | Path,
                              max_files: int = 0) -> int:
    """
    Create a new MPQ archive from a directory of files.

    Args:
        mpq_path: Output MPQ file path
        source_dir: Directory containing files to add
        max_files: Maximum number of files (0 = count files automatically)

    Returns:
        Number of files added
    """
    source_dir = Path(source_dir)
    mpq_path = Path(mpq_path)

    # Count files if max_files not specified
    files = list(source_dir.rglob('*'))
    files = [f for f in files if f.is_file()]

    if max_files == 0:
        max_files = max(len(files) + 100, 1024)  # Add some padding

    # Remove existing MPQ
    if mpq_path.exists():
        mpq_path.unlink()

    count = 0
    with MPQArchive(mpq_path, mode='w', max_files=max_files) as mpq:
        for file_path in files:
            # Get relative path and convert to MPQ-style path
            rel_path = file_path.relative_to(source_dir)
            archive_name = str(rel_path).replace('/', '\\')

            mpq.add_file(file_path, archive_name)
            count += 1

            if count % 100 == 0:
                print(f"  Added {count}/{len(files)} files...")

    return count


def update_mpq_from_directory(mpq_path: str | Path, source_dir: str | Path) -> tuple[int, int]:
    """
    Update an existing MPQ with files from a directory.
    Adds new files and replaces changed files.

    Args:
        mpq_path: MPQ file path
        source_dir: Directory containing files to add/update

    Returns:
        Tuple of (files_added, files_updated)
    """
    source_dir = Path(source_dir)
    mpq_path = Path(mpq_path)

    files = list(source_dir.rglob('*'))
    files = [f for f in files if f.is_file()]

    added = 0
    updated = 0

    with MPQArchive(mpq_path, mode='a') as mpq:
        for file_path in files:
            rel_path = file_path.relative_to(source_dir)
            archive_name = str(rel_path).replace('/', '\\')

            existed = mpq.has_file(archive_name)
            mpq.add_file(file_path, archive_name)

            if existed:
                updated += 1
            else:
                added += 1

    return added, updated
