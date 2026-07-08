# SPDX-License-Identifier: Apache-2.0
"""``python -m sndr.cli`` entry point.

The two entry points are DELIBERATELY different surfaces — do not "unify" them:

  * the ``sndr`` console script -> ``sndr.cli.main:main`` (pyproject.toml) — the
    curated, first-run operator surface (``quickstart``, ``up``, ``run``,
    ``chat``, ``remote``, plus the promoted verbs). This is what the READMEs and
    onboarding guides tell a user to run.
  * ``python -m sndr.cli`` -> ``sndr.cli.legacy.cli_main`` (below) — the FULL
    legacy/infra surface (``gui-api``, ``k8s``, ``proxmox``, ``routing-table``,
    ``self-test`` …). The Makefile ``gui-api`` target, the compose daemon and
    the install smoke scripts invoke ``python -m sndr.cli <infra-cmd>``; those
    verbs do not exist on the curated ``main`` dispatcher, so routing this entry
    through ``main`` would break daemon launch (regression-guarded by
    tests/unit/cli/test_gui_api_cli.py, which asserts ``python -m sndr.cli
    gui-api --help`` exits 0).

The modern first-run verbs live on the ``sndr`` binary; the full command set
(including infra) lives here. Neither dispatcher is a superset of the other.
"""
import sys

from sndr.cli.legacy import cli_main

if __name__ == "__main__":
    sys.exit(cli_main())
