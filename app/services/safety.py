import math
from datetime import datetime, timezone

CRIME_EDGE_RADIUS_METERS = 120
ROUTE_CRIME_RADIUS_METERS = 150
MAX_RECENT_CRIMES = 5


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2)
        * math.sin(delta_lambda / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _get_crime_field(crime, field, default=None):
    if hasattr(crime, field):
        return getattr(crime, field)
    if isinstance(crime, dict):
        return crime.get(field, default)
    return default


def _crime_identity(crime):
    return (
        round(float(_get_crime_field(crime, "lat", 0.0) or 0.0), 6),
        round(float(_get_crime_field(crime, "lng", 0.0) or 0.0), 6),
        str(_get_crime_field(crime, "type", "") or ""),
        round(float(_get_crime_field(crime, "severity", 0.0) or 0.0), 3),
        str(_get_crime_field(crime, "description", "") or ""),
    )


def dedupe_crimes(crimes):
    unique_crimes = []
    seen = set()

    for crime in crimes:
        identity = _crime_identity(crime)
        if identity in seen:
            continue
        seen.add(identity)
        unique_crimes.append(crime)

    return unique_crimes


def _get_edge_midpoint(G, u, v):
    y_u, x_u = G.nodes[u].get("y"), G.nodes[u].get("x")
    y_v, x_v = G.nodes[v].get("y"), G.nodes[v].get("x")

    if y_u is None or x_u is None or y_v is None or x_v is None:
        return None, None

    return (y_u + y_v) / 2.0, (x_u + x_v) / 2.0


def _get_crimes_near_edge(G, u, v, crimes, radius_m=CRIME_EDGE_RADIUS_METERS):
    lat_mid, lng_mid = _get_edge_midpoint(G, u, v)
    if lat_mid is None or lng_mid is None:
        return []

    nearby_crimes = []

    for crime in crimes:
        c_lat = float(_get_crime_field(crime, "lat", 0) or 0)
        c_lng = float(_get_crime_field(crime, "lng", 0) or 0)
        distance = haversine_distance(lat_mid, lng_mid, c_lat, c_lng)

        if distance <= radius_m:
            nearby_crimes.append((crime, distance))

    return nearby_crimes


def _edge_crime_penalty(G, u, v, crimes):
    weighted_penalty = 0.0

    for crime, distance in _get_crimes_near_edge(G, u, v, crimes):
        severity = float(_get_crime_field(crime, "severity", 0.0) or 0.0)
        proximity_weight = max(0.0, 1.0 - (distance / CRIME_EDGE_RADIUS_METERS))
        weighted_penalty += severity * proximity_weight

    return min(weighted_penalty * 2.5, 4.0)


def _read_visual_score(edge_data):
    visual_available = edge_data.get("visual_score_available", False)
    if isinstance(visual_available, str):
        visual_available = visual_available.lower() == "true"

    visual_score = edge_data.get("visual_score", 0.0)
    try:
        visual_score = float(visual_score)
    except Exception:
        visual_score = 0.0

    return visual_score, bool(visual_available)


class SafetyScorer:
    def __init__(self, G, crimes):
        self.G = G
        self.crimes = dedupe_crimes(crimes)

    def edge_weight_func(self, u, v, data):
        return self.edge_weight_with_safety_factor(u, v, data, safety_factor=1.0)

    def edge_weight_with_safety_factor(self, u, v, data, safety_factor=1.0):
        length = data.get("length", 1.0)
        try:
            length = float(length)
        except Exception:
            length = 1.0

        light_score = data.get("light_score", 0.5)
        try:
            light_score = float(light_score)
        except Exception:
            light_score = 0.5

        darkness_penalty = (1.0 - light_score) * 1.5

        crime_penalty = _edge_crime_penalty(self.G, u, v, self.crimes)

        visual_score, visual_available = _read_visual_score(data)
        visual_bonus = max(0.0, visual_score) if visual_available else 0.0

        safety_adjustment = max(
            0.0,
            1 + ((crime_penalty + darkness_penalty - visual_bonus) * safety_factor),
        )
        return length * safety_adjustment


def _route_reference_points(G, route_nodes):
    points = []

    for node_id in route_nodes:
        lat = G.nodes[node_id].get("y")
        lng = G.nodes[node_id].get("x")
        if lat is not None and lng is not None:
            points.append((float(lat), float(lng)))

    for i in range(len(route_nodes) - 1):
        lat_mid, lng_mid = _get_edge_midpoint(G, route_nodes[i], route_nodes[i + 1])
        if lat_mid is not None and lng_mid is not None:
            points.append((float(lat_mid), float(lng_mid)))

    return points


def _normalize_timestamp(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _sort_timestamp_value(value):
    normalized = _normalize_timestamp(value)
    return (
        normalized.year,
        normalized.month,
        normalized.day,
        normalized.hour,
        normalized.minute,
        normalized.second,
        normalized.microsecond,
    )


def get_recent_crimes_for_route(G, route_nodes, crimes, limit=MAX_RECENT_CRIMES):
    crimes = dedupe_crimes(crimes)
    route_points = _route_reference_points(G, route_nodes)
    nearby = []

    for crime in crimes:
        c_lat = float(_get_crime_field(crime, "lat", 0) or 0)
        c_lng = float(_get_crime_field(crime, "lng", 0) or 0)
        if not route_points:
            continue

        min_distance = min(
            haversine_distance(lat, lng, c_lat, c_lng)
            for lat, lng in route_points
        )

        if min_distance > ROUTE_CRIME_RADIUS_METERS:
            continue

        timestamp = _get_crime_field(crime, "timestamp")
        nearby.append(
            {
                "type": _get_crime_field(crime, "type", ""),
                "severity": round(float(_get_crime_field(crime, "severity", 0.0) or 0.0), 2),
                "description": _get_crime_field(crime, "description", ""),
                "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else None,
                "distance_m": round(min_distance, 1),
                "_sort_timestamp": _sort_timestamp_value(timestamp),
            }
        )

    nearby.sort(
        key=lambda item: (
            item["_sort_timestamp"],
            item["severity"],
            -item["distance_m"],
        ),
        reverse=True,
    )

    trimmed = nearby[:limit]
    for item in trimmed:
        item.pop("_sort_timestamp", None)

    return trimmed


def get_route_score_breakdown(G, route_nodes, crimes):
    crimes = dedupe_crimes(crimes)
    weighted_darkness = 0.0
    weighted_crime_penalty = 0.0
    weighted_visual_score = 0.0
    total_visual_length = 0.0
    total_length = 0.0
    light_edge_count = 0
    visual_edge_count = 0
    edge_count = 0

    for i in range(len(route_nodes) - 1):
        u, v = route_nodes[i], route_nodes[i + 1]

        if G.has_edge(u, v):
            edge_data = list(G[u][v].values())[0]
        else:
            edge_data = {}

        light_score = edge_data.get("light_score", 0.5)
        try:
            light_score = float(light_score)
        except Exception:
            light_score = 0.5

        if "light_score" in edge_data:
            light_edge_count += 1

        length = float(edge_data.get("length", 0.0) or 0.0)
        if length <= 0:
            length = 1.0

        darkness_penalty = (1.0 - light_score) * 1.5
        crime_penalty = _edge_crime_penalty(G, u, v, crimes)
        weighted_darkness += darkness_penalty * length
        weighted_crime_penalty += crime_penalty * length
        total_length += length

        visual_score, visual_available = _read_visual_score(edge_data)
        if visual_available:
            weighted_visual_score += visual_score * length
            total_visual_length += length
            visual_edge_count += 1

        edge_count += 1

    edge_count = max(edge_count, 1)
    total_length = max(total_length, 1.0)

    avg_darkness = weighted_darkness / total_length
    avg_crime_penalty = weighted_crime_penalty / total_length
    avg_visual = weighted_visual_score / total_visual_length if total_visual_length else 0.0
    all_nearby_crimes = get_recent_crimes_for_route(
        G, route_nodes, crimes, limit=len(crimes) or MAX_RECENT_CRIMES
    )
    recent_crimes = all_nearby_crimes[:MAX_RECENT_CRIMES]
    weighted_crime_severity = round(
        sum(
            item["severity"] * max(0.0, 1.0 - (item["distance_m"] / ROUTE_CRIME_RADIUS_METERS))
            for item in all_nearby_crimes
        ),
        2,
    )

    lighting_score_pct = int(max(0.0, min(1.0, 1.0 - (avg_darkness / 1.5))) * 100)
    crime_risk = max(
        0.0,
        min(
            1.0,
            (min(1.0, weighted_crime_severity / 2.5) * 0.75)
            + (min(1.0, len(all_nearby_crimes) / 5.0) * 0.25),
        ),
    )
    exposure_risk = max(0.0, min(1.0, total_length / 6000.0))
    darkness_risk = max(0.0, min(1.0, avg_darkness / 1.5))
    visual_safety = max(0.0, min(1.0, avg_visual + 0.5)) if visual_edge_count else 0.5
    visual_risk = max(0.0, min(1.0, 1.0 - visual_safety))

    weighted_risk = (crime_risk * 0.75) + (exposure_risk * 0.1)
    total_risk_weight = 0.85

    if light_edge_count:
        weighted_risk += darkness_risk * 0.1
        total_risk_weight += 0.1

    if visual_edge_count:
        weighted_risk += visual_risk * 0.05
        total_risk_weight += 0.05

    combined_risk = weighted_risk / total_risk_weight
    overall_safety_score = round((1.0 - combined_risk) * 10.0, 1)
    overall_safety_score = max(0.0, min(10.0, overall_safety_score))

    return {
        "overall_safety_score": overall_safety_score,
        "lighting_score_pct": lighting_score_pct,
        "light_edges_analyzed": light_edge_count,
        "crime_count": len(all_nearby_crimes),
        "recent_crimes": recent_crimes,
        "avg_crime_penalty": round(avg_crime_penalty, 2),
        "weighted_crime_severity": weighted_crime_severity,
        "avg_visual_score": round(avg_visual, 2),
        "visual_edges_analyzed": visual_edge_count,
    }
