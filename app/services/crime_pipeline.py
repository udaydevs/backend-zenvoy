import os
import json
import logging
from datetime import datetime, timezone
import requests
from google import genai
from app.models.crime import CrimeReport
from app.core.config import settings

logger = logging.getLogger(__name__)

PROMPT = """You are a crime data extraction assistant for a safety navigation app in Delhi, India.

Given a block of news headlines and descriptions, extract every crime or safety incident mentioned.
For each incident output a JSON object with these fields:
- lat: float — approximate latitude in Delhi where the incident occurred. Infer from neighborhood/landmark name. If unknown, use 28.6139 (city center).
- lng: float — approximate longitude in Delhi. If unknown, use 77.2090.
- type: string — one of: snatch, robbery, assault, harassment, stalking, murder, accident, other
- severity: float between 0.0 and 1.0 — where murder/assault=1.0, robbery=0.9, snatch=0.8, harassment=0.6, stalking=0.5, other=0.4
- description: string — one sentence summary of the incident in plain English, max 20 words.
- source_date: string — today's date in YYYY-MM-DD format.
- neighborhood: string — the Delhi neighborhood or area name, e.g. "Hauz Khas", "Lajpat Nagar". Empty string if unknown.

Return ONLY a valid JSON array. No explanation, no markdown, no code fences. Just the raw JSON array.
If no crimes are found, return an empty array []."""


from eventregistry import EventRegistry, QueryArticlesIter, QueryItems

def fetch_delhi_crime_news() -> str:
    api_key = settings.NEWSAPI_KEY
    if not api_key:
        raise RuntimeError("NEWSAPI_KEY is not set.")
    try:
        er = EventRegistry(apiKey=api_key, allowUseOfArchive=False)
        delhi_uri = er.getLocationUri("Delhi")
        street_keywords = [
            "snatching", "robbery", "pickpocket", "chain snatching",
            "theft", "bike theft", "car theft", "stabbing",
            "street assault"
        ]

        q = QueryArticlesIter(
            keywords=QueryItems.OR(street_keywords),
            sourceLocationUri=delhi_uri,
            dataType=["news"],
        )
        exclude_keywords = [
            "cyber", "fraud", "scam", "rape", "terror", "politics", "court"
        ]

        def is_street_crime(article):
            text = (
                (article.get("title", "") or "") + " " +
                (article.get("body", "") or "")
            ).lower()

            return (
                any(k in text for k in street_keywords) and
                not any(bad in text for bad in exclude_keywords)
            )

        lines = []

        for art in q.execQuery(er, sortBy="date", maxItems=30):
            if not is_street_crime(art):
                continue

            source = art.get("source", {}).get("title", "Unknown")
            title = art.get("title", "") or ""
            body = art.get("body", "") or ""

            snippet = body[:200].replace("\n", " ")

            lines.append(
                f"[{source}] TITLE: {title}. DESCRIPTION: {snippet}."
            )

        if not lines:
            logger.warning("No street crime articles found.")
            return ""
        print(lines)
        return "\n".join(lines)

    except Exception as e:
        raise RuntimeError(f"EventRegistry request failed: {e}")

def extract_crimes_from_news(news_text: str) -> list[dict]:
    if not news_text.strip():
        return []

    api_key = settings.GEMINI_API_KEY
    if not api_key:
        logger.error("GEMINI_API_KEY is not set.")
        return []

    raw_response_text = ""
    try:
        client = genai.Client(api_key=api_key)
        full_prompt = f"{PROMPT}\n\n{news_text}"

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=full_prompt,
        )

        raw_response_text = response.text.strip()

        # Strip markdown fences if Gemini ignores the prompt instruction
        if raw_response_text.startswith("```json"):
            raw_response_text = raw_response_text[7:]
        if raw_response_text.startswith("```"):
            raw_response_text = raw_response_text[3:]
        if raw_response_text.endswith("```"):
            raw_response_text = raw_response_text[:-3]

        data = json.loads(raw_response_text.strip())

        if not isinstance(data, list):
            logger.error(f"Gemini returned JSON but not a list: {data}")
            return []

        valid_crimes = []
        for item in data:
            if all(k in item for k in ("lat", "lng", "type", "severity", "description")):
                valid_crimes.append(item)
            else:
                logger.warning(f"Skipping malformed item: {item}")

        return valid_crimes

    except json.JSONDecodeError as e:
        logger.error(
            f"Failed to parse Gemini response as JSON. Error: {e}. "
            f"Raw response: {raw_response_text}"
        )
        return []
    except Exception as e:
        logger.error(f"Error calling Gemini: {e}")
        return []


async def process_daily_crimes():
    """
    Background task to fetch news, extract crimes, and insert into DB.
    """
    logger.info("process_daily_crimes: Pipeline started")
    try:
        news = fetch_delhi_crime_news()
        if not news:
            logger.info("process_daily_crimes: No news found today.")
            return
        logger.info(f"process_daily_crimes: Fetched {len(news.splitlines())} news lines")
    except Exception as e:
        logger.error(f"process_daily_crimes: Failed to fetch news: {e}")
        return

    try:
        crimes = extract_crimes_from_news(news)
        logger.info(f"process_daily_crimes: Gemini extracted {len(crimes)} crime events")
    except Exception as e:
        logger.error(f"process_daily_crimes: Failed to extract crimes: {e}")
        return

    inserted = 0
    for crime_data in crimes:
        try:
            lat = float(crime_data["lat"])
            lng = float(crime_data["lng"])
            crime_type = crime_data["type"]
            desc = crime_data["description"]
            severity = float(crime_data["severity"])

            existing = await CrimeReport.find_one(
                CrimeReport.lat == lat,
                CrimeReport.lng == lng,
                CrimeReport.type == crime_type,
                CrimeReport.description == desc,
            )

            if not existing:
                report = CrimeReport(
                    lat=lat,
                    lng=lng,
                    type=crime_type,
                    severity=severity,
                    description=desc,
                )
                await report.insert()
                inserted += 1

        except Exception as e:
            logger.error(f"process_daily_crimes: Failed to upsert crime report: {e}")

    logger.info(f"process_daily_crimes: Inserted {inserted} new records to MongoDB")
    logger.info("process_daily_crimes: Pipeline complete")