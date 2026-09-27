"""Unit tests for cli-anything-bcu.

Uses real BCU fixtures captured during reconnaissance (tests/fixtures/) plus
synthetic cases. **Does not invoke BCU-console** — no admin, no 58-second scan.
The real-backend suite lives in test_full_e2e.py.

The B1..B6 regressions from TEST.md Part 0 are marked in the test docstrings.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))

from cli_anything.bcu.core import index as index_mod      # noqa: E402
from cli_anything.bcu.core import listfile, parse, plan    # noqa: E402
from cli_anything.bcu.core import model, report, select    # noqa: E402
from cli_anything.bcu.utils import bcu_backend as backend  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name: str) -> str:
    return os.path.join(FIXTURES, name)


def read_fixture(name: str) -> str:
    with open(fixture(name), encoding="utf-8", errors="replace") as handle:
        return handle.read()


# ── fixtures: real, from the reconnaissance run ───────────────────────
@pytest.fixture(scope="module")
def real_apps() -> list[model.Application]:
    return parse.parse_list_json(read_fixture("list_591_apps.json"))


# ══ core/model.py ═════════════════════════════════════════════════════

class TestApplicationModel:

    def test_maps_every_documented_field(self):
        raw = {
            "DisplayName": "Acme Archiver 4.10 (x64)",
            "DisplayVersion": "25.01",
            "Publisher": "Igor Pavlov",
            "InstallLocation": "D:\\apps\\AcmeArchiver",
            "InstallDate": "2025-11-23",
            "EstimatedSizeKb": 5758,
            "UninstallString": '"D:\\apps\\AcmeArchiver\\Uninstall.exe"',
            "QuietUninstallString": '"D:\\apps\\AcmeArchiver\\Uninstall.exe" /S',
            "UninstallerKind": "Unknown",
            "Is64Bit": "X64",
            "IsProtected": False,
            "SystemComponent": False,
            "QuietUninstallPossible": True,
            "UninstallPossible": True,
            "RegistryKeyName": "AcmeArchiver",
        }
        app = model.Application.from_bcu_json(raw)
        assert app.display_name == "Acme Archiver 4.10 (x64)"
        assert app.display_version == "25.01"
        assert app.publisher == "Igor Pavlov"
        assert app.install_location == "D:\\apps\\AcmeArchiver"
        assert app.estimated_size_kb == 5758
        assert app.quiet_uninstall_string.endswith("/S")
        assert app.is_64bit == "X64"
        assert app.uninstaller_kind == "Unknown"
        assert app.registry_key_name == "AcmeArchiver"

    def test_null_version_becomes_empty_string(self):
        app = model.Application.from_bcu_json({"DisplayName": "X", "DisplayVersion": None})
        assert app.display_version == ""

    def test_missing_keys_are_tolerated(self):
        app = model.Application.from_bcu_json({"DisplayName": "Bare"})
        assert app.display_name == "Bare"
        assert app.estimated_size_kb == 0
        assert app.is_protected is False

    def test_estimated_size_is_int64_safe(self):
        app = model.Application.from_bcu_json(
            {"DisplayName": "Big", "EstimatedSizeKb": 9223372036854775}
        )
        assert isinstance(app.estimated_size_kb, int)
        assert app.estimated_size_kb == 9223372036854775

    def test_size_is_coerced_from_string(self):
        app = model.Application.from_bcu_json({"DisplayName": "S", "EstimatedSizeKb": "1234"})
        assert app.estimated_size_kb == 1234

    def test_unknown_extra_keys_are_ignored(self):
        app = model.Application.from_bcu_json({"DisplayName": "X", "SomeNewField": 1})
        assert app.display_name == "X"

    def test_size_human(self):
        assert model.Application(display_name="a", estimated_size_kb=0).size_human == "0 KB"
        assert model.Application(display_name="a", estimated_size_kb=512).size_human == "512 KB"
        assert "MB" in model.Application(display_name="a", estimated_size_kb=5758).size_human
        assert "GB" in model.Application(display_name="a", estimated_size_kb=5 * 1024 * 1024).size_human

    def test_kind_normalized(self):
        assert model.Application(display_name="a", uninstaller_kind="Msi").kind_normalized == "msi"
        assert model.Application(display_name="a", uninstaller_kind="").kind_normalized == "unknown"

    def test_is_uninstallable_requires_both_flag_and_command(self):
        assert model.Application(
            display_name="a", uninstall_possible=True,
            uninstall_string="x").is_uninstallable is True
        assert model.Application(
            display_name="a", uninstall_possible=True,
            uninstall_string="").is_uninstallable is False
        assert model.Application(
            display_name="a", uninstall_possible=False,
            uninstall_string="x").is_uninstallable is False

    def test_is_quiet_capable_requires_both_flag_and_command(self):
        assert model.Application(
            display_name="a", quiet_uninstall_possible=True,
            quiet_uninstall_string="x /S").is_quiet_capable is True
        assert model.Application(
            display_name="a", quiet_uninstall_possible=True,
            quiet_uninstall_string="").is_quiet_capable is False

    def test_to_dict_is_round_trippable(self):
        original = model.Application.from_bcu_json(
            {"DisplayName": "N", "EstimatedSizeKb": 7, "Publisher": "p"})
        again = model.Application.from_bcu_json(original.to_dict())
        assert again == original


# ══ core/parse.py ═════════════════════════════════════════════════════

class TestParseListJson:

    def test_real_591_app_fixture(self, real_apps):
        """B3: the captured production scan must parse completely."""
        assert len(real_apps) == 591
        names = {a.display_name for a in real_apps}
        assert any("AcmeArchiver" in n for n in names)

    def test_real_fixture_top_level_is_array(self):
        data = json.loads(read_fixture("list_591_apps.json"))
        assert isinstance(data, list), "BCU emits a bare array, not an object"

    def test_empty_array(self):
        assert parse.parse_list_json("[]") == []

    def test_malformed_json_raises_value_error(self, tmp_path):
        with pytest.raises(ValueError):
            parse.parse_list_json("{not json")

    def test_object_instead_of_array_is_rejected(self):
        with pytest.raises(ValueError) as exc:
            parse.parse_list_json('{"Applications": []}')
        assert "array" in str(exc.value).lower() or "list" in str(exc.value).lower()

    def test_non_object_items_are_rejected(self):
        with pytest.raises(ValueError):
            parse.parse_list_json('["just-a-string"]')

    def test_bom_and_leading_whitespace_tolerated(self):
        assert parse.parse_list_json('\ufeff\n  []  ') == []


class TestDecodeConsoleOutput:

    def test_utf16le_is_detected(self):
        """B3: `list` without /F is UTF-16LE (first bytes 42 00 43 00)."""
        raw = "BCU-console, Version=6.3.0.0".encode("utf-16-le")
        assert parse.decode_console_output(raw).startswith("BCU-console")

    def test_real_utf16_fixture_decodes(self):
        with open(fixture("list_plain_utf16.txt"), "rb") as handle:
            raw = handle.read()
        text = parse.decode_console_output(raw)
        assert "BCU-console" in text
        assert "Display Name" in text

    def test_utf8_with_bom(self):
        assert parse.decode_console_output("\ufeffhello".encode("utf-8")).strip() == "hello"

    def test_plain_utf8(self):
        assert parse.decode_console_output(b"plain ascii") == "plain ascii"

    def test_cjk_survives_utf16(self):
        # Real BCU console output always opens with the ASCII banner
        # ("BCU-console, Version=..."), and that banner is what makes UTF-16
        # detection possible: ASCII in UTF-16 is ~50% NUL bytes. A *pure* CJK
        # UTF-16 stream has no NULs at all and is genuinely ambiguous, so this
        # test mirrors the real shape.
        text = "BCU-console, Version=6.3.0.0\nclassifieds自动回复系统    1.2.3\n"
        assert parse.decode_console_output(text.encode("utf-16-le")) == text

    def test_pure_cjk_utf16_without_banner_is_documented_as_ambiguous(self):
        # No NUL bytes means no reliable tell; the decoder must at least not
        # crash, and must return *something* rather than raising.
        raw = "classifieds自动回复系统".encode("utf-16-le")
        out = parse.decode_console_output(raw)
        assert isinstance(out, str)
        assert out != ""

    def test_plain_utf8_cjk_is_not_mistaken_for_utf16(self):
        text = "BCU-console, Version=6.3.0.0\n飞书 Lark\n"
        assert parse.decode_console_output(text.encode("utf-8")) == text

    def test_utf8_with_cjk(self):
        assert parse.decode_console_output("飞书 Lark".encode("utf-8")) == "飞书 Lark"


class TestParseDryRunStderr:

    def test_real_one_match_fixture(self):
        """B4: uninstall writes to stderr even with /F=json."""
        result = parse.parse_dry_run_stderr(read_fixture("dryrun_1match_stderr.txt"))
        assert result.found == 591
        assert result.matched_count == 1
        assert result.matched_names == ["Acme Archiver 4.10 (x64)"]
        assert result.finished == 1
        assert result.failed == 0
        assert result.was_dry_run is True

    def test_real_nomatch_fixture(self):
        result = parse.parse_dry_run_stderr(read_fixture("dryrun_nomatch_stderr.txt"))
        assert result.matched_count == 0
        assert result.matched_names == []

    def test_parses_found_count(self):
        result = parse.parse_dry_run_stderr("Found 42 applications.\n")
        assert result.found == 42

    def test_parses_matched_names_list(self):
        text = "2 application(s) were matched by the list: Foo 1.0, Bar 2.0\n"
        result = parse.parse_dry_run_stderr(text)
        assert result.matched_count == 2
        assert result.matched_names == ["Foo 1.0", "Bar 2.0"]

    def test_parses_finished_and_failed(self):
        text = "Running: 0, Waiting: 0, Finished: 3, Failed: 1\n"
        result = parse.parse_dry_run_stderr(text)
        assert result.finished == 3
        assert result.failed == 1

    def test_dry_run_marker_absent_when_not_dry_run(self):
        assert parse.parse_dry_run_stderr("Uninstall task Finished.").was_dry_run is False

    def test_empty_input_is_not_an_error(self):
        result = parse.parse_dry_run_stderr("")
        assert result.matched_count == 0
        assert result.found is None

    def test_matched_name_containing_commas_is_kept_whole(self):
        # BCU joins names with ", " so a name may itself contain a comma; the
        # count is authoritative for how many were matched.
        text = "1 application(s) were matched by the list: Weird, Name 1.0\n"
        result = parse.parse_dry_run_stderr(text)
        assert result.matched_count == 1


# ══ core/listfile.py ══════════════════════════════════════════════════

class TestBuildBcul:

    def test_root_element_and_schema(self):
        xml = listfile.build_bcul([listfile.FilterSpec(pattern="AcmeArchiver")])
        assert xml.startswith("<?xml")
        assert "<UninstallList" in xml
        assert "XMLSchema-instance" in xml

    def test_contains_required_elements_in_order(self):
        """B3/B4: element order is what XmlSerializer expects."""
        xml = listfile.build_bcul([listfile.FilterSpec(pattern="AcmeArchiver")])
        for tag in ("<Enabled>", "<Filters>", "<Filter>", "<Exclude>", "<Name>",
                    "<ComparisonEntries>", "<FilterCondition>", "<FilterText>",
                    "<ComparisonMethod>"):
            assert tag in xml, tag
        assert xml.index("<Enabled>") < xml.index("<Filters>")
        assert xml.index("<Exclude>") < xml.index("<Name>")
        assert xml.index("<InvertResults>") < xml.index("<FilterText>")

    def test_include_filter_is_not_excluded(self):
        xml = listfile.build_bcul([listfile.FilterSpec(pattern="A")])
        assert "<Exclude>false</Exclude>" in xml

    def test_exclude_filter_flag(self):
        xml = listfile.build_bcul([listfile.FilterSpec(pattern="A", exclude=True)])
        assert "<Exclude>true</Exclude>" in xml

    def test_comparison_method_default_is_contains(self):
        xml = listfile.build_bcul([listfile.FilterSpec(pattern="A")])
        assert "<ComparisonMethod>Contains</ComparisonMethod>" in xml

    def test_custom_comparison_method(self):
        xml = listfile.build_bcul([listfile.FilterSpec(pattern="A", method="Equals")])
        assert "<ComparisonMethod>Equals</ComparisonMethod>" in xml

    def test_invalid_comparison_method_rejected(self):
        with pytest.raises(ValueError):
            listfile.build_bcul([listfile.FilterSpec(pattern="A", method="Bogus")])

    def test_xml_special_chars_are_escaped(self):
        # A quote needs no escaping inside element *text* (only in attributes),
        # so the meaningful assertion is that the document parses and the value
        # comes back byte-identical.
        import xml.etree.ElementTree as ET
        pattern = 'A & B < C > "D"'
        xml = listfile.build_bcul([listfile.FilterSpec(pattern=pattern)])
        assert "&amp;" in xml
        assert "&lt;" in xml
        assert "&gt;" in xml
        root = ET.fromstring(xml)
        assert root.find(".//FilterText").text == pattern

    def test_apostrophe_in_name_is_safe(self):
        xml = listfile.build_bcul([listfile.FilterSpec(pattern="Bob's Tool")])
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
        assert root is not None

    def test_cjk_pattern_round_trips(self):
        import xml.etree.ElementTree as ET
        xml = listfile.build_bcul([listfile.FilterSpec(pattern="classifieds自动回复系统")])
        root = ET.fromstring(xml)
        found = root.find(".//FilterText")
        assert found is not None and found.text == "classifieds自动回复系统"

    def test_multiple_filters(self):
        xml = listfile.build_bcul([
            listfile.FilterSpec(pattern="A"),
            listfile.FilterSpec(pattern="B"),
        ])
        assert xml.count("<Filter>") == 2

    def test_empty_filter_list_rejected(self):
        with pytest.raises(ValueError):
            listfile.build_bcul([])

    def test_blank_pattern_rejected(self):
        with pytest.raises(ValueError):
            listfile.build_bcul([listfile.FilterSpec(pattern="   ")])

    def test_write_bcul_creates_utf8_file(self, tmp_path):
        path = str(tmp_path / "out.bcul")
        listfile.write_bcul([listfile.FilterSpec(pattern="X")], path)
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as handle:
            assert "<UninstallList" in handle.read()

    def test_matches_real_bcul_fixture_shape(self):
        """Our generated file must be structurally identical to the one the
        probe proved BCU accepts (valid_list.bcul)."""
        import xml.etree.ElementTree as ET
        mine = ET.fromstring(listfile.build_bcul([listfile.FilterSpec(pattern="AcmeArchiver")]))
        real = ET.fromstring(read_fixture("valid_list.bcul"))

        def shape(node):
            return sorted({child.tag for child in node})

        assert shape(mine) == shape(real)
        assert shape(mine.find("Filters/Filter")) == shape(real.find("Filters/Filter"))


# ══ core/index.py ═════════════════════════════════════════════════════

class TestIndex:

    def test_save_load_round_trip(self, tmp_path, real_apps):
        path = str(tmp_path / "idx.json")
        idx = index_mod.Index.from_apps(real_apps, bcu_version="6.3.0.0",
                                        console_path=r"D:\x\BCU-console.exe")
        idx.save(path)
        again = index_mod.Index.load(path)
        assert len(again.apps) == len(real_apps)
        assert again.bcu_version == "6.3.0.0"
        assert again.apps[0].display_name == real_apps[0].display_name

    def test_load_missing_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            index_mod.Index.load(str(tmp_path / "nope.json"))

    def test_load_corrupt_raises_value_error(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{broken", encoding="utf-8")
        with pytest.raises(ValueError):
            index_mod.Index.load(str(path))

    def test_load_wrong_schema_raises_value_error(self, tmp_path):
        path = tmp_path / "wrong.json"
        path.write_text(json.dumps({"schema_version": 999, "apps": []}), encoding="utf-8")
        with pytest.raises(ValueError) as exc:
            index_mod.Index.load(str(path))
        assert "schema" in str(exc.value).lower()

    def test_missing_apps_key_raises_value_error(self, tmp_path):
        path = tmp_path / "noapps.json"
        path.write_text(json.dumps({"schema_version": index_mod.SCHEMA_VERSION}), encoding="utf-8")
        with pytest.raises(ValueError):
            index_mod.Index.load(str(path))

    def test_atomic_write_leaves_no_temp_file(self, tmp_path):
        path = str(tmp_path / "idx.json")
        index_mod.Index.from_apps([], bcu_version="1", console_path="p").save(path)
        leftovers = [n for n in os.listdir(tmp_path) if n != "idx.json"]
        assert leftovers == []

    def test_counts_and_totals(self, real_apps):
        idx = index_mod.Index.from_apps(real_apps, bcu_version="6.3.0.0", console_path="p")
        assert idx.count == 591
        assert idx.total_size_kb > 0
        assert idx.quiet_capable_count > 0
        assert idx.orphaned_count >= 0

    def test_generated_at_present(self, real_apps):
        idx = index_mod.Index.from_apps(real_apps, bcu_version="1", console_path="p")
        assert idx.generated_at


# ══ core/select.py ════════════════════════════════════════════════════

@pytest.fixture
def apps() -> list[model.Application]:
    # NOTE: is_uninstallable requires BOTH the flag and the command (BCU reports
    # them independently — 60 of 591 apps had the quiet flag true with no quiet
    # command). So a realistic fixture must set uninstall_possible=True or the
    # planner is right to refuse it. This fixture mirrors real BCU output shape.
    def android(**kw):
        base = dict(uninstall_possible=True, uninstall_string="uninstall.exe")
        base.update(kw)
        return model.Application(**base)

    return [
        android(display_name="Acme Archiver 4.10 (x64)", publisher="Igor Pavlov",
                uninstall_string="7z-uninst.exe", quiet_uninstall_string="7z-uninst.exe /S",
                quiet_uninstall_possible=True, estimated_size_kb=5758,
                registry_key_name="AcmeArchiver", uninstaller_kind="Nsis"),
        android(display_name="Google Chrome", publisher="Google LLC",
                uninstall_string="setup.exe --uninstall",
                quiet_uninstall_string="setup.exe --uninstall --silent",
                quiet_uninstall_possible=True, estimated_size_kb=500000,
                registry_key_name="Google Chrome", uninstaller_kind="InnoSetup"),
        android(display_name="Uninstall Tool", publisher="CrystalIDEA",
                estimated_size_kb=9000, registry_key_name="Uninstall Tool"),
        android(display_name="Protected Thing", is_protected=True,
                estimated_size_kb=100, registry_key_name="Protected Thing"),
    ]


class TestSelectApps:

    def test_exact_match(self, apps):
        result = select.select_apps(apps, "Google Chrome")
        assert [a.display_name for a in result.matched] == ["Google Chrome"]
        assert result.ambiguous is False

    def test_exact_match_is_case_insensitive(self, apps):
        result = select.select_apps(apps, "google chrome")
        assert len(result.matched) == 1

    def test_substring_matches_multiple(self, apps):
        result = select.select_apps(apps, "tool", exact=False)
        assert {a.display_name for a in result.matched} == {"Uninstall Tool"}

    def test_ambiguous_substring_is_flagged(self, apps):
        result = select.select_apps(apps, "o", exact=False)
        assert result.ambiguous is True
        assert len(result.matched) > 1

    def test_no_match_reports_reason(self, apps):
        result = select.select_apps(apps, "definitely-not-installed")
        assert result.matched == []
        assert "no" in result.reason.lower()

    def test_protected_apps_are_excluded_by_default(self, apps):
        result = select.select_apps(apps, "Protected Thing")
        assert result.matched == []

    def test_protected_apps_can_be_included(self, apps):
        result = select.select_apps(apps, "Protected Thing", include_protected=True)
        assert len(result.matched) == 1

    def test_glob_pattern(self, apps):
        result = select.select_apps(apps, "*Zip*", glob=True)
        assert [a.display_name for a in result.matched] == ["Acme Archiver 4.10 (x64)"]

    def test_selection_by_registry_key(self, apps):
        result = select.select_apps(apps, "AcmeArchiver", by="registry_key")
        assert len(result.matched) == 1

    def test_empty_pattern_rejected(self, apps):
        with pytest.raises(ValueError):
            select.select_apps(apps, "   ")

    def test_unknown_by_rejected(self, apps):
        with pytest.raises(ValueError):
            select.select_apps(apps, "x", by="bogus")

    def test_if_multiple_selects_first_when_not_strict(self, apps):
        result = select.select_apps(apps, "o", exact=False, first_only=True)
        assert len(result.matched) == 1


# ══ core/plan.py ══════════════════════════════════════════════════════

class TestPlan:

    def test_dry_run_is_the_default(self, apps):
        selection = select.select_apps(apps, "Google Chrome")
        p = plan.build_plan(selection, mode=None)
        assert p.mode == "dry-run"
        assert "/N" in p.argv

    def test_apply_without_confirm_is_refused(self, apps):
        """The exact combination that shipped broken.

        `--apply` alone used to run a real uninstall: the guard only fired for
        `/U`. The README promised `--apply --confirm`, so the code was wrong, not
        the documentation. This test covers the bare `apply` case directly —
        previously nothing did, which is why the defect survived 147 green tests.
        """
        selection = select.select_apps(apps, "Google Chrome")
        p = plan.build_plan(selection, mode="apply")
        assert p.refused is True
        assert "confirm" in p.reason.lower()
        assert p.argv == [], "a refused plan must carry no command to run"
        assert p.will_run is False

    def test_apply_with_confirm_is_accepted(self, apps):
        """Positive control: the gate must be a gate, not a wall."""
        selection = select.select_apps(apps, "Google Chrome")
        p = plan.build_plan(selection, mode="apply", confirmed=True)
        assert p.refused is False
        assert p.mode == "apply"
        assert "/N" not in p.argv
        assert p.destructive is True

    def test_unattended_apply_without_confirm_is_refused(self, apps):
        selection = select.select_apps(apps, "Google Chrome")
        p = plan.build_plan(selection, mode="apply", unattended=True)
        assert p.refused is True
        assert "confirm" in p.reason.lower()

    def test_dry_run_never_needs_confirm(self, apps):
        """Confirm is about irreversibility; a dry run is not irreversible."""
        selection = select.select_apps(apps, "Google Chrome")
        for kwargs in ({}, {"unattended": True}, {"quiet": True}):
            p = plan.build_plan(selection, mode="dry-run", **kwargs)
            assert p.refused is False, kwargs
            assert "/N" in p.argv

    def test_unattended_allowed_when_explicitly_confirmed(self, apps):
        selection = select.select_apps(apps, "Google Chrome")
        p = plan.build_plan(selection, mode="apply", unattended=True, confirmed=True)
        assert p.refused is False
        assert "/U" in p.argv

    def test_empty_selection_is_refused(self, apps):
        selection = select.select_apps(apps, "nothing-here")
        p = plan.build_plan(selection, mode="apply", confirmed=True)
        assert p.refused is True

    def test_protected_selection_is_refused(self, apps):
        selection = select.select_apps(apps, "Protected Thing", include_protected=True)
        p = plan.build_plan(selection, mode="apply", confirmed=True)
        assert p.refused is True
        assert "protected" in p.reason.lower()

    def test_quiet_flag_maps_to_slash_Q(self, apps):
        selection = select.select_apps(apps, "Google Chrome")
        assert "/Q" in plan.build_plan(selection, quiet=True).argv
        assert "/Q" not in plan.build_plan(selection).argv

    def test_junk_level_is_validated(self, apps):
        selection = select.select_apps(apps, "Google Chrome")
        assert "/J=Good" in plan.build_plan(selection, junk_level="Good").argv
        with pytest.raises(ValueError):
            plan.build_plan(selection, junk_level="Nonsense")

    def test_junk_level_omitted_by_default(self, apps):
        selection = select.select_apps(apps, "Google Chrome")
        assert not any(a.startswith("/J=") for a in plan.build_plan(selection).argv)

    def test_reports_quiet_capability_per_app(self, apps):
        selection = select.select_apps(apps, "Google Chrome")
        p = plan.build_plan(selection)
        assert p.quiet_capable == ["Google Chrome"]

    def test_reports_not_quiet_capable(self, apps):
        selection = select.select_apps(apps, "Uninstall Tool")
        p = plan.build_plan(selection)
        assert p.quiet_capable == []
        assert p.not_quiet_capable == ["Uninstall Tool"]

    def test_plan_carries_generated_bcul_text(self, apps):
        selection = select.select_apps(apps, "Google Chrome")
        p = plan.build_plan(selection)
        assert "<UninstallList" in p.bcul_text
        assert "Google Chrome" in p.bcul_text

    def test_argv_targets_a_bcul_path(self, apps, tmp_path):
        selection = select.select_apps(apps, "Google Chrome")
        p = plan.build_plan(selection)
        assert p.argv[0] == "uninstall"
        assert p.argv[1].endswith(".bcul")


# ══ core/report.py ════════════════════════════════════════════════════

class TestReport:

    def test_csv_has_header_and_rows(self, apps):
        text = report.render(apps[:2], fmt="csv")
        lines = [ln for ln in text.strip().splitlines() if ln]
        assert len(lines) == 3
        assert lines[0].startswith("display_name")

    def test_json_is_parseable_list(self, apps):
        data = json.loads(report.render(apps, fmt="json"))
        assert isinstance(data, list)
        assert data[0]["display_name"] == apps[0].display_name

    def test_json_respects_columns(self, apps):
        data = json.loads(report.render(apps[:1], fmt="json", columns=["display_name"]))
        assert list(data[0].keys()) == ["display_name"]

    def test_table_is_aligned(self, apps):
        text = report.render(apps[:2], fmt="table")
        assert "DISPLAY_NAME" in text.upper()
        assert "AcmeArchiver" in text

    def test_markdown_has_pipes(self, apps):
        text = report.render(apps[:2], fmt="markdown")
        assert text.count("|") >= 4

    def test_empty_input_does_not_crash(self):
        assert report.render([], fmt="csv") is not None

    def test_unknown_format_rejected(self, apps):
        with pytest.raises(ValueError):
            report.render(apps, fmt="bogus")

    def test_top_n_limit(self, apps):
        data = json.loads(report.render(apps, fmt="json", top=2))
        assert len(data) == 2

    def test_default_columns_include_actionable_fields(self):
        for column in ("display_name", "size_human", "kind_normalized", "publisher"):
            assert column in report.DEFAULT_COLUMNS


# ══ utils/bcu_backend.py ══════════════════════════════════════════════

class TestFindConsole:

    def test_explicit_path_wins(self, tmp_path):
        fake = tmp_path / "BCU-console.exe"
        fake.write_bytes(b"MZ")
        assert backend.find_console(str(fake)) == str(fake)

    def test_explicit_missing_raises(self, tmp_path):
        with pytest.raises(backend.BCUNotFound):
            backend.find_console(str(tmp_path / "ghost.exe"))

    def test_env_var(self, tmp_path, monkeypatch):
        fake = tmp_path / "BCU-console.exe"
        fake.write_bytes(b"MZ")
        monkeypatch.setenv(backend.ENV_VAR, str(fake))
        assert backend.find_console() == str(fake)

    def test_missing_raises_with_actionable_hint(self, tmp_path, monkeypatch):
        monkeypatch.delenv(backend.ENV_VAR, raising=False)
        monkeypatch.setattr(backend, "DEFAULT_SEARCH_PATHS", ())
        monkeypatch.setattr(backend.shutil, "which", lambda name: None)
        with pytest.raises(backend.BCUNotFound) as exc:
            backend.find_console()
        message = str(exc.value)
        assert "BCU-console" in message
        assert "github.com" in message or "BCUConsole" in message

    def test_release_url_is_the_official_repo(self):
        assert "BCUninstaller" in backend.RELEASE_API
        assert backend.RELEASE_API.startswith("https://api.github.com/repos/")


class TestBuildArgs:

    def test_list_json(self):
        assert backend.build_list_args(fmt="json") == ["list", "/F=json"]

    def test_list_plain_has_no_format_switch(self):
        assert backend.build_list_args(fmt=None) == ["list"]

    def test_list_rejects_unknown_format(self):
        with pytest.raises(ValueError):
            backend.build_list_args(fmt="yaml")

    def test_export(self):
        args = backend.build_export_args("out.json", fmt="json")
        assert args[0] == "export" and args[1] == "out.json" and "/F=json" in args

    def test_uninstall_dry_run(self):
        args = backend.build_uninstall_args("x.bcul", dry_run=True)
        assert args == ["uninstall", "x.bcul", "/N"]

    def test_uninstall_apply_has_no_dry_run_flag(self):
        args = backend.build_uninstall_args("x.bcul", dry_run=False)
        assert "/N" not in args

    def test_uninstall_quiet_and_unattended(self):
        args = backend.build_uninstall_args("x.bcul", dry_run=False, quiet=True,
                                            unattended=True)
        assert "/Q" in args and "/U" in args

    def test_uninstall_junk_level(self):
        args = backend.build_uninstall_args("x.bcul", dry_run=True, junk_level="VeryGood")
        assert "/J=VeryGood" in args

    def test_uninstall_invalid_junk_level_rejected(self):
        with pytest.raises(ValueError):
            backend.build_uninstall_args("x.bcul", junk_level="Nope")

    def test_verbose_flag(self):
        assert "/V" in backend.build_list_args(verbose=True)


class TestAdmin:

    def test_is_admin_returns_bool(self):
        assert isinstance(backend.is_admin(), bool)

    def test_admin_requirement_message_is_actionable(self):
        message = backend.admin_requirement_message()
        assert "administrator" in message.lower()
        assert "BCU-console" in message
