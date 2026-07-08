# SPDX-License-Identifier: Apache-2.0
"""Deterministic re-anchor proposer — the core of safer/simpler pin bumps.

Every pin bump breaks a handful of text-patches: their exact-substring anchor no
longer matches because upstream renamed a line, inserted a method, or reflowed a
call. Today that means manual archaeology per patch. `propose_anchor` turns it
into review-and-apply: given a drifted anchor and the new pristine source, it
locates the surviving landmark lines and proposes the corrected anchor (the
pristine region that spans them), classifying the drift.

The proposer is ANALYSIS ONLY — it never edits the apply engine, so it cannot
mis-apply a patch; it only advises. A human/agent reviews the proposal before it
is written.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "tools" / "propose_reanchors.py"


def _mod():
    spec = importlib.util.spec_from_file_location("_propose_reanchors", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_unchanged_anchor_is_recognized():
    m = _mod()
    anchor = "    def f(self):\n        return self.x\n"
    pristine = "class A:\n" + anchor + "\n    def g(self):\n        pass\n"
    p = m.propose_anchor(anchor, pristine)
    assert p["status"] == "unchanged"


def test_renamed_line_reanchors():
    """PN367-like: a line inside the anchor was renamed (cuda -> accelerator);
    the surrounding lines survive, so the region is re-derivable."""
    m = _mod()
    old = (
        "                        torch.accelerator.synchronize()\n"
        "                        free_after = torch.cuda.mem_get_info()[0]\n"
        "                        mem_samples.append(mem_before - free_after)\n"
    )
    pristine = (
        "def profile():\n"
        "                        torch.accelerator.synchronize()\n"
        "                        free_after = torch.accelerator.get_memory_info()[0]\n"
        "                        mem_samples.append(mem_before - free_after)\n"
        "    return\n"
    )
    p = m.propose_anchor(old, pristine)
    assert p["status"] == "reanchor"
    # the proposed anchor is a real, unique substring of the new pristine
    assert p["new_anchor"] in pristine
    assert pristine.count(p["new_anchor"]) == 1
    # it carries the upstream rename
    assert "get_memory_info" in p["new_anchor"]
    # and still spans the surviving landmark lines
    assert "mem_samples.append(mem_before - free_after)" in p["new_anchor"]
    assert p["confidence"] in ("high", "medium")


def test_inserted_line_extends_the_anchor():
    """PN12-like: upstream inserted a new method between the anchor's first and
    last lines; the corrected anchor must span the inserted region."""
    m = _mod()
    old = (
        "    def forward_xpu(self, x):\n"
        "        return self.forward_cuda(x)\n"
        "\n"
        "@register('op')\n"
    )
    pristine = (
        "    def forward_xpu(self, x):\n"
        "        return self.forward_cuda(x)\n"
        "\n"
        "    def forward_cpu(self, x):\n"
        "        return self.forward_native(x)\n"
        "\n"
        "@register('op')\n"
    )
    p = m.propose_anchor(old, pristine)
    assert p["status"] == "reanchor"
    assert "forward_cpu" in p["new_anchor"]
    assert p["new_anchor"] in pristine


def test_absent_anchor_is_manual():
    """The anchored code is gone entirely — no landmark survives; flag manual."""
    m = _mod()
    old = "        totally_unique_gone_symbol_xyz()\n        and_another_gone_qpr()\n"
    pristine = "def something_else():\n    pass\n"
    p = m.propose_anchor(old, pristine)
    assert p["status"] == "manual"
    assert p["confidence"] == "low"


def test_ambiguous_landmark_lowers_confidence():
    """The surviving landmark appears many times -> can't uniquely re-anchor."""
    m = _mod()
    old = "    x = 1\n    UNIQUE_MARKER_ABC = compute()\n    y = 2\n"
    pristine = "    x = 1\n" * 5 + "    y = 2\n" * 5  # marker gone, only common lines
    p = m.propose_anchor(old, pristine)
    assert p["status"] in ("manual", "reanchor")
    if p["status"] == "manual":
        assert p["confidence"] == "low"
