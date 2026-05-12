# SPDX-License-Identifier: Apache-2.0
"""C10 (UNIFIED_CONFIG plan 2026-05-09) — `sndr k8s` Kubernetes CLI.

Reads a preset's Y5 `kubernetes` block + `docker` + `genesis_env` and
renders k8s manifests (Deployment + Service + ConfigMap) ready for
`kubectl apply -f`.

Subcommands:
  sndr k8s render <key>      — print manifests to stdout
  sndr k8s apply <key>       — `kubectl apply -f` (--yes required)
  sndr k8s status <key>      — `kubectl get pods/svc` for the namespace
  sndr k8s logs <key>        — `kubectl logs` of the deployment
  sndr k8s delete <key>      — tear down (--yes required)

Dry-run by default; `--yes` to actually shell out to kubectl.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from typing import Any, Optional

from . import _io


__all__ = ["add_argparser", "run_render", "run_apply", "run_status",
           "run_logs", "run_delete", "run_doctor"]


def add_argparser(subparsers: Any) -> None:
    p = subparsers.add_parser(
        "k8s",
        help="Kubernetes deployment wrapper around Y5 KubernetesConfig (UNIFIED_CONFIG C10).",
        description=(
            "Render + apply Genesis presets to a Kubernetes cluster. "
            "Backends: microk8s-single-node / generic-single-node / "
            "generic-multinode. Default --dry-run; --yes to mutate."
        ),
    )
    sub = p.add_subparsers(dest="k8s_cmd", required=True)

    for cmd, helper, fn in (
        ("render", "Print manifests (Deployment + Service + ConfigMap)", run_render),
        ("apply",  "kubectl apply -f the rendered manifests",            run_apply),
        ("status", "kubectl get pods/svc",                               run_status),
        ("logs",   "kubectl logs of the deployment",                     run_logs),
        ("delete", "Tear down the deployment + service + configmap",     run_delete),
    ):
        sp = sub.add_parser(cmd, help=helper)
        sp.add_argument("config", help="model_config preset key")
        sp.add_argument("--yes", action="store_true",
                          help="Actually call kubectl (default: dry-run).")
        sp.add_argument("--lines", type=int, default=50,
                          help="logs: number of recent lines (default 50).")
        sp.set_defaults(func=fn)

    # `sndr k8s doctor` — verify cluster prerequisites for the preset
    p_doctor = sub.add_parser(
        "doctor",
        help="Verify cluster prerequisites for the preset.",
        description=(
            "Probes the current kubectl context for GPU operator / "
            "device-plugin presence, runtimeClass support, namespace "
            "existence, and basic NVIDIA driver visibility on nodes. "
            "Read-only — never mutates."
        ),
    )
    p_doctor.add_argument("config", nargs="?", default=None,
                            help="optional preset key (otherwise cluster-wide check).")
    p_doctor.add_argument("--json", action="store_true",
                            help="Emit JSON.")
    p_doctor.set_defaults(func=run_doctor)


def _resolve(key: str):
    from vllm.sndr_core.model_configs.registry import get
    cfg = get(key)
    if cfg is None:
        _io.warn(f"unknown preset key {key!r}")
        return None
    if cfg.kubernetes is None:
        _io.warn(f"preset {key!r} has no Y5 kubernetes block; "
                  f"add `kubernetes:` to the YAML to use this CLI.")
        return None
    return cfg


def _service_yaml(cfg) -> str:
    k = cfg.kubernetes
    name = f"sndr-{cfg.key}"
    port = (cfg.docker.effective_container_port()
            if cfg.docker else 8000)
    nodeport_line = (
        f"    nodePort: {k.service_node_port}\n"
        if k.service_type == "NodePort" and k.service_node_port
        else ""
    )
    return (
        f"apiVersion: v1\n"
        f"kind: Service\n"
        f"metadata:\n"
        f"  name: {name}\n"
        f"  namespace: {k.namespace}\n"
        f"spec:\n"
        f"  type: {k.service_type}\n"
        f"  selector:\n"
        f"    app: {name}\n"
        f"  ports:\n"
        f"  - port: {port}\n"
        f"    targetPort: {port}\n"
        f"    protocol: TCP\n"
        f"{nodeport_line}"
    )


def _image_ref(cfg) -> str:
    k = cfg.kubernetes
    if k.image:
        return k.image
    if cfg.docker:
        return cfg.docker.effective_image_ref()
    return ""


def _configmap_yaml(cfg) -> str:
    """Genesis env vars as a ConfigMap (simpler than Secret for typical knobs)."""
    name = f"sndr-{cfg.key}-env"
    k = cfg.kubernetes
    env_dict = {**cfg.system_env, **cfg.genesis_env}
    body = (
        f"apiVersion: v1\n"
        f"kind: ConfigMap\n"
        f"metadata:\n"
        f"  name: {name}\n"
        f"  namespace: {k.namespace}\n"
        f"data:\n"
    )
    for key, val in env_dict.items():
        # YAML escape: wrap value in quotes always
        body += f"  {key}: {str(val)!r}\n"
    return body


def _pvc_yaml(cfg) -> str:
    """S3.3 audit P3-3: per-claim PersistentVolumeClaim manifests.

    Возвращает пустую строку если pvc пусты — operator использует
    hostPath storage. Иначе по одному PVC на claim_name.
    """
    k = cfg.kubernetes
    if not k.pvc:
        return ""
    out = ""
    for claim_name in k.pvc:
        size_gib = k.pvc_size_gib.get(claim_name, 100)
        storage_class_line = (
            f"  storageClassName: {k.pvc_storage_class}\n"
            if k.pvc_storage_class else ""
        )
        out += (
            f"---\n"
            f"apiVersion: v1\n"
            f"kind: PersistentVolumeClaim\n"
            f"metadata:\n"
            f"  name: {claim_name}\n"
            f"  namespace: {k.namespace}\n"
            f"spec:\n"
            f"  accessModes:\n"
            f"  - ReadWriteOnce\n"
            f"  resources:\n"
            f"    requests:\n"
            f"      storage: {size_gib}Gi\n"
            f"{storage_class_line}"
        )
    return out


def _deployment_yaml(cfg) -> str:
    k = cfg.kubernetes
    name = f"sndr-{cfg.key}"
    port = (cfg.docker.effective_container_port()
            if cfg.docker else 8000)
    image = _image_ref(cfg)

    # Volumes + mounts: hostPath (legacy storage), PVC, Secret —
    # три источника на один volumes[] список.
    storage_volumes = ""
    storage_mounts = ""
    # 1) hostPath storage (existing)
    for vol_name, vol_path in k.storage.items():
        storage_volumes += (
            f"      - name: {vol_name}\n"
            f"        hostPath:\n"
            f"          path: {vol_path}\n"
        )
        storage_mounts += (
            f"        - name: {vol_name}\n"
            f"          mountPath: /{vol_name}\n"
            f"          readOnly: true\n"
        )
    # 2) PVC (S3.3)
    for claim_name, mount_path in k.pvc.items():
        storage_volumes += (
            f"      - name: {claim_name}\n"
            f"        persistentVolumeClaim:\n"
            f"          claimName: {claim_name}\n"
        )
        storage_mounts += (
            f"        - name: {claim_name}\n"
            f"          mountPath: {mount_path}\n"
        )
    # 3) Secret mounts (S3.3)
    for secret_name, mount_path in k.secret_mounts.items():
        storage_volumes += (
            f"      - name: {secret_name}\n"
            f"        secret:\n"
            f"          secretName: {secret_name}\n"
        )
        storage_mounts += (
            f"        - name: {secret_name}\n"
            f"          mountPath: {mount_path}\n"
            f"          readOnly: true\n"
        )

    # S3.3 fix: emit inline `[]` when no volumes (was misaligned before).
    volume_mounts_block = (
        f"        volumeMounts:\n{storage_mounts}"
        if storage_mounts
        else "        volumeMounts: []\n"
    )
    volumes_block = (
        f"      volumes:\n{storage_volumes}"
        if storage_volumes
        else "      volumes: []\n"
    )

    # S3.3: nodeSelector (опционально). Пустой → omit block.
    node_selector_block = ""
    if k.node_selector:
        node_selector_block = "      nodeSelector:\n"
        for key, value in k.node_selector.items():
            node_selector_block += f"        {key}: {value}\n"

    return (
        f"apiVersion: apps/v1\n"
        f"kind: Deployment\n"
        f"metadata:\n"
        f"  name: {name}\n"
        f"  namespace: {k.namespace}\n"
        f"spec:\n"
        f"  replicas: 1\n"
        f"  selector:\n"
        f"    matchLabels:\n"
        f"      app: {name}\n"
        f"  template:\n"
        f"    metadata:\n"
        f"      labels:\n"
        f"        app: {name}\n"
        f"    spec:\n"
        f"      runtimeClassName: {k.runtime_class_name}\n"
        f"{node_selector_block}"
        f"      containers:\n"
        f"      - name: {name}\n"
        f"        image: {image}\n"
        f"        imagePullPolicy: {k.image_pull_policy}\n"
        f"        ports:\n"
        f"        - containerPort: {port}\n"
        f"        envFrom:\n"
        f"        - configMapRef:\n"
        f"            name: {name}-env\n"
        f"        resources:\n"
        f"          limits:\n"
        f"            {k.gpu_resource_name}: {k.gpu_count}\n"
        f"        readinessProbe:\n"
        f"          httpGet:\n"
        f"            path: /health\n"
        f"            port: {port}\n"
        f"          initialDelaySeconds: {k.readiness_initial_delay}\n"
        f"        livenessProbe:\n"
        f"          httpGet:\n"
        f"            path: /health\n"
        f"            port: {port}\n"
        f"          initialDelaySeconds: {k.liveness_initial_delay}\n"
        f"{volume_mounts_block}"
        f"{volumes_block}"
    )


def _all_yaml(cfg) -> str:
    return (
        f"# Generated by sndr k8s render — preset {cfg.key!r}\n"
        f"# Do NOT edit by hand; re-run sndr k8s render to refresh.\n"
        f"---\n{_configmap_yaml(cfg)}"
        f"---\n{_service_yaml(cfg)}"
        f"{_pvc_yaml(cfg)}"
        f"---\n{_deployment_yaml(cfg)}"
    )


def _kubectl(*args, dry_run: bool, stdin: Optional[str] = None) -> int:
    if dry_run:
        cmd_str = " ".join(["kubectl"] + list(args))
        if stdin:
            cmd_str = f"<manifests> | {cmd_str}"
        _io.info(f"[dry-run] would: {cmd_str}")
        return 0
    if shutil.which("kubectl") is None:
        _io.error("kubectl not on PATH")
        return 1
    r = subprocess.run(["kubectl"] + list(args),
                        input=stdin, capture_output=True, text=True,
                        timeout=60)
    if r.stdout:
        print(r.stdout.rstrip())
    if r.stderr:
        print(r.stderr.rstrip())
    return r.returncode


# ─── render

def run_render(args: argparse.Namespace) -> int:
    cfg = _resolve(args.config)
    if cfg is None:
        return 2
    print(_all_yaml(cfg))
    return 0


# ─── apply

def run_apply(args: argparse.Namespace) -> int:
    cfg = _resolve(args.config)
    if cfg is None:
        return 2
    body = _all_yaml(cfg)
    return _kubectl("apply", "-f", "-", dry_run=not args.yes, stdin=body)


# ─── status

def run_status(args: argparse.Namespace) -> int:
    cfg = _resolve(args.config)
    if cfg is None:
        return 2
    namespace = cfg.kubernetes.namespace
    name = f"sndr-{cfg.key}"
    rc1 = _kubectl("get", "deploy", "-n", namespace, name, dry_run=False)
    rc2 = _kubectl("get", "svc", "-n", namespace, name, dry_run=False)
    rc3 = _kubectl("get", "pods", "-n", namespace, "-l", f"app={name}",
                    dry_run=False)
    return max(rc1, rc2, rc3)


# ─── logs

def run_logs(args: argparse.Namespace) -> int:
    cfg = _resolve(args.config)
    if cfg is None:
        return 2
    namespace = cfg.kubernetes.namespace
    name = f"sndr-{cfg.key}"
    return _kubectl("logs", "-n", namespace, "-l", f"app={name}",
                     "--tail", str(args.lines), dry_run=False)


# ─── delete

def run_delete(args: argparse.Namespace) -> int:
    cfg = _resolve(args.config)
    if cfg is None:
        return 2
    namespace = cfg.kubernetes.namespace
    name = f"sndr-{cfg.key}"
    dry_run = not args.yes
    rc1 = _kubectl("delete", "deploy", "-n", namespace, name,
                    "--ignore-not-found", dry_run=dry_run)
    rc2 = _kubectl("delete", "svc", "-n", namespace, name,
                    "--ignore-not-found", dry_run=dry_run)
    rc3 = _kubectl("delete", "configmap", "-n", namespace, f"{name}-env",
                    "--ignore-not-found", dry_run=dry_run)
    return max(rc1, rc2, rc3)


# ─── doctor: cluster prerequisite checks
def run_doctor(args: argparse.Namespace) -> int:
    """Cluster readiness probe.

    Walks a small set of checks and emits a structured report. Never
    mutates. Returns 0 when all checks pass, 1 when any FAIL, 2 when
    only WARN-level findings.
    """
    import json
    if not shutil.which("kubectl"):
        out = {
            "kubectl_present": False,
            "checks": [],
            "summary": "kubectl not on PATH — install it before using `sndr k8s`.",
        }
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            _io.error(out["summary"])
        return 1

    checks: list[dict] = []

    def _check(name: str, cmd: list[str], pass_if_zero: bool = True,
               warn_only: bool = False) -> dict:
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10,
            )
            ok = (r.returncode == 0) if pass_if_zero else (r.returncode != 0)
            severity = "PASS" if ok else ("WARN" if warn_only else "FAIL")
            return {
                "name": name,
                "severity": severity,
                "message": (r.stdout or r.stderr or "").strip()[:200],
            }
        except FileNotFoundError:
            return {"name": name, "severity": "FAIL", "message": "binary missing"}
        except subprocess.TimeoutExpired:
            return {"name": name, "severity": "WARN", "message": "command timed out"}
        except Exception as e:
            return {"name": name, "severity": "WARN", "message": f"{type(e).__name__}: {e}"}

    # 1. kubectl context reachable
    checks.append(_check(
        "cluster_reachable",
        ["kubectl", "cluster-info", "--request-timeout=5s"],
    ))

    # 2. node count + readiness
    r_nodes = _check(
        "nodes_ready",
        ["kubectl", "get", "nodes", "--no-headers"],
    )
    checks.append(r_nodes)

    # 3. GPU device plugin DaemonSet (nvidia.com/gpu)
    checks.append(_check(
        "nvidia_device_plugin",
        ["kubectl", "get", "daemonset", "-A",
         "-l", "k8s-app=nvidia-device-plugin",
         "--no-headers"],
        warn_only=True,
    ))

    # 4. runtimeClass nvidia
    checks.append(_check(
        "runtime_class_nvidia",
        ["kubectl", "get", "runtimeclass", "nvidia"],
        warn_only=True,
    ))

    # 5. NVIDIA GPU operator (alt installation method)
    checks.append(_check(
        "gpu_operator",
        ["kubectl", "get", "ns", "gpu-operator", "--no-headers"],
        warn_only=True,
    ))

    # 6. Per-preset checks: namespace exists, can list secrets in it
    if args.config:
        try:
            cfg = _resolve(args.config)
            ns = getattr(getattr(cfg, "kubernetes", None), "namespace",
                          None) or "default"
            checks.append(_check(
                f"namespace_{ns}",
                ["kubectl", "get", "ns", ns, "--no-headers"],
            ))
        except Exception as e:
            checks.append({
                "name": f"preset_{args.config}",
                "severity": "FAIL",
                "message": f"preset resolve failed: {e}",
            })

    fails = sum(1 for c in checks if c["severity"] == "FAIL")
    warns = sum(1 for c in checks if c["severity"] == "WARN")

    if args.json:
        print(json.dumps({"kubectl_present": True, "checks": checks,
                           "fails": fails, "warns": warns}, indent=2))
    else:
        _io.banner("sndr k8s doctor",
                    f"{len(checks)} checks — {fails} fail · {warns} warn")
        for c in checks:
            mark = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}[c["severity"]]
            line = f"  {mark} [{c['severity']:<4}] {c['name']:<24} {c['message'][:80]}"
            if c["severity"] == "FAIL":
                _io.error(line)
            elif c["severity"] == "WARN":
                _io.warn(line)
            else:
                _io.info(line)

    if fails:
        return 1
    if warns:
        return 2
    return 0
