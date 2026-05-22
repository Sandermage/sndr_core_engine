# Security policy

## Reporting a vulnerability

Genesis vLLM Patches is a runtime-patch package — security
disclosures must reach the maintainer privately before going
public.

- **Do NOT** open a GitHub issue for a suspected vulnerability.
- Email **`sander.odessa@gmail.com`** with the details. A
  disclosure is acknowledged within 72 hours and coordinated on
  standard responsible-disclosure timelines.

What to include:

- Reproducer (preset key, vLLM pin, GPU, environment, payload).
- Impact assessment (information disclosure, code execution,
  denial of service, ...).
- Suggested mitigation if you have one.

## Scope

Reports are in scope when they affect the public-core package
(`vllm.sndr_core`), the shipped CLI (`sndr`), or any artefact
under [`tools/`](tools/), [`scripts/`](scripts/), or
[`docs/`](docs/) in this repository.

Out of scope:

- Upstream vLLM bugs reproducible without Genesis — report those
  to <https://github.com/vllm-project/vllm/issues>.
- Hardware-specific kernel issues already documented in
  [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) (the named
  cliffs catalogue).
- Misconfigurations of the operator's own preset that don't
  affect anyone else's installation.

## Supported versions

Genesis pins a specific vLLM commit; security fixes track the
`KNOWN_GOOD_VLLM_PINS` allowlist in
`vllm/sndr_core/detection/guards.py`. Operators running an
unsupported pin should bump to the current pin per
[`docs/RELEASE_POLICY.md`](docs/RELEASE_POLICY.md) before
escalating.

## Public-core stays public

Genesis public core is Apache-2.0 and ships without any license
gate that restricts functionality. Any change that would gate a
public-core feature behind a license check is itself a security-
adjacent issue and falls under this policy.
