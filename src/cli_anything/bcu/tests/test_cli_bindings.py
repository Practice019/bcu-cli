"""Every CLI command must be invokable — no binding errors, no crashes.

This exists because of a real bug found only by the E2E suite:

    uninstall_cmd() got an unexpected keyword argument 'apply'. Did you mean 'apply_'

``--apply`` produced the parameter name ``apply`` while the function took
``apply_``. Nothing in the unit tests could catch it: the option decorators are
wrapped by ``with_globals``/``handle_error``, so the callback signature is
``(*args, **kwargs)`` and static checks see nothing wrong. The only reliable
detector is to actually invoke every command and reject a binding error.

``--help`` on every command is the strongest cheap probe: it forces Click to
build the parser and bind every parameter, without needing an index, a console,
or administrator rights.
"""

from __future__ import annotations

import os
import sys

import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))

from cli_anything.bcu.bcu_cli import cli  # noqa: E402


def _command_paths(group, prefix: str = "") -> list[str]:
    """Every *sub*-command as a space-separated path, groups included.

    The root command's own name is deliberately excluded: ``CliRunner.invoke``
    already treats the object passed in as the root, so passing "cli" would make
    Click look for a sub-command literally named ``cli``.
    """
    out: list[str] = []
    for name, sub in getattr(group, "commands", {}).items():
        path = f"{prefix} {name}".strip()
        out.append(path)
        out.extend(_command_paths(sub, path))
    return out


ALL_COMMANDS = _command_paths(cli)


class TestHelpRunsForEveryCommand:

    def test_there_are_commands_to_check(self):
        assert len(ALL_COMMANDS) >= 8, ALL_COMMANDS

    @pytest.mark.parametrize("path", ALL_COMMANDS)
    def test_help_succeeds(self, path):
        """Binds every parameter without executing the command body."""
        result = CliRunner().invoke(cli, [*path.split(), "--help"])
        assert result.exit_code == 0, (
            f"`{path} --help` failed:\n{result.output}\n"
            f"{result.exception!r}"
        )

    @pytest.mark.parametrize("path", ALL_COMMANDS)
    def test_help_output_mentions_the_command(self, path):
        result = CliRunner().invoke(cli, [*path.split(), "--help"])
        name = path.split()[-1]
        assert name in result.output or "Usage" in result.output


class TestNoCallbackBindingErrors:
    """Invoke each command with no arguments: a TypeError here is a real bug.

    A binding error is distinguishable from a legitimate failure: a legitimate
    failure raises a click exception (exit code 1/2 with a message), whereas a
    binding error is a TypeError reported by Click itself.
    """

    @pytest.mark.parametrize("args", [
        ["info"],
        ["query", "summary"],
        ["query", "list"],
        ["query", "orphaned"],
        ["query", "top"],
        ["report"],
        ["scan"],
        ["export"],
        ["uninstall"],
    ])
    def test_invocation_never_raises_a_binding_error(self, args, tmp_path, monkeypatch):
        monkeypatch.setenv("BCU_CLI_HOME", str(tmp_path))
        result = CliRunner().invoke(cli, args)

        text = f"{result.output}\n{result.exception!r}"
        assert "got an unexpected keyword argument" not in text, (
            f"`{' '.join(args)}` hit a Click binding error — an option name and "
            f"its function parameter disagree:\n{text}"
        )
        assert "takes" not in text or "positional argument" not in text


class TestKnownGoodBindings:
    """Direct guards on the specific names that are easy to get wrong."""

    def test_apply_option_binds_to_apply_(self):
        params = {p.name for p in cli.commands["uninstall"].params}
        assert "apply_" in params
        assert "apply" not in params

    def test_uninstall_flags_are_all_bound(self):
        params = {p.name for p in cli.commands["uninstall"].params}
        for expected in ("pattern", "apply_", "confirm", "unattended", "quiet",
                         "junk_level", "first_only", "bcul_path", "timeout"):
            assert expected in params, expected

    def test_query_show_takes_a_pattern(self):
        params = {p.name for p in cli.commands["query"].commands["show"].params}
        assert "pattern" in params
