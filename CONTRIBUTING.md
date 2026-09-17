# Contributing

Read `AGENTS.md` and the applicable gate contract before changing behavior. Preserve
CNMV original bytes, input hashes, the frozen canonical schema, and gate evidence.
Development checks do not execute gates, change verdicts, or authorize a new phase.

## Dependency decisions

- **ADOPT setuptools** (MIT) with its standard PEP 517 backend and `src` package
  discovery; **ADOPT build** (MIT) as the build frontend. No custom build system.
- **ADOPT unittest** (Python standard library, PSF license), **ADOPT Ruff** (MIT),
  and **ADOPT mypy** (MIT). Requests/jsonschema stubs are development-only
  (typeshed, Apache-2.0). No test framework dependency or coverage claim.
- **ADOPT uv** (MIT OR Apache-2.0) only to resolve a complete, cross-platform
  development requirements lock; installation uses pip (MIT). No custom resolver.
- **ADOPT Pydantic** (MIT) as a mandatory runtime dependency: the existing
  canonical model and frozen JSON Schema remain unchanged. **ADOPT Requests**
  (Apache-2.0) for the existing CNMV source adapters.
- **WRAP Arelle** (`arelle-release==2.44.0`, Apache-2.0) through the existing
  lazy-import adapter, exposed as the optional `xbrl` extra. Never relax its exact
  pin without the required corpus revalidation. No XBRL parser is implemented here.
- **ADOPT jsonschema** (MIT) explicitly in `dev`, independent of Arelle, for
  frozen-schema validation. Its optional format dependencies are not requested.

These decisions follow inspection of production imports, distribution dependency
metadata, the setuptools configuration documentation, uv's compile documentation,
and the G2-A verifier/builder. Existing installed versions of Pydantic, Requests,
Arelle, jsonschema, setuptools, build, and Ruff were retained. Other direct tools
are exact-pinned from available distributions. Transitive dependencies have their
own licenses; this is not a full license or legal audit. OpenCNMV's MIT license
does not relicense upstream software, CNMV artefacts, or taxonomy packages.

## Isolated Python 3.11 setup

Run from the repository root in a fresh environment; never install globally.
For Windows PowerShell, verify the parent first:

```powershell
Test-Path -LiteralPath .
py -3.11 -m venv .venv-audit
.\.venv-audit\Scripts\Activate.ps1
```

On Linux:

```sh
test -d .
python3.11 -m venv .venv-audit
. .venv-audit/bin/activate
```

Then, on either platform:

```sh
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e ".[dev,xbrl]"
python -B -m unittest discover -s tests -v
python -m ruff check src tests
python -m mypy src tests
python -m build --no-isolation
python -m pip check
```

The lock includes runtime, XBRL, development, installer, and build dependencies
with exact transitive pins and platform/Python markers. It is a version lock,
not an artefact-hash lock; installation still needs an index or prepared wheel
cache. Offline reproducibility of frozen inputs is distinct from dependency
installation and reproducibility of wheel archives. Python 3.11 is the CI
baseline; newer interpreters are not certified by this matrix.

For a core-only installation, use `python -m pip install .`; use
`python -m pip install ".[xbrl]"` when parsing XBRL. The contributor lock installs
Arelle to check dependency compatibility, but the regression tests do not parse
the full corpus or run the Arelle shim self-test.

## Checks and their limits

`tests/test_frozen_core.py` uses the existing G2-A builder functions in isolated
Python subprocesses, not either gate script's `main`. It verifies pinned inputs,
builds four fixtures in memory twice, compares their serialized bytes with the
preserved fixtures, and validates the frozen schema and runtime Pydantic model.
The builder's socket and gate-import guards stay confined to subprocesses.
Missing or altered evidence is a failure, not a skipped test. The existing TEF
fixture is a lifecycle regression control, not an expansion of corpus scope.
No gate results, manifests, fixtures, or other evidence are regenerated.

Ruff checks `E4`, `E7`, `E9`, and `F` rules in `src` and `tests`; this is not a
formatting or exhaustive style check. Mypy checks those same directories with
`check_untyped_defs`, but is deliberately not strict: unannotated boundaries and
dynamic dictionary payloads remain. Arelle internals are excluded from traversal
because they are upstream code, not OpenCNMV's typing contract. Historical gate
scripts and the dynamically loaded builder are not static-analysis targets.
There is no numerical coverage threshold or claim of full semantic verification.
Do not suppress library findings merely to turn CI green.

CI runs Linux and Windows with Python 3.11, builds an sdist and wheel, reinstalls
the wheel, reruns tests against that installation, and runs `pip check`. Checkout
and setup-python action SHAs were verified using `git ls-remote` against their
upstream v6 tags; changes to those pins need the same review. CI is not a gate.

## Updating the lock

After intentionally reviewing direct pins in `pyproject.toml`, use the pinned
resolver from the environment:

```sh
python -m uv pip compile pyproject.toml --extra dev --extra xbrl --python-version 3.11 --universal --no-header --no-annotate --no-emit-index-url
```

The command prints the complete lock to stdout. Replace `requirements-dev.lock`
with that output using the approved file-writing tool, without shell redirection.
Review the diff, reinstall in a fresh environment, and rerun all checks. Preserve
Arelle 2.44.0. Dependency changes do not authorize altering frozen evidence.
The coordinating session owns any required `docs/STATUS.md` update.
