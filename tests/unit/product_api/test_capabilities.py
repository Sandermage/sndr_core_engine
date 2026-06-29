# SPDX-License-Identifier: Apache-2.0
"""Tests for top-level GUI/Product API capability snapshots."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass

from sndr.product_api.legacy import capabilities
from sndr.product_api.legacy.types import ProductCapabilities


def _fake_which(present: set[str]):
    def which(tool: str):
        return f"/usr/bin/{tool}" if tool in present else None

    return which


def test_collect_capabilities_returns_frozen_dataclass_shape():
    snapshot = capabilities.collect_capabilities(
        which=_fake_which({"docker", "ssh"}),
        engine_installed=False,
    )

    assert isinstance(snapshot, ProductCapabilities)
    assert is_dataclass(snapshot)

    payload = asdict(snapshot)
    assert payload["platform"]["sndr_core_version"]
    assert payload["platform"]["engine_installed"] is False
    assert isinstance(payload["runtime_targets"], tuple)
    assert isinstance(payload["features"], tuple)


def test_runtime_target_status_reflects_tool_presence():
    snapshot = capabilities.collect_capabilities(
        which=_fake_which({"docker", "ssh"}),
        engine_installed=False,
    )
    runtimes = {item.id: item for item in snapshot.runtime_targets}

    assert runtimes["docker_compose"].status == "available"
    assert runtimes["docker_compose"].present_tools == ("docker",)
    assert runtimes["kubernetes"].status == "render_only"
    assert runtimes["kubernetes"].present_tools == ()
    assert runtimes["remote_ssh"].status == "available"


def test_engine_features_are_deferred_without_engine_package():
    snapshot = capabilities.collect_capabilities(
        which=_fake_which(set()),
        engine_installed=False,
    )
    features = {item.id: item for item in snapshot.features}

    assert features["catalog_overview"].status == "available"
    assert features["patch_plan"].status == "available"
    assert features["service_lifecycle"].status == "available"
    assert features["web_daemon"].status == "available"
    assert features["engine_fleet"].status == "deferred"


def test_engine_features_are_available_when_engine_is_present():
    snapshot = capabilities.collect_capabilities(
        which=_fake_which(set()),
        engine_installed=True,
    )
    features = {item.id: item for item in snapshot.features}

    assert snapshot.platform.engine_installed is True
    assert features["engine_fleet"].status == "available"


def test_external_services_feature_reflects_the_opt_in_key(monkeypatch):
    """The 'external_services' feature mirrors the SNDR_ENABLE_EXTERNAL_SERVICES
    key — available only when the operator opts in (so the GUI gates on it)."""
    monkeypatch.delenv("SNDR_ENABLE_EXTERNAL_SERVICES", raising=False)
    snap = capabilities.collect_capabilities(which=_fake_which(set()), engine_installed=False)
    feats = {i.id: i for i in snap.features}
    assert "external_services" in feats, "the proxy/aggregator connector feature must be advertised"
    assert feats["external_services"].status != "available", "off without the key"

    monkeypatch.setenv("SNDR_ENABLE_EXTERNAL_SERVICES", "1")
    snap2 = capabilities.collect_capabilities(which=_fake_which(set()), engine_installed=False)
    feats2 = {i.id: i for i in snap2.features}
    assert feats2["external_services"].status == "available", "on with the key set"
