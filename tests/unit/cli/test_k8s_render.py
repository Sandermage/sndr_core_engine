# SPDX-License-Identifier: Apache-2.0
"""S3.3 closure (audit P3-3, 2026-05-12): тесты для k8s YAML renderer.

Покрывают:

  • Existing hostPath storage path (regression safety).
  • New `node_selector` block рендерится в pod template spec.
  • New `pvc` блок создаёт `kind: PersistentVolumeClaim` + volume
    binding через persistentVolumeClaim.claimName.
  • `secret_mounts` создаёт volume через secret.secretName.
  • Все YAML документы parseable (yaml.safe_load_all).
"""
from __future__ import annotations

import pytest

yaml = pytest.importorskip("yaml")

from vllm.sndr_core.cli.k8s import _all_yaml
from vllm.sndr_core.model_configs.schema import (
    DockerConfig, HardwareSpec, KubernetesConfig, ModelConfig,
)


def _make_k8s_cfg(**k8s_overrides) -> ModelConfig:
    k8s_kwargs = dict(
        flavor="generic-single-node",
        namespace="test-ns",
        image="vllm/vllm-openai:nightly",
        gpu_count=2,
    )
    k8s_kwargs.update(k8s_overrides)
    return ModelConfig(
        key="test-k8s", title="K8s Test",
        description="d", schema_version=1, maintainer="x",
        model_path="/models/Test-7B",
        hardware=HardwareSpec(
            gpu_match_keys=["test"], n_gpus=2,
            min_vram_per_gpu_mib=24576,
        ),
        docker=DockerConfig(
            image="vllm/vllm-openai:nightly",
            container_name="vllm-test",
            port=8000,
        ),
        kubernetes=KubernetesConfig(**k8s_kwargs),
    )


class TestK8sRender:
    def test_baseline_yaml_parses(self):
        cfg = _make_k8s_cfg()
        docs = list(yaml.safe_load_all(_all_yaml(cfg)))
        # ConfigMap + Service + Deployment минимум
        kinds = [d.get("kind") for d in docs if d]
        assert "ConfigMap" in kinds
        assert "Service" in kinds
        assert "Deployment" in kinds

    def test_hostpath_storage_renders(self):
        cfg = _make_k8s_cfg(storage={"models": "/srv/models"})
        out = _all_yaml(cfg)
        assert "hostPath" in out
        assert "/srv/models" in out

    def test_node_selector_renders(self):
        cfg = _make_k8s_cfg(node_selector={
            "gpu-class": "a5000",
            "nvidia.com/gpu.present": "true",
        })
        out = _all_yaml(cfg)
        assert "nodeSelector:" in out
        assert "gpu-class: a5000" in out
        # Parseable
        docs = list(yaml.safe_load_all(out))
        deploy = next(d for d in docs if d and d.get("kind") == "Deployment")
        node_sel = deploy["spec"]["template"]["spec"]["nodeSelector"]
        assert node_sel["gpu-class"] == "a5000"

    def test_node_selector_omitted_when_empty(self):
        cfg = _make_k8s_cfg()  # no node_selector
        out = _all_yaml(cfg)
        assert "nodeSelector:" not in out

    def test_pvc_creates_persistent_volume_claim(self):
        cfg = _make_k8s_cfg(
            pvc={"genesis-models": "/models"},
            pvc_size_gib={"genesis-models": 500},
            pvc_storage_class="local-path",
        )
        out = _all_yaml(cfg)
        docs = list(yaml.safe_load_all(out))
        kinds = [d.get("kind") for d in docs if d]
        assert "PersistentVolumeClaim" in kinds
        pvc = next(d for d in docs
                    if d and d.get("kind") == "PersistentVolumeClaim")
        assert pvc["metadata"]["name"] == "genesis-models"
        assert pvc["spec"]["resources"]["requests"]["storage"] == "500Gi"
        assert pvc["spec"]["storageClassName"] == "local-path"

    def test_pvc_default_size_when_unspecified(self):
        cfg = _make_k8s_cfg(pvc={"hf-cache": "/root/.cache/huggingface"})
        out = _all_yaml(cfg)
        docs = list(yaml.safe_load_all(out))
        pvc = next(d for d in docs
                    if d and d.get("kind") == "PersistentVolumeClaim")
        assert pvc["spec"]["resources"]["requests"]["storage"] == "100Gi"

    def test_pvc_mounted_in_deployment(self):
        cfg = _make_k8s_cfg(pvc={"models-vol": "/models"})
        docs = list(yaml.safe_load_all(_all_yaml(cfg)))
        deploy = next(d for d in docs if d and d.get("kind") == "Deployment")
        container = deploy["spec"]["template"]["spec"]["containers"][0]
        mount = next(m for m in container["volumeMounts"]
                      if m["name"] == "models-vol")
        assert mount["mountPath"] == "/models"
        # Volume binding
        vol = next(v for v in deploy["spec"]["template"]["spec"]["volumes"]
                    if v["name"] == "models-vol")
        assert vol["persistentVolumeClaim"]["claimName"] == "models-vol"

    def test_secret_mount_renders(self):
        cfg = _make_k8s_cfg(secret_mounts={"hf-token": "/etc/hf-token"})
        docs = list(yaml.safe_load_all(_all_yaml(cfg)))
        deploy = next(d for d in docs if d and d.get("kind") == "Deployment")
        vol = next(v for v in deploy["spec"]["template"]["spec"]["volumes"]
                    if v["name"] == "hf-token")
        assert vol["secret"]["secretName"] == "hf-token"

    def test_no_pvc_when_empty(self):
        cfg = _make_k8s_cfg()  # no pvc / no secret
        out = _all_yaml(cfg)
        docs = list(yaml.safe_load_all(out))
        kinds = [d.get("kind") for d in docs if d]
        assert "PersistentVolumeClaim" not in kinds
