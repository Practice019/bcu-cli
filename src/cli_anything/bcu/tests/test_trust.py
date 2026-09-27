"""Tests for the field-trust helpers.

Each test encodes a mistake that was actually made and reported to a user, so a
future change that re-introduces it fails here instead of in the field.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))

from cli_anything.bcu.core import trust  # noqa: E402
from cli_anything.bcu.core.model import Application  # noqa: E402


def app(**kwargs) -> Application:
    base = dict(display_name="X", uninstall_possible=True, uninstall_string="u.exe")
    base.update(kwargs)
    return Application(**base)


class TestSizeReliability:

    def test_counts_entries_without_a_size(self):
        items = [app(estimated_size_kb=100), app(estimated_size_kb=0), app(estimated_size_kb=0)]
        report = trust.size_reliability(items)
        assert report["entry_count"] == 3
        assert report["entries_without_size"] == 2

    def test_coverage_percentage(self):
        items = [app(estimated_size_kb=1), app(estimated_size_kb=0)]
        assert trust.size_reliability(items)["coverage_pct"] == 50.0

    def test_empty_input_does_not_divide_by_zero(self):
        report = trust.size_reliability([])
        assert report["coverage_pct"] == 0.0

    def test_caveat_says_it_is_not_a_measurement(self):
        assert "not measurements" in trust.SIZE_CAVEAT.lower() or \
               "not a measurement" in trust.SIZE_CAVEAT.lower()


class TestDuplicateLocations:

    def test_finds_two_entries_sharing_a_directory(self):
        """The AcmeAnalytics case: 88 GB reported for a 44 GB directory."""
        items = [
            app(display_name="AcmeAnalytics", install_location=r"D:\apps\AcmeAnalytics",
                estimated_size_kb=44 * 1024 * 1024),
            app(display_name="AcmeAnalytics 2026.01", install_location=r"D:\apps\AcmeAnalytics",
                estimated_size_kb=44 * 1024 * 1024),
        ]
        dupes = trust.duplicate_locations(items)
        assert len(dupes) == 1
        assert set(dupes[r"d:\software\AcmeAnalytics"]) == {"AcmeAnalytics", "AcmeAnalytics 2026.01"}

    def test_trailing_separator_and_case_are_normalised(self):
        items = [
            app(install_location=r"C:\Dir"),
            app(install_location="c:\\dir\\"),
        ]
        assert len(trust.duplicate_locations(items)) == 1

    def test_distinct_directories_are_not_duplicates(self):
        items = [app(install_location=r"C:\A"), app(install_location=r"C:\B")]
        assert trust.duplicate_locations(items) == {}

    def test_missing_locations_are_ignored(self):
        assert trust.duplicate_locations([app(), app()]) == {}


class TestDeduplicatedTotal:

    def test_shared_directory_counted_once(self):
        items = [
            app(display_name="a", install_location=r"D:\x", estimated_size_kb=44_000_000),
            app(display_name="b", install_location=r"D:\x", estimated_size_kb=44_000_000),
        ]
        assert trust.deduplicated_total_kb(items) == 44_000_000

    def test_takes_the_largest_value_for_a_shared_directory(self):
        items = [
            app(install_location=r"D:\x", estimated_size_kb=100),
            app(install_location=r"D:\x", estimated_size_kb=500),
        ]
        assert trust.deduplicated_total_kb(items) == 500

    def test_entries_without_a_location_still_count(self):
        items = [app(estimated_size_kb=10), app(estimated_size_kb=20)]
        assert trust.deduplicated_total_kb(items) == 30

    def test_mixed(self):
        items = [
            app(install_location=r"D:\x", estimated_size_kb=100),
            app(install_location=r"D:\x", estimated_size_kb=100),
            app(install_location=r"D:\y", estimated_size_kb=50),
            app(estimated_size_kb=7),
        ]
        assert trust.deduplicated_total_kb(items) == 157


class TestTrulyDeadEntries:

    def test_registry_record_with_missing_files_is_dead(self, tmp_path):
        ghost = str(tmp_path / "gone")
        items = [app(registry_path=r"HKLM\...\Ghost", install_location=ghost)]
        assert len(trust.truly_dead_entries(items)) == 1

    def test_is_orphaned_is_not_the_test(self, tmp_path):
        """The mistake: treating BCU's orphan flag as 'leftover registry entry'.

        A portable app with files present and no registry record is what BCU
        calls orphaned, and it is very much alive.
        """
        alive = tmp_path / "portable"
        alive.mkdir()
        items = [app(display_name="portable", install_location=str(alive),
                     registry_path="", registry_key_name="", is_orphaned=True)]
        assert trust.truly_dead_entries(items) == []

    def test_portable_without_location_is_not_classed_as_dead(self):
        items = [app(install_location="", registry_path="", registry_key_name="")]
        assert trust.truly_dead_entries(items) == []

    def test_installed_and_present_is_not_dead(self, tmp_path):
        present = tmp_path / "here"
        present.mkdir()
        items = [app(registry_path=r"HKLM\...\Real", install_location=str(present))]
        assert trust.truly_dead_entries(items) == []


class TestSummarizeForReport:

    def test_bundles_every_caveat(self, tmp_path):
        # The shared directory must actually exist, otherwise every entry looks
        # dead and the test measures nothing. (First version used a literal
        # "D:\x" — which does not exist here — and the assertion below caught it.)
        shared = tmp_path / "shared"
        shared.mkdir()
        ghost = str(tmp_path / "ghost")
        items = [
            app(display_name="a", install_location=str(shared), estimated_size_kb=100,
                registry_path="k", is_orphaned=False),
            app(display_name="b", install_location=str(shared), estimated_size_kb=100,
                registry_path="k", is_orphaned=True),
            app(display_name="ghost", registry_path="k", install_location=ghost),
        ]
        report = trust.summarize_for_report(items)
        assert report["entry_count"] == 3
        assert report["deduplicated_total_kb"] == 100
        assert report["orphan_flag_count"] == 1
        assert report["truly_dead_count"] == 1
        assert "not a measurement" in report["size_reliability"]["caveat"].lower() or \
               "not measurements" in report["size_reliability"]["caveat"].lower()
        assert "directory scan" in report["orphan_caveat"].lower()
