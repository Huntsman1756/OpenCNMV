# Security Policy

## Scope

OpenCNMV is a data-integrity pipeline: it downloads public filings from the
official CNMV website, preserves the original bytes, and parses XBRL offline
with a pinned Arelle version. There is no service, account system, or
credential store.

Relevant security concerns for this project are:

- integrity or authenticity of downloaded artefacts and pinned taxonomy
  packages (sha256-pinned; report mismatches),
- vulnerabilities in the source adapters or the Arelle adapter
  (`src/opencnmv/`),
- accidental publication of credentials or personal information in commits.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's
["Report a vulnerability"](https://github.com/Huntsman1756/OpenCNMV/security/advisories/new)
feature (Security Advisories). Do not open a public issue for a
vulnerability.

If private reporting is unavailable, open an issue describing the affected
component without including exploit details or sensitive data.

## Supported versions

Only the `main` branch is maintained. The project is pre-1.0; there are no
supported release lines.
