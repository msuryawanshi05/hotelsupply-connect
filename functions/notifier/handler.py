import json
import logging
from datetime import datetime
from typing import List
from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notifier")

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="HotelSupply Connect Notifier")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

notifications_sent_total = Counter(
    "notifications_sent_total", "Total notifications sent", ["urgency", "channel"]
)

Instrumentator().instrument(app).expose(app)

class NotificationRequest(BaseModel):
    requirement_id: str
    hotel_id: str
    item: str
    quantity: int
    urgency: str
    supplier_id: str
    supplier_name: str
    score: float
    matched: bool

notification_log = []

@app.post("/notify")
async def notify(req: NotificationRequest):
    event = {
        "event": "supplier_notified",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "requirement_id": req.requirement_id,
        "supplier_id": req.supplier_id,
        "supplier_name": req.supplier_name,
        "item": req.item,
        "quantity": req.quantity,
        "urgency": req.urgency,
        "channel": "email",
        "status": "sent"
    }
    
    logger.info(json.dumps(event))
    
    notifications_sent_total.labels(urgency=req.urgency, channel="email").inc()
    
    notification_log.insert(0, event)
    if len(notification_log) > 100:
        notification_log.pop()
        
    return {
        "status": "notified",
        "requirement_id": req.requirement_id,
        "supplier_name": req.supplier_name,
        "channel": "email"
    }

@app.get("/notifications")
async def get_notifications():
    return notification_log[:20]

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "notifier"}

@app.get("/")
async def root():
    return {
        "service": "HotelSupply Connect Notifier",
        "version": "1.0.0",
        "note": "Designed for Knative/OpenShift Serverless deployment (scale-to-zero)"
    }
