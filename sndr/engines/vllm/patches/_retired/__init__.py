# SPDX-License-Identifier: Apache-2.0
"""``_retired/`` — terminal-lifecycle patch wiring archive.

Patches that reached the ``lifecycle: retired`` state move here. Their
wiring modules expose a no-op ``apply()`` returning ``("skipped",
"<reason>")`` so the dispatcher table can still reference them for
audit-trail continuity without raising ``ModuleNotFoundError``.
"""
