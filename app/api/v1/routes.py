"""
FastAPI route definitions for the Zenvoy routing engine.

Handles computing and serving fast and safe route paths using OSMnx.
"""
import math
from fastapi import APIRouter, Request, HTTPException, Query
from app.services.routing import (
    get_nearest_node,
    compute_fast_route,
    compute_safe_route,
)
from app.models.crime import CrimeReport

router = APIRouter()
MIN_CRIME_QUERY_BUFFER_METERS = 1500.0
MAX_CRIME_QUERY_BUFFER_METERS = 5000.0


def _haversine_distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _build_crime_query_bounds(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float):
    direct_distance_m = _haversine_distance_meters(origin_lat, origin_lng, dest_lat, dest_lng)
    buffer_m = max(
        MIN_CRIME_QUERY_BUFFER_METERS,
        min(MAX_CRIME_QUERY_BUFFER_METERS, direct_distance_m * 0.6),
    )

    lat_buffer = buffer_m / 111320.0
    ref_lat = (origin_lat + dest_lat) / 2.0
    lng_buffer = buffer_m / max(111320.0 * math.cos(math.radians(ref_lat)), 1e-6)

    return {
        "min_lat": min(origin_lat, dest_lat) - lat_buffer,
        "max_lat": max(origin_lat, dest_lat) + lat_buffer,
        "min_lng": min(origin_lng, dest_lng) - lng_buffer,
        "max_lng": max(origin_lng, dest_lng) + lng_buffer,
        "buffer_m": round(buffer_m, 1),
        "direct_distance_m": round(direct_distance_m, 1),
    }


async def _load_candidate_crimes(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float):
    bounds = _build_crime_query_bounds(origin_lat, origin_lng, dest_lat, dest_lng)
    query = {
        "lat": {"$gte": bounds["min_lat"], "$lte": bounds["max_lat"]},
        "lng": {"$gte": bounds["min_lng"], "$lte": bounds["max_lng"]},
    }

    try:
        filtered_crimes = await CrimeReport.find(query).to_list()
        return filtered_crimes
    except Exception:
        return await CrimeReport.find_all().to_list()


@router.get("/route/fast")
async def get_fast_route(
    request: Request,
    origin_lat: float = Query(...),
    origin_lng: float = Query(...),
    dest_lat: float = Query(...),
    dest_lng: float = Query(...),
):
    """
    Compute the fastest pedestrian route between origin and destination.
    
    Includes safety score breakdown for the generated route, but optimizes
    purely for physical distance / traversal time.
    """
    graph_network = request.app.state.graph
    if not graph_network:
        raise HTTPException(
            status_code=503, detail="Graph network is not loaded")
    origin_node = get_nearest_node(graph_network, origin_lat, origin_lng)
    dest_node = get_nearest_node(graph_network, dest_lat, dest_lng)

    crimes = await _load_candidate_crimes(origin_lat, origin_lng, dest_lat, dest_lng)

    route_data = compute_fast_route(graph_network, origin_node, dest_node, crimes)
    if not route_data:
        raise HTTPException(
            status_code=404, detail="No path found between the specified points"
        )

    return route_data


@router.get("/route/safe")
async def get_safe_route(
    request: Request,
    origin_lat: float = Query(...),
    origin_lng: float = Query(...),
    dest_lat: float = Query(...),
    dest_lng: float = Query(...),
):
    """
    Compute the safest pedestrian route between origin and destination.
    
    Uses custom edge weights factoring in historical crime data and
    ambient lighting scores.
    """
    graph_network = request.app.state.graph
    if not graph_network:
        raise HTTPException(
            status_code=503, detail="Graph network is not loaded")

    origin_node = get_nearest_node(graph_network, origin_lat, origin_lng)
    dest_node = get_nearest_node(graph_network, dest_lat, dest_lng)

    crimes = await _load_candidate_crimes(origin_lat, origin_lng, dest_lat, dest_lng)

    route_data = compute_safe_route(graph_network, origin_node, dest_node, crimes)
    if not route_data:
        raise HTTPException(
            status_code=404, detail="No path found between the specified points"
        )

    return route_data
