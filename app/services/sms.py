"""
Twilio integration module for dispatching emergency alert messages.
"""
from twilio.rest import Client
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


async def send_sos_sms(lat: float, lng: float, user_name: str, contact_number: str):
    """
    Dispatch an SMS bearing an SOS message and Google Maps location link.
    
    Requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER
    to be populated in the application environment variables.
    """
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        logger.warning(
            "Twilio credentials not configured. Skipping actual SMS send.")
        return {
            "status": "mock_sent",
            "message": f"Alert sent to {contact_number} (Mock mode)",
        }

    try:
        client = Client(settings.TWILIO_ACCOUNT_SID,
                        settings.TWILIO_AUTH_TOKEN)

        maps_link = f"https://www.google.com/maps?q={lat},{lng}"
        message_body = (
            f"SOS from {user_name}! They may be in danger. Location: {maps_link}"
        )

        client.messages.create(
            body=message_body, from_=settings.TWILIO_FROM_NUMBER, to=contact_number
        )
        return {"status": "sent", "message": f"Alert sent to {contact_number}"}
    except Exception as e:
        logger.error(f"Failed to send SMS: {e}")
        return {"status": "failed", "message": str(e)}
