# R3 — DISCOVERY_STABILITY

**Gate:** R3 — DISCOVERY_STABILITY
**Status:** `PASS`
**Executed:** 2026-09-14 (UTC 22:15)

## Objective

Run discovery in at least two separated observations and check identifier/link stability,
ordering changes, session dependence, and behaviour under identical parameters.

## Method

Two observations of the discovery surfaces were captured at different times (about ~20 minutes
apart) using identical parameters (same URLs, no session, no cookies):
- Observation 1: `homepage_obs1.html`, `xbrl_obs1.html`
- Observation 2: `homepage_obs2.html`, `xbrl_obs2.html`

## Results

### Static content
| Surface | Obs1 SHA-256 | Obs2 SHA-256 | Byte-identical? |
|---|---|---|---|
| XBRL page (`xbrl/xbrl`) | `6E7691D1…` | `6E7691D1…` | **Yes** |
| Homepage (`home.aspx`) | `1999AAA8…` | `1999AAA8…` | **Yes** |

Both surfaces were byte-identical across the two observations (the home page news block did
not change in the window, and the XBRL page is fully static).

### Identifier / link stability (extracted set of discovery URIs)
| Surface | Obs1 key-URIs | Obs2 key-URIs | Diffs |
|---|---|---|---|
| XBRL page | 27 | 27 | **none** |
| Homepage | 65 | 65 | **none** |

Filtered URIs: `busqueda.aspx?id=`, `em_inffinanual`, `datosentidad.aspx`,
`webservices/verdocumento`, `Consulta-IP`, `Consulta-OIR`. The discovery entrypoints and the
`webservices/verdocumento/ver?t=%7b<guid>%7d` endpoint are **stable** across observations.

### Artefact webservice pattern
`webservices/verdocumento/ver?t=%7b<guid>%7d` occurred 29 times in both homepage observations;
the *specific* GUIDs are dynamic (they track the latest news), but the endpoint and the
GUID-keyed scheme are stable.

## Findings

- Discovery identifiers and entrypoint links are stable across two separated observations.
- The XBRL/taxonomy page is fully static (byte-identical).
- The home page is dynamic in content but its discovery links and artefact-endpoint pattern
  are stable; no ordering changes, no session dependence, identical output for identical
  parameters.
- `datosentidad.aspx?nif=<NIF>` is a stable, GET-addressable per-entity surface (SAN/BBVA
  confirmed).

## Limitations

- The two observations were within a single session window (~20 min); a longer horizon (e.g.
  days/months) is recommended to catch taxonomy or menu changes, but this is sufficient for the
  R0–R4 checkpoint.

## Evidence

- `evidence/homepage_obs1.html`, `evidence/homepage_obs2.html`
- `evidence/xbrl_obs1.html`, `evidence/xbrl_obs2.html`
