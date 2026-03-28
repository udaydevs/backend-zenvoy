"""
FastAPI route definitions for the Zenvoy routing engine.

Handles computing and serving fast and safe route paths using OSMnx.
"""
from fastapi import APIRouter, Request, HTTPException, Query
from app.services.routing import (
    get_nearest_node,
    compute_fast_route,
    compute_safe_route,
)
from app.models.crime import CrimeReport

router = APIRouter()


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

    # We load crimes to calculate the score breakdown even for the fast route
    crimes = await CrimeReport.find_all().to_list()

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

    crimes = await CrimeReport.find_all().to_list()

    route_data = compute_safe_route(graph_network, origin_node, dest_node, crimes)
    if not route_data:
        raise HTTPException(
            status_code=404, detail="No path found between the specified points"
        )

    return route_data
