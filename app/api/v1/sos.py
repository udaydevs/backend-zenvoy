"""
SOS and Emergency alert API endpoints.
"""
from fastapi import APIRouter
from typing import List
from pydantic import BaseModel, Field
from app.services.sms import send_sos_sms

router = APIRouter()


class SOSRequest(BaseModel):
    """
    Payload required to trigger an SOS SMS alert.
    """
    lat: float
    lng: float
    user_name: str
    contact_number: str

@router.post("/sos")
async def trigger_sos(sos_data: SOSRequest):
    """
    Trigger an emergency SMS alert via Twilio to the provided contact.
    """
    result = await send_sos_sms(
        lat=sos_data.lat,
        lng=sos_data.lng,
        user_name=sos_data.user_name,
        contact_number=sos_data.contact_number,
    )
    return result
