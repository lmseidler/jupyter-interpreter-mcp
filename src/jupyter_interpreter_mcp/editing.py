"""File editing utilities: match-and-replace with fallback strategies.

Provides :func:`find_and_replace` for applying in-place text edits described
by an ``old_string`` / ``new_string`` pair.  Three matching strategies are
tried in order, from strictest to most permissive:

1. **Exact** — byte-for-byte substring match.
2. **Line-trimmed** — per-line leading/trailing whitespace is ignored.
3. **Indentation-flexible** — minimum common indentation is stripped from both
   the search pattern and each candidate block before comparison.
"""

from __future__ import annotations


class EditError(ValueError):
    """Raised when :func:`find_and_replace` cannot perform the requested edit."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_line_endings(line: str) -> str:
    """Strip trailing CR and/or LF characters."""
    return line.rstrip("\r\n")


def _has_trailing_inline_whitespace(content: str, end: int) -> bool:
    """Return True if *content[end:]* begins with only spaces/tabs before a newline.

    This is used to skip exact matches that end mid-line when the remainder of
    the line is pure horizontal whitespace, so that the line-trimmed strategy
    can handle the match more cleanly (preserving the newline and dropping
    the trailing spaces).
    """
    i = end
    while i < len(content) and content[i] in (" ", "\t"):
        i += 1
    # At this point content[i] is either a newline, end-of-string, or a
    # non-whitespace character.
    return i > end and (i == len(content) or content[i] in ("\n", "\r"))


def _find_exact_matches(content: str, old_string: str) -> list[tuple[int, int]]:
    """Return all ``(start, end)`` character ranges of *old_string* in *content*.

    Matches where the immediately following characters (up to the next newline)
    are all horizontal whitespace are excluded so that the line-trimmed strategy
    can handle such cases, avoiding spurious trailing spaces in the output.
    """
    matches: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = content.find(old_string, start)
        if idx == -1:
            break
        end = idx + len(old_string)
        if not _has_trailing_inline_whitespace(content, end):
            matches.append((idx, end))
        start = idx + 1
    return matches


def _find_line_trimmed_matches(content: str, old_string: str) -> list[tuple[int, int]]:
    """Return matches where each corresponding line is equal after ``.strip()``.

    Leading and trailing whitespace is stripped from every line before
    comparison.  The character range returned covers the original (un-stripped)
    lines in *content*.
    """
    old_lines = old_string.splitlines()
    if not old_lines:
        return []
    n = len(old_lines)
    old_stripped = [line.strip() for line in old_lines]

    content_lines = content.splitlines(keepends=True)
    if len(content_lines) < n:
        return []

    # Pre-compute stripped versions of all content lines once.
    content_stripped = [_strip_line_endings(line).strip() for line in content_lines]

    matches: list[tuple[int, int]] = []
    for i in range(len(content_lines) - n + 1):
        if content_stripped[i : i + n] == old_stripped:
            start = sum(len(line) for line in content_lines[:i])
            # Include all lines up to (but not including the last), then add
            # the last matched line up to (but not past) its trailing newline.
            # This prevents trailing horizontal whitespace on the last matched
            # line from leaking into the content that follows the replacement.
            last_line = content_lines[i + n - 1]
            end = (
                start
                + sum(len(line) for line in content_lines[i : i + n - 1])
                + len(_strip_line_endings(last_line))
            )
            matches.append((start, end))
    return matches


def _strip_min_indent(lines: list[str]) -> list[str]:
    """Strip the minimum common leading whitespace from all non-empty lines.

    Empty (or whitespace-only) lines are left unchanged.
    """
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return lines
    min_indent = min(len(line) - len(line.lstrip()) for line in non_empty)
    if min_indent == 0:
        return lines
    return [line[min_indent:] if len(line) >= min_indent else line for line in lines]


def _find_indent_flexible_matches(
    content: str, old_string: str
) -> list[tuple[int, int]]:
    """Return matches after stripping minimum common indentation from both sides.

    For each candidate block of *n* consecutive lines in *content*, the minimum
    common leading indentation is stripped from both the candidate and from
    *old_string*.  Trailing whitespace is also ignored.  This handles cases
    where the search pattern has a different absolute indentation level than
    the actual file content, while preserving the *relative* indentation
    between lines.
    """
    old_lines_raw = old_string.splitlines()
    if not old_lines_raw:
        return []
    n = len(old_lines_raw)
    # Strip min-indent and trailing whitespace from the search pattern once.
    old_normalised = [line.rstrip() for line in _strip_min_indent(old_lines_raw)]

    content_lines = content.splitlines(keepends=True)
    if len(content_lines) < n:
        return []

    matches: list[tuple[int, int]] = []
    for i in range(len(content_lines) - n + 1):
        # Strip line-endings, then strip min-indent and trailing whitespace.
        block = [_strip_line_endings(line) for line in content_lines[i : i + n]]
        block_normalised = [line.rstrip() for line in _strip_min_indent(block)]
        if block_normalised == old_normalised:
            start = sum(len(line) for line in content_lines[:i])
            # Include full lines up to the last, but stop before the newline of the last line.
            end = start + sum(len(line) for line in content_lines[i : i + n - 1])
            end += len(_strip_line_endings(content_lines[i + n - 1]))
            matches.append((start, end))
    return matches


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_and_replace(
    content: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> tuple[str, int]:
    """Replace *old_string* with *new_string* inside *content*.

    Three matching strategies are tried in order (exact → line-trimmed →
    indentation-flexible).  The first strategy that finds at least one match
    is used exclusively.

    When *replace_all* is ``False`` the match must be unique; an
    :class:`EditError` is raised if zero or more than one location is found.
    When *replace_all* is ``True``, every occurrence found by the successful
    strategy is replaced and the count is returned.

    Replacements are applied in reverse positional order so that earlier
    character offsets remain valid throughout the operation.

    :param content: The full text to search in.
    :type content: str
    :param old_string: The text to find and replace.  Must be non-empty.
    :type old_string: str
    :param new_string: The replacement text.
    :type new_string: str
    :param replace_all: Replace every occurrence instead of requiring a
        unique match.
    :type replace_all: bool
    :return: ``(new_content, replacement_count)`` where *replacement_count*
        is the number of substitutions made (≥ 1).
    :rtype: tuple[str, int]
    :raises EditError: If *old_string* is empty, not found, or matches
        multiple locations when *replace_all* is ``False``.
    """
    if not old_string:
        raise EditError(
            "old_string must not be empty; use write_file to create or overwrite files"
        )

    # Strategy 1: exact byte-for-byte match.
    matches = _find_exact_matches(content, old_string)

    # Strategy 2: line-trimmed (leading/trailing whitespace ignored per line).
    if not matches:
        matches = _find_line_trimmed_matches(content, old_string)

    # Strategy 3: indentation-flexible (common indent stripped from both sides).
    if not matches:
        matches = _find_indent_flexible_matches(content, old_string)

    if not matches:
        raise EditError(
            "old_string not found in file. "
            "Verify that old_string exactly matches the text you want to replace "
            "(including surrounding context, whitespace, and indentation)."
        )

    if len(matches) > 1 and not replace_all:
        raise EditError(
            f"Found {len(matches)} occurrences of old_string. "
            "Provide more surrounding context to uniquely identify the target "
            "location, or set replace_all=True to replace every occurrence."
        )

    # Apply replacements in reverse order so earlier offsets stay valid.
    targets = matches if replace_all else matches[:1]
    result = content
    for start, end in reversed(targets):
        result = result[:start] + new_string + result[end:]

    return result, len(targets)
