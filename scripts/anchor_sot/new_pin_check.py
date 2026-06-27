#!/usr/bin/env python3
"""Phase 4 — NEW-pin readiness orchestrator (host-runnable, deterministic).

One command that takes a freshly-generated ``pins/<new>/`` manifest (from
``make rebuild-pin``) and runs the FULL bump-readiness assessment against the
correct previous pin, so the operator does not have to hand-pick the OLD pin dir
(picking the wrong one silently produces a meaningless diff). Composes the
existing pieces:

  1. resolve the PREVIOUS committed pin DETERMINISTICALLY — the committed pin
     with the same release whose ``.devNNN`` is the highest strictly below the
     new pin's (chronological order within a release). No hand-picking.
  2. coverage sanity — the new manifest's drift.rej.json accounts for every
     discovered anchor (discovered == ok + rejected; build_manifest already
     asserts this, re-checked here so a hand-edited manifest can't slip).
  3. summarize_rej on the new pin (genuine drift + retired + the PART 1b
     perf-soft-skip latent-no-op callout + retire-broken dependents).
  4. bump_preflight OLD->NEW (retire-impact + perf-landmine + (c2) sub-patch
     no-op gate). Its exit code drives the readiness verdict.

Pure host code — operates only on COMMITTED manifests, no rig / no vLLM — so the
whole flow is deterministic and unit-testable.

Usage:
    new_pin_check.py <new_pin_dir>           # explicit new pin
    new_pin_check.py                          # auto = most-recent committed pin
    new_pin_check.py <new_pin_dir> --old <dir>  # override previous pin

Exit codes:
    0  ready — no UNMITIGATED HIGH dependency break (advisory perf deltas may
       still be present; they are surfaced + A/B-gated, not a hard fail).
    1  NOT ready — bump_preflight failed (unmitigated HIGH perf dependent).
    2  usage / unresolvable input (no new pin, no previous pin to diff against).
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PINS_DIR = os.path.abspath(os.path.join(
    HERE, "..", "..", "sndr", "engines", "vllm", "pins"))

_PIN_RE = re.compile(
    r"(?P<rel>\d+\.\d+\.\d+)(?:rc\d+)?(?:\.dev(?P<dev>\d+))?\+g[0-9a-f]+")


def _pin_of(pin_dir):
    """Return the full vllm pin string recorded in <pin_dir>/anchors.json."""
    p = os.path.join(pin_dir, "anchors.json")
    if not os.path.isfile(p):
        return None
    try:
        return ((json.load(open(p)).get("pins") or {}).get("vllm")) or None
    except (OSError, ValueError):
        return None


def parse_pin(pin):
    """(release, dev) for a vllm pin string, e.g. '0.23.1rc1.dev424+g3f5..' ->
    ('0.23.1', 424). dev defaults to 0 when absent. None when unparseable."""
    if not pin:
        return None
    m = _PIN_RE.match(str(pin))
    if not m:
        return None
    return m.group("rel"), int(m.group("dev") or 0)


def list_committed_pin_dirs(pins_dir=PINS_DIR):
    """All committed pin dirs that carry BOTH anchors.json + drift.rej.json."""
    if not os.path.isdir(pins_dir):
        return []
    out = []
    for name in sorted(os.listdir(pins_dir)):
        d = os.path.join(pins_dir, name)
        if (os.path.isdir(d) and os.path.isfile(os.path.join(d, "anchors.json"))
                and os.path.isfile(os.path.join(d, "drift.rej.json"))):
            out.append(d)
    return out


def resolve_previous_pin_dir(new_pin_dir, pins_dir=PINS_DIR):
    """Deterministically pick the PREVIOUS committed pin dir for ``new_pin_dir``.

    The previous pin is the committed pin with the SAME release whose ``.devNNN``
    is the highest value STRICTLY below the new pin's dev (chronological order
    within a release). Ties / unparseable pins are skipped. Returns None when no
    earlier same-release pin exists (a brand-new release line — bump_preflight
    has nothing to diff against, the caller treats that as 'first pin, nothing to
    compare')."""
    new_parsed = parse_pin(_pin_of(new_pin_dir))
    if new_parsed is None:
        return None
    new_rel, new_dev = new_parsed
    best_dir, best_dev = None, None
    new_abs = os.path.abspath(new_pin_dir)
    for d in list_committed_pin_dirs(pins_dir):
        if os.path.abspath(d) == new_abs:
            continue
        parsed = parse_pin(_pin_of(d))
        if parsed is None:
            continue
        rel, dev = parsed
        if rel != new_rel or dev >= new_dev:
            continue
        if best_dev is None or dev > best_dev:
            best_dir, best_dev = d, dev
    return best_dir


def most_recent_pin_dir(pins_dir=PINS_DIR):
    """The committed pin dir with the highest (release, dev) — the 'new' pin when
    none is given. Sorts release lexically then dev numerically."""
    dirs = list_committed_pin_dirs(pins_dir)
    ranked = [(parse_pin(_pin_of(d)), d) for d in dirs]
    ranked = [(p, d) for p, d in ranked if p is not None]
    if not ranked:
        return None
    ranked.sort(key=lambda x: (x[0][0], x[0][1]))
    return ranked[-1][1]


def _run(script, *args):
    return subprocess.run(
        [sys.executable, os.path.join(HERE, script), *args],
        capture_output=True, text=True)


def _coverage_ok(new_pin_dir):
    """Re-check discovered == ok + rejected from the committed drift.rej.json (so
    a hand-edited manifest can't slip past the build-time assertion)."""
    try:
        rej = json.load(open(os.path.join(new_pin_dir, "drift.rej.json")))
    except (OSError, ValueError):
        return False, "drift.rej.json unreadable"
    cov = rej.get("coverage") or {}
    disc, ok, rj = (cov.get("discovered"), cov.get("ok"), cov.get("rejected"))
    if None in (disc, ok, rj):
        return False, "coverage block missing"
    if ok + rj != disc:
        return False, "discovered=%s != ok=%s + rejected=%s" % (disc, ok, rj)
    return True, "discovered=%s == ok=%s + rejected=%s" % (disc, ok, rj)


def new_pin_check(new_pin_dir, old_pin_dir=None):
    new_pin = _pin_of(new_pin_dir)
    if new_pin is None:
        print("FATAL: %s has no readable anchors.json" % new_pin_dir,
              file=sys.stderr)
        return 2
    print("=== new-pin readiness: %s (%s) ===" % (
        os.path.basename(new_pin_dir.rstrip("/")), new_pin))

    # (1) coverage sanity on the new manifest.
    cov_ok, cov_msg = _coverage_ok(new_pin_dir)
    print("\n[1] coverage: %s — %s" % ("OK" if cov_ok else "FAIL", cov_msg))
    if not cov_ok:
        print("\nRESULT: NOT READY — new manifest coverage is broken (silent "
              "anchor loss). Regenerate with make rebuild-pin.")
        return 1

    # (2) summarize the new pin (genuine drift + perf-soft-skip latent no-ops).
    print("\n[2] drift.rej.json summary:")
    s = _run("summarize_rej.py", new_pin_dir)
    sys.stdout.write(s.stdout)
    if s.returncode != 0:
        sys.stderr.write(s.stderr)

    # (3) resolve previous pin + run the bump_preflight gate.
    if old_pin_dir is None:
        old_pin_dir = resolve_previous_pin_dir(new_pin_dir)
    if old_pin_dir is None:
        print("\n[3] bump_preflight: SKIPPED — no earlier same-release committed "
              "pin to diff against (first pin on this release line).")
        print("\nRESULT: READY (first pin) — coverage clean, nothing to diff. "
              "Still bench-validate the pin per the bump playbook.")
        return 0
    old_pin = _pin_of(old_pin_dir)
    print("\n[3] bump_preflight vs previous pin %s (%s):" % (
        os.path.basename(old_pin_dir.rstrip("/")), old_pin))
    pf = _run("bump_preflight.py", old_pin_dir, new_pin_dir)
    sys.stdout.write(pf.stdout)
    if pf.stderr:
        sys.stderr.write(pf.stderr)

    if pf.returncode == 1:
        print("\nRESULT: NOT READY — bump_preflight FAILED (unmitigated HIGH "
              "perf dependent broken). Re-anchor the dependent OR prove no "
              "regression with a canonical A/B before promoting this pin.")
        return 1
    if pf.returncode != 0:
        print("\nRESULT: NOT READY — bump_preflight errored (rc=%d)."
              % pf.returncode)
        return 2
    print("\nRESULT: READY — coverage clean + no unmitigated HIGH dependency "
          "break vs %s. Honor any advisory perf-delta A/B gate above before "
          "promoting." % old_pin)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    old_override = None
    positionals = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--old":
            i += 1
            if i >= len(argv):
                print("--old requires a pin dir argument", file=sys.stderr)
                return 2
            old_override = argv[i]
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        elif a.startswith("-"):
            print("unknown option: %s" % a, file=sys.stderr)
            return 2
        else:
            positionals.append(a)
        i += 1

    if positionals:
        new_pin_dir = positionals[0]
    else:
        new_pin_dir = most_recent_pin_dir()
        if new_pin_dir is None:
            print("FATAL: no committed pin manifests found under %s — run "
                  "make rebuild-pin first." % PINS_DIR, file=sys.stderr)
            return 2
    return new_pin_check(new_pin_dir, old_override)


if __name__ == "__main__":
    sys.exit(main())
