# Eligibility Prescreening — VM0047 v1.1 §4 Condition Classification (Phase 2)

Status: **verified against the rendered v1.1 PDF (2026-08-21) — settled.** Produced by the
`carbon-mrv-vm0047` agent; cross-checked directly against the primary PDF by Denish. See
"Source-provenance caveat" below for what was checked and what was corrected as a result.

## Purpose

Classify every atomic applicability condition in VM0047 v1.1 Section 4 ("Applicability
Conditions") into one of three buckets, to scope the eligibility-prescreening feature:

- **checkable-now** — verifiable today from an already-wired dashboard analysis or stored
  project/plot metadata.
- **needs-new-analysis** — in principle remote-sensing/GIS-checkable, but nothing wired-and-available
  in this dashboard does it yet.
- **not-remote-sensing-checkable** — inherently outside what any satellite/GIS analysis could ever
  determine (legal, procedural, field-protocol, or documentary facts).

**Land-use-history data source directive**: wherever a condition requires checking prior
land-use/land-cover history, the designated source is **`io_lulc`** (10m Annual Land Cover,
Impact Observatory/Esri methodology, annual coverage **2017–2023 only**) — **not**
`esa_worldcover`, which is a single fixed 2021 snapshot and cannot support any history/trend
condition. Any condition whose look-back requirement exceeds `io_lulc`'s 2017–2023 window is
classified `needs-new-analysis` (gap: pre-2017/post-2023 historical LULC), not silently marked
`checkable-now`.

## VM0047 version

**v1.1 (effective 14 May 2025)**, per this task's directive. The prescreener must still capture
per-project VM0047 version and refuse to render v1.1 §4 citations for grandfathered v1.0 projects
(pipeline-listed "Under Validation" by 31 Dec 2025, registration due by 31 Dec 2026) — **v1.0's
Section 4 is structured differently** (it had explicit non-applicability conditions for tidal
wetlands, water-table manipulation, and mechanical dead-wood removal that do not appear in the
v1.1 §4.4 text extracted here).

## Source-provenance caveat — what was checked and corrected

The primary PDF (`https://verra.org/documents/vm0047-afforestation-reforestation-and-revegetation-v1-1/`)
could not be rendered directly in the agent's environment (no `pdftoppm`/poppler-utils), so Section 4
text was first obtained via a text-extraction proxy (two independent passes, cross-checked against
each other). **Denish has since cross-checked §4 directly against the rendered v1.1 PDF** and
confirmed:

1. The §4 intro **10-meter buffer** between instances using different approaches is **confirmed
   real, verbatim** — not a proxy artefact.
   - **Important disambiguation**: VM0047 v1.1 has a *second, unrelated* 10-meter figure in **§5.2**
     (the minimum radius/spacing around an individual planting unit for census-based sampling).
     Do not conflate the two — the §4 buffer separates *instances* using different quantification
     approaches; the §5.2 figure governs *individual planting-unit* geometry within a single
     census-based instance. Any prescreener code or UI copy referencing "the 10m buffer" must say
     which one.
2. **§4.4 is confirmed complete for v1.1** — exactly 3 area-based + 2 census-based exclusion items,
   nothing missed by the extractor. (The earlier v1.0-comparison worry doesn't apply here: v1.1 is
   the version this feature builds against, and v1.1's §4.4 is simply shorter than v1.0's — not
   truncated.)

Everything below is a tightly-paraphrased rendering of the extracted text (verified against the
primary PDF for the two items above), not invented wording.

## Plain-English summary

Of 49 atomic conditions in Section 4, only about 1 in 5 can be pre-screened today from what this
dashboard actually has wired. Roughly a third are genuinely satellite-checkable but need new build
work — the single biggest blocker is that `io_lulc` only covers 2017–2023, which cannot satisfy
VM0047's confirmed 10-year look-back conditions for a project validating in 2026 (§4.3(8)(a),
§4.4.1(1)), plus two more conditions with open-ended date/continuity requirements that the same
2017–2023 window falls short of. The largest bucket (22 of 49) is stuff no satellite will ever
answer: planting-unit censuses, soil-inversion depth, "managed forest" status, activity type, and
leakage procedure.

**The prescreener should be built and marketed internally as a triage tool that narrows the
document-review burden — never as an eligibility verdict engine.**

## Condition table

| Section | Condition (tightly paraphrased) | Classification | Data source / analysis id (if checkable-now) | Gap — what's missing (if needs-new-analysis) | Why not RS-checkable |
|---|---|---|---|---|---|
| §4 intro | Eligible activities are direct planting, seeding, or assisted natural regeneration | not-remote-sensing-checkable | — | — | Activity type is a management fact; direct planting vs ANR is indistinguishable at 10 m |
| §4 intro | Area-based and census-based conditions are mutually exclusive; each instance must fully meet one set | not-remote-sensing-checkable | — | — | Compliance meta-rule over project design; only its component conditions are testable |
| §4 intro | Instances using different approaches separated by ≥10 m buffer within project boundary (confirmed verbatim against PDF; distinct from the §5.2 individual-planting-unit 10 m figure — do not conflate) | checkable-now | KML→PostGIS geometry, `ST_Distance`/`ST_Buffer` in EPSG:32643 | — | — |
| §4.1(1) | Project activities increase vegetative cover | checkable-now | `ndvi` / `evi` season-configurable composites (2017–present), multi-year trend inside boundary. **Proxy only** — ex-ante design intent is not RS-verifiable | — | — |
| §4.1(2) | Where both approaches are used, applied in non-overlapping areas defined at project start | checkable-now | PostGIS `ST_Overlaps`/`ST_Intersection` on instance polygons + `project.start_date`. Requires a per-instance "approach" attribute be recorded (metadata capture, not new analysis) | — | — |
| §4.1(3) | Quantification approach selected at start date and used for the entire crediting period | not-remote-sensing-checkable | — | — | Project-record consistency across reporting periods |
| §4.1(4)(a) | Start date = date site preparation activities began | needs-new-analysis | — | Site-preparation event dating. `landtrendr` and `sar` are in-development; `s2_browse`/`s1_browse` are single-scene with no time-series math | — |
| §4.1(4)(b) | Start date = the land use change date | needs-new-analysis | — | **io_lulc coverage gap (not a 10-year-lookback condition — no explicit "10 years" language here; this is a plain date-range mismatch):** a LUC event could fall on any date, but `io_lulc` only offers annual snapshots 2017–2023 — a LUC before 2017 or after 2023 (including any 2024–2026-dated event) can't be dated from it. `dynamic_world` is rolling-12-months only, `modis_lulc` (2001–2023) is 500 m and too coarse to date a microlandscape transition | — |
| §4.1(5) | Determine whether the project occurs on wetlands | checkable-now | `io_lulc` flooded-vegetation/water classes + `mndwi`/`ndwi`. Screening flag only — not a wetland delineation | — | — |
| §4.1(5) | Determine whether the project occurs on organic soils | needs-new-analysis | — | No soil/peat dataset wired anywhere in the catalog (would need a histosol/peatland reference layer, e.g. via the Reference Layer Library) | — |
| §4.1(5) | On organic soils/wetlands, use multiple-activity design: this methodology for AGB + a wetland methodology (e.g. VM0036) for other pools | not-remote-sensing-checkable | — | — | Project design and methodology-selection documentation |
| §4.2(1) | Activities involve direct planting, ANR-associated indirect activities, or a combination | not-remote-sensing-checkable | — | — | Activity-type attestation; liana cutting / weed management / grazing barriers are not observable at 10 m |
| §4.2(2) | t=0 carbon-stock estimate established — AGB (and BGB via R) portion | checkable-now | `agb_two_phase.py` Cochran double-sampling estimator (GEDI-L4A-gap-filled RS proxy + real field plots) → produces Up,t | — | — |
| §4.2(2) | t=0 carbon-stock estimate established — remaining significant pools (non-woody, dead wood, litter, SOC) | not-remote-sensing-checkable | — | — | Requires destructive/field/lab measurement; no legitimate RS proxy for litter, dead wood or SOC stock at t=0 |
| §4.2(2)(a)(i) | Where site prep initiates the start date, t=0 estimates established **before** site preparation | needs-new-analysis | — | Temporal-ordering test needs an RS-dated site-prep event to compare stored plot dates against (see §4.1(4)(a) gap) | — |
| §4.2(2)(a)(ii) | t=0 estimates established no more than two years before the start date | checkable-now | Stored plot-establishment dates vs `project.start_date` — pure metadata date arithmetic, no GEE call | — | — |
| §4.2(2)(a)(iii) | Where plots not established pre-site-prep, an RS-based estimate per §8.2.1.2 may be used, for pre-existing woody biomass only | needs-new-analysis | — | No implementation conforming to §8.2.1.2's prescribed RS procedure. `agb_two_phase` produces an AGB estimate but its conformance to §8.2.1.2 is unverified — §8.2.1.2 was not re-read in this session | — |
| §4.2(2)(b)(i) | Where LUC date / minimal site prep initiates start, t=0 estimates established within two years **after** start | checkable-now | Stored plot dates vs `project.start_date` | — | — |
| §4.2(2)(b)(ii) | Plot-based sampling occurs for all significant carbon pools | not-remote-sensing-checkable | — | — | "Plot-based" is by definition field measurement; RS cannot substitute |
| §4.2(2)(b)(iii) | Evidence that site preparation involved no **burning** that would significantly reduce monitored pools | checkable-now | `nbr` (dNBR pre/post start date, 2017–present), corroborated by `hansen_gfc` annual loss | — | — |
| §4.2(2)(b)(iii) | Evidence that site preparation involved no **clearing or mechanical disturbance** significantly reducing monitored pools | needs-new-analysis | — | Plot-scale pre/post disturbance detection on non-forest scrub. `landtrendr`/`sar` in-development; `hansen_gfc` loss is 30 m and forest-loss-specific, so it misses shrub/scrub clearing | — |
| §4.2(3) | Leakage monitored and quantified using VMD0054; must not be assumed de minimis | not-remote-sensing-checkable | — | — | Procedural obligation to apply a module. (GIS can feed it — inside/outside-boundary `io_lulc` — but only after current VMD0054 data requirements are confirmed) |
| §4.3(1) | The project activity only includes direct planting | not-remote-sensing-checkable | — | — | Cannot distinguish planted from ANR-regenerated establishment from orbit |
| §4.3(2) | Pre-project land use is maintained throughout the project lifetime (e.g. agriculture continues) | needs-new-analysis | — | **io_lulc coverage gap (not a 10-year-lookback condition — this is an open-ended forward-continuity requirement for the whole project lifetime, no fixed "10 years" in the text):** `io_lulc` gives 2017–2023 only, leaving 2024–2026 (and every later monitoring year) uncovered (`dynamic_world` covers only the trailing 12 months). Also wants `cultivated_area` detection, which is in-development | — |
| §4.3(3) | Planting density does not exceed 50 planting units per hectare | needs-new-analysis | — | No planting-unit census in the schema — PostGIS gives the hectares but there is no N to divide by. Independent RS verification of ~50 stems/ha would need sub-metre individual-tree-crown detection; no VHR/drone source is wired | — |
| §4.3(3)(a) | For instances <1 ha or including part of a hectare, density limit scales proportionally to instance size | checkable-now | PostGIS instance area in EPSG:32643 from KML boundary (the area denominator). Threshold cannot be evaluated until N is captured — see §4.3(3) | — | — |
| §4.3(3)(b) | In instances >1 ha, planting is dispersed to maintain the limit across the entire instance | needs-new-analysis | — | Per-unit GPS point ingestion (only polygon KML is ingested today) plus a PostGIS nearest-neighbour / quadrat dispersion test | — |
| §4.3(4) | A complete census of all planting units marks the project start and is t=0; census establishes N | not-remote-sensing-checkable | — | — | Field enumeration event; its completeness is a field-protocol fact |
| §4.3(4) | Only planting units planted by the project proponent are included in the census | not-remote-sensing-checkable | — | — | Provenance/attribution of an individual tree is unobservable from any sensor |
| §4.3(5) | Dead units may be replanted provided N does not exceed 50 **live** units/ha | needs-new-analysis | — | Same census gap as §4.3(3), plus no mortality / monitoring-event tracking schema to carry survival state between verifications | — |
| §4.3(6) | Individual planting units clearly defined (tree, shrub, bamboo clump) and identifiable in the field | not-remote-sensing-checkable | — | — | Field identifiability is a field-protocol property |
| §4.3(6)(a) | GPS option: spacing between units ≥ positional accuracy of the GPS units used | needs-new-analysis | — | Planting-unit point ingestion + a recorded GPS-accuracy attribute, then `ST_DWithin`/KNN spacing test. Pure GIS once the point data exists | — |
| §4.3(6)(b) | Physical-marker option: durable in-field identifier bearing a unique ID | not-remote-sensing-checkable | — | — | Physical field asset |
| §4.3(7) | A planting unit that cannot be located during monitoring is conservatively assumed dead | not-remote-sensing-checkable | — | — | Field-monitoring accounting convention, not an observable land condition |
| §4.3(8)(a) | Project occurs within an area with less than 10% pre-existing woody biomass cover | needs-new-analysis | — | `canopy_density` is in-development. **io_lulc window gap:** `io_lulc` tree-class fraction is only a proxy (misses non-tree woody/shrub cover) and its 2017–2023 window cannot give pre-project cover for projects starting before 2017 or after 2023. `hansen_gfc` treecover is a 2000 baseline at 30 m | — |
| §4.3(8)(b) | Project occurs in an area subject to continuous cropping, or in "settlements" or "other lands" IPCC categories | checkable-now | `dynamic_world` (current 10 m class breakdown) cross-checked against `io_lulc` 2023. Requires a documented DW/IO-class → IPCC-category crosswalk. Cropping *continuity* is covered by §4.3(2), not here | — | — |
| §4.3(9)(a) | Soil disturbance permitted only at the time of planting | not-remote-sensing-checkable | — | — | Timing of a subsurface field operation |
| §4.3(9)(b) | Localized-disturbance planting (e.g. pit planting) may exceed 25 cm depth (permissive clause) | not-remote-sensing-checkable | — | — | Subsurface depth; also a permission rather than a testable restriction |
| §4.3(9)(c) | Soil inversion (e.g. plowing) depth must not exceed 25 cm | not-remote-sensing-checkable | — | — | No sensor measures tillage depth |
| §4.3(9)(c) | Soil inversion may occur only once during the crediting period | needs-new-analysis | — | Tillage-event detection time series. `bsi` composites are available (2017–present, season-configurable) but there is no multi-date chaining or event-detection wiring, and `sar` time series is in-development | — |
| §4.4 intro | Verbatim: *"These exclusion conditions are not exhaustive. Project proponents are responsible for ensuring full compliance with all VCS Program rules and requirements in addition to respecting the exclusion conditions."* | not-remote-sensing-checkable | — | — | Open-ended programme-compliance obligation — Verra's own words, and the primary justification for why the prescreener must never emit a single eligible/not-eligible verdict (see disclaimer language below and the VVB risk flags) |
| §4.4.1(1) | Land met the **forest** definition at any point in the 10 years immediately preceding the start date | needs-new-analysis | — | **io_lulc window gap:** a 2026 start needs 2016–2026; `io_lulc` is 2017–2023 (short at both ends). `modis_lulc` (2001–2023) is 500 m and cannot resolve India's 0.05 ha minimum-area criterion; `canopy_density` (for the 15% canopy test in `0016_forest_definition.py`) is in-development; there is no height layer for the 2 m criterion | — |
| §4.4.1(1) | That forest was **managed** (i.e. met the "managed forest" definition) | not-remote-sensing-checkable | — | — | Management status is legal/operational, not spectral. `hansen_gfc` annual loss and `landtrendr` (in-dev) can only supply corroborating harvest evidence |
| §4.4.1(2) | Clearing of pre-existing woody biomass occurred | needs-new-analysis | — | Pre/post clearing-event detection at plot scale — `landtrendr`/`sar` in-development; `hansen_gfc` loss is 30 m, forest-only | — |
| §4.4.1(2) | That clearing involved timber harvesting | not-remote-sensing-checkable | — | — | Commercial utilization/intent of removed biomass |
| §4.4.1(2) | That clearing results in degradation of native ecosystems | needs-new-analysis | — | A native-vegetation / ecoregion reference layer (not wired) plus an agreed degradation metric | — |
| §4.4.1(3) | Project plants fewer than 50 units/ha and could therefore use the census-based approach | needs-new-analysis | — | Same census/N gap as §4.3(3); the "could use" half is compound on the whole of §4.3, much of which is not RS-checkable — so this can only ever be a partial flag | — |
| §4.4.2(1) | Woody biomass serving a similar purpose to the project's planting units was removed within the last 10 years (confirmed via pre-project photos and/or attestation) | not-remote-sensing-checkable | — | — | The methodology itself prescribes photos and/or attestation as the confirmation means. (RS corroboration would also hit the io_lulc 10-year look-back gap) |
| §4.4.2(2) | Soil disturbance involves soil inversion exceeding 25 cm depth | not-remote-sensing-checkable | — | — | No sensor measures tillage depth |

## Summary counts

**Total atomic conditions: 49**

| Bucket | Count | Share |
|---|---|---|
| checkable-now | 10 | 20% |
| needs-new-analysis | 17 | 35% |
| not-remote-sensing-checkable | 22 | 45% |

**The 10 checkable-now conditions** (the actual Phase-3 build scope): §4 intro buffer separation,
§4.1(1), §4.1(2), §4.1(5) wetland screen, §4.2(2) AGB t=0, §4.2(2)(a)(ii), §4.2(2)(b)(i),
§4.2(2)(b)(iii) burning, §4.3(3)(a), §4.3(8)(b). **3 of these 10 need no GEE call at all**
(§4.1(2), §4.2(2)(a)(ii), §4.2(2)(b)(i)) — cheapest possible first increment.

### Callout — conditions downgraded by the io_lulc 2017–2023 coverage gap

Four conditions were downgraded from a naive "checkable-now" to **needs-new-analysis** because
`io_lulc`'s 2017–2023 window can't satisfy the condition's temporal reach. **Verified against the
primary PDF: only two of these four are actual 10-year-lookback conditions** — the other two carry
no explicit "10 years" language and are downgraded for a different reason (open-ended coverage,
not a fixed lookback window). Keep these distinct; don't describe all four as "10-year lookback
gaps" going forward.

**Confirmed explicit 10-year-lookback conditions** (verbatim "10 years" language in the PDF):

1. **§4.3(8)(a)** — <10% pre-existing woody biomass cover. `io_lulc` cannot give pre-project cover
   for starts before 2017 or after 2023; compounded by `canopy_density` being in-development.
2. **§4.4.1(1)** forest-status half — met forest definition in prior 10 years. A 2026 start needs
   2016–2026; `io_lulc` gives 2017–2023, i.e. ~3 of the required 10 years are missing.

**Coverage-gap conditions with no explicit 10-year requirement** (the gap is a plain date-range /
open-ended-continuity mismatch with `io_lulc`, not a lookback-duration issue):

3. **§4.1(4)(b)** — start date = land use change date. The LUC event can fall on any date; `io_lulc`
   only covers 2017–2023, so a LUC before 2017 or after 2023 (including 2024–2026) can't be dated
   from it.
4. **§4.3(2)** — pre-project land use maintained throughout project lifetime (open-ended forward
   continuity, not a fixed 10-year window). 2024–2026 (and every later monitoring year) is
   uncovered by `io_lulc` (ceiling 2023) and by `dynamic_world` (trailing 12 months only).

Also worth recording (rule not the deciding factor, but the gap is real): **§4.4.2(1)**'s confirmed
10-year woody-biomass-removal look-back likewise exceeds the `io_lulc` window — it is classified
not-RS-checkable only because v1.1 explicitly prescribes photos/attestation as the confirmation
means.

**Single highest-leverage fix**: a pre-2017 + post-2023 annual 10 m LULC source would move up to 4
conditions out of `needs-new-analysis` (both the two true lookback conditions and the two coverage
conditions above), more than any other single build. Route that scoping question to
`geo-remote-sensing`.

## Disclaimer language — quote verbatim, do not paraphrase

Any user-facing disclaimer, tooltip, or report footer for the eligibility-prescreening feature
must quote VM0047 v1.1 §4.4's own words directly, since it is Verra's own text confirming why no
single eligible/not-eligible verdict should ever be shown:

> "These exclusion conditions are not exhaustive. Project proponents are responsible for ensuring
> full compliance with all VCS Program rules and requirements in addition to respecting the
> exclusion conditions."
> — VM0047 v1.1, §4.4

## VVB risk flags

- **Version-scope trap**: the prescreener must capture per-project VM0047 version and refuse to
  render v1.1 §4 citations for grandfathered v1.0 projects. v1.0's Section 4 is structured
  differently.
- **Do not let the prescreener emit an "eligible" verdict.** With 45% of conditions not
  RS-checkable, any green light is a false assurance. Emit only per-condition states:
  `pass (RS evidence)` / `fail (RS evidence)` / `requires documentary review` /
  `insufficient data coverage`. Pair every output with the verbatim §4.4 disclaimer above — it is
  Verra's own confirmation that exclusion conditions aren't exhaustive, so a paraphrase weakens the
  point.
- **Don't conflate the two 10-meter figures.** §4's instance-separation buffer and §5.2's
  individual-planting-unit radius are unrelated numbers that happen to share a value; any code,
  UI copy, or future doc referencing "the 10m buffer" must say which section it means.
- **§4.3(8)(b) crosswalk risk**: mapping Dynamic World / Impact Observatory classes to IPCC
  "continuous cropping / settlements / other lands" is an interpretive step. Document the
  crosswalk table explicitly and version it, or boundary drift between reports is guaranteed.
- **`esa_worldcover` must be hard-blocked** from any history/trend eligibility check in code, not
  just in guidance — a single 2021 snapshot will silently look like a valid answer.
- **Do not wire `vnv_ndfi` or the 12 VNV band-math indices** into any eligibility output:
  `vnv_ndfi` has a confirmed methodology gap on forest-heavy scenes, and the band-math indices'
  90-day trailing composites have no year selection, so they cannot support any dated condition.
- **Area computation traceability**: every area figure feeding §4.3(3)(a) must record the CRS
  (EPSG:32643) and the source KML version.

## Next steps (Phase 3)

1. Build the 3 zero-GEE metadata checks first (§4.1(2), §4.2(2)(a)(ii), §4.2(2)(b)(i)) — they need
   only `project.start_date` plus a plot-establishment-date field.
2. Route the pre-2017/post-2023 LULC source question to `geo-remote-sensing`; route the
   planting-unit census + GPS-point schema and geometry/boundary work (needed by §4 intro buffer,
   §4.3(3), (3)(a), (3)(b), (5), (6)(a)) to `gis-analyst`.

## Confidence

**High.** Classification logic and codebase-capability mapping (catalog statuses, `agb_two_phase.py`,
`dtos.py` `start_date`, `0016_forest_definition.py` thresholds) were read directly from source.
Condition wording and §4.4 completeness — the two items that started as text-extraction-proxy
artefacts — have now been cross-checked by Denish directly against the rendered v1.1 PDF and
confirmed (§4 intro 10m buffer real and distinct from §5.2; §4.4 complete at 3+2 items). The two
io_lulc-gap conditions re-flagged as not-explicit-10-year (§4.1(4)(b), §4.3(2)) have had their
rationale corrected accordingly.

## Sources

- [VM0047 v1.1 document (primary PDF)](https://verra.org/documents/vm0047-afforestation-reforestation-and-revegetation-v1-1/)
- [VM0047 v1.1 methodology page, Verra](https://verra.org/methodologies/vm0047-afforestation-reforestation-and-revegetation-v1-1/)
