"""CANONICAL_MODEL_V1 objects (production implementation).

Conforms to the frozen contract
g1/G1-E-canonical-model-freeze/canonical_model_v1.schema.json.
Field order mirrors the frozen serialization layout.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Lang(str, Enum):
    es = "es"
    en = "en"


class ResolutionMode(str, Enum):
    SUBMITTED_VARIANT = "SUBMITTED_VARIANT"
    FALLBACK_TO_ES = "FALLBACK_TO_ES"


class ScopeStatus(str, Enum):
    BOTH_VARIANTS_REPLACED = "BOTH_VARIANTS_REPLACED"
    ES_ONLY_REPLACED = "ES_ONLY_REPLACED"
    EN_ONLY_REPLACED = "EN_ONLY_REPLACED"
    VARIANT_SCOPE_NOT_OBSERVABLE = "VARIANT_SCOPE_NOT_OBSERVABLE"
    NOT_A_VERSION_TRANSITION = "NOT_A_VERSION_TRANSITION"


class ComponentScope(str, Enum):
    WHOLE_VARIANT_ARTIFACT_SET = "WHOLE_VARIANT_ARTIFACT_SET"
    SOURCE_DESCRIBED = "SOURCE_DESCRIBED"
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
    artifact_id: str
    role: ArtifactRole
    sha256: str
    bytes: Optional[int] = None
    media_type: Optional[str] = None
    source_url: Optional[str] = None
    package_lang_tag: Optional[Lang] = None


class FactKey(BaseModel):
    """Structural fact identity — payload is never part of it."""
    concept: str
    entity: str
    period: str
    dimensions: dict[str, str] = Field(default_factory=dict)
    unit: Optional[str] = None
    language: Optional[Lang] = None


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
    variant_version_id: str
    variant_id: str
    observed: bool
    artifact_set_id: Optional[str] = None
    artifacts: list[Artifact] = Field(default_factory=list)
    created_by_event_id: Optional[str] = None
    supersedes_variant_version_id: Optional[str] = None

    @model_validator(mode="after")
    def _observed_requires_set(self):
        if self.observed and not self.artifact_set_id:
            raise ValueError("observed variant_version needs artifact_set_id")
        return self


class SubmissionVariant(BaseModel):
    variant_id: str
    filing_id: str
    submission_language: Lang
    variant_versions: list[VariantVersion] = Field(default_factory=list)


class ViewResolution(BaseModel):
    requested_ui_language: Lang
    resolved_variant_id: str
    resolution_mode: ResolutionMode


class FilingVersion(BaseModel):
    filing_version_id: str
    source_nreg: Optional[str] = None
    filed_at: Optional[str] = None
    submission_kind: Optional[str] = None


class EventAffects(BaseModel):
    variant_id: Optional[str] = None
    affected_component_scope: ComponentScope = ComponentScope.NOT_IDENTIFIED
    component_description: Optional[str] = None
    before_variant_version_id: Optional[str] = None
    after_variant_version_id: Optional[str] = None
    scope_basis: Optional[str] = None


class VersionEvent(BaseModel):
    event_id: str
    event_date: Optional[str] = None
    event_type: EventType
    source_label: Optional[str] = None
    source_nreg: Optional[str] = None
    evidence_artifact_id: Optional[str] = None
    scope_status: ScopeStatus
    affects: list[EventAffects] = Field(default_factory=list)


class ExtensionMapping(BaseModel):
    pair_id: str
    filing_id: str
    source_variant_id: str
    target_variant_id: str
    source_qname: str
    target_qname: str
    mapping_type: str
    verdict: str
    evidence: list[str] = Field(default_factory=list)


class IssuerRef(BaseModel):
    denomination: str
    nif: Optional[str] = None
    lei: Optional[str] = None


class CanonicalFiling(BaseModel):
    model_config = ConfigDict(extra="allow")

    filing_id: str
    issuer: IssuerRef
    registro_oficial: str
    family: str
    period_end: str
    filing_versions: list[FilingVersion] = Field(default_factory=list)
    submission_variants: list[SubmissionVariant] = Field(default_factory=list)
    view_resolutions: list[ViewResolution] = Field(default_factory=list)
    version_events: list[VersionEvent] = Field(default_factory=list)
    extension_mappings: list[ExtensionMapping] = Field(default_factory=list)
