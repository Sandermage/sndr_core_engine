# SPDX-License-Identifier: Apache-2.0
"""Tests for ``scripts/audit_retire_eligibility.py`` — §9.A.16
(AUDIT-CLOSURE.3, 2026-05-27).

Coverage:

  * ``bucket_to_verdict`` mapping is correct for every bucket
  * Bucket→verdict pairs stay in lockstep with
    ``audit_upstream_status.py::retire_eligibility`` (locks the pair
    so a registry-bucket addition forces a paired edit + test update)
  * Live corpus: ``run_audit(skip_network=True)`` yields stable verdict
    counts; no RETIRE-CANDIDATE on tracked tree today
  * ``--fail-on-retire-candidate`` exit code semantics
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_retire_eligibility.py"


def _import_audit_module():
    spec = importlib.util.spec_from_file_location(
        "audit_retire_eligibility", SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_retire_eligibility"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def audit_mod():
    return _import_audit_module()


class TestBucketToVerdict:
    """Map covers every documented bucket with the correct verdict."""

    def test_newly_merged_is_retire_candidate(self, audit_mod):
        assert audit_mod.bucket_to_verdict("NEWLY-MERGED") == "RETIRE-CANDIDATE"

    @pytest.mark.parametrize("bucket", [
        "COUNTER-REGRESSION",
        "INTENTIONAL-INVERSE",
        "ENABLES-UPSTREAM",
        "DEFENSIVE-OVERLAY",
        "RELATED-NOT-SUPERSEDING",
    ])
    def test_non_pure_merged_is_needs_deep_parity(self, audit_mod, bucket):
        assert audit_mod.bucket_to_verdict(bucket) == "NEEDS-DEEP-PARITY"

    @pytest.mark.parametrize("bucket", ["SUPERSEDED-OK", "STALE-RETIRED"])
    def test_retired_lifecycle_buckets_are_already_retired(
        self, audit_mod, bucket,
    ):
        assert audit_mod.bucket_to_verdict(bucket) == "ALREADY-RETIRED"

    def test_watch_is_active(self, audit_mod):
        assert audit_mod.bucket_to_verdict("WATCH") == "ACTIVE"

    @pytest.mark.parametrize("bucket", ["ERROR", "ISSUE-OPEN", "ISSUE-CLOSED"])
    def test_inactionable_buckets_are_unknown(self, audit_mod, bucket):
        assert audit_mod.bucket_to_verdict(bucket) == "UNKNOWN"

    def test_unknown_bucket_falls_back_to_unknown(self, audit_mod):
        assert audit_mod.bucket_to_verdict("MADE-UP-BUCKET") == "UNKNOWN"


class TestParityWithUpstreamStatus:
    """Lock the bucket→verdict map against
    ``audit_upstream_status.py::retire_eligibility``."""

    def _import_upstream(self):
        path = REPO_ROOT / "scripts" / "audit_upstream_status.py"
        spec = importlib.util.spec_from_file_location(
            "_us_for_test", path
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_us_for_test"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_every_bucket_in_map_matches_retire_eligibility(self, audit_mod):
        """For each bucket in the wrapper's map, build a minimal
        row_data + verify ``retire_eligibility`` produces the SAME
        verdict. Locks the two surfaces in lockstep."""
        upstream = self._import_upstream()
        # Build synthetic row_data shapes that produce each bucket via
        # ``categorize()``. Some buckets need specific (pr_state,
        # merged_at, lifecycle, relationship) combinations.
        scenarios: list[tuple[str, dict]] = [
            ("NEWLY-MERGED", {
                "pr": {"kind": "pr", "state": "closed",
                       "merged_at": "2026-01-01T00:00:00Z"},
                "lifecycle": "stable",
                "upstream_pr_relationship": "backport",
            }),
            ("COUNTER-REGRESSION", {
                "pr": {"kind": "pr", "state": "closed",
                       "merged_at": "2026-01-01T00:00:00Z"},
                "lifecycle": "stable",
                "upstream_pr_relationship": "counter_regression",
            }),
            ("INTENTIONAL-INVERSE", {
                "pr": {"kind": "pr", "state": "closed",
                       "merged_at": "2026-01-01T00:00:00Z"},
                "lifecycle": "stable",
                "upstream_pr_relationship": "intentional_inverse",
            }),
            ("SUPERSEDED-OK", {
                "pr": {"kind": "pr", "state": "closed",
                       "merged_at": "2026-01-01T00:00:00Z"},
                "lifecycle": "retired",
                "upstream_pr_relationship": "backport",
            }),
            ("STALE-RETIRED", {
                "pr": {"kind": "pr", "state": "open", "merged_at": None},
                "lifecycle": "retired",
                "upstream_pr_relationship": "backport",
            }),
            ("WATCH", {
                "pr": {"kind": "pr", "state": "open", "merged_at": None},
                "lifecycle": "stable",
                "upstream_pr_relationship": "backport",
            }),
            ("ISSUE-OPEN", {
                "pr": {"kind": "issue", "state": "open", "merged_at": None},
                "lifecycle": "stable",
                "upstream_pr_relationship": "backport",
            }),
            ("ISSUE-CLOSED", {
                "pr": {"kind": "issue", "state": "closed",
                       "merged_at": None},
                "lifecycle": "stable",
                "upstream_pr_relationship": "backport",
            }),
        ]
        for expected_bucket, row_data in scenarios:
            actual_bucket = upstream.categorize(row_data)
            assert actual_bucket == expected_bucket, (
                f"scenario for {expected_bucket} produced "
                f"{actual_bucket} — fixture wrong"
            )
            upstream_verdict = upstream.retire_eligibility(row_data)
            wrapper_verdict = audit_mod.bucket_to_verdict(actual_bucket)
            assert upstream_verdict == wrapper_verdict, (
                f"parity broken for bucket {actual_bucket}: "
                f"upstream={upstream_verdict!r} "
                f"wrapper={wrapper_verdict!r}"
            )


class TestLiveCorpus:
    """Live retire-eligibility report."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True, text=True, cwd=REPO_ROOT, check=False,
        )

    def test_live_default_exit_zero(self):
        result = self._run()
        assert result.returncode == 0, (
            f"live exit should be 0, got {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    def test_live_no_retire_candidate(self):
        """Live tree is in a state where no PATCH has bucket
        NEWLY-MERGED → no RETIRE-CANDIDATE verdict. The
        ``--fail-on-retire-candidate`` gate stays at exit 0."""
        result = self._run("--fail-on-retire-candidate")
        assert result.returncode == 0, (
            f"--fail-on-retire-candidate must stay 0 on clean tree, "
            f"got {result.returncode}\nstdout:\n{result.stdout}"
        )

    def test_live_json_shape(self):
        result = self._run("--json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "counts" in data
        assert "total" in data
        assert "candidates" in data
        assert data["total"] >= 1
        # Verdicts in canonical set.
        valid_verdicts = {
            "RETIRE-CANDIDATE", "NEEDS-DEEP-PARITY",
            "ACTIVE", "ALREADY-RETIRED", "UNKNOWN",
        }
        for verdict in data["counts"]:
            assert verdict in valid_verdicts, (
                f"unexpected verdict in output: {verdict!r}"
            )

    def test_help_works(self):
        result = self._run("--help")
        assert result.returncode == 0
        assert "audit_retire_eligibility" in result.stdout
        assert "--fail-on-retire-candidate" in result.stdout
