from app.services.score_pipeline import (
    CRIME_RADIUS_METERS,
    MAX_EDGE_CRIME_RISK,
    MERGED_CRIME_TYPE_PRIORS,
    ScoreGenerationPipeline,
    distance_to_segment_meters,
    read_visual_score,
)


class SafetyScorer:
    def __init__(self, G, crimes):
        self.pipeline = ScoreGenerationPipeline(G, crimes)

    def edge_weight_func(self, u, v, data):
        length = data.get("length", 1.0)
        try:
            length = float(length)
        except Exception:
            length = 1.0

        edge_breakdown = self.pipeline.compute_edge_risk_breakdown(u, v, data)
        return length * (
            1
            + edge_breakdown.crime_penalty * 2.8
            + edge_breakdown.darkness_penalty
            - edge_breakdown.visual_bonus
        )


def get_route_score_breakdown(G, route_nodes, crimes):
    pipeline = ScoreGenerationPipeline(G, crimes)
    return pipeline.build_route_score_breakdown(route_nodes)


__all__ = [
    "CRIME_RADIUS_METERS",
    "MAX_EDGE_CRIME_RISK",
    "MERGED_CRIME_TYPE_PRIORS",
    "SafetyScorer",
    "ScoreGenerationPipeline",
    "distance_to_segment_meters",
    "get_route_score_breakdown",
    "read_visual_score",
]
