"""
Downloads real mapped routing data from OpenStreetMap
"""
import os
import osmnx as ox

try:
    # Download a 5km radius walking graph
    G = ox.graph_from_place(
        "National Capital Territory of Delhi, India",
        network_type="walk",
        simplify=True
    )
    os.makedirs("app/data", exist_ok=True)
    ox.save_graphml(G, filepath="app/data/delhi_walk.graphml")
    print(f"Success! Graph with {len(G.nodes)} nodes saved to app/data/delhi_walk.graphml")
except Exception as e:
    print(f"Error generating graph: {e}")
