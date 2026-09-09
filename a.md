# Satellite dMRV Verification Layer — Reference Architecture

**Prepared for:** VNV Advisory Services — GIS & Carbon Analytics
**Author:** Denish M
**Date:** 5 September 2026
**Status:** Technical design document for internal review. Not a commitment, contract, or RFP.

---

## 0. Verification status of this document — read this first

The user asked for cross-checking. Here is exactly what was and was not verified, so nothing in this document is trusted more than it deserves.

### Facts verified against primary sources (September 2026)

| Claim | Verified value | Source |
|---|---|---|
| Sentinel-1/2 data timeliness | ~24 hours after sensing | CDSE FAQ |
| Sentinel-3/5P timeliness | ~3 hours after sensing | CDSE FAQ |
| Landsat 8 RT availability | 4–6 hours after acquisition (< 12 h worst case) | USGS Collection 2 L1 |
| Landsat 8 RT → T1/T2 | 4–11 days (some USGS pages say 3–10) | USGS Collection 2 |
| Landsat 9 → T1/T2 | 4–6 hours after acquisition (no RT stage) | USGS Collection 2 |
| Landsat 9 → Level-2 | ~3 days total | USGS Generation Timeline |
| Landsat 8 → Level-2 | ~4–11 days total | USGS Generation Timeline |
| "14–26 days" figure | **Collection 1 legacy only** — do not use | USGS Collection 1 page |
| Landsat on AWS | `s3://usgs-landsat`, **Requester Pays**, us-west-2 (Oregon) | USGS / AWS ODR |
| Landsat reprocessing | USGS explicitly recommends replacing already-downloaded data and derived products | USGS Collection 2 |
| CDSE transfer quota | 12 TB rolling 30-day (Immediately Available Data) | CDSE Quotas page |
| CDSE over-quota penalty | Bandwidth drops to 1 MB/s, concurrent connections drop to 1 | CDSE Quotas page |
| CDSE concurrent connections | 4 (IAD) | CDSE Quotas page |
| CDSE bandwidth per connection | 20 MB/s | CDSE Quotas page |
| CDSE S3 request rate | 2,000 requests/minute | CDSE Quotas page |
| CDSE direct COG HTTP access | 50,000 requests/month | CDSE Quotas page |
| CDSE token lifetime | 10 minutes active; refreshable within 60 minutes | CDSE Quotas page |
| CDSE concurrent sessions | 100 max, **not raisable even with a paid plan** | CDSE Quotas page |
| openEO free tier | 10,000 credits/month (temporary boost from 4,000) | CDSE Quotas / openEO page |
| openEO concurrency | 2 concurrent jobs; 12 requests/min (1 per 5 s) | CDSE Quotas page |
| Sentinel Hub free tier | 10,000 requests + 10,000 processing units per month | CDSE Quotas page |
| Sentinel-1 constellation | S1C + S1D, 6-day revisit restored ~July 2026; S1A retired 29 June 2026 | ESA / Copernicus |
| Sentinel-1 coverage gap | Dec 2021 – Apr 2025 was single-satellite / patchy | ASF HyP3 |
| GEE commercial use | Requires paid commercial licence; free tier is noncommercial/research/academic/government only | Google |
| Multi-account quota evasion | Explicitly a Terms & Conditions breach; may result in service cessation | CDSE T&C |

### Claims that are engineering judgement, not verified fact

Marked inline with **[JUDGEMENT]**. Cost figures, effort estimates, and architectural recommendations fall in this category. Treat them as a starting position for debate, not as findings.

---

## 1. What this system must do

Derived from the Satellite dMRV brief. The system exists to answer one question, repeatedly and defensibly:

> For a given plot, in a given season, does independent satellite evidence agree with what was reported on the ground?

### 1.1 Functional requirements

| ID | Requirement |
|---|---|
| F1 | Ingest Sentinel-1, Sentinel-2, Landsat 8, Landsat 9 for all enrolled plots |
| F2 | Produce observations at three lifecycle stages: baseline, monitoring, reversal |
| F3 | Every observation carries: value, confidence, discrepancy vs. ground claim, metadata, method reference |
| F4 | Never overwrite the ground record; never auto-decide an outcome |
| F5 | Support EUDR forest-baseline determination against the 31 Dec 2020 cutoff |
| F6 | Support crop-specific checks: rice water regime, sugarcane/cotton burn, coffee/cocoa canopy & deforestation, plot area |
| F7 | Fail loudly — missing or low-confidence data flags for human review, never silently passes |
| F8 | Full audit trail: any issued credit must be traceable to the exact imagery and algorithm version that produced it |
| F9 | Reversal monitoring continues indefinitely after credit issuance |
| F10 | Distinguish temporary/natural disturbance from permanent/human disturbance before triggering buffer drawdown |

### 1.2 Non-functional requirements

| ID | Requirement | Target **[JUDGEMENT]** |
|---|---|---|
| N1 | Observation latency (acquisition → result available) | ≤ 72 h p95 for optical, ≤ 48 h p95 for SAR |
| N2 | Reproducibility | Any observation re-computable bit-for-bit from stored inputs + version pins |
| N3 | Scale | 100,000 plots without architectural change |
| N4 | Availability | Ingestion may lag; audit query path must stay available |
| N5 | Cost predictability | No unbounded per-plot cost growth |
| N6 | Data sovereignty | Comply with EUDR evidentiary expectations and Indian data norms |

### 1.3 Explicit non-goals

- **True real-time monitoring.** Physically impossible with this sensor stack. Sentinel-1 revisit is 6 days; Sentinel-2 is ~5 days; Landsat 8+9 combined is 8 days. Add ~24 h delivery. The honest floor is roughly **6–8 days between independent looks at a plot**, and cloud cover makes the optical figure worse in practice during Indian monsoon.
- **Replacing field verification.** The system reduces field visits; it does not eliminate them.
- **Automated credit issuance or rejection.** The system produces evidence. Humans decide.

---

## 2. Design principles

These are load-bearing. Every later decision traces back to one of them.

**P1 — Evidence, not verdict.** The satellite layer emits observations and flags. It never mutates the ground record and never renders a decision. (Directly from the brief.)

**P2 — Immutability with supersession.** Observations are append-only. A corrected value does not overwrite its predecessor; it supersedes it, and the predecessor remains queryable forever. This is the single most important departure from a naive design, and it exists because carbon credits are financial instruments subject to audit.

**P3 — Provenance is a first-class output, not metadata garnish.** Sensor, product ID, processing level, product generation date, checksum, algorithm version, model version, and calibration reference are stored per observation. If an auditor asks "which pixels produced this number, and what code processed them," the system answers without archaeology.

**P4 — Fail loudly.** Missing data, cloud occlusion, low valid-pixel fraction, provider errors — all produce an explicit `needs_review` state. Silence is never success.

**P5 — Provider independence.** No provider's API shape reaches business logic. Adapters normalise; everything downstream sees one internal schema.

**P6 — Cache what you'll re-read.** Reprocessing is guaranteed (model retraining, algorithm fixes, provider reprocessing). Re-downloading the same scene from ESA three times is a design smell.

**P7 — Process per acquisition, not per plot.** Satellite data arrives as scenes/tiles. Organise compute around that grain, then fan out to plots. The inverse is the classic N+1 problem transplanted into geospatial.

**P8 — Sensor-specific processing contracts.** Sentinel-1 is not "another band." Each sensor gets its own explicit pre-processing pipeline with its own quality semantics.

---

## 3. Data source ground truth

The architecture must be built around what these sources actually are, not around what would be convenient.

### 3.1 Revisit and latency reality

| Sensor | Native revisit | Effective revisit (India, monsoon) | Delivery latency | Notes |
|---|---|---|---|---|
| Sentinel-2 (2 sats) | ~5 days | Frequently 15–30+ days usable | ~24 h | Optical; cloud-limited |
| Sentinel-1 (S1C+S1D) | 6 days | 6 days | ~24 h | SAR; cloud-independent |
| Landsat 8 | 16 days | Cloud-limited | RT: 4–6 h; T1: 4–11 d | RT tier exists |
| Landsat 9 | 16 days | Cloud-limited | T1/T2: 4–6 h | **No RT stage** |
| Landsat 8+9 combined | 8 days | Cloud-limited | Mixed — see above | Different tier semantics per satellite |

**Critical asymmetry:** Landsat 8 and Landsat 9 have fundamentally different product timelines. L8 goes RT → (4–11 days) → T1/T2. L9 goes straight to T1/T2 in 4–6 hours. A pipeline that treats "Landsat" as one thing will either needlessly delay L9 data or wrongly treat L8 RT as final. The processing tier must be a first-class field, not an assumption.

**Sentinel-1 archive caveat:** From Sentinel-1B's failure (Dec 2021) until Sentinel-1C reached regular acquisition (Mar 2025), the constellation ran degraded — 12-day revisit at best, with genuinely missing coverage in places. Any historical baseline analysis touching 2022–2024 must handle sparse and irregular SAR coverage explicitly. This is a real data-quality landmine for retrospective rice AWD analysis.

### 3.2 Access channels and their true cost

| Channel | Cost | Best for | Gotcha |
|---|---|---|---|
| CDSE STAC/OData/S3 | Free within quota | Sentinel discovery + download | 12 TB/30-day rolling; 4 concurrent connections; 20 MB/s per connection |
| CDSE openEO | 10,000 credits/month free | Server-side processing | 2 concurrent jobs; 1 request/5 s; flat 7 credits per synchronous download regardless of size |
| CDSE Sentinel Hub | 10,000 req + 10,000 PU/month | Statistical API, time series | Batch Processing API not available on free tier |
| USGS M2M / EarthExplorer | Free | Landsat, all tiers | Not COG-native for all access paths |
| `s3://usgs-landsat` | **Requester Pays** | Landsat COG partial reads | You pay GET requests + egress; bucket is in **us-west-2 (Oregon)** |
| AWS Open Data (Element84 Earth Search) | Free reads | Sentinel-2 COGs | Not all collections; verify per-collection terms |
| Microsoft Planetary Computer | Free tier | Both, STAC-native | Azure-side; cross-cloud egress if you're on AWS |
| CREODIAS | Paid | Overflow beyond CDSE quota | Separate procurement, not an automatic switch |

**The Oregon problem.** VNV's AWS footprint is presumably `ap-south-1` (Mumbai). The USGS Landsat bucket is `us-west-2`. That means every Landsat COG read is cross-region *and* requester-pays. Two cost sources, not zero. Options: (a) run a small ingestion worker in `us-west-2` that pulls and re-stages into your Mumbai bucket, paying egress once per scene rather than once per plot-read; (b) use CDSE's Landsat-8 mirror instead, which is within the CDSE quota; (c) accept the cost and measure it. **[JUDGEMENT]** Option (a) is almost certainly right at scale — it converts a per-read cost into a per-scene cost, which is exactly what caching is for.

### 3.3 Quota arithmetic — do this before committing

CDSE free tier gives 12 TB per rolling 30 days at 20 MB/s across 4 concurrent connections.

- Theoretical max throughput: 4 × 20 MB/s = 80 MB/s = ~6.9 TB/day. Quota is the binding constraint, not bandwidth.
- A Sentinel-2 L2A tile is roughly 0.5–1 GB. 12 TB ≈ 12,000–24,000 tile-equivalents per 30 days.
- A Sentinel-1 GRD scene is roughly 1–2 GB (IW mode). Materially fewer scenes per TB.

**[JUDGEMENT]** For a portfolio confined to a handful of Indian districts, the free tier is likely sufficient for years — you're pulling tens of tiles per revisit cycle, not thousands. For a pan-India or multi-country EUDR portfolio touching hundreds of Sentinel-2 tiles per cycle, model this carefully before assuming free.

**Do not create multiple accounts to evade quota.** CDSE's Terms and Conditions name this explicitly as a breach that may result in immediate cessation of service. Losing CDSE access mid-programme would be an existential operational failure for this system.

---

## 4. Architecture — layer by layer

```
┌───────────────────────────────────────────────────────────────────────┐
│  L0  PLOT REGISTRY (PostGIS)                                          │
│      plot geometry, enrolment, crop, stage, tile assignment           │
└──────────────────────────────┬────────────────────────────────────────┘
                               │ spatial join → tile work units
┌──────────────────────────────▼────────────────────────────────────────┐
│  L1  DISCOVERY                                                        │
│      CDSE STAC │ USGS M2M/STAC │ Earth Search │ (SNS notifications)    │
│      per-provider adapters, rate-limit aware, token lifecycle         │
└──────────────────────────────┬────────────────────────────────────────┘
┌──────────────────────────────▼────────────────────────────────────────┐
│  L2  NORMALISATION                                                    │
│      provider Item → internal scene record (one schema, all sources)  │
└──────────────────────────────┬────────────────────────────────────────┘
┌──────────────────────────────▼────────────────────────────────────────┐
│  L3  ORCHESTRATION                                                    │
│      scene ledger (Postgres) → work queue → idempotent K8s workers    │
└──────────────────────────────┬────────────────────────────────────────┘
┌──────────────────────────────▼────────────────────────────────────────┐
│  L4  CACHE + INTERNAL STAC                                            │
│      S3 (ap-south-1) raw scenes + derived rasters; own STAC catalogue │
└──────────────────────────────┬────────────────────────────────────────┘
┌──────────────────────────────▼────────────────────────────────────────┐
│  L5  SENSOR-SPECIFIC PROCESSING                                       │
│      S2 chain │ S1 SAR chain │ Landsat chain (L8 ≠ L9)                │
└──────────────────────────────┬────────────────────────────────────────┘
┌──────────────────────────────▼────────────────────────────────────────┐
│  L6  PLOT EXTRACTION                                                  │
│      polygon mask, zonal stats, valid-pixel accounting                │
└──────────────────────────────┬────────────────────────────────────────┘
┌──────────────────────────────▼────────────────────────────────────────┐
│  L7  INDICATORS & MODELS                                              │
│      crop-specific: AWD, burn, canopy, deforestation, area, SOC flag  │
└──────────────────────────────┬────────────────────────────────────────┘
┌──────────────────────────────▼────────────────────────────────────────┐
│  L8  RECONCILIATION                                                   │
│      compare vs. ground claim → discrepancy + confidence + review flag│
└──────────────────────────────┬────────────────────────────────────────┘
┌──────────────────────────────▼────────────────────────────────────────┐
│  L9  SERVING                                                          │
│      API into VNV GIS & Spatial module; audit/evidence export         │
└───────────────────────────────────────────────────────────────────────┘
```

---

### L0 — Plot registry

**Store:** PostGIS.

**Why PostGIS and not something exotic:** it is the mature, boring, well-understood choice; VNV's platform already has a GIS & Spatial module; and the spatial-join pattern this architecture depends on (§L1) is precisely what PostGIS GIST indexes are built for.

**Core table:**

```sql
CREATE TABLE plot (
  plot_id            uuid PRIMARY KEY,
  external_ref       text,              -- TraceX / KOBO / manual source key
  geom               geometry(MultiPolygon, 4326) NOT NULL,
  geom_valid         boolean NOT NULL,  -- ST_IsValid result, stored not recomputed
  area_ha_reported   numeric,           -- what the farmer/field agent claimed
  area_ha_geometric  numeric,           -- ST_Area on an equal-area projection
  crop               text NOT NULL,     -- cotton|rice|sugarcane|coffee|cocoa|tea
  enrolment_date     date NOT NULL,
  lifecycle_stage    text NOT NULL,     -- baseline|monitoring|reversal
  country_code       text NOT NULL,
  eudr_in_scope      boolean NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX plot_geom_gix ON plot USING GIST (geom);
CREATE INDEX plot_stage_ix ON plot (lifecycle_stage, crop);
```

**Design notes:**

- **Store `geom_valid`, don't recompute it.** Invalid geometries (self-intersections, ring order errors) are extremely common in smallholder boundary data uploaded from field apps. Validate once at ingest, store the verdict, and let the pipeline skip-and-flag rather than crash mid-batch.
- **`area_ha_reported` vs `area_ha_geometric` are different columns on purpose.** Their divergence is itself a dMRV signal — the very first discrepancy check the system can run, before any imagery is touched.
- **Equal-area projection for area.** Computing area in EPSG:4326 (degrees) is a classic and silent error. Use an equal-area CRS appropriate to the region, or `ST_Area(geography)`.
- **Tile assignment is materialised, not computed per query.** See L1.

**Tile assignment table** — the key to P7:

```sql
CREATE TABLE plot_tile (
  plot_id     uuid REFERENCES plot(plot_id),
  tile_system text NOT NULL,   -- 'MGRS' (Sentinel-2) | 'WRS2' (Landsat) | 'S1_SLICE'
  tile_id     text NOT NULL,   -- e.g. '43QCV' or '146/047'
  PRIMARY KEY (plot_id, tile_system, tile_id)
);
CREATE INDEX plot_tile_lookup ON plot_tile (tile_system, tile_id);
```

Recomputed only when a plot's geometry changes or a new plot enrols. This turns "which plots does this scene cover?" into a single indexed lookup instead of a spatial scan over the whole portfolio.

---

### L1 — Discovery

**Responsibility:** find out that new imagery exists. Nothing else.

**Trigger model — three tiers, use all three:**

1. **Push where available.** USGS publishes SNS topics for new Landsat Collection 2 scene notifications (`arn:aws:sns:us-west-2:673253540267:public-c2-notify-v2` for L1/L2 scenes). Subscribing to this is strictly better than polling — you learn about a scene when it lands, not up to N hours later. **This is the single highest-leverage detail most designs miss.**
2. **Poll CDSE STAC on a schedule** for Sentinel-1/2. CDSE also offers OData catalogue subscriptions, which are worth evaluating as a push alternative.
3. **Reconciliation sweep**, daily. Re-query a wider window (e.g. last 14 days) and compare against the scene ledger to catch anything both mechanisms missed. Push and poll both fail sometimes; a slow sweep is the safety net.

**Query construction — the trap and the fix.**

Do **not** issue one STAC query per plot. With 20,000 plots that is 20,000 queries per cycle, which will get you rate-limited (CDSE: 2,000 requests/min on S3; openEO: 1 request per 5 seconds) and is pure waste, since thousands of plots often fall inside a single Sentinel-2 MGRS tile.

Correct pattern:

```
1. SELECT DISTINCT tile_id FROM plot_tile WHERE tile_system='MGRS'
   → e.g. 6 tiles cover the whole portfolio
2. One STAC query per tile per time window
3. For each returned Item, look up affected plots via plot_tile index
```

Query count becomes O(tiles), not O(plots). For an Indian district-scale portfolio this is typically single-digit to low-double-digit queries per cycle.

**Adapter responsibilities per provider:**

| Concern | Why it needs adapter handling |
|---|---|
| Auth | CDSE uses OAuth tokens valid **10 minutes**, refreshable within **60 minutes**. USGS M2M uses its own token scheme. AWS requester-pays needs SigV4 + `x-amz-request-payer` header. Three completely different models. |
| Cloud-cover property name | `eo:cloud_cover` in some catalogues, provider-specific elsewhere |
| Asset naming | Band naming differs (`B04` vs `red` vs `SR_B4`) |
| Pagination | Token-based vs offset-based, different page sizes |
| Rate limits | Per-provider, per-endpoint; adapter owns the backoff |
| Session limits | CDSE caps at **100 concurrent sessions, not raisable with payment** — the adapter must pool tokens, not mint one per worker |
| Asset availability | CDSE distinguishes Immediately Available Data from Deferred Available Data (offline); DAD must be *ordered* via Data Workspace first, and free-tier DAD transfer is capped at 0.1 TB/month with 1 concurrent order |

That last row is a genuine operational hazard: an older Sentinel scene needed for a 2020 EUDR baseline may be offline and require an ordering step with a very tight quota. The pipeline must model "requested, awaiting availability" as a first-class state, not treat it as an error.

**[JUDGEMENT]** Implement adapters as a plugin interface with a conformance test suite. When a provider changes, one adapter changes and its tests catch the drift.

---

### L2 — Normalisation

**One internal schema. Everything downstream sees only this.**

```sql
CREATE TABLE scene (
  scene_id              uuid PRIMARY KEY,
  provider              text NOT NULL,        -- cdse|usgs|earthsearch|planetary
  provider_product_id   text NOT NULL,        -- native ID, e.g. S2A_MSIL2A_...
  platform              text NOT NULL,        -- sentinel-2a|sentinel-1c|landsat-8|landsat-9
  sensor                text NOT NULL,        -- MSI|C-SAR|OLI-TIRS
  acquisition_time      timestamptz NOT NULL,
  processing_level      text NOT NULL,        -- L1C|L2A|GRD|SLC|L1TP|L2SP
  processing_tier       text,                 -- RT|T1|T2|NULL(sentinel)
  product_generation_dt timestamptz,          -- when the provider MADE this file
  collection            text NOT NULL,        -- e.g. landsat-c2l2-sr
  tile_system           text,
  tile_id               text,
  footprint             geometry(Polygon,4326) NOT NULL,
  cloud_cover_pct       numeric,              -- NULL for SAR
  orbit_direction       text,                 -- ASCENDING|DESCENDING (SAR-critical)
  relative_orbit        integer,              -- SAR-critical
  asset_manifest        jsonb NOT NULL,       -- normalised band → URI map
  checksum              text,
  is_superseded_by      uuid REFERENCES scene(scene_id),
  discovered_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider, provider_product_id, product_generation_dt)
);
CREATE INDEX scene_footprint_gix ON scene USING GIST (footprint);
CREATE INDEX scene_tile_time_ix ON scene (tile_system, tile_id, acquisition_time DESC);
```

**Why `product_generation_dt` is in the uniqueness constraint:** because providers reprocess. USGS explicitly recommends replacing already-downloaded data and derived products when scenes are reprocessed. If the unique key were `(provider, provider_product_id)` alone, a reprocessed scene would either collide or silently overwrite. Including generation date makes reprocessing a *new row that supersedes the old one*, which is exactly the behaviour P2 demands.

**`orbit_direction` and `relative_orbit` are not optional for SAR.** Sentinel-1 backscatter from an ascending pass and a descending pass over the same field are not comparable — different incidence angle, different geometry. Comparing them naively produces phantom change. These fields must be present so downstream logic can restrict time series to a consistent orbit.

---

### L3 — Orchestration

**The CronJob is the trigger, not the workflow.**

A single K8s CronJob that discovers, downloads, processes, and writes is fine for a prototype and wrong for production. It has no retry granularity, no backpressure, no partial-failure recovery, and it will eventually run past its own schedule and overlap with itself.

**Structure:**

```
CronJob (discovery only, short-lived)
    ↓ writes scene rows
Scene ledger (Postgres) — source of truth for "what needs doing"
    ↓ transactional outbox
Queue (SQS / Redis Streams / Postgres-backed queue)
    ↓
Worker pool (K8s Deployment, HPA on queue depth)
    ↓ writes results + state transitions
Scene ledger updated
```

**State machine per scene:**

```
discovered → queued → fetching → fetched → processing → processed
                ↓         ↓          ↓          ↓
             failed ← ────┴──────────┴──────────┘
                ↓
            retrying (exponential backoff, capped)
                ↓
        permanently_failed → needs_review   [P4: fail loudly]

Additional states:
  awaiting_availability   (CDSE Deferred Available Data ordered, not yet online)
  superseded              (provider reprocessed; replacement scene exists)
```

**Idempotency is mandatory.** Every worker task must be safely re-runnable. Use `(scene_id, algorithm_version, model_version)` as the natural idempotency key: if a result already exists for that triple, the task is a no-op. Without this, a queue redelivery silently produces duplicate observations — and in an audit context, duplicate observations are worse than missing ones.

**Backpressure against provider quotas.** The worker pool must not scale past what CDSE allows: 4 concurrent connections for IAD, 2 concurrent openEO jobs, 100 total sessions. A naive HPA scaling to 50 pods will hit quota walls and get throttled to 1 MB/s — which then looks like a mysterious performance collapse. Encode provider concurrency as an explicit semaphore/lease, not as a pod-count coincidence.

**Priority queues.** Not all work is equal. **[JUDGEMENT]** Suggested lanes:
- `p0` — EUDR deforestation alerts on in-scope plots (legal exposure)
- `p1` — active-season monitoring for rice AWD (highest-value carbon claim, time-sensitive water regime)
- `p2` — routine monitoring
- `p3` — backfill, reprocessing, model re-runs

---

### L4 — Cache and internal STAC

**This is the component most often omitted and most often regretted.**

**What it does:** every scene fetched from a provider is written once to VNV-controlled object storage in `ap-south-1`, registered in an internal STAC catalogue, and thereafter read from there.

**Why it is non-negotiable here:**

| Reason | Consequence without it |
|---|---|
| Reprocessing is guaranteed | Every model retrain re-downloads terabytes; quota exhausted |
| Requester-pays Landsat | Every plot-read costs money; caching converts to per-scene cost |
| Cross-region egress | Oregon → Mumbai on every read instead of once |
| Provider archive changes | Provider reprocesses or removes a product; your evidence vanishes |
| Audit reproducibility | Cannot prove what pixels produced a 2027 credit if the source moved |
| Provider outage | Pipeline stalls entirely instead of degrading |
| CDSE DAD/offline products | Re-ordering an offline product is slow and quota-limited |

**The audit argument is the decisive one.** If a verifier challenges a credit issued in 2027 and the pipeline's only reference is an external URL that now 404s or serves reprocessed pixels, VNV cannot substantiate the claim. Caching is not a performance optimisation here; it is evidence preservation.

**Layout:**

```
s3://vnv-eo-cache/           (ap-south-1)
  raw/
    sentinel-2/{tile}/{date}/{product_id}/
    sentinel-1/{relorbit}/{date}/{product_id}/
    landsat/{path}/{row}/{date}/{product_id}/
  derived/
    {algorithm}/{version}/{tile}/{date}/
  stac/
    catalog.json → collections → items
```

**Lifecycle policy** **[JUDGEMENT]**: raw scenes on S3 Standard for 90 days → Standard-IA to 1 year → Glacier Instant Retrieval thereafter. Derived rasters stay on Standard-IA. Never expire anything that backs an issued credit — apply an S3 Object Lock or a legal-hold tag on those, since deletion of credit-backing evidence is an audit failure regardless of cost savings.

**Cache-or-stream decision.** COG partial reads are genuinely efficient, but COG does **not** mean "only my polygon's bytes transfer." Reads happen at internal tile-block granularity (typically 256×256 or 512×512), across requested bands, after any reprojection. A 2-hectare plot may still pull several MB. Rule of thumb **[JUDGEMENT]**:

- **Stream directly** when a scene serves few plots and won't be re-read.
- **Cache the whole scene** when a scene serves many plots (common — thousands of smallholder plots per MGRS tile), or when reprocessing is anticipated.
- Concretely: if `plots_in_tile × expected_reads_per_plot > ~3`, cache.

---

### L5 — Sensor-specific processing

**P8 in practice.** Three distinct chains, not one parameterised chain.

#### L5a — Sentinel-2 optical

```
L2A product (BOA reflectance, already atmospherically corrected by ESA)
    ↓
Cloud + shadow + cirrus + snow masking
    ↓  SCL scene classification layer as baseline,
    ↓  s2cloudless probability layer for the hard cases
    ↓
Band selection + resampling to common grid (20 m recommended for mixed-band indices)
    ↓
Index computation (NDVI, NDMI, NBR, NDWI as needed)
    ↓
Per-pixel validity mask carried forward
```

**Notes:**
- Prefer **L2A** (bottom-of-atmosphere) over L1C. If only L1C is available for a historical date, atmospheric correction must be applied and *recorded as an algorithm step with its own version*, because Sen2Cor version differences change reflectance values measurably.
- **SCL alone is insufficient.** It systematically misses thin cirrus and cloud shadow edges. Combining SCL with a probability-based mask (s2cloudless) is standard practice. Apply a dilation buffer around detected clouds — shadow adjacency is the main source of contaminated "valid" pixels.
- **Resampling matters.** Sentinel-2 bands are natively 10 m, 20 m, and 60 m. NDVI from B8 (10 m) and B4 (10 m) is clean; anything mixing 10 m and 20 m bands requires an explicit, recorded resampling decision. Nearest-neighbour vs. bilinear changes edge pixels.

#### L5b — Sentinel-1 SAR

This is the chain the naive design underestimates most. From GRD to analysis-ready backscatter:

```
GRD product
    ↓ apply precise orbit file (POD/POEORB — published ~20 days after acquisition;
    ↓   RESORB restituted orbits available within ~180 min for faster turnaround)
    ↓ GRD border noise removal
    ↓ thermal noise removal
    ↓ radiometric calibration → σ⁰ (sigma nought)
    ↓ terrain correction (Range-Doppler, using a DEM — Copernicus DEM or SRTM)
    ↓ optional: radiometric terrain flattening → γ⁰ (gamma nought)
    ↓ speckle filtering (or explicitly NOT — see below)
    ↓ dB conversion
    ↓ VV, VH, and derived ratios
```

**Critical points:**

- **Orbit files create a latency/accuracy tradeoff.** RESORB restituted orbits arrive within ~180 minutes and are accurate to roughly 10 cm; precise POEORB orbits arrive ~20 days later. Processing with RESORB gives speed; reprocessing with POEORB gives final geometry. This is *the SAR equivalent of Landsat's RT→T1 problem*, and it must be handled by the same supersession mechanism.
- **Orbit direction and relative orbit must be held constant in a time series.** Comparing an ascending-pass backscatter value against a descending-pass value over the same paddy field is not a valid change signal. Enforce this at query time, not by convention.
- **Speckle filtering is a judgement call with consequences.** Filtering (Lee, Refined Lee, multi-temporal) reduces noise but smooths boundaries — bad for small smallholder plots where the plot may be only a few dozen pixels. **[JUDGEMENT]** For rice AWD on small plots, prefer multi-temporal speckle filtering or no filtering with larger-sample statistics, over spatial filters that bleed across plot edges.
- **Terrain effects.** In flat paddy regions this matters less; in coffee/cocoa agroforestry on slopes it matters a great deal. Radiometric terrain flattening (γ⁰) is worth the extra step for hilly terrain.
- **Consider ready-made RTC products.** AWS hosts Sentinel-1 RTC (radiometrically terrain-corrected) products. Using these skips most of the chain above at the cost of accepting someone else's processing choices — which must then be recorded as the algorithm provenance. **[JUDGEMENT]** For Phase 1, using pre-processed RTC is the pragmatic choice; build the in-house chain only if RTC's parameters prove unsuitable.

#### L5c — Landsat

```
Landsat 8:  RT (4-6 h) → provisional observation
              ↓ 4-11 days later
            T1/T2 → supersede
              ↓ +~24 h
            L2 Surface Reflectance → supersede again if L2 is the analysis input

Landsat 9:  T1/T2 direct (4-6 h) → no RT stage
              ↓ ~3 days total
            L2 Surface Reflectance
```

**Notes:**
- **Do not treat L8 and L9 identically.** Encode the tier expectations per platform in configuration, not in code branches scattered through the pipeline.
- **RT is geometrically provisional.** L8 RT uses initial TIRS line-of-sight parameters; T1 applies refined parameters. For thermal work the difference is significant; for optical NDVI it is smaller but non-zero, and the georegistration difference can shift which pixels fall inside a small plot boundary.
- **Tier 2 is a quality signal, not just a label.** T2 scenes failed T1's geometric accuracy threshold (T1 guarantees ≤12 m RMSE georegistration). For small smallholder plots, a T2 scene's positional error may be a meaningful fraction of the plot. **[JUDGEMENT]** Treat T2 as reduced-confidence and record it as such rather than silently mixing it with T1 in a time series.
- **Cross-calibration.** Tier 1 data is inter-calibrated across Landsat sensors — that is an explicit design property of Collection 2 and one reason to prefer T1 for time series spanning L8 and L9.

---

### L6 — Plot extraction

**Bounding box for discovery. Exact polygon for statistics.** These are different operations and conflating them is a real accuracy bug.

A bounding box around an irregular smallholder plot can easily include roads, farm buildings, neighbouring fields with different crops, tree lines, and irrigation channels. Computing NDVI over the bbox and attributing it to the plot produces a number that is not about the plot.

```
scene footprint ∩ tile → candidate plots (from plot_tile index)
    ↓
per plot: read COG window covering plot bbox   [efficiency]
    ↓
rasterise exact plot polygon → mask            [correctness]
    ↓
apply validity mask (cloud/shadow/nodata)      [quality]
    ↓
zonal statistics over valid ∩ in-polygon pixels
```

**Pixel accounting — output all of these, always:**

```
total_pixels_in_polygon     -- geometric extent
valid_pixels                -- after cloud/shadow/nodata masking
valid_pixel_fraction        -- valid / total
edge_pixel_fraction         -- pixels touching polygon boundary
```

**Why edge pixels get their own field:** for a 2 ha plot at 10 m resolution, roughly 200 pixels total, a large share of which touch the boundary and are therefore spectrally mixed. Mixed pixels systematically bias smallholder statistics. Options: erode the polygon by one pixel before statistics (loses signal on tiny plots), or report the fraction and let downstream confidence logic weight it. **[JUDGEMENT]** Report it; don't silently erode. Erosion on a 0.5 ha plot can remove most of the plot.

**Minimum plot size.** **[JUDGEMENT]** Below roughly 0.5 ha, Sentinel-2 at 10 m gives ~50 pixels, mostly mixed. Below ~0.2 ha the measurement is not meaningfully about the plot. Define an explicit minimum-viable-area threshold per sensor, and flag plots below it as `insufficient_resolution` rather than producing a confident-looking number from twelve pixels. This is directly relevant to the cocoa case in the brief, which specifically flags fragmented smallholder plots.

**Coordinate reference systems.** Reproject the polygon to the raster's CRS, not the raster to the polygon's. Reprojecting rasters resamples pixel values; reprojecting vectors does not. This is a small detail with real numerical consequences.

---

### L7 — Indicators and models

Per-crop, mapped to the brief's requirements.

| Crop | Check | Primary sensor | Method sketch | Difficulty |
|---|---|---|---|---|
| Rice | AWD water regime | S1 SAR | VV/VH backscatter drop = flooding; time series vs. farmer water log | Medium — well-established |
| Rice | Crop calendar | S2 NDVI | Phenology curve fitting | Low |
| Sugarcane | Pre-harvest burning | VIIRS/MODIS active fire + S2 NBR/dNBR | Thermal anomaly + burn scar confirmation | Low–Medium |
| Cotton | Residue burning | Same as above | Same | Low–Medium |
| Cotton | Tillage | S1 SAR | Roughness/backscatter change | Medium–High, noisy |
| Cotton/Rice/Cane | Plot area | Any optical | Geometry vs. reported | Low |
| Coffee/Cocoa | EUDR forest baseline pre-2020-12-31 | Landsat + S2 archive | Custom agroforestry classifier | **High** |
| Coffee/Cocoa | Canopy cover | S2 + canopy height products | Classification + density | High |
| Coffee/Cocoa | Deforestation alerts | GLAD/RADD + S2 verification | Third-party alert + own confirmation | Medium |
| Tea | Plot area, canopy | S2 | Basic | Low (lowest priority per brief) |
| All | SOC | S2 bare-soil composites | **Flag only, never a standalone trigger** | Very High, low confidence |

**The agroforestry classification problem deserves its own note.** The brief correctly identifies that a generic forest classifier will misclassify shade-grown coffee and cocoa — either flagging productive agroforestry as forest, or failing to detect its clearance. This is not a tuning problem; it requires purpose-built training data from the specific regions in scope. **[JUDGEMENT]** This is the highest-risk technical component in the entire programme, and it is on the EUDR critical path. It should be prototyped first, in GEE, before any production infrastructure is built for it.

**Third-party alerts as input, not gospel.** GLAD and RADD alerts are excellent triggers but should feed the `p0` queue as *candidate* events requiring own-imagery confirmation, not as findings. Their thresholds and false-positive characteristics are not tuned for VNV's crops or geographies.

**Fire detection resolution mismatch.** VIIRS active fire is 375 m; MODIS is 1 km. A smallholder plot is far smaller than one pixel. A fire detection therefore indicates *fire in the vicinity*, not *fire on this plot*. Combine with a burn-scar index (dNBR from before/after Sentinel-2) at 20 m for plot-level attribution. Reporting a VIIRS hit as "this plot burned" is a false-positive generator that will destroy trust in the system quickly.

---

### L8 — Reconciliation

**Where evidence meets claim. Where the system's core discipline lives.**

```sql
CREATE TABLE observation (
  observation_id      uuid PRIMARY KEY,
  plot_id             uuid NOT NULL REFERENCES plot(plot_id),
  scene_id            uuid NOT NULL REFERENCES scene(scene_id),
  lifecycle_stage     text NOT NULL,        -- baseline|monitoring|reversal
  indicator           text NOT NULL,        -- ndvi|sar_water|burn|canopy|area|...
  acquisition_time    timestamptz NOT NULL,
  algorithm_version   text NOT NULL,        -- semver of the processing code
  model_version       text,                 -- semver of any ML model applied
  parameter_hash      text NOT NULL,        -- hash of all config/thresholds used
  status              text NOT NULL,        -- provisional|final|superseded|failed
  supersedes_id       uuid REFERENCES observation(observation_id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (plot_id, scene_id, indicator, algorithm_version, model_version, parameter_hash)
);

CREATE TABLE observation_result (
  observation_id        uuid PRIMARY KEY REFERENCES observation(observation_id),
  value_numeric         numeric,
  value_categorical     text,
  value_json            jsonb,              -- for time-series indicators e.g. AWD
  total_pixels          integer NOT NULL,
  valid_pixels          integer NOT NULL,
  valid_pixel_fraction  numeric NOT NULL,
  edge_pixel_fraction   numeric,
  confidence            numeric NOT NULL,   -- 0..1
  confidence_basis      jsonb NOT NULL      -- which factors drove the score
);

CREATE TABLE reconciliation (
  reconciliation_id   uuid PRIMARY KEY,
  observation_id      uuid NOT NULL REFERENCES observation(observation_id),
  ground_claim_ref    text NOT NULL,        -- pointer into VNV's ground record
  ground_value        jsonb NOT NULL,       -- snapshot at comparison time
  discrepancy_type    text,                 -- none|magnitude|categorical|missing
  discrepancy_value   numeric,
  review_flag         text NOT NULL,        -- ok|needs_review|needs_data|escalate
  review_reason       text,
  resolved_by         text,                 -- human reviewer, NULL until reviewed
  resolved_at         timestamptz,
  resolution          text                  -- VNV's decision, free text + code
);
```

**Why `parameter_hash` is in the uniqueness key:** algorithm version alone is insufficient. The same code with a different cloud-probability threshold produces a different answer. Hashing the full effective configuration makes "same inputs, same code, same config" genuinely reproducible, and makes a threshold change produce a *new* observation rather than silently altering an old one.

**Why `ground_value` is snapshotted, not referenced:** the ground record may be corrected later. The reconciliation must record what was compared *at the time of comparison*, or the audit trail becomes unreconstructable.

**Why the reconciliation is a separate table from the observation:** an observation is a measurement of the world. A reconciliation is a judgement about a claim. The same observation may be compared against a corrected ground claim later, producing a second reconciliation. Merging them would conflate physics with bookkeeping.

**Confidence scoring** — must be composite and explainable, not a single opaque number. **[JUDGEMENT]** Factors:

```
confidence = f(
  valid_pixel_fraction,        -- how much of the plot was actually seen
  edge_pixel_fraction,         -- how much is spectrally mixed
  plot_area_vs_resolution,     -- is the plot big enough for this sensor
  processing_tier,             -- RT/T2 penalised vs T1
  temporal_gap,                -- days since last valid observation
  sensor_appropriateness,      -- SAR for water = high; optical for water = lower
  model_uncertainty            -- classifier probability, where applicable
)
```

Store `confidence_basis` as JSON so a reviewer can see *why* confidence was 0.4, not just that it was.

**Discrepancy is not a verdict.** The brief is explicit: the satellite layer does not set thresholds or decide outcomes. So `review_flag` values mean:
- `ok` — observed and reported agree within tolerance
- `needs_review` — they disagree; a human must look
- `needs_data` — insufficient valid observation to compare at all (**this is the P4 case — never a silent pass**)
- `escalate` — high-confidence disagreement on a high-stakes indicator (EUDR deforestation, sugarcane burn)

Thresholds that map raw discrepancy to these flags are **VNV's governance parameters**, versioned and stored, not hard-coded constants.

#### Reversal monitoring and the temporary/permanent distinction

The brief specifically warns against treating every disturbance signal as a loss event — a drought may look like decline and recover. Encode this:

```
disturbance signal detected
    ↓
classify: natural/temporary vs. human/permanent
    ↓ requires: multiple confirming passes (≥2 independent acquisitions)
    ↓           seasonal-context comparison (vs. same plot's historical phenology,
    ↓                                        and vs. neighbouring control plots)
    ↓           persistence window (does the signal recover?)
    ↓
if permanent AND confirmed → escalate → human decision → buffer drawdown
if temporary or unconfirmed → record, monitor, do NOT trigger
```

**The control-plot comparison is the strongest single discriminator.** If a regional drought is depressing NDVI, neighbouring plots show it too; if one plot alone declines, it is plot-specific. This is cheap to compute and dramatically reduces false positives. **[JUDGEMENT]** Build this in from the start; retrofitting it after a false buffer drawdown is far more expensive.

---

### L9 — Serving

**Two distinct consumers, two distinct interfaces.**

1. **VNV platform integration** — the GIS & Spatial module consumes observations and reconciliations. Per the brief's own options, this can be a direct API, an adapter into the existing ingestion pipeline, or the bulk-upload path. **[JUDGEMENT]** API is right long-term; but starting with the existing bulk-upload path (which already has a review/approval step) is the lower-risk Phase 1 integration, because it reuses machinery VNV has already built and tested.

2. **Audit/evidence export** — given a plot and date range, produce a complete evidence package: every observation, its scene provenance, algorithm and model versions, parameter hash, confidence basis, reconciliation history, and links to the cached source imagery. This is what gets handed to a verifier. **Design it as a first-class product feature, not a report you generate under pressure the week before an audit.**

**Read model.** Observation queries by `(plot_id, indicator, time_range)` where `status != 'superseded'` are the hot path. **[JUDGEMENT]** A materialised view or a separate read table keyed on this is worth building once the observation table passes a few million rows; premature before that.

---

## 5. Cross-cutting concerns

### 5.1 Cross-sensor harmonisation

Sentinel-2 NDVI and Landsat NDVI over the same field on the same day will differ. Causes: different spectral response functions (band centres and widths differ), different spatial resolution (10 m vs 30 m — a different pixel mixture), different overpass times (different sun angle, different canopy moisture state), different atmospheric correction chains.

**Consequences for design:**
- Never merge sensors into one time series without an explicit harmonisation step, recorded as an algorithm version.
- Where a harmonisation coefficient set is applied, store which one — coefficients from the published literature (e.g. HLS-style adjustments) are regionally and land-cover dependent.
- **[JUDGEMENT]** For change detection, prefer within-sensor comparison. Use cross-sensor only to fill gaps, and flag those observations as harmonised.
- Landsat Collection 2 Tier 1 being inter-calibrated across Landsat sensors means L8↔L9 harmonisation is far less problematic than Landsat↔Sentinel.

### 5.2 Reprocessing and provider drift

**Triggers for reprocessing:**
1. Provider reprocesses a scene (USGS explicitly recommends replacing derived products)
2. Algorithm version bump
3. Model retrain
4. Threshold/parameter change
5. Plot geometry correction
6. Ground claim correction (reconciliation only, not observation)

**Mechanism:** a reprocessing job enqueues affected `(plot, scene, indicator)` triples, produces new observations with new version stamps, and marks predecessors superseded. Nothing is deleted.

**Impact assessment before executing.** A model retrain touching 100,000 plots × 3 years × 4 indicators is a large batch. The system should be able to answer "how many observations would this change, and how many back an already-issued credit?" *before* the job runs. Reprocessing that alters the evidential basis of issued credits is a governance event, not a routine job.

**Provider schema drift detection.** **[JUDGEMENT]** Run a daily canary: fetch a known scene through each adapter and assert the normalised output matches a stored fixture. Schema changes then surface as a failing canary rather than as silently wrong data three weeks later.

### 5.3 Observability

**[JUDGEMENT]** Metrics that actually matter here (Prometheus/Grafana, which VNV already runs):

| Metric | Why |
|---|---|
| Discovery→availability latency, per provider | Detects provider degradation before users do |
| Acquisition→observation latency, p50/p95/p99 | The real SLA |
| Scenes in each state machine state | Queue health, stuck work |
| `needs_review` rate, by crop and indicator | A spike means either real events or a broken model |
| `needs_data` rate | Cloud-cover reality check; sustained high = coverage problem |
| Valid-pixel-fraction distribution | Data quality trend |
| CDSE quota consumption vs. 12 TB rolling window | **Alert at 70%** — hitting it degrades to 1 MB/s |
| AWS requester-pays spend, daily | Cost runaway detection |
| Adapter canary pass/fail | Provider drift |
| Superseded-observation rate | How much rework the pipeline is doing |

**Do not measure latency from "when we noticed."** Measure from `acquisition_time`. Measuring from discovery hides discovery lag, which is exactly the failure you most need to see.

### 5.4 Failure modes

| Failure | Detection | Response |
|---|---|---|
| Provider API down | Adapter health check | Queue backs up; alert; no data loss (ledger persists) |
| CDSE quota exhausted | Quota metric | Throttle to essential lanes; escalate to CREODIAS decision |
| Requester-pays cost spike | Daily spend metric | Circuit-break Landsat direct reads; fall back to cache/CDSE mirror |
| Persistent cloud cover | `needs_data` rate | Flag plots; escalate to field verification; do not fabricate |
| Invalid plot geometry | `geom_valid=false` | Skip + flag for data correction; never guess a fix |
| Provider reprocessed scene | New `product_generation_dt` | Auto-enqueue reprocessing; supersede |
| Adapter schema drift | Canary failure | Halt that provider's ingestion; fix adapter; backfill |
| Model produces implausible value | Range/plausibility assertions | Quarantine observation; `needs_review` |
| Duplicate processing | Idempotency key collision | No-op; log |
| Worker crash mid-scene | Lease expiry | Requeue; idempotency makes retry safe |

**Plausibility assertions deserve emphasis.** NDVI outside [-1, 1], canopy cover >100%, a rice plot flooded for 400 days, an area discrepancy of 50×. These indicate a bug, not a finding. Assert and quarantine rather than storing nonsense with a confidence score attached.

### 5.5 Security and compliance

- **Credential management.** CDSE OAuth, USGS M2M tokens, AWS IAM roles. Use IRSA (IAM Roles for Service Accounts) on EKS rather than static keys. Token pooling to respect the 100-session cap.
- **Plot geometry is sensitive data.** Smallholder plot boundaries are personally identifying in effect — they locate a specific farmer's land. Treat as PII: access control, audit logging on reads, and a considered retention/deletion policy. This intersects with EUDR due-diligence data handling and Indian data-protection norms.
- **Evidence integrity.** Checksums on cached scenes. **[JUDGEMENT]** For credit-backing evidence, consider S3 Object Lock in compliance mode — it makes "the evidence was altered" structurally impossible to claim.
- **Attribution.** Copernicus and Landsat both carry attribution expectations. Landsat products carry no use restrictions but USGS acknowledgement is encouraged; Copernicus has its own legal notice. Any product or report VNV ships should carry proper attribution.

---

## 6. Cost model

**[JUDGEMENT] throughout this section.** These are structural, not quoted.

### One-time build


### Recurring, at steady state

**Fixed floors regardless of portfolio size:**
- CDSE: ₹0 within quota
- AWS baseline (EKS, RDS/PostGIS, S3, monitoring): **[JUDGEMENT]** $1,500–4,000/month depending on worker fleet
- Human review team (2–4 analysts): ₹15–40 L/year

**Variable:**
- S3 storage: grows monotonically with archive. **[JUDGEMENT]** ~$25/TB/month Standard-IA, less on Glacier IR.
- Requester-pays Landsat: proportional to scene fetches, minimised by caching
- CREODIAS overflow: only if CDSE quota is exceeded

**Benchmarks from comparable deployments:** an Indian tree/agroforestry dMRV programme reported ₹52/ha/year for satellite verification versus ₹380/ha/year for manual field audit. Traditional field-only MRV runs $4–7/ha/year and can consume 25–40% of a carbon project's budget.

**Realistic fully-loaded range: $1–10/ha/year**, with coffee/cocoa at the top (custom models, EUDR rigour) and cotton/tea at the bottom.

**Sanity check at scale:**

| Portfolio | Estimated recurring/year |
|---|---|
| 10,000 ha | ~$40–150k (dominated by fixed floors) |
| 50,000 ha | ~$90–550k |
| 100,000 ha | ~$150k–1M+ |

**Honest comparison against GEE.** GEE commercial costs $500–2,000/month platform fee plus EECU-hour usage. Self-hosting eliminates that but adds AWS infra, engineering salaries, and permanent maintenance burden. **Self-hosting is not automatically cheaper.** It becomes cheaper at sustained scale and when you need control GEE cannot give — provenance, caching, custom SAR chains, audit reproducibility. Those control requirements, not cost, are the real argument here.

---

## 7. Phasing

**Do not build all of §4 before validating any science.**

### Phase 1 — Scientific validation (months 0–5)
- **Tool: GEE** (commercial licence), plus notebooks. No production infrastructure.
- **Scope: rice AWD only.** Highest carbon value, cleanest technique, cloud-independent sensor.
- **Deliverable:** does S1-based water-regime detection agree with ground water logs on real VNV plots, at what accuracy, with what false-positive rate?
- **Gate:** if this fails, the programme's core premise needs rethinking before any infrastructure spend.

### Phase 2 — Agroforestry classifier prototype (months 3–9, overlapping)
- **Tool: GEE.** Highest-risk component, EUDR critical path.
- **Deliverable:** a coffee/cocoa agroforestry classifier validated against ground truth, with an honest confusion matrix against both "forest" and "non-forest" error modes.
- **Gate:** EUDR compliance depends entirely on this. If it can't reach defensible accuracy, that changes the EUDR strategy, not just the tech stack.

### Phase 3 — Production core (months 6–14)
- Build L0–L4 and L6, L8, L9. One sensor pair (S1 + S2), one crop (rice).
- Full provenance, supersession, caching, internal STAC from day one — these cannot be retrofitted cheaply.
- **Gate:** end-to-end rice pipeline running in production with audit-quality provenance.

### Phase 4 — Sensor and crop expansion (months 12–22)
- Add Landsat 8/9 (with correct tier handling per platform).
- Add fire detection, canopy, area indicators.
- Roll out coffee/cocoa (EUDR), then sugarcane/cotton, then tea last per the brief's own prioritisation.

### Phase 5 — Reversal monitoring and buffer integration (months 18–24)
- Long-horizon monitoring, disturbance classification, control-plot comparison, buffer drawdown workflow.
- This is last because it requires the credit-issuance side to exist first.

**Total: 18–24 months to defensible full coverage.** Anything materially shorter is either an MVP being described as complete, or EUDR rigour being cut.

---

## 8. Is this actually best practice? — honest assessment

The user asked specifically whether this method is best practice across engineering, system design, remote sensing, and infrastructure. Direct answers:

**Established best practice, not controversial:**
- STAC for discovery — the de facto community standard, exactly what it was designed for
- COG for raster access — USGS delivers Collection 2 as COG specifically to enable partial reads
- PostGIS + GIST for spatial joins — mature, boring, correct
- Queue + idempotent workers over monolithic cron — standard distributed systems practice
- Adapter/anti-corruption layer between external APIs and domain logic — standard DDD
- Immutable append-only records with supersession for audit domains — standard in finance, standard in regulated data
- Sensor-specific SAR pre-processing chain — this is simply what SAR requires; the steps listed are the conventional ESA SNAP-equivalent chain
- Caching source data for reproducibility — standard in any EO operational system

**Defensible but with real alternatives:**
- Self-hosting versus GEE/Sentinel Hub/openEO. Fully managed platforms are a legitimate choice and materially reduce engineering burden. The case for self-hosting rests on provenance control and long-horizon audit reproducibility, not on cost. A smaller team should seriously consider staying on managed infrastructure longer than Phase 3 suggests.
- Own STAC catalogue versus just a database table. At VNV's likely scale, a plain Postgres scene table may suffice; a full internal STAC catalogue is more valuable if you expect to expose data to other tools (QGIS, external auditors, partner systems).
- Building the SAR chain in-house versus consuming pre-processed RTC products.

**Where this design is opinionated beyond consensus:**
- Insisting on `parameter_hash` in the observation uniqueness key is stricter than most EO pipelines. It is justified here specifically because carbon credits are audited financial instruments; it would be over-engineering for a research pipeline.
- The control-plot comparison for disturbance classification is good practice but not universal.
- Minimum-plot-size thresholds are a judgement call; different programmes set them differently.

**Where I have genuine uncertainty and would not defend a position:**
- Whether Sentinel-2's effective revisit in Indian monsoon conditions is sufficient for the crop-calendar checks the brief wants, for all six crops. This needs measurement against real cloud statistics for the specific districts, not assumption.
- Whether SOC estimation from bare-soil composites reaches usable confidence for any of these crops. The brief already treats it as flag-only, which is the right posture; my honest view is it may not clear even that bar without substantial soil sampling.
- Whether an agroforestry classifier can reach EUDR-defensible accuracy for cocoa specifically, given plot fragmentation. This is the single largest unknown in the programme.

---

## 9. Open questions for the team

1. What is the target portfolio size, per crop, at full scale? Every cost figure above is a range until this is answered.
2. Which AWS region does VNV operate in? This determines the Landsat egress strategy.
3. Does VNV have, or can it obtain, ground-truth training data for shade-grown coffee and cocoa in the specific regions in scope?
4. What is the existing GIS & Spatial module's data model, and how closely can the scene/observation schema align with it?
5. Who owns the governance thresholds that map discrepancy → review flag? This is explicitly not the satellite layer's decision, so someone must own it.
6. What is the retention obligation for credit-backing evidence under the applicable standards? This sets the S3 lifecycle policy floor.
7. Is there appetite to run Phase 1 and 2 entirely on GEE, accepting the commercial licence cost, before any infrastructure commitment?

---

## 10. Summary

The architecture is: **STAC for discovery → provider adapters → normalised ledger → queue → cached COGs in own storage → sensor-specific processing → exact-polygon extraction → versioned immutable observations → reconciliation with explicit review flags → audit-grade serving.**

The three things that make it fit for carbon dMRV rather than generic EO:

1. **Supersession instead of overwriting** — because a credit issued in 2027 must be defensible in 2035.
2. **Caching as evidence preservation** — because external URLs are not an audit trail.
3. **Evidence not verdict** — because the brief says so, and because a satellite that automatically docks a farmer's credits is a system nobody will trust.

The largest risks are not infrastructural. They are the coffee/cocoa agroforestry classifier, the honest usability of optical revisit under Indian cloud cover, and the ongoing engineering cost of operating a bespoke EO platform. Validate the science in GEE first; build the platform only for what has been proven to work.
