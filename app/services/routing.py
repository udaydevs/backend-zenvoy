"""
OSMnx graph loading and routing utilities.

Provides mechanisms to calculate the shortest path (Fast Route) and the
safest route customized by edge weights.
"""
import time
import logging
import osmnx as ox
import networkx as nx
from app.services.safety import SafetyScorer, get_route_score_breakdown

logger = logging.getLogger(__name__)


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
    return ox.distance.nearest_nodes(G, X=lng, Y=lat)


def get_route_coordinates(G, route_nodes):
    """
    Convert a sequence of node IDs into a list of [lat, lng] pairs.
    """
    return [[G.nodes[n]["y"], G.nodes[n]["x"]] for n in route_nodes]


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


def compute_total_distance(G, route_nodes):
    total = 0
    for i in range(len(route_nodes) - 1):
        u, v = route_nodes[i], route_nodes[i + 1]
        edge_data = list(G[u][v].values())[0]
        total += float(edge_data.get("length", 0))
    return round(total / 1000, 2)


def estimate_time_min(distance_km):
    """
    Estimate walking time based on edge lengths at 5 km/h walking speed.
    """
    return int(max(1, distance_km / 5 * 60))  # 5 km/h


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

    distance = compute_total_distance(G, route_nodes)

    score_breakdown = get_route_score_breakdown(G, route_nodes, crimes or [])

    return {
        "type": "fast",
        "coordinates": get_route_coordinates(G, route_nodes),
        "distance_km": distance,
        "estimated_time_min": estimate_time_min(distance),
        "score_breakdown": score_breakdown,
        "score": score_breakdown,
        "crime_reports": score_breakdown["crime_reports"],
        "origin_preview": get_node_image_payload(G, origin_node),
        "destination_preview": get_node_image_payload(G, dest_node),
    }

def compute_safe_route(G, origin_node, dest_node, crimes):
    """
    Compute the safest walking route by dynamically weighting edges.
    
    Edges are weighted by a custom SafetyScorer which factors in darkness
    and clustered crime reports.
    """
    scorer = SafetyScorer(G, crimes)

    route_nodes = nx.shortest_path(
        G,
        source=origin_node,
        target=dest_node,
        weight=scorer.edge_weight_func,
    )

    distance = compute_total_distance(G, route_nodes)

    score_breakdown = get_route_score_breakdown(G, route_nodes, crimes)

    return {
        "type": "safe",
        "coordinates": get_route_coordinates(G, route_nodes),
        "distance_km": distance,
        "estimated_time_min": estimate_time_min(distance),
        "score_breakdown": score_breakdown,
        "score": score_breakdown,
        "crime_reports": score_breakdown["crime_reports"],
        "origin_preview": get_node_image_payload(G, origin_node),
        "destination_preview": get_node_image_payload(G, dest_node),
    }
