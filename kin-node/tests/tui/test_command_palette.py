"""Unit tests for Command Palette 4-tier ranking function and colon command security parser.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §5.4, §14.4
"""

import pytest

from kin.tui.palette import CommandItem, parse_colon_command, rank_command_palette


def test_command_palette_ranking_golden():
    """GOLDEN TEST for Command Palette 4-tier ranking function (§5.4, §14.4).

    Strictly asserts exact ranking order for a fixed candidate list:
      Tier 1: Exact command match
      Tier 2: Recent action match
      Tier 3: Contextual relevance match
      Tier 4: Fuzzy match
    """
    candidates = [
        CommandItem(command_id="dispatch_fuzzy", title="Dispatch a collaboration", category="Actions", recent=False, contextual=False),
        CommandItem(command_id="dispatch", title="dispatch", category="Actions", recent=False, contextual=False),  # Exact match
        CommandItem(command_id="dispatch_recent", title="Dispatch recent session", category="Actions", recent=True, contextual=False),
        CommandItem(command_id="dispatch_contextual", title="Dispatch contextual hint", category="Actions", recent=False, contextual=True),
    ]

    ranked = rank_command_palette("dispatch", candidates)
    ranked_ids = [item.command_id for item in ranked]

    # Tier 1 (exact) -> Tier 2 (recent) -> Tier 3 (contextual) -> Tier 4 (fuzzy)
    expected_order = ["dispatch", "dispatch_recent", "dispatch_contextual", "dispatch_fuzzy"]
    assert ranked_ids == expected_order, f"Ranking order mismatch! Got {ranked_ids}, expected {expected_order}"


def test_colon_command_security_parser():
    """Assert colon command parser validates whitelisted commands and strictly rejects shell execution (§5.4, §14.4)."""
    # 1. Valid whitelisted colon commands
    ok_theme, cmd1, arg1, msg1 = parse_colon_command(":theme kin-graphite")
    assert ok_theme
    assert cmd1 == "theme"
    assert arg1 == "kin-graphite"

    ok_open, cmd2, arg2, msg2 = parse_colon_command(":open home")
    assert ok_open
    assert cmd2 == "open"

    # 2. Dangerous shell-like injection attempts MUST be rejected safely
    bad_vectors = [
        ":!rm -rf /",
        ":!ls -la",
        ":exec(import os; os.system('calc'))",
        ":eval(1+1)",
        ":import os",
        ":system(ls)",
        ":unrecognized_cmd_xyz",
    ]

    for bad in bad_vectors:
        ok, cmd, arg, err = parse_colon_command(bad)
        assert not ok, f"Unsafe command '{bad}' was incorrectly accepted!"
        assert "Security Error" in err
