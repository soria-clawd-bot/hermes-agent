"""Tests for Discord outbound formatting transforms in format_message():

- GFM markdown tables -> aligned monospace code blocks (Discord has no native
  table rendering), display-width aware via wcwidth.
- Heading/subtext blank-line insertion.
- Composition of the two (tables fenced first, headings skip fenced content).
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from wcwidth import wcswidth as _disp

from gateway.config import PlatformConfig


def _ensure_discord_mock():
    if "discord" in sys.modules and hasattr(sys.modules["discord"], "__file__"):
        return
    discord_mod = MagicMock()
    discord_mod.Intents.default.return_value = MagicMock()
    discord_mod.Client = MagicMock
    discord_mod.File = MagicMock
    discord_mod.DMChannel = type("DMChannel", (), {})
    discord_mod.Thread = type("Thread", (), {})
    discord_mod.ForumChannel = type("ForumChannel", (), {})
    discord_mod.ui = SimpleNamespace(View=object, button=lambda *a, **k: (lambda fn: fn), Button=object)
    discord_mod.ButtonStyle = SimpleNamespace(success=1, primary=2, secondary=2, danger=3, green=1, grey=2, blurple=2, red=3)
    discord_mod.Color = SimpleNamespace(orange=lambda: 1, green=lambda: 2, blue=lambda: 3, red=lambda: 4, purple=lambda: 5)
    discord_mod.Interaction = object
    discord_mod.Embed = MagicMock
    discord_mod.app_commands = SimpleNamespace(
        describe=lambda **kwargs: (lambda fn: fn),
        choices=lambda **kwargs: (lambda fn: fn),
        Choice=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    ext_mod = MagicMock()
    commands_mod = MagicMock()
    commands_mod.Bot = MagicMock
    ext_mod.commands = commands_mod
    sys.modules.setdefault("discord", discord_mod)
    sys.modules.setdefault("discord.ext", ext_mod)
    sys.modules.setdefault("discord.ext.commands", commands_mod)


_ensure_discord_mock()

from plugins.platforms.discord.adapter import DiscordAdapter  # noqa: E402


@pytest.fixture
def adapter():
    return DiscordAdapter(PlatformConfig(enabled=True, token="fake-token"))


def _table_lines(text):
    return [ln for ln in text.split("\n") if ln.startswith("| ")]


def _display_aligned(text):
    """Every emitted table row must have identical DISPLAY width."""
    widths = {_disp(ln) for ln in _table_lines(text)}
    return len(widths) == 1


# --- Table conversion -------------------------------------------------------

def test_gfm_table_becomes_aligned_code_block(adapter):
    src = (
        "Summary:\n\n"
        "| Pattern | Frequency | Where |\n"
        "|---|---|---|\n"
        "| **Tool-progress** | `terminal` x5244 | run.py |\n"
        "| Result tables | 30.5% | my prose |\n\n"
        "after"
    )
    out = adapter.format_message(src)
    # Wrapped in a code block.
    assert out.count("```") == 2
    # Aligned by display width.
    assert _display_aligned(out)
    # Inline markdown flattened (no ** or backticks inside the block).
    body = out.split("```")[1]
    assert "**" not in body
    assert "`" not in body
    assert "x5244" in out
    # Surrounding prose preserved.
    assert "Summary:" in out and "after" in out


def test_table_alignment_markers_and_emoji_width(adapter):
    src = (
        "| Name | Score |\n"
        "|:---|--:|\n"
        "| ✅ ok | 5 |\n"
        "| no | 100 |"
    )
    out = adapter.format_message(src)
    assert out.count("```") == 2
    # Emoji is 1 char / 2 columns — must still align by display width.
    assert _display_aligned(out)
    # Right-aligned numeric column: 5 padded to the right.
    assert "|     5 |" in out or "|   5 |" in out


def test_identifier_underscores_preserved_in_table(adapter):
    """``read_file`` / ``sites_default_files`` must NOT lose underscores."""
    src = (
        "| Tool | Count |\n"
        "|---|--:|\n"
        "| read_file | 2696 |\n"
        "| sites_default_files | 1 |"
    )
    out = adapter.format_message(src)
    assert "read_file" in out
    assert "sites_default_files" in out
    assert _display_aligned(out)


def test_non_table_pipes_untouched(adapter):
    """Shell pipes with no separator row must not be treated as a table."""
    src = "run this: echo a | grep b | wc -l\nplain line"
    assert adapter.format_message(src) == src


def test_table_inside_existing_fence_untouched(adapter):
    src = "```\n| a | b |\n|---|---|\n| 1 | 2 |\n```"
    assert adapter.format_message(src) == src


def test_render_tables_config_gate_off(adapter):
    adapter.config.extra["render_tables"] = False
    src = "| a | b |\n|---|---|\n| 1 | 2 |"
    out = adapter.format_message(src)
    # No conversion: raw pipes remain, no code fence added.
    assert "```" not in out
    assert "| a | b |" in out


# --- Heading fix ------------------------------------------------------------

def test_heading_gets_blank_line(adapter):
    src = "Some intro text.\n## Results\nbody"
    out = adapter.format_message(src)
    assert "\n\n## Results" in out


def test_heading_inside_fence_untouched(adapter):
    src = "```\ncode\n## not a heading\n```\nafter"
    out = adapter.format_message(src)
    # The '## not a heading' must stay adjacent to 'code' (no blank inserted).
    assert "code\n## not a heading" in out


# --- Composition ------------------------------------------------------------

def test_table_then_heading_compose(adapter):
    src = (
        "Summary line.\n"
        "## Results\n"
        "| Tool | Count |\n"
        "|---|--:|\n"
        "| terminal | 5244 |\n"
        "| read_file | 2696 |\n"
        "Done."
    )
    out = adapter.format_message(src)
    # Heading got its blank line.
    assert "\n\n## Results" in out
    # Exactly one fenced table block.
    assert out.count("```") == 2
    # Identifier underscores preserved through both transforms.
    assert "read_file" in out
    assert _display_aligned(out)


def test_diff_block_passthrough(adapter):
    """A ```diff block (the Claude-Code change look) is left intact."""
    src = "Change:\n```diff\n+ added_line\n- removed_line\n```\ndone"
    out = adapter.format_message(src)
    assert "```diff" in out
    assert "+ added_line" in out
    assert "- removed_line" in out
