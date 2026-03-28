"""
YOLO v8 + Mapillary preprocessing.

This script enriches graph edges with a visual safety signal. When no nearby
street-view image is found, the edge is marked as having no visual evidence
instead of being treated as visually unsafe.
"""

import os
import random
import time

import osmnx as ox
import requests
from ultralytics import YOLO

MAPILLARY_TOKEN = os.getenv("MAPILLARY_TOKEN")

# Load model once.
model = YOLO("yolov8n.pt")

# Load graph once.
G = ox.load_graphml("app/data/delhi_walk.graphml")
print(f"Total edges: {len(G.edges)}")

image_cache = {}


def get_mapillary_image(lat, lng):
    key = (round(lat, 5), round(lng, 5))

    if key in image_cache:
        return image_cache[key]

    url = "https://graph.mapillary.com/images"

    for radius in [500, 1000, 2000]:
        params = {
            "access_token": MAPILLARY_TOKEN,
            "fields": "id,thumb_1024_url",
            "closeto": f"{lng},{lat}",
            "radius": radius,
            "limit": 5,
        }

        try:
            res = requests.get(url, params=params, timeout=10)

            if res.status_code != 200:
                continue

            data = res.json().get("data", [])
            if not data:
                continue

            image_url = random.choice(data).get("thumb_1024_url")
            if image_url:
                image_cache[key] = image_url
                return image_url

        except Exception as exc:
            print("Mapillary error:", exc)

    image_cache[key] = "NO_IMAGE"
    return "NO_IMAGE"


def run_yolo(image_url):
    try:
        results = model(image_url, verbose=False)
        detections = []

        for result in results:
            for box in result.boxes:
                detections.append(
                    {
                        "label": model.names[int(box.cls)],
                        "confidence": float(box.conf),
                    }
                )

        return detections

    except Exception as exc:
        print("YOLO error:", exc)
        return []


def compute_visual_score(detections):
    score = 0.0

    for detection in detections:
        label = detection["label"]
        confidence = detection["confidence"]

        if label == "person":
            score -= 0.2 * confidence
        elif label == "motorcycle":
            score -= 0.3 * confidence
        elif label == "car":
            score += 0.05 * confidence
        elif label == "truck":
            score += 0.1 * confidence

    return max(-0.5, min(0.5, score))


def attach_node_image_metadata(node_id):
    node_data = G.nodes[node_id]

    if "image_url" in node_data:
        return

    lat = node_data.get("y")
    lng = node_data.get("x")

    if lat is None or lng is None:
        node_data["image_url"] = ""
        node_data["image_available"] = False
        return

    image_url = get_mapillary_image(lat, lng)
    if image_url == "NO_IMAGE":
        node_data["image_url"] = ""
        node_data["image_available"] = False
    else:
        node_data["image_url"] = image_url
        node_data["image_available"] = True


edges = list(G.edges(keys=True, data=True))
edges = random.sample(edges, min(300, len(edges)))

print(f"Processing {len(edges)} edges...")

for idx, (u, v, k, data) in enumerate(edges):
    try:
        lat = (G.nodes[u]["y"] + G.nodes[v]["y"]) / 2
        lng = (G.nodes[u]["x"] + G.nodes[v]["x"]) / 2

        image_url = get_mapillary_image(lat, lng)
        attach_node_image_metadata(u)
        attach_node_image_metadata(v)

        if image_url != "NO_IMAGE":
            detections = run_yolo(image_url)
            visual_score = compute_visual_score(detections)
            data["visual_score_available"] = True
            data["visual_score_source"] = "mapillary_yolo"
        else:
            # No nearby image means we do not have enough evidence to score
            # this edge visually. Keep it neutral and exclude it downstream.
            visual_score = 0.0
            data["visual_score_available"] = False
            data["visual_score_source"] = "no_image_assumed_safe"

        data["visual_score"] = visual_score

        print(
            f"[{idx}] Edge {u}->{v} | score={round(visual_score, 3)} "
            f"| available={data['visual_score_available']}"
        )

        time.sleep(0.2)

    except Exception as exc:
        print("Edge error:", exc)
        data["visual_score"] = 0.0
        data["visual_score_available"] = False
        data["visual_score_source"] = "processing_error"


ox.save_graphml(G, "graph_with_visual.graphml")
print("Graph saved successfully")
