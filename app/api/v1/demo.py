from fastapi import APIRouter, HTTPException

router = APIRouter()

DEMO_ROUTES = {
    "hauz_khas": {
        "fast": {
            "coordinates": [[28.549, 77.200], [28.548, 77.201], [28.547, 77.205]],
            "estimated_time_min": 6,
            "score_breakdown": {
                "overall_safety_score": 4.2,
                "lighting_score_pct": 45,
                "crime_density": "High",
                "crime_count": 3,
                "callouts": [
                    "\u26a0 Contains dark segments detected by AI",
                    "\u26a0 3 incidents reported on this route",
                ],
            },
        },
        "safe": {
            "coordinates": [
                [28.549, 77.200],
                [28.551, 77.202],
                [28.550, 77.204],
                [28.547, 77.205],
            ],
            "estimated_time_min": 10,
            "score_breakdown": {
                "overall_safety_score": 8.5,
                "lighting_score_pct": 82,
                "crime_density": "Low",
                "crime_count": 0,
                "callouts": [
                    "\u2713 Passes well-lit roads",
                    "\u2713 No reported incidents nearby",
                ],
            },
        },
    },
    "lajpat_nagar": {
        "fast": {
            "coordinates": [[28.567, 77.243], [28.566, 77.244], [28.565, 77.245]],
            "estimated_time_min": 5,
            "score_breakdown": {
                "overall_safety_score": 3.8,
                "lighting_score_pct": 50,
                "crime_density": "Medium",
                "crime_count": 2,
                "callouts": ["\u26a0 Contains dark segments detected by AI"],
            },
        },
        "safe": {
            "coordinates": [
                [28.567, 77.243],
                [28.569, 77.245],
                [28.568, 77.247],
                [28.565, 77.245],
            ],
            "estimated_time_min": 9,
            "score_breakdown": {
                "overall_safety_score": 7.9,
                "lighting_score_pct": 75,
                "crime_density": "Low",
                "crime_count": 0,
                "callouts": [
                    "\u2713 Passes well-lit roads",
                    "\u2713 No reported incidents nearby",
                ],
            },
        },
    },
}


@router.get("/demo/{route_id}")
async def get_demo_route(route_id: str):
    if route_id not in DEMO_ROUTES:
        raise HTTPException(status_code=404, detail="Demo route not found")
    return DEMO_ROUTES[route_id]
