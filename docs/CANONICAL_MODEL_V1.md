# CANONICAL_MODEL_V1 — frozen at G1-E

Machine-readable schema: `g1/G1-E-canonical-model-freeze/canonical_model.py`
(Pydantic) → `canonical_model_v1.schema.json` (exported JSON Schema).
Fixtures: `g1/G1-E-canonical-model-freeze/fixtures/*.json`, all rebuilt
deterministically from preserved G1 evidence.

## Entities

```text
filing                     identity = registro oficial / nregaud
  filing_id                cnmv:ifa:<nregaud>
  issuer                   denomination + NIF + LEI
  family                   ESEF_IFA | IPP | ...
  period_end

├─ filing_version          a source submission record, when CNMV exposes one
│    source_nreg           nullable
│    filed_at
│    submission_kind
│
├─ submission_variant      STABLE identity — never a content hash
│    variant_id            <filing_id>#<submission_language>
│    submission_language   es | en
│
│   └─ variant_version     content state of that variant
│        variant_version_id  <variant_id>#v<n>
│        artifact_set_id     hash of the served artifact set (content
│                            identity — changes when the variant changes)
│        artifacts[]
│        facts[]
│        created_by_event_id
│        supersedes_variant_version_id
│        observed            false = superseded state, bytes not held
│
├─ view_resolution         observation record, not identity
│    requested_ui_language es | en
│    resolved_variant_id
│    resolution_mode       SUBMITTED_VARIANT | FALLBACK_TO_ES
│
└─ version_event
     event_date, event_type, source_label (evidence, not authority)
     source_nreg           nullable — a version transition may exist
                           without an exposed nreg (TEF 13/03/2025)
     evidence_artifact_id
     scope_status          BOTH_VARIANTS_REPLACED | ES_ONLY_REPLACED |
                           EN_ONLY_REPLACED | VARIANT_SCOPE_NOT_OBSERVABLE |
                           NOT_A_VERSION_TRANSITION

     └─ affects[]           may point below variant granularity
          variant_id
          affected_component_scope
            WHOLE_VARIANT_ARTIFACT_SET | SOURCE_DESCRIBED | NOT_IDENTIFIED
          component_description
          before_variant_version_id / after_variant_version_id
          scope_basis        e.g. official certificate artifact sha256

extension_mapping          G1-C cross-variant identity evidence
  pair_id, verdict, evidence — only PROVEN_EQUIVALENT may rewrite identity
```

## Frozen invariants

```text
I1  requested_ui_language != submission variant
    (IBE: lang=en resolves to #es via FALLBACK_TO_ES — 1 variant, 2 views)
I2  submission_variant identity != content hash — stable across versions
I3  variant_version identity == content state (artifact_set_id)
I4  no silent variant merge; no variant designated "truth"
I5  fact structural identity != fact payload
I6  no concept+period dedup — entity/period/dimensions/unit/language are
    part of fact identity
I7  version_event may affect 0..N variants and a subset of artifact roles;
    source_nreg may be null
I8  shared registry/date never implies BOTH_VARIANTS_REPLACED
I9  only PROVEN extension mappings rewrite cross-variant identity;
    AMBIGUOUS/CONFLICT/UNMATCHED never merge
```

## Migration G0 → V1

- R6/R13 `source_registration_no` → `filing.registro_oficial`; per-submission
  `nreg` → `filing_version.source_nreg` / `version_event.source_nreg`.
- R13 `revision_event` (CERTIFICATE/SUBSTITUTION) → `version_event` with
  `event_type`; `creates_version_transition` semantics absorbed by
  `scope_status`/`affects`.
- G0 artifacts attach to `variant_version` (ESEF) or `filing_version`
  (IPP — single-variant family, one implicit variant may be used).
- `variant_artifact_set_id` (G1-B) → `variant_version.artifact_set_id`
  (content identity, not variant identity).

## Key evidence anchors

- `ibe_fy2024.json` — I1 (fallback, no phantom variant).
- `bbva_fy2024.json` — I5 (Equity +98M/−98M `DIVERGENT_SUBMISSION_FACT`).
- `san_fy2024.json` — I9 (PROVEN mapping example; 12 non-proven unmerged).
- `tef_20484.json` — I2/I7/I8: `#en` has v1 (unobserved) → v2 (observed)
  created by the 13/03 `EN_ONLY_REPLACED` event (`source_nreg` null,
  component `SOURCE_DESCRIBED`); `#es` has a single version; the 28/02
  event remains `VARIANT_SCOPE_NOT_OBSERVABLE`.
