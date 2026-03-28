# Zenvoy Data Pipeline And Score Generalization Context

This document describes the backend pipeline as it exists in the current codebase on branch `dev-env`. It focuses on:

- where routing inputs come from
- how crime and visual signals are produced
- how those signals are used at decision time
- what kind of score generalization logic is used

It is intentionally implementation-oriented, not aspirational.

## 1. System Overview

The backend combines three signal sources:

1. Road graph data from a prebuilt GraphML walking graph.
2. Crime reports stored in MongoDB.
3. Visual safety metadata attached to graph edges and nodes during preprocessing.
4. A merged crime-type prior built from official Delhi Police counts plus local geocoded seed incidents.

The runtime score generation is now implemented as an explicit pipeline in:

- [app/services/score_pipeline.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/services/score_pipeline.py)

At request time, the routing engine computes:

- a `fast` route using physical edge length
- a `safe` route using a custom weighted safety cost

For each route, the backend returns:

- `coordinates`
- `distance_km`
- `estimated_time_min`
- `score_breakdown`
- `crime_reports`
- `origin_preview`
- `destination_preview`

The `score_breakdown` also includes a `decision_trace` object so the scoring path is inspectable.

## 2. Data Sources

### 2.1 Graph Data

Configured in [app/core/config.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/core/config.py) via `GRAPH_PATH`, defaulting to:

`app/data/delhi_walk.graphml`

Loaded during FastAPI startup in [app/main.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/main.py) through:

- `load_graph(...)` in [app/services/routing.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/services/routing.py)

The graph is a NetworkX / OSMnx walking graph. Nodes carry coordinates:

- `y` = latitude
- `x` = longitude

Edges may also carry precomputed attributes such as:

- `length`
- `light_score`
- `visual_score`
- `visual_score_available`

### 2.2 Crime Reports

MongoDB document model in [app/models/crime.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/models/crime.py):

- `lat`
- `lng`
- `type`
- `severity`
- `description`
- `timestamp`

Crime data reaches MongoDB in two ways:

1. Seed file load at startup from `app/data/crime_data.json`
2. Optional daily ingestion from Delhi news via the crime pipeline

### 2.3 Merged Crime-Type Prior

The backend now merges two crime data layers into one calibration source for score generalization:

1. Official aggregate Delhi Police counts
2. Local geocoded incident seed counts

The merged prior is documented in:

- [app/data/crime_type_priors_merged.json](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/data/crime_type_priors_merged.json)

Official aggregate counts are stored in:

- [app/data/delhi_police_crime_stats_2022.json](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/data/delhi_police_crime_stats_2022.json)

The geocoded incident seed file remains:

- [app/data/crime_data.json](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/data/crime_data.json)

These are not collapsed into one fake incident table. Instead, they are merged into one type-prior layer for app crime types such as:

- `snatch`
- `robbery`
- `assault`
- `harassment`
- `stalking`

The merge is useful because:

- official counts provide city-scale prevalence
- seed data provides support for app categories that are geocoded in the route engine
- categories missing in the official mapping, such as `stalking`, no longer collapse to an uninformative default if the local dataset supports them

Current blend:

- `official_score = official_count / max_official_count`
- `seed_score = seed_count / max_seed_count`
- `blended_score = official_score * 0.7 + seed_score * 0.3`
- `weight = 0.7 + blended_score * 0.9`

This merged `weight` is what now calibrates incident contribution during route scoring.

### 2.4 Visual Metadata

Visual metadata is generated offline by [scripts/street_view_preprocessing.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/scripts/street_view_preprocessing.py).

That script:

1. Loads the graph.
2. Samples graph edges.
3. Fetches nearby Mapillary images.
4. Runs YOLOv8 on those images.
5. Converts detections into a bounded `visual_score`.
6. Stores edge and node metadata back into GraphML.

Node-level preview metadata:

- `image_url`
- `image_available`

Edge-level visual metadata:

- `visual_score`
- `visual_score_available`
- `visual_score_source`

## 3. Runtime Request Pipeline

The runtime request pipeline for `/route/fast` and `/route/safe` is implemented in [app/api/v1/routes.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/api/v1/routes.py).

### Step 1: Validate graph availability

The endpoint reads `request.app.state.graph`. If the graph failed to load at startup, the API returns `503`.

### Step 2: Snap origin and destination to graph nodes

`get_nearest_node(...)` in [app/services/routing.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/services/routing.py) uses:

- `ox.distance.nearest_nodes(G, X=lng, Y=lat)`

### Step 3: Load all crime reports

The route endpoints load crimes from MongoDB with:

- `await CrimeReport.find_all().to_list()`

This is currently an all-record fetch. There is no spatial prefilter at query time.

### Step 4: Compute route

- `compute_fast_route(...)` uses shortest path weighted by `length`
- `compute_safe_route(...)` uses shortest path weighted by `SafetyScorer.edge_weight_func`

### Step 5: Build response payload

Each route response includes:

- route geometry
- travel distance/time
- route-level score breakdown
- serialized nearby crime reports for that route
- origin/destination preview images
- an explicit decision trace describing how the final score was assembled

## 4. Crime Ingestion Pipeline

Implemented in [app/services/crime_pipeline.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/services/crime_pipeline.py).

This is an asynchronous background ingestion flow intended to run on a schedule, although the scheduler block is currently commented out in [app/main.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/main.py).

### 4.1 News collection

`fetch_delhi_crime_news()`:

- uses EventRegistry
- narrows results to Delhi
- filters on street-crime style keywords
- excludes categories such as cyber fraud, politics, court, terror, rape
- returns a compact text bundle of headline + snippet entries

### 4.2 LLM extraction

`extract_crimes_from_news(news_text)`:

- sends the news bundle to Gemini
- asks for structured JSON only
- expects inferred coordinates and severity
- parses the returned JSON array
- discards malformed items

Expected extracted fields:

- `lat`
- `lng`
- `type`
- `severity`
- `description`
- plus optional contextual fields like neighborhood and source date

### 4.3 Deduplication and insert

`process_daily_crimes()`:

1. fetches news
2. extracts incidents
3. validates/coerces each crime record
4. checks for an existing record with same `lat`, `lng`, `type`, and `description`
5. inserts only new records

This is simple application-level deduplication, not a robust entity-resolution pipeline.

## 5. Visual Safety Preprocessing Pipeline

Implemented in [scripts/street_view_preprocessing.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/scripts/street_view_preprocessing.py).

### 5.1 Image retrieval

For each sampled edge midpoint:

- query Mapillary around the midpoint
- retry with increasing radii: `500`, `1000`, `2000` meters
- cache the chosen image by rounded coordinates

### 5.2 Object detection

YOLOv8 is run against the image URL. Detected objects are converted into a visual score.

### 5.3 Visual score mapping

Current heuristic:

- `person` reduces score
- `motorcycle` reduces score more strongly
- `car` increases score slightly
- `truck` increases score slightly more

The output is clamped to `[-0.5, 0.5]`.

Important: this is not a learned route-safety model. It is a hand-authored proxy heuristic over object detections.

### 5.4 Missing image handling

If no nearby image is found:

- `visual_score = 0.0`
- `visual_score_available = False`

This means "no evidence", not "unsafe".

## 6. Decision Making At Routing Time

The actual decision-making logic is implemented in [app/services/safety.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/services/safety.py).

The main implementation lives in:

- [app/services/score_pipeline.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/services/score_pipeline.py)

This is a deterministic heuristic scoring system, not a trained ML inference model.

The explicit stages are:

1. load merged crime-type priors
2. extract segment-level crime evidence
3. estimate edge-level risk breakdown
4. aggregate route evidence
5. normalize components into a final route score
6. emit a decision trace for inspection

### 6.1 Fast route decision rule

Fast route uses:

`networkx.shortest_path(..., weight="length")`

This is pure distance optimization.

### 6.2 Safe route decision rule

Safe route uses:

`networkx.shortest_path(..., weight=scorer.edge_weight_func)`

For each edge, the cost is:

`length * (1 + crime_penalty + darkness_penalty - visual_bonus)`

Where:

- `crime_penalty` is derived from nearby crimes
- `darkness_penalty` is derived from `light_score`
- `visual_bonus` is derived from positive visual evidence

The safe route is therefore a shortest-path optimization over a custom risk-adjusted edge cost.

## 7. How Crime Risk Is Generalized

This is the core "score generalization" behavior.

The system does not predict route safety with a learned statistical model. Instead, it generalizes from local incident evidence to route safety using spatial heuristics.

### 7.1 Edge-level spatial generalization

For each edge:

1. The actual route segment geometry is used.
2. Crimes within `90` meters of that segment are treated as relevant.
3. Each relevant crime contributes risk based on:
   - severity
   - distance from the segment
   - merged crime-type prior weight

The per-crime contribution is:

`(0.35 + severity) * type_weight * proximity_weight`

Where:

`proximity_weight = max(0, 1 - distance / 90)`

So the system generalizes incident risk by:

- assuming nearby crimes are informative for adjacent street segments
- decaying their influence with distance
- weighting severe incidents more heavily
- calibrating contribution by official citywide prevalence of the incident type

This is a proximity-weighted local-risk transfer heuristic.

### 7.2 Edge-level crime risk cap

The summed risk per edge is capped at:

`MAX_EDGE_CRIME_RISK = 3.0`

This prevents a single hotspot from making edge cost unbounded.

### 7.3 Merged type calibration

The backend loads both the official Delhi Police aggregate file and the local geocoded seed file, then computes a merged per-type prior table.

Current behavior:

- mapped crime types with higher official counts get larger weights
- categories that are frequent in the local seed set also receive meaningful support
- unmapped or unsupported types fall back to a conservative default weight
- the prior adjusts the impact of incident categories, but does not create risk where there are no nearby incidents

This means the merged prior acts as a calibration layer, not as a replacement for route-local evidence.

### 7.4 Darkness generalization

Darkness risk is computed from:

`darkness_penalty = (1 - light_score) * 2.2`

This assumes low light is a transferable proxy for reduced perceived safety.

### 7.5 Visual generalization

If visual evidence is available:

`visual_bonus = max(0, visual_score) * 0.35`

Negative visual scores do not directly add extra penalty at route-decision time. They only fail to contribute a positive bonus.

This makes visual evidence a conservative positive adjustment rather than a dominant penalty source.

## 8. How Route-Level Score Generalization Works

The route-level score returned to the frontend is not the same object as the pathfinding cost. It is a human-readable summary score derived from the chosen path.

### 8.1 Route aggregation

For each edge on the selected route, the backend accumulates:

- darkness penalty
- edge crime risk
- visual score

It also collects all nearby crimes across the route and deduplicates them into a route crime list.

### 8.2 Deduplicated route crime reports

The route payload now includes serialized nearby crimes with:

- `id`
- `lat`
- `lng`
- `type`
- `severity`
- `description`
- `timestamp`
- `distance_m`

If the same crime is near multiple edges, the route keeps the closest occurrence.

### 8.3 Normalization

The route-level aggregates are converted to normalized components:

- `crime_risk = clamp(avg_crime / 3.0, 0, 1)`
- `darkness_risk = clamp(avg_darkness / 2.2, 0, 1)`
- `visual_safety = clamp(avg_visual + 0.5, 0, 1)` when visual evidence exists, otherwise `0.5`

### 8.4 Weighted route safety score

Combined route risk is:

`combined_risk = crime_risk * 0.6 + darkness_risk * 0.25 + (1 - visual_safety) * 0.15`

Final route score is:

`overall_safety_score = clamp((1 - combined_risk) * 10, 0, 10)`

This means:

- crime risk is the dominant factor
- darkness is the secondary factor
- visual evidence is a smaller stabilizing factor

In practical terms, the backend is using weighted heuristic aggregation with normalization, not a probabilistic model.

### 8.5 Decision trace

The score pipeline now returns:

- `decision_trace.model`
- `decision_trace.stages`
- `decision_trace.weights`
- `decision_trace.normalized_components`

This makes the score generation process auditable and easier to tune without changing the frontend route contract.

## 9. What Type Of Decision Making This Is

The current system uses:

- rule-based decision making
- deterministic cost-sensitive pathfinding
- proximity-based spatial generalization
- merged official-plus-local prior calibration
- weighted multi-factor heuristic aggregation

It does **not** use:

- supervised learning
- reinforcement learning
- Bayesian inference
- graph neural networks
- calibrated probability estimation

The decision logic is best described as:

`shortest-path optimization over hand-engineered safety costs, followed by route-level heuristic score summarization`

## 10. Why Fast And Safe Scores Can Differ

Fast and safe scores differ when the two route geometries expose the traveler to different combinations of:

- nearby crime density and severity
- darkness
- positive visual evidence

If the graph offers only one realistic path, both endpoints may still return the same or very similar route and therefore similar scores. That is expected.

If the graph offers alternatives, the stronger edge penalty model should now make the safe route more willing to avoid risky shortcuts.

## 11. Current Limitations

The current pipeline has several important limitations:

- crime lookup is done in Python over all loaded crime reports rather than a geospatial Mongo query per route segment
- route crime relevance still uses a fixed corridor threshold rather than full map-matching or polygon buffering
- visual safety is based on a simple object-to-score heuristic, not scene understanding
- news-to-crime extraction depends on LLM output quality and inferred coordinates
- deduplication is approximate and based on a small field set
- route score is heuristic and should not be interpreted as a calibrated safety probability

## 12. Suggested Language For Team Communication

If this needs to be explained in demos, docs, or reviews, the accurate short version is:

> Zenvoy uses deterministic pathfinding with hand-engineered safety costs. Crime reports are spatially generalized to nearby road segments using severity- and distance-weighted heuristics, then combined with lighting and visual metadata to produce a route safety score from 0 to 10.

## 13. Key Implementation Files

- [app/main.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/main.py)
- [app/api/v1/routes.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/api/v1/routes.py)
- [app/services/routing.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/services/routing.py)
- [app/services/safety.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/services/safety.py)
- [app/services/score_pipeline.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/services/score_pipeline.py)
- [app/services/crime_pipeline.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/services/crime_pipeline.py)
- [scripts/street_view_preprocessing.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/scripts/street_view_preprocessing.py)
- [app/models/crime.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/models/crime.py)
- [app/core/db.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/core/db.py)
- [app/core/config.py](/home/uday-pratap-singh/Desktop/zenvoy/backend/app/core/config.py)
