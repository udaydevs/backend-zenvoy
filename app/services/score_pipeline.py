import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


CRIME_RADIUS_METERS = 90
MAX_EDGE_CRIME_RISK = 3.0
DEFAULT_TYPE_WEIGHT = 0.8
BASE_DIR = Path(__file__).resolve().parents[2]
DELHI_POLICE_STATS_PATH = BASE_DIR / "app" / "data" / "delhi_police_crime_stats_2022.json"
CRIME_DATA_PATH = BASE_DIR / "app" / "data" / "crime_data.json"


@dataclass(frozen=True)
class CrimeEvidence:
    crime: object
    distance_m: float
    severity: float
    crime_type: str
    crime_type_weight: float


@dataclass(frozen=True)
class EdgeRiskBreakdown:
    darkness_penalty: float
    crime_penalty: float
    visual_bonus: float
    visual_score: float
    visual_available: bool


def _load_seed_type_counts():
    try:
        with CRIME_DATA_PATH.open() as crime_data_file:
            crime_data = json.load(crime_data_file)
    except Exception:
        return {}

    return {
        str(crime_type): float(count)
        for crime_type, count in Counter(
            item.get("type", "unknown") for item in crime_data if item.get("type")
        ).items()
    }


def _normalize_counts(counts):
    if not counts:
        return {}

    max_count = max(counts.values())
    if max_count <= 0.0:
        return {}

    return {
        crime_type: float(count) / float(max_count)
        for crime_type, count in counts.items()
    }


def _load_merged_crime_type_priors():
    try:
        with DELHI_POLICE_STATS_PATH.open() as stats_file:
            data = json.load(stats_file)
    except Exception:
        data = {}

    official_counts = {
        crime_type: float(details.get("total_count", 0.0))
        for crime_type, details in data.get("app_signal_mapping", {}).items()
    }
    seed_counts = _load_seed_type_counts()
    official_norm = _normalize_counts(official_counts)
    seed_norm = _normalize_counts(seed_counts)
    all_types = sorted(set(official_counts) | set(seed_counts))

    priors = {}
    for crime_type in all_types:
        official_score = official_norm.get(crime_type, 0.0)
        seed_score = seed_norm.get(crime_type, 0.0)
        blended_score = (official_score * 0.7) + (seed_score * 0.3)
        weight = round(0.7 + (blended_score * 0.9), 3)
        priors[crime_type] = {
            "official_count": int(official_counts.get(crime_type, 0.0)),
            "seed_count": int(seed_counts.get(crime_type, 0.0)),
            "official_score": round(official_score, 3),
            "seed_score": round(seed_score, 3),
            "blended_score": round(blended_score, 3),
            "weight": weight,
        }

    return priors


MERGED_CRIME_TYPE_PRIORS = _load_merged_crime_type_priors()


def _coerce_crime_value(crime, field_name, default=None):
    if isinstance(crime, dict):
        return crime.get(field_name, default)
    return getattr(crime, field_name, default)


def get_crime_coordinates(crime):
    lat = _coerce_crime_value(crime, "lat")
    lng = _coerce_crime_value(crime, "lng")
    if lat is None or lng is None:
        return None, None

    try:
        return float(lat), float(lng)
    except Exception:
        return None, None


def get_crime_severity(crime):
    severity = _coerce_crime_value(crime, "severity", 0.5)
    try:
        severity = float(severity)
    except Exception:
        severity = 0.5
    return max(0.0, min(1.0, severity))


def get_crime_type_weight(crime):
    crime_type = str(_coerce_crime_value(crime, "type", "unknown"))
    return MERGED_CRIME_TYPE_PRIORS.get(crime_type, {}).get("weight", DEFAULT_TYPE_WEIGHT)


def crime_identifier(crime, fallback_index):
    crime_id = _coerce_crime_value(crime, "id") or _coerce_crime_value(crime, "_id")
    if crime_id is not None:
        return str(crime_id)

    lat, lng = get_crime_coordinates(crime)
    crime_type = _coerce_crime_value(crime, "type", "unknown")
    timestamp = _coerce_crime_value(crime, "timestamp", "")
    return f"{fallback_index}:{lat}:{lng}:{crime_type}:{timestamp}"


def serialize_crime_report(crime, fallback_index, distance_m):
    timestamp = _coerce_crime_value(crime, "timestamp")
    if hasattr(timestamp, "isoformat"):
        timestamp = timestamp.isoformat()

    lat, lng = get_crime_coordinates(crime)

    return {
        "id": crime_identifier(crime, fallback_index),
        "lat": lat,
        "lng": lng,
        "type": _coerce_crime_value(crime, "type", "unknown"),
        "severity": get_crime_severity(crime),
        "crime_type_weight": get_crime_type_weight(crime),
        "description": _coerce_crime_value(crime, "description", ""),
        "timestamp": timestamp,
        "distance_m": round(distance_m, 1),
    }


def _project_to_local_meters(lat, lng, ref_lat):
    meters_per_degree_lat = 111320.0
    meters_per_degree_lng = 111320.0 * math.cos(math.radians(ref_lat))
    return lng * meters_per_degree_lng, lat * meters_per_degree_lat


def distance_to_segment_meters(lat, lng, start_lat, start_lng, end_lat, end_lng):
    ref_lat = (start_lat + end_lat + lat) / 3.0
    px, py = _project_to_local_meters(lat, lng, ref_lat)
    ax, ay = _project_to_local_meters(start_lat, start_lng, ref_lat)
    bx, by = _project_to_local_meters(end_lat, end_lng, ref_lat)

    abx = bx - ax
    aby = by - ay
    ab_len_sq = (abx * abx) + (aby * aby)
    if ab_len_sq == 0:
        return math.hypot(px - ax, py - ay)

    apx = px - ax
    apy = py - ay
    t = max(0.0, min(1.0, ((apx * abx) + (apy * aby)) / ab_len_sq))
    closest_x = ax + (t * abx)
    closest_y = ay + (t * aby)
    return math.hypot(px - closest_x, py - closest_y)


def read_visual_score(edge_data):
    visual_available = edge_data.get("visual_score_available", True)
    if isinstance(visual_available, str):
        visual_available = visual_available.lower() == "true"

    visual_score = edge_data.get("visual_score", 0.0)
    try:
        visual_score = float(visual_score)
    except Exception:
        visual_score = 0.0

    return visual_score, bool(visual_available)


class ScoreGenerationPipeline:
    def __init__(self, graph, crimes):
        self.graph = graph
        self.crimes = crimes
        self.crime_type_priors = MERGED_CRIME_TYPE_PRIORS

    def get_edge_crime_evidence(self, u, v, radius_meters=CRIME_RADIUS_METERS):
        nearby_crimes = []
        y_u, x_u = self.graph.nodes[u].get("y"), self.graph.nodes[u].get("x")
        y_v, x_v = self.graph.nodes[v].get("y"), self.graph.nodes[v].get("x")

        if y_u is None or x_u is None or y_v is None or x_v is None:
            return []

        for crime in self.crimes:
            c_lat, c_lng = get_crime_coordinates(crime)
            if c_lat is None or c_lng is None:
                continue

            distance = distance_to_segment_meters(c_lat, c_lng, y_u, x_u, y_v, x_v)
            if distance > radius_meters:
                continue

            nearby_crimes.append(
                CrimeEvidence(
                    crime=crime,
                    distance_m=distance,
                    severity=get_crime_severity(crime),
                    crime_type=str(_coerce_crime_value(crime, "type", "unknown")),
                    crime_type_weight=get_crime_type_weight(crime),
                )
            )

        return nearby_crimes

    def compute_edge_risk_breakdown(self, u, v, edge_data):
        light_score = edge_data.get("light_score", 0.5)
        try:
            light_score = float(light_score)
        except Exception:
            light_score = 0.5

        darkness_penalty = (1.0 - light_score) * 2.2
        crime_penalty = 0.0
        for evidence in self.get_edge_crime_evidence(u, v):
            proximity_weight = max(0.0, 1.0 - (evidence.distance_m / CRIME_RADIUS_METERS))
            crime_penalty += (0.35 + evidence.severity) * evidence.crime_type_weight * proximity_weight
        crime_penalty = min(crime_penalty, MAX_EDGE_CRIME_RISK)

        visual_score, visual_available = read_visual_score(edge_data)
        visual_bonus = (max(0.0, visual_score) * 0.35) if visual_available else 0.0

        return EdgeRiskBreakdown(
            darkness_penalty=darkness_penalty,
            crime_penalty=crime_penalty,
            visual_bonus=visual_bonus,
            visual_score=visual_score,
            visual_available=visual_available,
        )

    def build_route_score_breakdown(self, route_nodes):
        total_darkness = 0.0
        total_crime_penalty = 0.0
        total_visual_score = 0.0
        visual_edge_count = 0
        edge_count = 0
        route_crime_map = {}

        for i in range(len(route_nodes) - 1):
            u, v = route_nodes[i], route_nodes[i + 1]
            edge_data = list(self.graph[u][v].values())[0] if self.graph.has_edge(u, v) else {}
            edge_breakdown = self.compute_edge_risk_breakdown(u, v, edge_data)

            total_darkness += edge_breakdown.darkness_penalty
            total_crime_penalty += edge_breakdown.crime_penalty
            if edge_breakdown.visual_available:
                total_visual_score += edge_breakdown.visual_score
                visual_edge_count += 1

            for idx, evidence in enumerate(self.get_edge_crime_evidence(u, v)):
                crime_id = crime_identifier(evidence.crime, idx)
                previous_distance = route_crime_map.get(crime_id, {}).get("distance_m")
                if previous_distance is not None and previous_distance <= evidence.distance_m:
                    continue
                route_crime_map[crime_id] = serialize_crime_report(
                    evidence.crime,
                    idx,
                    evidence.distance_m,
                )

            edge_count += 1

        edge_count = max(edge_count, 1)
        avg_darkness = total_darkness / edge_count
        avg_crime = total_crime_penalty / edge_count
        avg_visual = total_visual_score / visual_edge_count if visual_edge_count else 0.0

        lighting_score_pct = int(max(0.0, min(1.0, 1.0 - (avg_darkness / 2.2))) * 100)
        crime_risk = max(0.0, min(1.0, avg_crime / MAX_EDGE_CRIME_RISK))
        darkness_risk = max(0.0, min(1.0, avg_darkness / 2.2))
        visual_safety = max(0.0, min(1.0, avg_visual + 0.5)) if visual_edge_count else 0.5
        combined_risk = (crime_risk * 0.6) + (darkness_risk * 0.25) + ((1.0 - visual_safety) * 0.15)
        overall_safety_score = round((1.0 - combined_risk) * 10.0, 1)
        overall_safety_score = max(0.0, min(10.0, overall_safety_score))

        sorted_crimes = sorted(
            route_crime_map.values(),
            key=lambda crime: (-crime["severity"], crime["distance_m"]),
        )

        decision_trace = {
            "model": "heuristic_v2",
            "stages": [
                "segment_crime_evidence",
                "edge_risk_estimation",
                "route_aggregation",
                "normalized_decision_score",
            ],
            "weights": {
                "crime_risk": 0.6,
                "darkness_risk": 0.25,
                "visual_risk": 0.15,
            },
            "normalized_components": {
                "crime_risk": round(crime_risk, 3),
                "darkness_risk": round(darkness_risk, 3),
                "visual_safety": round(visual_safety, 3),
                "combined_risk": round(combined_risk, 3),
            },
        }

        return {
            "overall_safety_score": overall_safety_score,
            "lighting_score_pct": lighting_score_pct,
            "crime_count": len(sorted_crimes),
            "avg_visual_score": round(avg_visual, 2),
            "visual_edges_analyzed": visual_edge_count,
            "crime_type_priors": self.crime_type_priors,
            "decision_trace": decision_trace,
            "crime_reports": sorted_crimes,
        }
