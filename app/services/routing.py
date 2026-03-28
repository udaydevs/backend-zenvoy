"""
OSMnx graph loading and routing utilities.

Provides mechanisms to calculate the shortest path (Fast Route) and the
safest route customized by edge weights.
"""
import time
import logging
import math
import osmnx as ox
import networkx as nx
from app.services.safety import SafetyScorer, get_route_score_breakdown

logger = logging.getLogger(__name__)

CONNAUGHT_PLACE_CENTER = (28.6315, 77.2167)
CONNAUGHT_PLACE_RADIUS_METERS = 1200
MAX_CP_IMAGES = 5
MAX_SAFE_DETOUR_RATIO = 1.2
MAX_SAFE_DETOUR_RATIO_LOW_SAFETY = 1.4
LOW_SAFETY_SCORE_THRESHOLD = 5.5
MIN_SAFETY_SCORE_IMPROVEMENT_FOR_DETOUR = 0.3
BALANCED_SAFE_FACTOR = 0.6


def load_graph(path: str):
    """
    Load a pre-computed walking graph from a GraphML file.
    
    Args:
        path (str): The filesystem path to the GraphMLFile.
        
    Returns:
        networkx.MultiDiGraph: The loaded graph, or None if failed.
    """
    start_time = time.time()
    logger.info("Loading graph from %s", path)
    try:
        graphml = ox.load_graphml(path)
        logger.info("Graph loaded in %.2f seconds", time.time() - start_time)
        return graphml
    except FileNotFoundError as e:
        logger.error("Graph file not found at %s: %s", path, e)
        return None
    except OSError as e:
        logger.error("Failed to read graph file at %s: %s", path, e)
        return None
    except ValueError as e:
        logger.error("Invalid GraphML format at %s: %s", path, e)
        return None

def get_nearest_node(G, lat: float, lng: float):
    """
    Find the closest node in the map graph to the given coordinates.
    
    Args:
        G (networkx.MultiDiGraph): The routing graph.
        lat (float): Latitude of the point.
        lng (float): Longitude of the point.
        
    Returns:
        int: The nearest node ID in the graph.
    """
    try:
        return ox.distance.nearest_nodes(G, X=lng, Y=lat)
    except ImportError:
        logger.warning(
            "Falling back to linear nearest-node search because optional "
            "OSMnx nearest_nodes dependencies are unavailable."
        )
        best_node = None
        best_distance = None

        for node_id, data in G.nodes(data=True):
            node_lat = data.get("y")
            node_lng = data.get("x")
            if node_lat is None or node_lng is None:
                continue

            distance = haversine_distance_meters(lat, lng, node_lat, node_lng)
            if best_distance is None or distance < best_distance:
                best_node = node_id
                best_distance = distance

        if best_node is None:
            raise ValueError("No graph nodes with coordinates were available.")

        return best_node


def get_route_coordinates(G, route_nodes):
    """
    Convert a sequence of node IDs into a list of [lat, lng] pairs.
    """
    return [[G.nodes[n]["y"], G.nodes[n]["x"]] for n in route_nodes]


def haversine_distance_meters(lat1, lng1, lat2, lng2):
    """
    Compute distance between two coordinates in meters.
    """
    lat1, lng1, lat2, lng2 = map(
        float, (lat1, lng1, lat2, lng2)
    )
    earth_radius = 6371000
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2
    )

    return earth_radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_connaught_place_node(G, node_id):
    node_data = G.nodes[node_id]
    lat = node_data.get("y")
    lng = node_data.get("x")

    if lat is None or lng is None:
        return False

    return haversine_distance_meters(
        lat,
        lng,
        CONNAUGHT_PLACE_CENTER[0],
        CONNAUGHT_PLACE_CENTER[1],
    ) <= CONNAUGHT_PLACE_RADIUS_METERS


def get_node_image_payload(G, node_id):
    node_data = G.nodes[node_id]
    image_url = node_data.get("image_url", "")
    image_available = node_data.get("image_available", False)

    if isinstance(image_available, str):
        image_available = image_available.lower() == "true"

    return {
        "node_id": str(node_id),
        "image_url": image_url or None,
        "image_available": bool(image_available) and bool(image_url),
        "coordinates": [node_data.get("y"), node_data.get("x")],
    }


def get_connaught_place_images(G, route_nodes):
    """
    Return unique image previews for route nodes that fall inside Connaught Place.
    """
    images = []
    seen_urls = set()

    for node_id in route_nodes:
        if not is_connaught_place_node(G, node_id):
            continue

        payload = get_node_image_payload(G, node_id)
        image_url = payload.get("image_url")
        if not payload["image_available"] or not image_url or image_url in seen_urls:
            continue

        seen_urls.add(image_url)
        images.append(payload)

        if len(images) >= MAX_CP_IMAGES:
            break

    return images


def get_connaught_place_payload(G, route_nodes):
    passes_connaught_place = any(
        is_connaught_place_node(G, node_id) for node_id in route_nodes
    )
    if not passes_connaught_place:
        return None

    return {
        "passes_connaught_place": True,
        "images": get_connaught_place_images(G, route_nodes),
    }


def compute_total_distance(G, route_nodes):
    total = 0
    for i in range(len(route_nodes) - 1):
        u, v = route_nodes[i], route_nodes[i + 1]
        edge_data = list(G[u][v].values())[0]
        total += float(edge_data.get("length", 0))
    return round(total / 1000, 2)


def compute_total_distance_meters(G, route_nodes):
    total = 0.0
    for i in range(len(route_nodes) - 1):
        u, v = route_nodes[i], route_nodes[i + 1]
        edge_data = list(G[u][v].values())[0]
        total += float(edge_data.get("length", 0) or 0)
    return total


def estimate_time_min(distance_km):
    """
    Estimate walking time based on edge lengths at 5 km/h walking speed.
    """
    return int(max(1, distance_km / 5 * 60))  # 5 km/h


def build_route_response(G, route_nodes, route_type, crimes, origin_node, dest_node):
    distance = compute_total_distance(G, route_nodes)
    cp_payload = get_connaught_place_payload(G, route_nodes)

    response = {
        "type": route_type,
        "coordinates": get_route_coordinates(G, route_nodes),
        "distance_km": distance,
        "estimated_time_min": estimate_time_min(distance),
        "score": get_route_score_breakdown(G, route_nodes, crimes or []),
        "origin_preview": get_node_image_payload(G, origin_node),
        "destination_preview": get_node_image_payload(G, dest_node),
    }

    if cp_payload:
        response["connaught_place"] = cp_payload

    return response


def choose_balanced_safe_route(G, origin_node, dest_node, crimes):
    scorer = SafetyScorer(G, crimes)

    fast_route_nodes = nx.shortest_path(
        G, source=origin_node, target=dest_node, weight="length"
    )
    pure_safe_route_nodes = nx.shortest_path(
        G,
        source=origin_node,
        target=dest_node,
        weight=scorer.edge_weight_func,
    )

    fast_distance_m = compute_total_distance_meters(G, fast_route_nodes)
    pure_safe_distance_m = compute_total_distance_meters(G, pure_safe_route_nodes)
    fast_score = get_route_score_breakdown(G, fast_route_nodes, crimes)
    pure_safe_score = get_route_score_breakdown(G, pure_safe_route_nodes, crimes)
    balanced_safe_route_nodes = nx.shortest_path(
        G,
        source=origin_node,
        target=dest_node,
        weight=lambda u, v, data: (
            scorer.edge_weight_with_safety_factor(
                u, v, data, safety_factor=BALANCED_SAFE_FACTOR
            )
        ),
    )
    balanced_safe_distance_m = compute_total_distance_meters(G, balanced_safe_route_nodes)
    balanced_safe_score = get_route_score_breakdown(
        G, balanced_safe_route_nodes, crimes
    )

    max_detour_ratio = (
        MAX_SAFE_DETOUR_RATIO_LOW_SAFETY
        if fast_score["overall_safety_score"] <= LOW_SAFETY_SCORE_THRESHOLD
        else MAX_SAFE_DETOUR_RATIO
    )
    max_allowed_distance_m = fast_distance_m * max_detour_ratio

    if (
        pure_safe_distance_m <= max_allowed_distance_m
        and (
            pure_safe_distance_m <= fast_distance_m
            or (
                pure_safe_score["overall_safety_score"] - fast_score["overall_safety_score"]
            ) >= MIN_SAFETY_SCORE_IMPROVEMENT_FOR_DETOUR
            or fast_score["overall_safety_score"] <= LOW_SAFETY_SCORE_THRESHOLD
        )
    ):
        return pure_safe_route_nodes, "pure_safe"

    if (
        balanced_safe_distance_m <= max_allowed_distance_m
        and (
            balanced_safe_distance_m <= fast_distance_m
            or (
                balanced_safe_score["overall_safety_score"] - fast_score["overall_safety_score"]
            ) >= MIN_SAFETY_SCORE_IMPROVEMENT_FOR_DETOUR
            or fast_score["overall_safety_score"] <= LOW_SAFETY_SCORE_THRESHOLD
        )
    ):
        return balanced_safe_route_nodes, "balanced_safe"

    return fast_route_nodes, "fallback_fast_low_gain"


def compute_fast_route(G, origin_node, dest_node, crimes=None):
    """
    Compute the shortest possible physical walking route.
    
    Args:
        G (networkx.MultiDiGraph): The routing graph.
        origin_node (int): Source node ID.
        dest_node (int): Destination node ID.
        crimes (list): Optional list of crime reports to evaluate route safety.
        
    Returns:
        dict: A dictionary containing the route coordinates and safety metrics.
    """
    route_nodes = nx.shortest_path(
        G, source=origin_node, target=dest_node, weight="length"
    )

    return build_route_response(
        G, route_nodes, "fast", crimes or [], origin_node, dest_node
    )

def compute_safe_route(G, origin_node, dest_node, crimes):
    """
    Compute the safest walking route by dynamically weighting edges.
    
    Edges are weighted by a custom SafetyScorer which factors in darkness
    and clustered crime reports.
    """
    route_nodes, selection_mode = choose_balanced_safe_route(
        G, origin_node, dest_node, crimes
    )
    response = build_route_response(
        G, route_nodes, "safe", crimes, origin_node, dest_node
    )
    response["route_selection_mode"] = selection_mode
    return response
