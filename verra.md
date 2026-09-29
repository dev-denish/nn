# Carbon Project Spatial Screening — Build Plan (MVP)

Status: overnight build 2026-09-28, branch `feature/carbon-registry-screening`
(worktree `.claude/worktrees/feature+carbon-registry-screening`). Not merged, not pushed.

Source brief: user-pasted "Global Carbon Project Screening Platform" spec (PRD/TRD/UX/schema).
This document records how that spec is mapped onto the EXISTING dMRV platform, which
decisions were made autonomously overnight, and which items are deliberately GATED
for human review.

## 0. Core product rules (non-negotiable, from the brief)

1. Three separated layers: **Data** (what the source says) → **Spatial analysis**
   (what geometry mathematically shows) → **Screening interpretation** (what needs review).
2. Never output "eligible"/"not eligible". Finding categories are exactly:
   `CONFIRMED_OVERLAP`, `POTENTIAL_ISSUE`, `NO_ISSUE_DETECTED`, `INSUFFICIENT_DATA`.
3. Never hide uncertainty. Every run stores and displays a **coverage statement**
   (projects screened, with usable boundaries, without boundaries, registries enabled,
   data last-checked date). "No overlap" is always phrased "No overlap detected among N
   projects with usable boundaries in the selected screening dataset."
4. Every finding carries evidence: source, source URL, source type, retrieved date,
   source version, boundary version, boundary confidence.
5. Registry data is versioned and immutable: boundaries/metadata are never overwritten;
   a change creates a new version and a `registry_data_change` row.
6. Uploaded boundaries are commercially sensitive: private to the uploader by default.

## 1. Stack mapping (spec → existing platform)

| Spec | Built as | Why |
|---|---|---|
| Next.js + Tailwind + MapLibre | Existing React 18 + Vite app, existing CSS conventions, existing map stack | One app, one auth, one design system; no second frontend |
| Celery/Dramatiq | Existing arq worker + `job` table (progress already supported) | Already deployed |
| S3 | Existing storage abstraction (`app/services/ingestion/storage.py`) | Already S3-compatible-ready |
| Shapely/pyproj | **PostGIS** for all geometry (validation, MakeValid, transform, area, intersection) | Neither lib is installed; PostGIS already does all of it |
| OpenSearch | Postgres ILIKE / full-text | Spec says start here |
| Terraform/AWS | Out of scope | Infra decision, not overnight |

## 2. Schema (one Alembic migration, revision `crs_0001_registry_screening`)

NOTE migration numbering: `feature/eligibility-prescreening` already owns 0035–0044 on its
branch. This branch uses revision id `crs_0001_registry_screening` with
`down_revision = "0034_user_sessions_valid_from"` so the id can never collide; whichever
branch merges second must rebase its `down_revision` (known, documented collision class —
see 2026-09-11 CDSE merge). DEVIATION: originally spec'd as `crs_0001_carbon_registry_screening`
(34 chars) — shortened to `crs_0001_registry_screening` (27 chars) after `alembic upgrade head`
against the isolated test DB failed with `StringDataRightTruncation`: `alembic_version.version_num`
is `VARCHAR(32)`, confirmed by every existing revision id already being <=30 chars.

Tables (singular names, matching codebase convention):

- `registry` — code (VERRA, GS, ACR, CAR, ART, PLANVIVO, CERCARBONO, GCC, PURO, ISOMETRIC,
  MANUAL), name, website, api_available, data_access_type, active. Seeded.
- `registry_data_source` — the **license registry** (brief Problem 12): name, url, license,
  attribution, commercial_use, redistribution_allowed, derived_data_allowed, notes, review_status
  (`APPROVED`/`CONDITIONAL`/`BLOCKED`/`UNREVIEWED`). Ingestion from a BLOCKED source is refused.
- `registry_source_snapshot` — raw file kept for reproducibility: data_source_id, storage_uri,
  sha256, original_filename, retrieved_at, processor_version, row/feature counts.
- `registry_project` — registry_id, external_project_id, name, description, country_code,
  region, status, project_type, sector, developer, validation_body, verification_body,
  start_date, crediting_start, crediting_end, reported_area_ha, ingestion_state,
  registry_metadata JSONB (registry-specific fields), last_seen_at, last_verified_at.
  UNIQUE(registry_id, external_project_id).
- `registry_project_version` — immutable metadata snapshots: project_id, version_number,
  snapshot_id, metadata JSONB, metadata_hash, valid_from, valid_to, retrieved_at.
- `registry_methodology` (+ version) and `registry_project_methodology` (effective_from/to).
- `registry_boundary` — project_id, version, boundary_type (`POLYGON`/`POINT`),
  geom geometry(Geometry,4326) (MultiPolygon or Point), geom_simplified, area_ha (geodesic),
  source_type (`REGISTRY_FILE`/`PROJECT_DOCUMENT`/`DIGITIZED_MAP`/`APPROXIMATE_POINT`/`MANUAL`),
  source_url, source_document, confidence, snapshot_id, valid_from, valid_to (NULL = current),
  retrieved_at, geometry_hash. GiST on geom and on `geom::geography`. Partial unique index:
  one current (valid_to IS NULL) boundary per project.
- `registry_document`, `registry_evidence`, `registry_data_change` — per brief §5.
- `world_admin_area` — global admin-0/admin-1 polygons for country/region derivation
  (existing admin boundaries are India-only LGD). Loaded by script from Natural Earth
  (public domain). Screening works without it (country = null + warning).
- `screening_submission` — owner_id (FK app_user), name, original_filename, storage_uri,
  geom (MultiPolygon 4326, made-valid), original_geom, area_ha, bbox, centroid, country_code,
  admin1_name, validation_report JSONB, created_at, deleted_at.
- `screening_run` — submission_id, job_id, status, config JSONB (registries, radius_km,
  statuses), started_at, completed_at, error_message, summary JSONB, coverage JSONB,
  analysis_version, dataset_snapshot_at.
- `screening_result` — run_id, project_id, boundary_id (the exact version used), relationship,
  distance_m, bearing_deg, intersection_area_ha, intersection_pct_of_submission,
  intersection_pct_of_project, shared_boundary_m, boundary_confidence, finding_category,
  finding_reason, intersection_geom, evidence JSONB (frozen copy at run time).

Boundary confidence enum (brief §2.11 — transparent categories, no 0-100 score):
`OFFICIAL_DIGITAL` (HIGH), `OFFICIAL_DOCUMENT` (MEDIUM), `DERIVED`, `DIGITIZED` (LOW),
`APPROXIMATE` (VERY LOW, point only), `UNKNOWN`.

Ingestion state enum: `DISCOVERED`, `METADATA_FETCHED`, `DOCUMENTS_FETCHED`,
`BOUNDARY_FOUND`, `BOUNDARY_VALIDATED`, `NORMALIZED`, `PUBLISHED`, `BOUNDARY_NOT_FOUND`.

## 3. Spatial engine (PostGIS only)

- Canonical storage EPSG:4326. **All areas/distances use `geography`** (geodesic on WGS84
  spheroid) — globally correct, no per-zone projection choice needed. ha = m²/10 000.
- Candidate search: `ST_DWithin(b.geom::geography, :sub::geography, :radius_m)` backed by the
  GiST geography index → exact ops only on candidates. Never a global scan.
- **Relationship predicates are geodesic, not planar** (review-fix, 2026-09-28 — see §11):
  `ST_Intersects(geog, geog)` and `ST_Covers(geog, geog)` (both ways), evaluated in this order:
  `CONTAINS` (submission covers project) / `WITHIN` (project covers submission) /
  `INTERSECTS` (geodesic intersection, area above sliver tolerance) / `TOUCHES` (geodesic
  intersection, area at/below sliver tolerance — geography has no `ST_Touches`, so a real
  shared-edge touch and a digitization-noise sliver are the same case: "intersects, but the
  overlap is negligible") / `NEARBY` (within radius, no geodesic intersection at all).
  Planar predicates on the raw `geom` column disagreed with the (already geodesic)
  distance/area — reproduced live: an antimeridian project ~22 km away came out
  WITHIN/100 %/CONFIRMED_OVERLAP; a true antimeridian overlap came out NEARBY/distance 0; a
  long-edge high-latitude box that truly contained a project came out NEARBY (the geodesic top
  edge bulges north of the planar latitude line).
- **Antimeridian-crossing intersection geometry/area**: if either geometry's planar x-extent
  is > 180° (crosses the dateline), both are normalised with `ST_ShiftLongitude` before
  `ST_Intersection` (a geometry, not geography, operation — no geodesic overload exists), then
  the result is shifted back once more (round-trips exactly, live-verified) before storage/
  display, so the stored `intersection_geom` is always valid −180..180 GeoJSON.
- **Consistency guard**: if the relationship implies an area overlap (CONTAINS/WITHIN/
  INTERSECTS) but geodesic distance is still > 1 m, or distance is 0 but there is no geodesic
  intersection at all, the candidate is flagged `geometric_inconsistency` by the spatial engine;
  `app.domain.screening_interpretation.classify` (not the engine) turns that into
  `POTENTIAL_ISSUE` with reason `"geometric inconsistency - manual review"` — kept in the
  interpretation layer, per §0.1's own three-layers rule.
- Metrics: intersection area ha (geography), % of submission, % of project, min distance m,
  **geodesic** centroid bearing deg (`ST_Azimuth` on `::geography` casts, not planar geometry —
  review-fix), shared boundary length m (for TOUCHES/INTERSECTS, computed on the same
  antimeridian-safe geometries as the intersection).
- **Sliver tolerance (review-fix, spec error correction): AND, not OR.** An intersection is a
  sliver (reported as `TOUCHES`, raw value retained) only if it is BOTH < 0.01 ha AND < 0.01 %
  of the smaller of the two areas. (Originally spec'd as OR — that wrongly downgraded a 60 ha
  overlap between two 1.2M ha polygons, 0.005 % of the smaller area but nowhere near 0.01 ha, to
  a "touch". Regression cases: 60 ha overlap of two 1.2M ha polygons → `INTERSECTS`; 0.0012 ha
  overlap of a 0.0024 ha project → `INTERSECTS` (tiny absolute value, but ~50 % of the project's
  own tiny area, so not tiny relatively either — only ONE condition holds, not both).) Constant
  named and documented; shown in report methodology section.
- Point-only projects (`APPROXIMATE`): distance only, never an area overlap.
- Projects with no boundary in the submission's country: counted in coverage and listed as
  `INSUFFICIENT_DATA` (country-level match), never silently dropped.
- **Licence gating (D2, review-fix)**: a candidate's boundary is joined to its
  `registry_data_source`; only `APPROVED`/`CONDITIONAL` sources are used. `UNREVIEWED`/`BLOCKED`
  sources are excluded — a QUERY-TIME join, not a copy, so a source later marked `BLOCKED` is
  excluded from every future run automatically. Excluded-project count surfaced as
  `projects_excluded_pending_licence_review` in the run's coverage.
- **Search-radius display (G7, review-fix)**: buffers the submission's actual polygon edge
  (`ST_Buffer(geom::geography, radius_m)`), not its centroid — matches the real search
  (`ST_DWithin` from the edge) exactly; the old centroid buffer visually mismatched the real
  search area for anything but a near-circular submission.

## 4. Screening interpretation (separate module, pure function over spatial results)

| Condition | Finding |
|---|---|
| Spatial engine flagged `geometric_inconsistency` (review-fix, §3) | `POTENTIAL_ISSUE`, reason exactly `"geometric inconsistency - manual review"` — checked FIRST, before every rule below |
| Area overlap with `OFFICIAL_DIGITAL`/`OFFICIAL_DOCUMENT` boundary | `CONFIRMED_OVERLAP` (spatial overlap confirmed against an official boundary — still a screening finding, not a registry decision) |
| Area overlap with `DERIVED`/`DIGITIZED`/`UNKNOWN` boundary | `POTENTIAL_ISSUE` |
| Point-only project within radius | `POTENTIAL_ISSUE` (location approximate) |
| TOUCHES / NEARBY polygon | `NO_ISSUE_DETECTED` (listed for context) |
| Same-country project with no boundary | `INSUFFICIENT_DATA` |

Run-level headline: the most severe category present, with the coverage statement.
Methodology-rule screening (brief Phase 7) is NOT built.

Coverage statement (review-fix, §0.3 enforcement corrected): the "no overlap" sentence's project
count is `projects_with_usable_boundaries` (was wrongly `projects_screened`, the bigger TOTAL
including no-boundary rows — overstated how many projects were actually spatially checked, and
could say "no overlap" while INSUFFICIENT_DATA rows existed). Whenever M>0 projects in the
dataset have no usable boundary, a coverage `warnings` entry is ALWAYS added (independent of
whether the run also found a real overlap/issue) — previously this was only implicit in a raw
count field, never surfaced as an actual warning banner. `RunOut.coverage`'s own `warnings` field
was also being silently dropped by the `CoverageStatement` DTO (not declared, Pydantic ignores
unknown fields) — the exports (which read the raw JSONB) always saw it; the API response never
did until this field was added.

## 5. Upload (submission) pipeline

Formats: GeoJSON, KML, KMZ, SHP-ZIP (reuse existing parsers + existing ZIP-bomb guard),
**plus new** GeoPackage (stdlib sqlite3 + GPKG binary header → WKB → PostGIS) and WKT (text).
Non-WGS84 input: SHP `.prj` / GPKG `srs_id` → EPSG → `ST_Transform` in PostGIS; unknown CRS
without a user-supplied EPSG is rejected with a clear message.
Validation report (checks list, each PASS/WARN/FAIL + message): readable, polygon present
(points/lines rejected), non-empty, coordinate range, CRS, validity (ST_IsValidReason per
feature), self-intersection feature index, duplicate features, internal overlaps, multipart,
vertex-count complexity limit, area. Invalid geometry is repaired with ST_MakeValid for the
analysis geometry; the original is kept. Limits: file size (existing setting), 50 000 total
vertices, 1 000 features.

## 6. Registry ingestion (adapters)

`app/services/registry_adapters/` with a `RegistryAdapter` protocol:
`discover_projects / fetch_metadata / fetch_documents / fetch_boundaries / normalize / validate`.
Built tonight:
- `manual` adapter — admin uploads (a) normalized project-metadata CSV, (b) a boundary file
  per project with source_type/confidence/source_url/retrieved_at/data_source. Snapshot +
  sha256 stored, version rows created, changes logged.
- `verra` adapter — **file-based only**: parses a Verra registry search-results CSV export
  that a human downloaded from registry.verra.org. Metadata only (no boundaries: Verra does
  not publish a bulk boundary dataset; boundaries live in per-project documents).

## 7. GATED — not built tonight, needs a human decision

1. **Automated/live registry fetching (any registry)**: scraping/API use of registry.verra.org
   etc. requires a terms-of-use + licensing review first (brief Problem 12; same discipline as
   the eligibility licensing review wave). Adapters have the hooks; no network fetcher ships.
2. **Bulk boundary acquisition** (extracting KML/SHP from project documents, digitizing maps):
   operational/data-team process + licensing question, not code.
3. **Third-party boundary databases** (BeZero etc.): commercial — do not ingest.
4. **Berkeley VROD import** (CC BY 4.0, 6 registries): good next adapter, needs `openpyxl`
   (new dependency → supply-chain review) or a CSV conversion step.
5. **Organization/tenant sharing** of submissions: platform has no org/tenant model yet.
6. **Methodology rule engine**, **AI document reading**: brief itself says later.
7. **Malware scanning** of uploads: needs ClamAV sidecar decision.

## 8. API contract (prefix `/api/v1`)

Screening (review-fix, D5: **creation** now requires `SCREENING_ROLES = {Administrator,
GIS Associate, Analyst}` — was "any authenticated user"; Verifier/Viewer may still read their
OWN past submissions/runs unchanged. Policy default pending human confirmation. Object-level:
owner or Administrator only, everywhere):
- `POST /screening/submissions` multipart: `file`, `name`, optional `epsg` → `SubmissionOut`
  (incl. `validation_report`, `area_ha`, `bbox`, `centroid`, `country_code`, `admin1_name`).
  Max upload size is now `max_screening_upload_bytes` (20 MB default, review-fix S3), not the
  generic 2 GiB cap.
- `GET /screening/submissions` (own; admin sees all) · `GET /screening/submissions/{id}` ·
  `GET /screening/submissions/{id}/geojson` · `DELETE /screening/submissions/{id}` (soft —
  review-fix S5: also deletes the stored file; a soft-deleted submission's runs 404 everywhere,
  including exports).
- `POST /screening/submissions/{id}/runs` body `{registry_codes: [..], radius_km: 0–100,
  statuses: [..] | null}` → `RunOut` (with `job_id`; poll existing `/jobs/{id}` or the run).
- `GET /screening/runs/{id}` → `RunOut` incl. `summary`, `coverage` (now also carries
  `projects_excluded_pending_licence_review: int` and `warnings: list[str]`, review-fix D2/G9),
  `status`.
- `GET /screening/runs/{id}/results` → list of `ResultOut` (project metadata + metrics +
  finding + evidence).
- `GET /screening/runs/{id}/geojson` → FeatureCollection: `role` ∈ submission | project |
  intersection | search_radius. Internal display only — shows geometry from any non-BLOCKED
  source regardless of redistribution licence (review-fix D1 — this is NOT an export).
- `GET /screening/runs/{id}/export.{csv|geojson|html}` — **review-fix D3: 409 Conflict unless
  the run's status is `succeeded`** (was: readable at any status). **Review-fix D1: a project
  boundary's GEOMETRY is included only if its data source's `redistribution_allowed` is true**;
  otherwise the feature/row carries `geometry: null` (GeoJSON) or omits geometry entirely (CSV/
  HTML), a `geometry_withheld: true` property, and the note `"geometry withheld: source licence
  does not permit redistribution"`. Every export lists each contributing source's name, licence,
  attribution (GeoJSON: `properties.contributing_sources`; CSV: `#`-commented header lines +
  per-row `source_name`/`source_url`/`source_type`/`retrieved_at`/`boundary_version`/`license`
  columns; HTML: a "Registry information" section). CSV cells are sanitised against formula
  injection (review-fix S7: a leading `=`/`+`/`-`/`@`/tab/CR gets a `'` prefix). HTML response
  now sets `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, and a
  restrictive CSP (review-fix S8). `/report.pdf` still not built (unchanged from original plan).

Registry data (review-fix D5: `GET /registry/data-sources` is now
`MANAGE_REGISTRY_DATA_ROLES = {Administrator}`-only, was any authenticated user — policy default
pending human confirmation. Everything else: read any authenticated; write
`MANAGE_REGISTRY_DATA_ROLES = {Administrator}`):
- `GET /registry/registries` (with project/boundary counts, last_seen).
- `GET /registry/projects?registry=&country=&q=&has_boundary=&page=` ·
  `GET /registry/projects/{id}` (metadata, versions, boundaries history, documents, evidence,
  changes) · `GET /registry/projects/{id}/boundary.geojson?version=` — **review-fix D1: for a
  non-Administrator, withholds geometry the same way an export does** (redistribution_allowed
  gate), returning `{"type":"Feature","geometry":null,"properties":{"geometry_withheld":true,
  "note":"..."}}` instead.
- `GET/POST/PATCH /registry/data-sources` — **review-fix D4: `PATCH` requires a non-empty
  `change_reason` (Body field) whenever `review_status` changes (422 otherwise); the audit log
  now records OLD→NEW for `review_status` and the three licence flags.** `url` (and boundary-
  upload `source_url`, review-fix S6) must match `^https?://` or 422.
- `POST /registry/imports/metadata` multipart: `file`, `adapter` (manual|verra), `data_source_id`
  (already required pre-fix). Offloaded to a thread (review-fix S1 — was blocking the event
  loop).
- `POST /registry/projects/{id}/boundaries` multipart: `file`, `source_type`, `confidence`,
  `source_url`, `source_document`, `retrieved_at`, **`data_source_id` (review-fix D2: now
  REQUIRED, was optional — 422 if missing)**. Offloaded to a thread (review-fix S1). **Review-fix
  D6: re-uploading with an identical `geometry_hash` AND identical provenance (source_type,
  confidence, source_url, source_document, data_source_id) creates no new version — returns the
  existing current boundary with `unchanged: true`** (new `UploadBoundaryResult.unchanged: bool`
  field, default `false`).

## 9. Frontend

New nav items: **Screening** (all users) and **Registry Data** (Administrator).
Screening flow on one route `/screening` with steps: Upload → Validation → Configure →
Processing (job progress) → Results. Results = summary cards + coverage statement banner
(always visible) + map (submission, project boundaries coloured by confidence, intersections,
radius) + results table (Project | Registry | Relationship | Overlap ha/% | Distance |
Confidence | Finding) + detail drawer with tabs Overview / Spatial / Evidence / History.
Three visually separate sections: Spatial findings / Registry information / Review flags.
`/screening/runs/:id` deep-link. `/registry-data`: registries table, data-source/license
registry, metadata import, per-project boundary upload with provenance form.

## 10. Verification

- Integration tests against the isolated `deploy/docker-compose.test.yml` PostGIS (never the
  live `deploy-db-1`): geodesic area checked against an analytically known polygon, overlap
  %, containment, touches vs sliver, antimeridian-adjacent and high-latitude polygons,
  point-only projects, versioning immutability, RBAC (non-owner 404), BLOCKED source refusal.
- Independent `qa-geospatial-validator` pass, `appsec-reviewer` pass, `data-governance` pass.
- Live end-to-end in an isolated preview stack with Playwright.
- All test data is **synthetic** (registry `MANUAL`/`TEST`, obviously fake names) — no fabricated
  records presented as real registry projects.

## 11. Review-fix pass (2026-09-28)

Three independent reviews (geospatial, security, data-governance) plus a live end-to-end run
found real defects in the overnight build. This section records what changed; §3/§4/§8 above are
updated in place to describe the FIXED behavior, not the original bug. Migration
`crs_0001_registry_screening` was edited in place (unreleased — see its own module docstring);
no new migration file.

**Geospatial** (`app/services/spatial_engine.py`, `app/repositories/screening.py`,
`app/repositories/registry.py`, `app/services/screening/validation.py`,
`app/services/screening/parsers.py`, `app/services/screening/run_service.py`,
`app/services/registry_import_service.py`, `scripts/load_world_admin_areas.py`):
- **G1** — relationship predicates are now geodesic (`ST_Intersects`/`ST_Covers` on `::geography`),
  not planar; antimeridian-crossing intersection geometry/area normalised via `ST_ShiftLongitude`
  (shifted back for storage); a `geometric_inconsistency` guard flags a relationship/distance
  disagreement, turned into `POTENTIAL_ISSUE` by the interpretation layer, never the engine.
- **G2** — multi-feature submissions/boundaries are `ST_UnaryUnion`'d before `ST_Multi` (was:
  per-part `ST_MakeValid` only, +33% area, occasional `TopologyException`); the validation
  report's `internal_overlaps` check now reports the real overlap area in ha.
- **G3** — geometry area is measured AFTER `ST_MakeValid`, not before (a bowtie's raw signed area
  can read near-zero); FAILs only if the REPAIRED area is still zero; WARN says
  "self-intersection repaired" with the feature index.
- **G4** — `screening_submission.original_geom` is now untyped-SRID `geometry` (was
  `geometry(Geometry,4326)`, mislabeling e.g. UTM metre coordinates as WGS84 degrees) plus a new
  `original_srid` column recording the true source EPSG.
- **G5** — a registry boundary with no polygonal part (lines/empty) is rejected with a 422 before
  insert, never silently stored as `MULTIPOLYGON EMPTY`; Point AND MultiPoint are both accepted
  as the point-only/APPROXIMATE path; migration adds `CHECK (NOT ST_IsEmpty(geom))` on both
  `registry_boundary` and `screening_submission`.
- **G6** — sliver rule is AND, not OR (my own spec error) — a sliver must be BOTH < 0.01 ha AND
  < 0.01% of the smaller area.
- **G7** — the drawn search-radius circle buffers the submission's polygon EDGE
  (`ST_Buffer(geom::geography, r)`), not its centroid, matching the real `ST_DWithin` search.
- **G8** — bearing is `ST_Azimuth` on `::geography` centroids (geodesic), not planar geometry.
- **G9** — the coverage "no overlap" sentence uses `projects_with_usable_boundaries`, not the
  bigger `projects_screened` total; a "M projects have no usable boundary" warning is always
  added when M>0; `CoverageStatement.warnings` (was silently dropped by the DTO) now reaches the
  API response, not just exports.
- **G10** — `.prj`/GPKG WKT → EPSG resolution now finds the OUTERMOST PROJCS/GEOGCS element's own
  direct-child `AUTHORITY` tag (bracket-depth-aware scan), never a nested GEOGCS/UNIT tag; the
  ESRI `WGS_1984_UTM_Zone_NN[NS]` naming convention is resolved generally (any zone/hemisphere),
  not just the handful hardcoded near Karnataka; a coordinate-range check now runs on the
  POST-reprojection 4326 result too (catches a wrongly-resolved CRS the pre-transform check
  cannot).
- **G11** — `derive_admin` picks admin-0 (country) by largest overlap FIRST, then admin-1 only
  within that same country (was: single `ORDER BY admin_level DESC, overlap DESC LIMIT 1`, which
  could pick an admin-1 polygon from the WRONG country); `scripts/load_world_admin_areas.py` adds
  `--admin1-scale {10m,50m}` (default 10m — the 50m admin-1 set only covers ~9 countries in
  practice).

**Security** (`app/api/v1/screening.py`, `app/api/v1/registry.py`,
`app/services/screening/parsers.py`, `app/services/screening/validation.py`,
`app/services/screening/submission_service.py`, `app/services/screening/report_service.py`,
`app/services/user_service.py`, `app/services/ingestion/storage.py`, `app/core/config.py`):
- **S1** — submission/import/boundary-upload handlers now `await asyncio.to_thread(...)` their
  synchronous parse+PostGIS work, matching the codebase's earlier worker-freeze fix.
- **S2** — GPKG parsing opens read-only (`file:...?mode=ro`), sets `PRAGMA trusted_schema=OFF`,
  bounds work via `set_progress_handler`, requires the feature layer be a REAL TABLE
  (`sqlite_master.type='table'`, rejecting a view — including a recursive-CTE view posing as the
  feature table), quotes identifiers, and `fetchmany`s (never `fetchall`s) capped at
  `MAX_GPKG_FEATURES + 1`.
- **S3** — new `Settings.max_screening_upload_bytes` (20 MB default, was the generic 2 GiB cap);
  hashing is chunked; WKT size is checked via `os.path.getsize` before reading the file.
- **S4** — a WKT upload now gets the same vertex-count/must-have-a-polygon checks every other
  format already had, via PostGIS (`ST_NPoints`, `ST_CollectionExtract`), before insert.
- **S5** — the uploaded file is saved to storage only AFTER a successful insert (was: before
  validation, orphaning the file on any failure); soft-delete removes the stored file;
  `ScreeningRunRepository.get` now excludes a run whose submission is soft-deleted; permanent
  user delete removes that user's `screening/submissions/{user_id}/` files via a new
  `Storage.delete_prefix` API (both `LocalStorage`/`S3Storage`).
- **S6** — `source_url` (data-source `url`, boundary-upload `source_url`) must match `^https?://`
  or 422.
- **S7** — CSV cells starting with `= + - @ \t \r` get a `'` prefix (formula-injection guard).
- **S8** — the HTML export sets `Content-Disposition: attachment`, `X-Content-Type-Options:
  nosniff`, and a restrictive CSP.
- **S9** — every malformed-input path (shapefile, GPKG, WKT/WKB) now raises a FIXED client-safe
  message; the raw exception is logged server-side only, never echoed to the client; unexpected
  exceptions are caught and turned into a 422, never an unhandled 500.

**Data governance** (`app/services/screening/report_service.py`, `app/services/registry_service.py`,
`app/services/registry_import_service.py`, `app/domain/enums.py`, `app/api/v1/screening.py`,
`app/api/v1/registry.py`, migration):
- **D1** — exports (csv/geojson/html) and `GET /registry/projects/{id}/boundary.geojson` (for
  non-Administrators) withhold a boundary's GEOMETRY unless its data source's
  `redistribution_allowed` is true (metrics/finding still shown, plus an explicit withheld-note);
  every export lists each contributing source's name, licence, attribution. The in-app run
  geojson (the map) is unaffected — internal display, not redistribution.
- **D2** — `registry_boundary.data_source_id`/`registry_source_snapshot.data_source_id` are now
  `NOT NULL`; screening runs only use boundaries whose data source is APPROVED/CONDITIONAL
  (query-time join in `spatial_engine.find_candidates`, so a source later marked BLOCKED is
  excluded from every future run automatically); excluded-project count surfaced as
  `projects_excluded_pending_licence_review`.
- **D3** — exports return 409 unless the run's status is `succeeded`; the
  `summary.get('headline') or 'NO_ISSUE_DETECTED'` fallback is removed; the CSV starts with
  `#`-commented coverage-statement lines and adds provenance columns (source_name, source_url,
  source_type, retrieved_at, boundary_version, boundary_confidence, license).
- **D4** — `PATCH /registry/data-sources/{id}` records OLD→NEW for `review_status` and the three
  licence flags in the audit detail, and requires a non-empty `change_reason` (Body field) when
  `review_status` changes (422 otherwise).
- **D5** — `GET /registry/data-sources` is now Administrator-only; a new `SCREENING_ROLES =
  {Administrator, GIS Associate, Analyst}` constant gates screening submission/run CREATION
  (Verifier/Viewer can no longer create, but still read their own). Both are policy defaults
  pending human confirmation, not final decisions.
- **D6** — re-uploading a boundary with an identical `geometry_hash` AND identical provenance
  (source_type, confidence, source_url, source_document, data_source_id) creates no new version —
  returns the existing current boundary with `unchanged: true`.

**API contract changes the frontend must match**: see §8 above (inline, marked "review-fix").
New/changed fields: `RunOut.coverage.projects_excluded_pending_licence_review`,
`RunOut.coverage.warnings` (now actually present, was silently dropped),
`UploadBoundaryResult.unchanged`, export endpoints now 409 on a non-succeeded run, boundary-upload
`data_source_id` Form field is now required, `GET /registry/data-sources` is Administrator-only.

## 12. Handoff status (end of overnight build, 2026-09-28)

**State:** built, reviewed, fixed and live-verified on this branch. Not merged, not pushed.

**Verified live** (isolated compose project `dmrv-crs-e2e`, synthetic data only), numbers checked
against hand calculation:
- 50 % overlap of two 0.02° squares at 0.5°N → 246.17 ha / 50 % / CONFIRMED_OVERLAP.
- Antimeridian project (179.2E–179.8W, 17°S), submission 0.2° west → NEARBY 21.29 km (= 0.2° × 106.4 km).
  Submission inside it → WITHIN / CONFIRMED_OVERLAP. Bearing across the antimeridian 90.16°.
- Overlapping two-feature upload → stored as the union (738.5 ha, not 984.7) with an internal-overlap WARN.
  A bowtie is repaired (246.17 ha), not rejected.
- An UNREVIEWED-licence project is excluded from the run and counted in coverage. A BLOCKED source is refused
  at ingest. A `javascript:` source_url is rejected with 422. Identical re-upload → `unchanged: true`.
- Non-owner → 404 on every submission/run/export route. Viewer cannot create (403). Analyst cannot write
  registry data (403).
- Exports: the CSV opens with the coverage statement; the HTML is sent as an attachment with CSP and nosniff;
  geometry is withheld when the source doesn't allow redistribution.

**Tests at handoff:** backend unit 1421 passed. Integration 433 passed / 4 failed, and all 4 are
pre-existing: 3 WMS tests fail identically on `main`; `test_forest_definition::…audit_logged_old_to_new`
passes alone on both branches and is an order-dependent tie on `ORDER BY created_at DESC LIMIT 1`.
Frontend 316/317; the 1 failure is the pre-existing SpectralIndicesPortal.cdsePreview timeout. `npm run build` OK.

**Needs a human decision** (in addition to §7):
1. `SCREENING_ROLES` = {Administrator, GIS Associate, Analyst} can create screenings. Should Verifiers?
2. Retention: how long a soft-deleted submission's rows are kept before a hard purge (files are already
   removed on soft delete).
3. Permanent user delete cascades that user's submissions/runs. Should it be blocked when a submission
   is referenced as evidence?
4. Sliver rule is now AND (< 0.01 ha AND < 0.01 %). This needs a methodology owner's sign-off.
5. Merge order vs `feature/eligibility-prescreening` (migration down_revision rebase, see §2).

**Known gaps / follow-ups:**
- The Verra CSV column mapping is UNVERIFIED because the registry export sits behind a login. Check it against a real
  export before first use.
- There is no real registry data; every project is synthetic. Loading real data depends on the §7 licensing gate.
- CARTO light tiles now return an "API KEY REQUIRED" placeholder. The screening maps were switched to the
  app default, but `PortfolioMap.jsx` on `main` still uses CARTO and is probably blank. Not fixed here (out of scope).
- The CSV header prints the licence-exclusion notice twice (cosmetic).
- A fix agent reported an intermittent 401 in screening HTTP tests during full-suite runs. It was not
  reproduced in 3 subset runs + 1 full run afterwards.
- Load Natural Earth admin areas per environment: `python scripts/load_world_admin_areas.py --download`
  (10m admin-1 by default, 4 596 polygons).
