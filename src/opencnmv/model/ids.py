"""Deterministic identifier constructors for CANONICAL_MODEL_V1.

filing_id             cnmv:ifa:<nregaud>          (registro oficial)
variant_id            <filing_id>#<lang>          (stable, never a hash)
variant_version_id    <variant_id>#v<n>
filing_version_id     <filing_id>#nreg:<nreg>
event_id              <filing_id>#evt:<key>
artifact_id           sha256:<hex>
"""

IFA = "cnmv:ifa"
IPP = "cnmv:ipp"


def filing_id(registro: str, family: str = IFA) -> str:
    return f"{family}:{registro}"


def variant_id(filing: str, lang: str) -> str:
    return f"{filing}#{lang}"


def variant_version_id(variant: str, n: int) -> str:
    return f"{variant}#v{n}"


def filing_version_id(filing: str, nreg: str) -> str:
    return f"{filing}#nreg:{nreg}"


def event_id(filing: str, key: str) -> str:
    return f"{filing}#evt:{key}"


def artifact_id(sha256: str) -> str:
    return f"sha256:{sha256}"
