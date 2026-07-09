from gateway.run import _format_discord_reasoning_progress_message


def test_discord_reasoning_progress_renders_subtext_lines():
    out = _format_discord_reasoning_progress_message("checked config\nqueried DB")

    assert out == (
        "-# 💭 Reasoning\n"
        "-# checked config\n"
        "-# queried DB"
    )


def test_discord_reasoning_progress_filters_blank_and_partial_markdown_fragments():
    out = _format_discord_reasoning_progress_message(
        "Inspecting system configuration\n\n|\n-#\nchecked restart state"
    )

    assert out == (
        "-# 💭 Reasoning · latest 2 lines\n"
        "-# Inspecting system configuration\n"
        "-# checked restart state"
    )
    assert "\n-#\n" not in out
    assert "\n-# |" not in out
    assert "earlier reasoning" not in out


def test_discord_reasoning_progress_collapses_intrusive_spacing():
    out = _format_discord_reasoning_progress_message(
        "Assessing Finnhub concerns  \n\n  I need to consider   reliability and coverage."
    )

    assert out == (
        "-# 💭 Reasoning · latest 2 lines\n"
        "-# Assessing Finnhub concerns\n"
        "-# I need to consider reliability and coverage."
    )


def test_discord_reasoning_progress_tails_long_reasoning():
    out = _format_discord_reasoning_progress_message(
        "\n".join(f"step {i}" for i in range(20)),
        max_lines=3,
    )

    assert out.startswith("-# 💭 Reasoning · latest 3 lines")
    assert "earlier reasoning" not in out
    assert "step 0" not in out
    assert "step 17" in out
    assert "step 18" in out
    assert "step 19" in out


def test_discord_reasoning_progress_redacts_obvious_secret():
    out = _format_discord_reasoning_progress_message("token sk-proj-abcdefghijklmnopqrstuvwxyz123456")

    assert "sk-proj-abcdefghijklmnopqrstuvwxyz123456" not in out
    assert "Reasoning" in out
