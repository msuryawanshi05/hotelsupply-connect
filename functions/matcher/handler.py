import os
import json
import httpx
import logging
import asyncio
from typing import List, Optional
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("matcher")

NOTIFIER_URL = os.getenv("NOTIFIER_URL", "http://localhost:8002")

DEMO_CATALOG = [
    {
        "supplier_id": "sup-001",
        "supplier_name": "CleanPro Supplies",
        "items": ["soap", "shampoo", "conditioner", "body wash", "hand sanitizer"],
        "min_quantity": 100,
        "lead_time_days": 2,
        "reliability_score": 0.95
    },
    {
        "supplier_id": "sup-002",
        "supplier_name": "LinenMaster Co.",
        "items": ["towels", "bed sheets", "pillowcases", "blankets", "bathrobes"],
        "min_quantity": 50,
        "lead_time_days": 3,
        "reliability_score": 0.92
    },
    {
        "supplier_id": "sup-003",
        "supplier_name": "HotelEssentials Ltd.",
        "items": ["soap", "towels", "toilet paper", "tissue boxes", "cleaning spray", "mop heads", "trash bags"],
        "min_quantity": 200,
        "lead_time_days": 1,
        "reliability_score": 0.88
    },
    {
        "supplier_id": "sup-004",
        "supplier_name": "GreenClean Solutions",
        "items": ["cleaning spray", "disinfectant", "floor cleaner", "glass cleaner", "mop heads", "gloves"],
        "min_quantity": 50,
        "lead_time_days": 2,
        "reliability_score": 0.90
    },
    {
        "supplier_id": "sup-005",
        "supplier_name": "Premier Hospitality Goods",
        "items": ["soap", "shampoo", "towels", "bed sheets", "coffee pods", "tea bags", "sugar packets"],
        "min_quantity": 100,
        "lead_time_days": 2,
        "reliability_score": 0.93
    }
]

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="HotelSupply Connect Matcher")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Metrics
matcher_requests_total = Counter(
    "matcher_requests_total", "Total requests to match", ["matched"]
)
matcher_score_distribution = Histogram(
    "matcher_score_distribution", "Distribution of top match scores"
)

Instrumentator().instrument(app).expose(app)

class Requirement(BaseModel):
    requirement_id: str
    item: str
    quantity: int
    urgency: str
    department: str
    deadline: str
    hotel_id: str

def score_supplier(requirement: Requirement, supplier: dict) -> float:
    req_item_words = set(requirement.item.lower().split())
    supplier_items_words = set()
    for item in supplier["items"]:
        supplier_items_words.update(item.lower().split())
        
    if not req_item_words.intersection(supplier_items_words):
        return 0.0

    score = 0.0

    if supplier["min_quantity"] > requirement.quantity:
        score -= 20.0

    urgency = requirement.urgency.lower()
    lead_time = supplier["lead_time_days"]
    
    if urgency == "high":
        if lead_time <= 1:
            score += 30.0
        elif lead_time <= 2:
            score += 20.0
        elif lead_time <= 3:
            score += 10.0
        else:
            score -= 10.0
    elif urgency == "medium":
        if lead_time <= 3:
            score += 20.0
        else:
            score += 5.0
    else:  # low
        score += 10.0

    score += supplier["reliability_score"] * 40.0

    return score

async def notify_supplier(match_data: dict):
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{NOTIFIER_URL}/notify", json=match_data)
            logger.info(f"Notifier responded with status {resp.status_code}")
    except Exception as e:
        logger.error(f"Failed to call notifier: {e}")

@app.post("/match")
async def match_requirement(req: Requirement, background_tasks: BackgroundTasks):
    scored_suppliers = []
    
    for supplier in DEMO_CATALOG:
        score = score_supplier(req, supplier)
        if score > 0:
            scored_suppliers.append({
                "supplier_id": supplier["supplier_id"],
                "supplier_name": supplier["supplier_name"],
                "score": score
            })
            
    scored_suppliers.sort(key=lambda x: x["score"], reverse=True)
    top_matches = scored_suppliers[:2]
    
    if not top_matches:
        matcher_requests_total.labels(matched="false").inc()
        logger.info(json.dumps({"event": "match_attempted", "requirement_id": req.requirement_id, "matched": False}))
        return {"matched": False, "candidates": []}

    matcher_requests_total.labels(matched="true").inc()
    top_score = top_matches[0]["score"]
    matcher_score_distribution.observe(top_score)
    
    match_response = {
        "matched": True,
        "candidates": top_matches
    }
    
    logger.info(json.dumps({
        "event": "match_success", 
        "requirement_id": req.requirement_id, 
        "matched": True,
        "top_supplier_id": top_matches[0]["supplier_id"],
        "top_score": top_score
    }))

    notify_payload = {
        "requirement_id": req.requirement_id,
        "hotel_id": req.hotel_id,
        "item": req.item,
        "quantity": req.quantity,
        "urgency": req.urgency,
        "supplier_id": top_matches[0]["supplier_id"],
        "supplier_name": top_matches[0]["supplier_name"],
        "score": top_score,
        "matched": True
    }
    
    background_tasks.add_task(notify_supplier, notify_payload)
    
    return match_response

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "matcher"}

@app.get("/")
async def root():
    return {
        "service": "HotelSupply Connect Matcher",
        "version": "1.0.0",
        "note": "Designed for Knative/OpenShift Serverless deployment (scale-to-zero)"
    }
