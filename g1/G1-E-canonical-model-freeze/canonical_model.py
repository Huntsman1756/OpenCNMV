# G1-E — CANONICAL MODEL V1 (frozen).
#
# Pydantic schema for the canonical layer. Frozen invariants (enforced by
# g1e_verify.py over serialized fixtures):
#
#   I1  requested_ui_language != submission variant (fallback is a
#       resolution, not a variant)
#   I2  submission_variant identity != content hash — stable across versions
#   I3  variant_version identity == content state (artifact_set_id)
#   I4  no silent variant merge; no variant designated "truth"
#   I5  fact structural identity != fact payload
#   I6  no concept+period dedup (entity/period/dims/unit/lang are identity)
#   I7  version_event may affect 0..N variants and a subset of artifact
#       roles; source_nreg may be null
#   I8  shared registry/date never implies BOTH_VARIANTS_REPLACED
#   I9  only PROVEN extension mappings may rewrite cross-variant identity
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Lang(str, Enum):
    es = "es"
    en = "en"


class ResolutionMode(str, Enum):
    SUBMITTED_VARIANT = "SUBMITTED_VARIANT"
    FALLBACK_TO_ES = "FALLBACK_TO_ES"


class ScopeStatus(str, Enum):
    """Preregistered lifecycle scope vocabulary (G1-D)."""
    BOTH_VARIANTS_REPLACED = "BOTH_VARIANTS_REPLACED"
    ES_ONLY_REPLACED = "ES_ONLY_REPLACED"
    EN_ONLY_REPLACED = "EN_ONLY_REPLACED"
    VARIANT_SCOPE_NOT_OBSERVABLE = "VARIANT_SCOPE_NOT_OBSERVABLE"
    NOT_A_VERSION_TRANSITION = "NOT_A_VERSION_TRANSITION"


class ComponentScope(str, Enum):
    WHOLE_VARIANT_ARTIFACT_SET = "WHOLE_VARIANT_ARTIFACT_SET"
    SOURCE_DESCRIBED = "SOURCE_DESCRIBED"          # cert names a component set
    NOT_IDENTIFIED = "NOT_IDENTIFIED"


class EventType(str, Enum):
    CERTIFICATE = "CERTIFICATE"
    SUBSTITUTION = "SUBSTITUTION"
    OTHER_SUPPLEMENTARY = "OTHER_SUPPLEMENTARY"
    ORIGINAL_SUBMISSION = "ORIGINAL_SUBMISSION"


class ArtifactRole(str, Enum):
    ESEF_PACKAGE_ZIP_XBRL = "ESEF_PACKAGE_ZIP_XBRL"
    IXBRL_CONSOLIDATED = "IXBRL_CONSOLIDATED"
    IXBRL_INDIVIDUAL = "IXBRL_INDIVIDUAL"
    ESEF_COVER = "ESEF_COVER"
    EVENT_DOCUMENT = "EVENT_DOCUMENT"
    INFADICIONIFA_PAGE = "INFADICIONIFA_PAGE"
    SEARCH_RESULTS_PAGE = "SEARCH_RESULTS_PAGE"


class Artifact(BaseModel):
    artifact_id: str                     # sha256:<hex>
    role: ArtifactRole
    sha256: str
    bytes: Optional[int] = None
    media_type: Optional[str] = None
    source_url: Optional[str] = None
    package_lang_tag: Optional[Lang] = None


class FactKey(BaseModel):
    """I5/I6: structural identity — payload is NOT part of it."""
    concept: str                         # QName ns#local
    entity: str                          # scheme|LEI
    period: str
    dimensions: dict[str, str] = Field(default_factory=dict)
    unit: Optional[str] = None
    language: Optional[Lang] = None      # semantic when applicable


class FactPayload(BaseModel):
    value: Optional[str] = None
    xvalue: Optional[str] = None
    decimals: Optional[str] = None
    is_nil: bool = False
    value_sha256: Optional[str] = None


class Fact(BaseModel):
    fact_id: str
    variant_version_id: str
    key: FactKey
    payload: FactPayload


class VariantVersion(BaseModel):
    """I3: the content state of one variant. artifact_set_id identifies the
    version's content, never the variant itself (I2)."""
    variant_version_id: str              # <variant_id>#v<n>
    variant_id: str
    observed: bool                       # False = superseded, bytes not held
    artifact_set_id: Optional[str] = None   # required iff observed
    artifacts: list[Artifact] = Field(default_factory=list)
    created_by_event_id: Optional[str] = None
    supersedes_variant_version_id: Optional[str] = None

    @model_validator(mode="after")
    def _observed_requires_set(self):
        if self.observed and not self.artifact_set_id:
            raise ValueError("observed variant_version needs artifact_set_id")
        return self


class SubmissionVariant(BaseModel):
    """I2: stable identity = (filing_id, submission_language)."""
    variant_id: str                      # <filing_id>#<lang>
    filing_id: str
    submission_language: Lang
    variant_versions: list[VariantVersion] = Field(default_factory=list)


class ViewResolution(BaseModel):
    """I1: what a UI view resolved to — an observation, not an identity."""
    requested_ui_language: Lang
    resolved_variant_id: str
    resolution_mode: ResolutionMode


class FilingVersion(BaseModel):
    """A source submission record, kept when CNMV exposes one."""
    filing_version_id: str               # <filing_id>#nreg:<nreg>
    source_nreg: Optional[str] = None
    filed_at: Optional[str] = None
    submission_kind: Optional[str] = None


class EventAffects(BaseModel):
    """I7: an event may point below variant granularity."""
    variant_id: Optional[str] = None
    affected_component_scope: ComponentScope = ComponentScope.NOT_IDENTIFIED
    component_description: Optional[str] = None
    before_variant_version_id: Optional[str] = None
    after_variant_version_id: Optional[str] = None
    scope_basis: Optional[str] = None    # e.g. official certificate artifact


class VersionEvent(BaseModel):
    event_id: str
    event_date: Optional[str] = None
    event_type: EventType
    source_label: Optional[str] = None   # UI label — evidence, not authority
    source_nreg: Optional[str] = None    # I7: may be null (TEF 13/03 event)
    evidence_artifact_id: Optional[str] = None
    scope_status: ScopeStatus
    affects: list[EventAffects] = Field(default_factory=list)


class ExtensionMapping(BaseModel):
    """I9: cross-variant identity rewrite evidence (G1-C)."""
    pair_id: str
    filing_id: str
    source_variant_id: str
    target_variant_id: str
    source_qname: str
    target_qname: str
    mapping_type: str                    # EXTENSION_CONCEPT | DIMENSION_MEMBER
    verdict: str                         # PROVEN_EQUIVALENT | AMBIGUOUS | ...
    evidence: list[str] = Field(default_factory=list)


class IssuerRef(BaseModel):
    denomination: str
    nif: Optional[str] = None
    lei: Optional[str] = None


class CanonicalFiling(BaseModel):
    filing_id: str                       # cnmv:ifa:<nregaud>
    issuer: IssuerRef
    registro_oficial: str
    family: str                          # ESEF_IFA | IPP | ...
    period_end: str
    filing_versions: list[FilingVersion] = Field(default_factory=list)
    submission_variants: list[SubmissionVariant] = Field(default_factory=list)
    view_resolutions: list[ViewResolution] = Field(default_factory=list)
    version_events: list[VersionEvent] = Field(default_factory=list)
    extension_mappings: list[ExtensionMapping] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_truth_designation(self):
        # I4: schema deliberately has no primary/truth/preferred flag —
        # this validator documents the invariant and guards regression.
        assert not hasattr(self, "primary_variant_id")
        return self


CANONICAL_SCHEMA_JSON = CanonicalFiling.model_json_schema()
