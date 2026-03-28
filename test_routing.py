import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import networkx as nx

from app.api.v1.routes import _build_crime_query_bounds, _load_candidate_crimes
from app.services.routing import compute_fast_route, compute_safe_route
from app.services.safety import distance_to_segment_meters


class RoutingSafetyTests(unittest.TestCase):
    def setUp(self):
        graph = nx.MultiDiGraph()
        graph.add_node("A", y=12.0000, x=77.0000)
        graph.add_node("B", y=12.0000, x=77.0006)
        graph.add_node("C", y=12.0000, x=77.0012)
        graph.add_node("D", y=12.0008, x=77.0006)

        graph.add_edge(
            "A",
            "B",
            length=40,
            light_score=0.1,
            visual_score=-0.2,
            visual_score_available=True,
        )
        graph.add_edge(
            "B",
            "C",
            length=40,
            light_score=0.1,
            visual_score=-0.2,
            visual_score_available=True,
        )
        graph.add_edge(
            "A",
            "D",
            length=65,
            light_score=0.95,
            visual_score=0.3,
            visual_score_available=True,
        )
        graph.add_edge(
            "D",
            "C",
            length=65,
            light_score=0.95,
            visual_score=0.3,
            visual_score_available=True,
        )

        self.graph = graph
        self.crimes = [
            {
                "lat": 12.0000,
                "lng": 77.0006,
                "type": "harassment",
                "severity": 1.0,
                "description": "Reported harassment hotspot",
                "timestamp": "2026-03-28T00:00:00",
            }
        ]

    def test_route_payload_includes_nearby_crime_reports(self):
        route = compute_fast_route(self.graph, "A", "C", self.crimes)

        self.assertIn("score_breakdown", route)
        self.assertIn("crime_reports", route)
        self.assertEqual(route["crime_reports"], route["score_breakdown"]["crime_reports"])
        self.assertEqual(len(route["crime_reports"]), 1)
        self.assertEqual(route["crime_reports"][0]["type"], "harassment")
        self.assertIn("crime_type_priors", route["score_breakdown"])
        self.assertIn("decision_trace", route["score_breakdown"])
        self.assertEqual(
            route["score_breakdown"]["decision_trace"]["model"],
            "heuristic_v2",
        )
        self.assertGreater(route["crime_reports"][0]["crime_type_weight"], 0.0)

    def test_safe_route_avoids_risky_edges_and_scores_higher(self):
        fast_route = compute_fast_route(self.graph, "A", "C", self.crimes)
        safe_route = compute_safe_route(self.graph, "A", "C", self.crimes)

        self.assertEqual(fast_route["coordinates"][1], [12.0, 77.0006])
        self.assertEqual(safe_route["coordinates"][1], [12.0008, 77.0006])
        self.assertGreater(
            safe_route["score_breakdown"]["overall_safety_score"],
            fast_route["score_breakdown"]["overall_safety_score"],
        )
        self.assertNotEqual(
            safe_route["score_breakdown"]["overall_safety_score"],
            fast_route["score_breakdown"]["overall_safety_score"],
        )

    def test_merged_type_prior_increases_risk_for_more_prevalent_crime_types(self):
        snatch_crime = [
            {
                "lat": 12.0000,
                "lng": 77.0006,
                "type": "snatch",
                "severity": 0.7,
                "description": "Snatching hotspot",
                "timestamp": "2026-03-28T00:00:00",
            }
        ]
        other_crime = [
            {
                "lat": 12.0000,
                "lng": 77.0006,
                "type": "other",
                "severity": 0.7,
                "description": "Generic incident hotspot",
                "timestamp": "2026-03-28T00:00:00",
            }
        ]

        snatch_route = compute_fast_route(self.graph, "A", "C", snatch_crime)
        other_route = compute_fast_route(self.graph, "A", "C", other_crime)

        self.assertGreater(
            snatch_route["crime_reports"][0]["crime_type_weight"],
            other_route["crime_reports"][0]["crime_type_weight"],
        )
        self.assertLess(
            snatch_route["score_breakdown"]["overall_safety_score"],
            other_route["score_breakdown"]["overall_safety_score"],
        )

    def test_seed_support_keeps_stalking_above_default_floor(self):
        stalking_crime = [
            {
                "lat": 12.0000,
                "lng": 77.0006,
                "type": "stalking",
                "severity": 0.7,
                "description": "Stalking hotspot",
                "timestamp": "2026-03-28T00:00:00",
            }
        ]
        other_crime = [
            {
                "lat": 12.0000,
                "lng": 77.0006,
                "type": "other",
                "severity": 0.7,
                "description": "Generic incident hotspot",
                "timestamp": "2026-03-28T00:00:00",
            }
        ]

        stalking_route = compute_fast_route(self.graph, "A", "C", stalking_crime)
        other_route = compute_fast_route(self.graph, "A", "C", other_crime)

        self.assertGreater(
            stalking_route["crime_reports"][0]["crime_type_weight"],
            other_route["crime_reports"][0]["crime_type_weight"],
        )

    def test_segment_distance_filter_excludes_midpoint_false_positive(self):
        graph = nx.MultiDiGraph()
        graph.add_node("A", y=12.0000, x=77.0000)
        graph.add_node("B", y=12.0000, x=77.0020)
        graph.add_edge(
            "A",
            "B",
            length=180,
            light_score=0.8,
            visual_score=0.0,
            visual_score_available=True,
        )

        far_from_segment_crime = [
            {
                "lat": 12.0009,
                "lng": 77.0010,
                "type": "snatch",
                "severity": 0.7,
                "description": "Near midpoint, but not near the route line",
                "timestamp": "2026-03-28T00:00:00",
            }
        ]

        distance = distance_to_segment_meters(12.0009, 77.0010, 12.0, 77.0, 12.0, 77.0020)
        self.assertGreater(distance, 90.0)

        route = compute_fast_route(graph, "A", "B", far_from_segment_crime)
        self.assertEqual(route["score_breakdown"]["crime_count"], 0)
        self.assertEqual(route["crime_reports"], [])

    def test_crime_query_bounds_focus_on_route_corridor(self):
        bounds = _build_crime_query_bounds(28.5670, 77.2430, 28.5700, 77.2450)

        self.assertGreaterEqual(bounds["buffer_m"], 1500.0)
        self.assertLessEqual(bounds["buffer_m"], 5000.0)
        self.assertLess(bounds["min_lat"], 28.5670)
        self.assertGreater(bounds["max_lat"], 28.5700)
        self.assertLess(bounds["min_lng"], 77.2430)
        self.assertGreater(bounds["max_lng"], 77.2450)

    def test_empty_location_query_does_not_fallback_to_all_crimes(self):
        mock_find_query = AsyncMock()
        mock_find_query.to_list.return_value = []
        mock_find_all_query = AsyncMock()
        mock_find_all_query.to_list.return_value = [{"type": "should_not_be_used"}]

        with patch("app.api.v1.routes.CrimeReport.find", return_value=mock_find_query) as mocked_find:
            with patch(
                "app.api.v1.routes.CrimeReport.find_all",
                return_value=mock_find_all_query,
            ) as mocked_find_all:
                crimes = asyncio.run(
                    _load_candidate_crimes(28.5670, 77.2430, 28.5700, 77.2450)
                )

        self.assertEqual(crimes, [])
        mocked_find.assert_called_once()
        mocked_find_all.assert_not_called()


if __name__ == "__main__":
    unittest.main()
