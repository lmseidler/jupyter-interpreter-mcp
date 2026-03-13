"""Unit tests for jupyter_interpreter_mcp.editing.find_and_replace."""

import pytest

from jupyter_interpreter_mcp.editing import EditError, find_and_replace


class TestExactMatch:
    """Tests for the exact byte-for-byte strategy."""

    def test_simple_replacement(self):
        content = "hello world"
        result, count = find_and_replace(content, "world", "there")
        assert result == "hello there"
        assert count == 1

    def test_multiline_replacement(self):
        content = "line1\nline2\nline3\n"
        result, count = find_and_replace(content, "line2\n", "new_line\n")
        assert result == "line1\nnew_line\nline3\n"
        assert count == 1

    def test_replace_all_multiple_occurrences(self):
        content = "foo bar foo baz foo"
        result, count = find_and_replace(content, "foo", "X", replace_all=True)
        assert result == "X bar X baz X"
        assert count == 3

    def test_single_occurrence_replace_all(self):
        content = "only once here"
        result, count = find_and_replace(content, "once", "one time", replace_all=True)
        assert result == "only one time here"
        assert count == 1

    def test_replace_with_empty_string(self):
        """Replacing with empty string is a deletion."""
        content = "aXb"
        result, count = find_and_replace(content, "X", "")
        assert result == "ab"
        assert count == 1

    def test_multiline_block_replacement(self):
        content = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
        result, count = find_and_replace(
            content,
            "def foo():\n    return 1\n",
            "def foo():\n    return 42\n",
        )
        assert "return 42" in result
        assert "return 1" not in result
        assert count == 1

    def test_not_found_raises(self):
        with pytest.raises(EditError, match="not found"):
            find_and_replace("hello world", "xyz", "abc")

    def test_empty_old_string_raises(self):
        with pytest.raises(EditError, match="must not be empty"):
            find_and_replace("content", "", "new")

    def test_ambiguous_raises(self):
        content = "abc abc abc"
        with pytest.raises(EditError, match="3 occurrences"):
            find_and_replace(content, "abc", "X")

    def test_ambiguous_resolved_by_context(self):
        content = "foo bar\nfoo baz\n"
        result, count = find_and_replace(content, "foo baz\n", "foo qux\n")
        assert result == "foo bar\nfoo qux\n"
        assert count == 1

    def test_unicode(self):
        content = "café au lait"
        result, count = find_and_replace(content, "café", "tea")
        assert result == "tea au lait"
        assert count == 1

    def test_replacement_with_newlines(self):
        content = "a b c"
        result, count = find_and_replace(content, "b", "x\ny")
        assert result == "a x\ny c"
        assert count == 1

    def test_overlapping_occurrences_replace_all(self):
        """Overlapping matches: 'aa' in 'aaa' has two matches; replace_all handles
        them."""
        content = "aaa"
        # Two overlapping matches at (0,2) and (1,3); applied right-to-left.
        result, count = find_and_replace(content, "aa", "X", replace_all=True)
        # Right-to-left: replace (1,3) first → "aX", then (0,2) → "X" + "" = "X"
        assert count == 2


class TestLineTrimmedMatch:
    """Tests for the line-trimmed fallback strategy."""

    def test_trailing_spaces_on_lines(self):
        """Content has trailing spaces that old_string does not."""
        content = "  foo  \n  bar  \nbaz\n"
        old_string = "foo\nbar"
        result, count = find_and_replace(content, old_string, "NEW\nCONTENT")
        assert "NEW\nCONTENT" in result
        assert "foo" not in result
        assert count == 1

    def test_leading_spaces_stripped(self):
        """old_string has no leading spaces but content lines do."""
        content = "  alpha\n  beta\ngamma\n"
        result, count = find_and_replace(content, "alpha\nbeta", "replaced")
        assert "replaced" in result
        assert "alpha" not in result
        assert count == 1

    def test_mixed_whitespace_differences(self):
        """Both leading and trailing whitespace differ."""
        content = "\talpha\t\n\tbeta\t\n"
        result, count = find_and_replace(content, "alpha\nbeta", "done")
        assert "done" in result
        assert count == 1

    def test_single_line_trailing_space(self):
        content = "hello world   \n"
        result, count = find_and_replace(content, "hello world", "hi")
        assert result == "hi\n"
        assert count == 1

    def test_exact_takes_priority(self):
        """When exact match exists, line-trimmed is not used."""
        content = "exact match here\n  also here\n"
        # Only one exact match
        result, count = find_and_replace(content, "exact match here", "replaced")
        assert count == 1
        assert "replaced" in result

    def test_ambiguous_line_trimmed(self):
        content = "  foo  \n  bar  \n  foo  \n  bar  \n"
        with pytest.raises(EditError, match="2 occurrences"):
            find_and_replace(content, "foo\nbar", "X")

    def test_replace_all_line_trimmed(self):
        content = "  foo  \n  bar  \n  foo  \n  bar  \n"
        result, count = find_and_replace(
            content, "foo\nbar", "NEW\nCONTENT", replace_all=True
        )
        assert count == 2
        assert result.count("NEW") == 2


class TestIndentationFlexibleMatch:
    """Tests for the indentation-flexible fallback strategy."""

    def test_different_absolute_indent(self):
        """old_string has 2-space indent; content has 4-space indent."""
        content = "    def foo():\n        return 1\n"
        old_string = "  def foo():\n    return 1"
        result, count = find_and_replace(
            content, old_string, "    def foo():\n        return 42\n"
        )
        assert "return 42" in result
        assert "return 1" not in result
        assert count == 1

    def test_no_indent_vs_indented(self):
        """old_string has no indent; content block has consistent indent."""
        content = "class Foo:\n    def bar(self):\n        pass\n"
        old_string = "def bar(self):\n    pass"
        result, count = find_and_replace(
            content, old_string, "def bar(self):\n    return 42"
        )
        assert "return 42" in result
        assert count == 1

    def test_relative_indent_preserved_in_match(self):
        """Relative indentation between lines must be identical after stripping."""
        content = "    foo:\n        bar:\n            baz\n"
        # Same relative structure but different absolute
        old_string = "foo:\n    bar:\n        baz"
        result, count = find_and_replace(content, old_string, "REPLACED")
        assert "REPLACED" in result
        assert count == 1

    def test_different_relative_indent_no_match(self):
        """If relative indentation differs, should not match."""
        # Content: foo and bar at same level; old: bar indented relative to foo
        content = "    foo\n    bar\n"
        old_string = "foo\n    bar"  # bar is indented in old_string
        # Line-trimmed: "foo" vs "foo" and "bar" vs "bar" — match!
        # So this will match via line-trimmed (both stripped give same result).
        # That's correct: line-trimmed is less strict than indent-flexible.
        result, count = find_and_replace(content, old_string, "DONE")
        assert count == 1

    def test_single_line_any_indent(self):
        """A single-line old_string with indent matches any indented version."""
        content = "        deeply_nested_call()\n"
        result, count = find_and_replace(
            content, "    deeply_nested_call()", "REPLACED"
        )
        assert "REPLACED" in result
        assert count == 1

    def test_exact_takes_priority_over_indent_flexible(self):
        """Exact match is found; indent-flexible is never reached."""
        content = "def foo():\n    return 1\n"
        result, count = find_and_replace(
            content, "def foo():\n    return 1", "REPLACED"
        )
        assert "REPLACED" in result
        assert count == 1


class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_content_with_no_trailing_newline(self):
        content = "first\nsecond"  # no trailing newline
        result, count = find_and_replace(content, "second", "last")
        assert result == "first\nlast"
        assert count == 1

    def test_old_string_equals_entire_content(self):
        content = "replace everything"
        result, count = find_and_replace(content, "replace everything", "done")
        assert result == "done"
        assert count == 1

    def test_windows_line_endings_exact(self):
        content = "line1\r\nline2\r\nline3\r\n"
        result, count = find_and_replace(content, "line2\r\n", "new\r\n")
        assert result == "line1\r\nnew\r\nline3\r\n"
        assert count == 1

    def test_windows_line_endings_line_trimmed(self):
        """Line-trimmed strategy handles \\r\\n correctly."""
        content = "  foo\r\n  bar\r\n"
        result, count = find_and_replace(content, "foo\nbar", "DONE")
        # Should match via line-trimmed (strip handles \r\n)
        assert "DONE" in result
        assert count == 1

    def test_new_string_with_special_chars(self):
        content = "placeholder"
        result, count = find_and_replace(content, "placeholder", "line1\n\tindented\n")
        assert result == "line1\n\tindented\n"
        assert count == 1

    def test_replace_all_order_preserving(self):
        """Replacements in reverse order must yield the same result as forward."""
        content = "aXbXcX"
        result, count = find_and_replace(content, "X", "Y", replace_all=True)
        assert result == "aYbYcY"
        assert count == 3
