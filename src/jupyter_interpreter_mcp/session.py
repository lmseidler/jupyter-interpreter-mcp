"""Session management for Jupyter code execution."""

import os
import re
import time
import uuid
from dataclasses import dataclass

# Module-level state for configured allowed upload directories.
# None  = not explicitly set; fall back to ALLOWED_UPLOAD_DIRS env var or CWD.
# []    = allow all (set via --allow-all).
# [..] = restrict to these resolved absolute paths.
_configured_allowed_dirs: list[str] | None = None


def set_allowed_upload_dirs(dirs: list[str]) -> None:
    """Set the allowed upload directories, taking precedence over the env var.

    Paths are resolved (symlinks followed) at set time.

    :param dirs: Directory paths to allow uploads from.
    :type dirs: list[str]
    """
    global _configured_allowed_dirs
    _configured_allowed_dirs = [os.path.realpath(d) for d in dirs]


def generate_session_id() -> str:
    """Generate a unique session identifier.

    :return: UUID4 string for session identification.
    :rtype: str
    """
    return str(uuid.uuid4())


def validate_path(session_dir: str, relative_path: str) -> str:
    """Validate that a path stays within the session directory.

    Resolves the path and ensures it doesn't escape the session directory
    through '..' components or symbolic links.

    :param session_dir: Absolute path to the session directory.
    :type session_dir: str
    :param relative_path: Relative path to validate.
    :type relative_path: str
    :return: Absolute resolved path.
    :rtype: str
    :raises ValueError: If path escapes session directory.
    """
    # Resolve both paths to absolute, following symlinks
    session_real = os.path.realpath(session_dir)
    target_real = os.path.realpath(os.path.join(session_dir, relative_path))

    # Ensure target is within session directory
    if (
        not target_real.startswith(session_real + os.sep)
        and target_real != session_real
    ):
        raise ValueError(f"Path '{relative_path}' escapes session directory")

    return target_real


def get_allowed_upload_dirs() -> list[str]:
    """Return the configured allowed upload directories.

    Priority:
    1. Explicit config set via :func:`set_allowed_upload_dirs` (e.g. CLI args).
    2. ``ALLOWED_UPLOAD_DIRS`` environment variable (colon-separated paths).
    3. Current working directory as the sole default.

    An empty list (``[]``) means *all* directories are allowed (set via
    ``--allow-all``).

    :return: List of resolved absolute directory paths, or ``[]`` for allow-all.
    :rtype: list[str]
    """
    if _configured_allowed_dirs is not None:
        return _configured_allowed_dirs

    env_value = os.environ.get("ALLOWED_UPLOAD_DIRS", "").strip()
    if env_value:
        return [os.path.realpath(d.strip()) for d in env_value.split(":") if d.strip()]

    return [os.path.realpath(os.getcwd())]


def validate_host_path(host_path: str, allowed_dirs: list[str] | None = None) -> str:
    """Validate that a host filesystem path is within allowed directories.

    The path must be absolute.  After resolving symlinks the resolved path
    must fall inside one of the *allowed_dirs*.

    When *allowed_dirs* is ``None`` (default), the configured allowed
    directories are used.  If no explicit configuration is active (neither
    :func:`set_allowed_upload_dirs` nor ``ALLOWED_UPLOAD_DIRS`` env var), any
    absolute path is accepted.  An empty *allowed_dirs* list also accepts all
    absolute paths (equivalent to ``--allow-all``).

    :param host_path: Absolute path on the host filesystem.
    :type host_path: str
    :param allowed_dirs: Directories the path must reside within, or ``None``
        to use the globally configured directories.
    :type allowed_dirs: list[str] | None
    :return: The resolved absolute path.
    :rtype: str
    :raises ValueError: If the path is not absolute or is outside allowed
        directories.
    """
    if not os.path.isabs(host_path):
        raise ValueError(f"Host path must be absolute: {host_path}")

    resolved = os.path.realpath(host_path)

    if allowed_dirs is None:
        # No explicit restriction configured and no env var → allow all
        if not _configured_allowed_dirs and not os.environ.get("ALLOWED_UPLOAD_DIRS"):
            return resolved
        allowed_dirs = get_allowed_upload_dirs()

    # Empty list means allow-all (e.g. --allow-all)
    if not allowed_dirs:
        return resolved

    for allowed in allowed_dirs:
        if resolved == allowed or resolved.startswith(allowed + os.sep):
            return resolved

    raise ValueError(f"Path '{host_path}' is outside allowed upload directories")


# Patterns that indicate sensitive files which should never be uploaded.
_SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(^|/)\.env($|\.\w+$)", re.IGNORECASE),
    re.compile(r"(^|/)\.ssh/", re.IGNORECASE),
    re.compile(r"(^|/)\.gnupg/", re.IGNORECASE),
    re.compile(r"(^|/)\.aws/", re.IGNORECASE),
    re.compile(r"(^|/)\.docker/config\.json$", re.IGNORECASE),
    re.compile(r"(^|/)credentials(\.json|\.yaml|\.yml)?$", re.IGNORECASE),
    re.compile(r"(^|/)\.netrc$", re.IGNORECASE),
    re.compile(r"(^|/)id_rsa($|\.pub$)", re.IGNORECASE),
    re.compile(r"(^|/)id_ed25519($|\.pub$)", re.IGNORECASE),
    re.compile(r"(^|/)id_ecdsa($|\.pub$)", re.IGNORECASE),
    re.compile(r"(^|/)\.npmrc$", re.IGNORECASE),
    re.compile(r"(^|/)\.pypirc$", re.IGNORECASE),
    re.compile(r"(^|/)secret[s]?(\.json|\.yaml|\.yml|\.txt)?$", re.IGNORECASE),
    re.compile(r"(^|/)token[s]?(\.json|\.yaml|\.yml|\.txt)?$", re.IGNORECASE),
    re.compile(r"(^|/)\.git-credentials$", re.IGNORECASE),
]


def is_sensitive_file(file_path: str) -> bool:
    """Check whether a file path matches known sensitive file patterns.

    :param file_path: File path (absolute or relative) to check.
    :type file_path: str
    :return: ``True`` if the path matches a sensitive pattern.
    :rtype: bool
    """
    # Normalise to forward-slash for consistent matching
    normalised = file_path.replace(os.sep, "/")
    for pattern in _SENSITIVE_PATTERNS:
        if pattern.search(normalised):
            return True
    return False


# Known binary file extensions
BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",  # Images
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",  # Archives
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",  # Documents
    ".exe",
    ".dll",
    ".so",
    ".dylib",  # Binaries
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".wav",
    ".flac",  # Media
    ".pyc",
    ".pyo",
    ".pkl",
    ".pickle",  # Python binary
}


def detect_content_type(filename: str, content: bytes) -> str:
    """Detect whether content should be treated as binary or text.

    :param filename: Name of the file (used for extension check).
    :type filename: str
    :param content: Raw file content.
    :type content: bytes
    :return: Either 'binary' or 'text'.
    :rtype: str
    """
    # Check file extension first
    _, ext = os.path.splitext(filename.lower())
    if ext in BINARY_EXTENSIONS:
        return "binary"

    # Try to decode as UTF-8
    try:
        content.decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        return "binary"


@dataclass
class Session:
    """Represents a code execution session.

    :ivar id: Unique session identifier (UUID string).
    :ivar kernel_id: ID of the associated Jupyter kernel.
    :ivar created_at: Unix timestamp when session was created.
    :ivar last_access: Unix timestamp of last session access.
    :ivar directory: Path to session directory on remote filesystem.
    """

    id: str
    kernel_id: str
    created_at: float
    last_access: float
    directory: str

    def touch(self) -> None:
        """Update last access timestamp to current time."""
        self.last_access = time.time()

    def is_expired(self, ttl: float) -> bool:
        """Check if session has exceeded its time-to-live.

        :param ttl: Time-to-live in seconds (0 = never expires).
        :type ttl: float
        :return: True if session is expired, False otherwise.
        :rtype: bool
        """
        if ttl <= 0:
            return False
        return (time.time() - self.last_access) > ttl
