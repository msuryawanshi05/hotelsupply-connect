import os
import uuid
import logging
from datetime import datetime, date
from enum import Enum
from typing import Optional, List
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Depends, HTTPException, status, Form, BackgroundTasks, Request
from fastapi.security import OAuth2PasswordBearer
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Field, Session, create_engine, select
from jose import JWTError, jwt
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Config ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://hotelsupply:hotelsupply@localhost:5432/hotelsupplydb")
MATCHER_URL = os.getenv("MATCHER_URL", "http://localhost:8001")
NOTIFIER_URL = os.getenv("NOTIFIER_URL", "http://localhost:8002")
SECRET_KEY = os.getenv("SECRET_KEY", "changeme-replace-in-production")
ALGORITHM = "HS256"

if SECRET_KEY == "changeme-replace-in-production":
    logger.warning(
        "SECURITY WARNING: SECRET_KEY is set to the default insecure value. "
        "Set the SECRET_KEY environment variable to a strong random secret before deploying to production. "
        "Generate one with: openssl rand -hex 32"
    )

engine = create_engine(DATABASE_URL)

# --- Models ---
class HotelBase(SQLModel):
    name: str
    contact_email: str

class Hotel(HotelBase, table=True):
    __tablename__ = "hotels"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class SupplierBase(SQLModel):
    name: str
    contact_email: str
    catalog_items: str

class Supplier(SupplierBase, table=True):
    __tablename__ = "suppliers"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class RequirementStatus(str, Enum):
    open = "open"
    matched = "matched"
    accepted = "accepted"
    fulfilled = "fulfilled"

class RequirementBase(SQLModel):
    hotel_id: uuid.UUID = Field(foreign_key="hotels.id")
    item: str
    quantity: int
    urgency: str
    department: str
    deadline: date

class Requirement(RequirementBase, table=True):
    __tablename__ = "requirements"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: RequirementStatus = Field(default=RequirementStatus.open)
    matched_supplier_id: Optional[uuid.UUID] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

# Response Models
class HotelRead(HotelBase):
    id: uuid.UUID
    created_at: datetime

class SupplierRead(SupplierBase):
    id: uuid.UUID
    created_at: datetime

class RequirementRead(RequirementBase):
    id: uuid.UUID
    status: RequirementStatus
    matched_supplier_id: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime

class RequirementCreate(RequirementBase):
    pass

# --- Auth ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

def create_access_token(data: dict):
    to_encode = data.copy()
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub: str = payload.get("sub")
        role: str = payload.get("role")
        if sub is None or role is None:
            raise credentials_exception
        return {"sub": sub, "role": role}
    except JWTError:
        raise credentials_exception

def require_role(*allowed_roles: str):
    def role_dependency(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return current_user
    return role_dependency

# --- Database Dependency ---
def get_session():
    with Session(engine) as session:
        yield session

# --- Metrics ---
requirements_created_total = Counter(
    "requirements_created_total",
    "Total number of requirements created",
    ["urgency", "department"]
)
requirements_fulfilled_total = Counter(
    "requirements_fulfilled_total",
    "Total number of requirements fulfilled"
)
matcher_duration_seconds = Histogram(
    "matcher_duration_seconds",
    "Time spent waiting for matcher response"
)

def seed_initial_data():
    with Session(engine) as session:
        existing_hotels = session.exec(select(Hotel)).all()
        if existing_hotels:
            return

        logger.info("Seeding 5 Hotels, 5 Suppliers, and 8 Requirements...")
        
        # 5 Hotels
        h1 = Hotel(name="Grand Hyatt Mumbai", contact_email="procurement@grandhyattmumbai.com")
        h2 = Hotel(name="The Taj Mahal Palace", contact_email="supply@tajhotels.com")
        h3 = Hotel(name="Marriott Marquis Delhi", contact_email="procurement@marriottmarquis.com")
        h4 = Hotel(name="Oberoi Udaivilas", contact_email="purchasing@oberoihotels.com")
        h5 = Hotel(name="ITC Maurya New Delhi", contact_email="inventory@itchotels.in")
        
        session.add_all([h1, h2, h3, h4, h5])
        session.commit()
        for h in [h1, h2, h3, h4, h5]:
            session.refresh(h)

        # 5 Suppliers
        s1 = Supplier(name="CleanPro Supplies", contact_email="sales@cleanpro.com", catalog_items="soap,shampoo,conditioner,body wash,hand sanitizer")
        s2 = Supplier(name="LinenMaster Co.", contact_email="orders@linenmaster.com", catalog_items="towels,bed sheets,pillowcases,blankets,bathrobes")
        s3 = Supplier(name="HotelEssentials Ltd.", contact_email="b2b@hotelessentials.com", catalog_items="soap,towels,toilet paper,tissue boxes,cleaning spray,mop heads,trash bags")
        s4 = Supplier(name="GreenClean Solutions", contact_email="info@greenclean.com", catalog_items="cleaning spray,disinfectant,floor cleaner,glass cleaner,mop heads,gloves")
        s5 = Supplier(name="Premier Hospitality Goods", contact_email="supply@premiergoods.com", catalog_items="soap,shampoo,towels,bed sheets,coffee pods,tea bags,sugar packets")

        session.add_all([s1, s2, s3, s4, s5])
        session.commit()
        for s in [s1, s2, s3, s4, s5]:
            session.refresh(s)

        # 8 Requirements across open, matched, accepted, fulfilled
        from datetime import date, timedelta
        today = date.today()

        r1 = Requirement(hotel_id=h1.id, item="Luxury Soap Bars", quantity=500, urgency="high", department="housekeeping", deadline=today + timedelta(days=2), status=RequirementStatus.fulfilled, matched_supplier_id=s1.id)
        r2 = Requirement(hotel_id=h2.id, item="Cotton Towel Sets", quantity=200, urgency="medium", department="housekeeping", deadline=today + timedelta(days=4), status=RequirementStatus.accepted, matched_supplier_id=s2.id)
        r3 = Requirement(hotel_id=h3.id, item="Cleaning Spray", quantity=350, urgency="high", department="janitorial", deadline=today + timedelta(days=1), status=RequirementStatus.matched, matched_supplier_id=s4.id)
        r4 = Requirement(hotel_id=h4.id, item="Bed Sheet Sets", quantity=150, urgency="low", department="housekeeping", deadline=today + timedelta(days=7), status=RequirementStatus.open)
        r5 = Requirement(hotel_id=h5.id, item="Disinfectant Solution", quantity=100, urgency="medium", department="janitorial", deadline=today + timedelta(days=3), status=RequirementStatus.fulfilled, matched_supplier_id=s4.id)
        r6 = Requirement(hotel_id=h1.id, item="Herbal Shampoo", quantity=400, urgency="medium", department="housekeeping", deadline=today + timedelta(days=5), status=RequirementStatus.accepted, matched_supplier_id=s1.id)
        r7 = Requirement(hotel_id=h2.id, item="Toilet Paper Rolls", quantity=800, urgency="high", department="housekeeping", deadline=today + timedelta(days=2), status=RequirementStatus.matched, matched_supplier_id=s3.id)
        r8 = Requirement(hotel_id=h5.id, item="Espresso Pods", quantity=600, urgency="low", department="food_beverage", deadline=today + timedelta(days=10), status=RequirementStatus.open)

        session.add_all([r1, r2, r3, r4, r5, r6, r7, r8])
        session.commit()
        logger.info("Dummy data successfully seeded!")

# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    try:
        seed_initial_data()
    except Exception as e:
        logger.error(f"Error seeding data: {e}")
    yield


app = FastAPI(title="HotelSupply Connect API", version="1.0.0", lifespan=lifespan)

# CORS — allow browser dashboard to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static dashboard files
_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

Instrumentator().instrument(app).expose(app)

# --- Error Handlers ---
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    # Log the full exception server-side for debugging, but never expose details to clients
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please try again later."}
    )

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    from fastapi.responses import Response
    return Response(status_code=204)

def _serve_page(filename: str):
    path = os.path.join(os.path.dirname(__file__), "static", filename)
    if os.path.exists(path):
        return FileResponse(path)
    # Fallback to index.html if specific page doesn't exist
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"service": "HotelSupply Connect API", "version": "1.0.0"}

@app.get("/", include_in_schema=False)
def root():
    return _serve_page("landing.html")

@app.get("/landing", include_in_schema=False)
def page_landing():
    return _serve_page("landing.html")

@app.get("/dashboard", include_in_schema=False)
def page_dashboard():
    return _serve_page("dashboard.html")


@app.get("/orders", include_in_schema=False)
def page_requirements():
    return _serve_page("requirements.html")

@app.get("/entities-page", include_in_schema=False)
def page_entities():
    return _serve_page("entities.html")

@app.get("/events-page", include_in_schema=False)
def page_events():
    return _serve_page("events.html")

@app.get("/matcher-page", include_in_schema=False)
def page_matcher():
    return _serve_page("matcher.html")

@app.get("/health-page", include_in_schema=False)
def page_health():
    return _serve_page("health.html")

@app.get("/profile", include_in_schema=False)
def page_profile():
    return _serve_page("profile.html")


@app.post("/auth/token")
def login(username: str = Form(...), role: str = Form(...), password: str = Form(...)):
    if password != "demo123":
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": username, "role": role})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/hotels", response_model=HotelRead)
def create_hotel(hotel: HotelBase, session: Session = Depends(get_session), user: dict = Depends(require_role("admin", "hotel"))):
    db_hotel = Hotel.model_validate(hotel)
    session.add(db_hotel)
    session.commit()
    session.refresh(db_hotel)
    return db_hotel

@app.get("/hotels", response_model=List[HotelRead])
def list_hotels(session: Session = Depends(get_session), user: dict = Depends(get_current_user)):
    return session.exec(select(Hotel)).all()

@app.post("/suppliers", response_model=SupplierRead)
def create_supplier(supplier: SupplierBase, session: Session = Depends(get_session), user: dict = Depends(require_role("admin"))):
    db_supplier = Supplier.model_validate(supplier)
    session.add(db_supplier)
    session.commit()
    session.refresh(db_supplier)
    return db_supplier

@app.get("/suppliers", response_model=List[SupplierRead])
def list_suppliers(session: Session = Depends(get_session), user: dict = Depends(get_current_user)):
    return session.exec(select(Supplier)).all()

async def match_requirement_async(req_id: uuid.UUID, requirement_dict: dict):
    """Call the matcher microservice and update requirement status on match."""
    import time
    try:
        start_time = time.time()
        # Build flat payload matching the matcher's Requirement Pydantic model
        match_payload = {
            "requirement_id": requirement_dict.get("id", str(req_id)),
            "item": requirement_dict["item"],
            "quantity": requirement_dict["quantity"],
            "urgency": requirement_dict["urgency"],
            "department": requirement_dict["department"],
            "deadline": str(requirement_dict["deadline"]),
            "hotel_id": str(requirement_dict["hotel_id"]),
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{MATCHER_URL}/match", json=match_payload)

        matcher_duration_seconds.observe(time.time() - start_time)

        if resp.status_code == 200:
            match_data = resp.json()
            # Matcher returns {"matched": bool, "candidates": [{supplier_id, supplier_name, score}]}
            if match_data.get("matched") and match_data.get("candidates"):
                top_candidate = match_data["candidates"][0]
                matched_supplier_id = top_candidate["supplier_id"]
                with Session(engine) as session:
                    db_req = session.get(Requirement, req_id)
                    if db_req:
                        # matched_supplier_id from matcher is a catalog string ID; store as note
                        # For full integration, look up actual supplier UUID from DB
                        suppliers = session.exec(
                            select(Supplier).where(Supplier.name == top_candidate["supplier_name"])
                        ).first()
                        db_req.matched_supplier_id = suppliers.id if suppliers else None
                        db_req.status = RequirementStatus.matched
                        db_req.updated_at = datetime.utcnow()
                        session.add(db_req)
                        session.commit()
                logger.info(f"Requirement {req_id} matched to supplier {matched_supplier_id}")
                # Notifier is already called by the matcher via BackgroundTasks
        else:
            logger.warning(f"Matcher returned non-200 status {resp.status_code} for requirement {req_id}")
    except Exception as e:
        logger.error(f"Error in async matcher call for requirement {req_id}: {e}")

@app.post("/requirements", response_model=RequirementRead)
def create_requirement(requirement: RequirementCreate, background_tasks: BackgroundTasks, session: Session = Depends(get_session), user: dict = Depends(require_role("hotel"))):
    db_req = Requirement.model_validate(requirement)
    session.add(db_req)
    session.commit()
    session.refresh(db_req)
    
    requirements_created_total.labels(urgency=db_req.urgency, department=db_req.department).inc()
    # Launch matcher async — synchronously triggers the event-driven matching pipeline
    background_tasks.add_task(match_requirement_async, db_req.id, db_req.model_dump(mode='json'))
    
    return db_req

@app.get("/requirements", response_model=List[RequirementRead])
def list_requirements(session: Session = Depends(get_session), user: dict = Depends(get_current_user)):
    return session.exec(select(Requirement)).all()

@app.patch("/requirements/{id}/accept", response_model=RequirementRead)
def accept_requirement(id: uuid.UUID, session: Session = Depends(get_session), user: dict = Depends(require_role("supplier"))):
    db_req = session.get(Requirement, id)
    if not db_req:
        raise HTTPException(status_code=404, detail="Requirement not found")
    db_req.status = RequirementStatus.accepted
    db_req.updated_at = datetime.utcnow()
    session.add(db_req)
    session.commit()
    session.refresh(db_req)
    return db_req

@app.patch("/requirements/{id}/fulfill", response_model=RequirementRead)
def fulfill_requirement(id: uuid.UUID, session: Session = Depends(get_session), user: dict = Depends(require_role("supplier"))):
    db_req = session.get(Requirement, id)
    if not db_req:
        raise HTTPException(status_code=404, detail="Requirement not found")
    db_req.status = RequirementStatus.fulfilled
    db_req.updated_at = datetime.utcnow()
    session.add(db_req)
    session.commit()
    session.refresh(db_req)
    
    requirements_fulfilled_total.inc()
    return db_req

@app.get("/dashboard/summary")
def dashboard_summary(session: Session = Depends(get_session)):
    reqs = session.exec(select(Requirement)).all()
    total = len(reqs)
    open_count = sum(1 for r in reqs if r.status == RequirementStatus.open)
    matched_count = sum(1 for r in reqs if r.status == RequirementStatus.matched)
    accepted_count = sum(1 for r in reqs if r.status == RequirementStatus.accepted)
    fulfilled_count = sum(1 for r in reqs if r.status == RequirementStatus.fulfilled)
    fulfillment_rate = (fulfilled_count / total) if total > 0 else 0.0
    
    return {
        "total": total,
        "open": open_count,
        "matched": matched_count,
        "accepted": accepted_count,
        "fulfilled": fulfilled_count,
        "fulfillment_rate": fulfillment_rate
    }

@app.get("/healthz")
def healthz():
    # Deliverable 10: liveness probe — checks real DB reachability
    try:
        from sqlalchemy import text
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "db": "reachable"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Database unreachable")

@app.get("/readyz")
def readyz():
    # Deliverable 10: readiness probe — checks DB + service config
    try:
        from sqlalchemy import text
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        if not MATCHER_URL or not NOTIFIER_URL:
            raise ValueError("Service URLs not configured")
        return {"status": "ok", "db": "reachable", "matcher": "configured", "notifier": "configured"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail="Services unreachable")

@app.get("/startupz", dependencies=[Depends(get_session)])
def startupz(session: Session = Depends(get_session)):
    try:
        session.exec(select(1)).first()
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Startup check failed: {e}")
        raise HTTPException(status_code=503, detail="Database tables not ready")

# --- Proxy Endpoints (for Frontend API Gateway routing) ---
@app.api_route("/proxy/matcher/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_matcher(path: str, request: Request):
    async with httpx.AsyncClient() as client:
        url = f"{MATCHER_URL}/{path}"
        req_headers = {k: v for k, v in request.headers.items() if k.lower() not in ['host', 'content-length']}
        body = await request.body()
        resp = await client.request(request.method, url, headers=req_headers, content=body, params=request.query_params)
        content_type = resp.headers.get("content-type", "")
        return JSONResponse(status_code=resp.status_code, content=resp.json() if "application/json" in content_type else resp.text)

@app.api_route("/proxy/notifier/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_notifier(path: str, request: Request):
    async with httpx.AsyncClient() as client:
        url = f"{NOTIFIER_URL}/{path}"
        req_headers = {k: v for k, v in request.headers.items() if k.lower() not in ['host', 'content-length']}
        body = await request.body()
        resp = await client.request(request.method, url, headers=req_headers, content=body, params=request.query_params)
        content_type = resp.headers.get("content-type", "")
        return JSONResponse(status_code=resp.status_code, content=resp.json() if "application/json" in content_type else resp.text)

