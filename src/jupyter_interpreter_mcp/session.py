"""Session management for Jupyter code execution."""

import os
import time
import uuid
from dataclasses import dataclass


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
