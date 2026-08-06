# HotelSupply Connect API
# OpenShift Webhook Trigger Verification
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
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////tmp/hotelsupply.db")

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
        # Clean up any leftover duplicate test hotels & requirements created during automated DOM testing
        test_hotels = session.exec(select(Hotel).where(Hotel.name.like("Test%"))).all()
        if test_hotels:
            test_hotel_ids = [th.id for th in test_hotels]
            test_reqs = session.exec(select(Requirement).where(Requirement.hotel_id.in_(test_hotel_ids))).all()
            for tr in test_reqs:
                session.delete(tr)
            for th in test_hotels:
                session.delete(th)
            session.commit()

        logger.info("Ensuring 25 Real Hotels, 25 Suppliers, and 25 Requirements are seeded...")

        
        # 25 Real Hotels
        hotel_data = [
            ("Grand Hyatt Mumbai", "procurement@grandhyattmumbai.com"),
            ("The Taj Mahal Palace Mumbai", "supply@tajhotels.com"),
            ("Marriott Marquis New Delhi", "procurement@marriottmarquis.com"),
            ("Oberoi Udaivilas Udaipur", "purchasing@oberoihotels.com"),
            ("ITC Maurya New Delhi", "inventory@itchotels.in"),
            ("The Leela Palace Bengaluru", "supply@theleela.com"),
            ("The St. Regis Mumbai", "procurement@stregismumbai.com"),
            ("JW Marriott Juhu Mumbai", "supply@jwmarriottjuhu.com"),
            ("Four Seasons Hotel Mumbai", "procurement@fourseasonsmumbai.com"),
            ("Fairmont Jaipur", "purchasing@fairmontjaipur.com"),
            ("Trident Nariman Point Mumbai", "supply@tridenthotels.com"),
            ("The Ritz-Carlton Bengaluru", "inventory@ritzcarltonbengaluru.com"),
            ("W Goa Resort", "procurement@wgoa.com"),
            ("Conrad Pune", "supply@conradpune.com"),
            ("Taj Falaknuma Palace Hyderabad", "purchasing@falaknumapalace.com"),
            ("Hyatt Regency Kolkata", "inventory@hyattregencykolkata.com"),
            ("The Lalit New Delhi", "supply@thelalit.com"),
            ("Park Hyatt Goa Resort", "procurement@parkhyattgoa.com"),
            ("Novotel Mumbai Juhu Beach", "purchasing@novotelmumbai.com"),
            ("Alila Diwa Goa", "supply@aliladiwagoa.com"),
            ("Radisson Blu Udaipur Palace", "inventory@radissonbluudaipur.com"),
            ("Le Meridien New Delhi", "procurement@lemeridiennewdelhi.com"),
            ("Taj Lake Palace Udaipur", "supply@tajlakepalace.com"),
            ("Sofitel Mumbai BKC", "purchasing@sofitelmumbai.com"),
            ("ITC Grand Chola Chennai", "inventory@itcgrandchola.com")
        ]

        hotels = []
        for name, email in hotel_data:
            existing = session.exec(select(Hotel).where(Hotel.name == name)).first()
            if not existing:
                h = Hotel(name=name, contact_email=email)
                session.add(h)
                hotels.append(h)
            else:
                hotels.append(existing)
        session.commit()
        for h in hotels:
            session.refresh(h)

        # 25 Real Suppliers
        supplier_data = [
            ("CleanPro Supplies", "sales@cleanpro.com", "soap,shampoo,conditioner,body wash,hand sanitizer"),
            ("LinenMaster Co.", "orders@linenmaster.com", "towels,bed sheets,pillowcases,blankets,bathrobes"),
            ("HotelEssentials Ltd.", "b2b@hotelessentials.com", "soap,towels,toilet paper,tissue boxes,cleaning spray,mop heads,trash bags"),
            ("GreenClean Solutions", "info@greenclean.com", "cleaning spray,disinfectant,floor cleaner,glass cleaner,mop heads,gloves"),
            ("Premier Hospitality Goods", "supply@premiergoods.com", "soap,shampoo,towels,bed sheets,coffee pods,tea bags,sugar packets"),
            ("Apex Amenity Co.", "b2b@apexamenity.com", "soap,shampoo,shower gel,lotion,dental kits,sewing kits"),
            ("EcoBath Luxuries", "orders@ecobath.com", "organic soap,bamboo towels,eco shampoo,herbal conditioner,bath salts"),
            ("Crest Sanitation Supplies", "sales@crestsanitation.com", "disinfectant,sanitizing wipes,hand sanitizer,bleach,trash bags"),
            ("UniformCraft India", "info@uniformcraft.in", "chef aprons,housekeeping uniforms,front desk suits,waiter vests"),
            ("BeverageDirect Hospitality", "orders@beveragedirect.com", "coffee pods,espresso capsules,tea bags,bottled water,fruit juices"),
            ("FreshLinen Express", "b2b@freshlinen.com", "bed sheets,duvet covers,pillowcases,tablecloths,napkins"),
            ("SparkleClean Chem", "sales@sparkleclean.com", "glass cleaner,floor cleaner,carpet shampoo,degreaser,stainless steel polish"),
            ("ComfortRest Bedding", "orders@comfortrest.com", "pillows,mattress protectors,duvets,bed toppers,feather beds"),
            ("ChefPro Kitchen Supplies", "sales@chefpro.com", "chef knives,cookware,cutting boards,stainless utensils,pans"),
            ("PureWater Systems", "info@purewater.com", "water filtration cartridges,bottled mineral water,water carafes"),
            ("SafeGuard Protection", "b2b@safeguard.com", "latex gloves,nitrile gloves,face masks,safety goggles,first aid kits"),
            ("Glassware Luxuries", "orders@glasswareluxuries.com", "wine glasses,water tumblers,cocktail shakers,decanters"),
            ("EcoPaper Products", "sales@ecopaper.com", "toilet paper,tissue boxes,paper towels,paper napkins,coasters"),
            ("Royal Velvet Fabrics", "b2b@royalvelvet.com", "blackout curtains,sheer drapes,table runners,cushion covers"),
            ("Golden Touch Amenities", "orders@goldentouch.com", "comb kits,shaving kits,vanity kits,shower caps,shoe mitts"),
            ("CleanTech Solutions", "sales@cleantech.com", "vacuum cleaner bags,floor scrubbing pads,microfiber cloths,dusters"),
            ("MasterChef Utensils", "info@masterchefutensils.com", "buffet chafing dishes,serving tongs,chafing fuel,soup tureens"),
            ("Hospitality Direct", "orders@hospitalitydirect.com", "do not disturb signs,luggage tags,keycard sleeves,leather blotters"),
            ("PureAir Filtration", "b2b@pureair.com", "hepa air filters,hvac filters,aroma diffusers,essential oils"),
            ("BrightLight Fixtures", "sales@brightlight.com", "led bulb fixtures,bedside lamps,emergency torches,dimmer switches")
        ]

        suppliers = []
        for name, email, items in supplier_data:
            existing = session.exec(select(Supplier).where(Supplier.name == name)).first()
            if not existing:
                s = Supplier(name=name, contact_email=email, catalog_items=items)
                session.add(s)
                suppliers.append(s)
            else:
                suppliers.append(existing)
        session.commit()
        for s in suppliers:
            session.refresh(s)

        # 25 Real Requirements Orders across open, matched, accepted, fulfilled
        from datetime import date, timedelta
        today = date.today()

        req_specs = [
            (0, "Luxury Soap Bars", 500, "high", "housekeeping", 2, RequirementStatus.fulfilled, 0),
            (1, "Egyptian Cotton Towel Sets", 250, "medium", "housekeeping", 4, RequirementStatus.accepted, 1),
            (2, "Heavy Duty Disinfectant", 350, "high", "janitorial", 1, RequirementStatus.matched, 3),
            (3, "Percale Bed Sheet Sets", 150, "low", "housekeeping", 7, RequirementStatus.open, None),
            (4, "Gourmet Espresso Pods", 600, "low", "food_beverage", 3, RequirementStatus.fulfilled, 4),
            (5, "Organic Herbal Shampoo", 400, "medium", "housekeeping", 5, RequirementStatus.accepted, 5),
            (6, "Eco Toilet Paper 3-ply", 800, "high", "housekeeping", 2, RequirementStatus.matched, 2),
            (7, "Biodegradable Trash Bags", 500, "low", "janitorial", 8, RequirementStatus.open, None),
            (8, "Premium English Tea Bags", 1000, "low", "food_beverage", 6, RequirementStatus.fulfilled, 9),
            (9, "Plush Velvet Bathrobes", 120, "medium", "housekeeping", 4, RequirementStatus.accepted, 1),
            (10, "Glass Cleaner Concentrate", 200, "high", "janitorial", 1, RequirementStatus.matched, 11),
            (11, "Bamboo Fiber Pillows", 180, "low", "housekeeping", 9, RequirementStatus.open, None),
            (12, "Bottled Mineral Water 500ml", 1200, "medium", "food_beverage", 3, RequirementStatus.fulfilled, 14),
            (13, "Stainless Steel Chef Aprons", 80, "medium", "kitchen", 5, RequirementStatus.accepted, 8),
            (14, "Nitrile Cleaning Gloves", 300, "high", "housekeeping", 2, RequirementStatus.matched, 15),
            (15, "Keycard Sleeves Embossed", 2000, "low", "front_desk", 10, RequirementStatus.open, None),
            (16, "Microfiber Dusting Cloths", 450, "medium", "housekeeping", 4, RequirementStatus.fulfilled, 20),
            (17, "Crystal Wine Glassware", 160, "high", "dining", 2, RequirementStatus.accepted, 16),
            (18, "HEPA Air Filters 24x24", 90, "medium", "maintenance", 5, RequirementStatus.matched, 23),
            (19, "Dental Kit Travel Packs", 500, "low", "housekeeping", 11, RequirementStatus.open, None),
            (20, "Damask Tablecloth Linen", 110, "high", "dining", 3, RequirementStatus.fulfilled, 10),
            (21, "Floor Scrubbing Pads 16in", 140, "medium", "janitorial", 6, RequirementStatus.accepted, 20),
            (22, "LED Bedside Lamp Bulbs", 220, "high", "maintenance", 2, RequirementStatus.matched, 24),
            (23, "Woven Disposable Slippers", 600, "low", "housekeeping", 12, RequirementStatus.open, None),
            (24, "Leather Desk Blotters", 50, "medium", "front_desk", 4, RequirementStatus.fulfilled, 22),
        ]

        existing_reqs = session.exec(select(Requirement)).all()
        if len(existing_reqs) < 25:
            req_objects = []
            for h_idx, item, qty, urg, dept, days, status, s_idx in req_specs:
                h_id = hotels[h_idx % len(hotels)].id
                s_id = suppliers[s_idx % len(suppliers)].id if s_idx is not None else None
                r = Requirement(
                    hotel_id=h_id,
                    item=item,
                    quantity=qty,
                    urgency=urg,
                    department=dept,
                    deadline=today + timedelta(days=days),
                    status=status,
                    matched_supplier_id=s_id
                )
                req_objects.append(r)
            session.add_all(req_objects)
            session.commit()

        logger.info("25 Real Hotels, 25 Suppliers, and 25 Requirements successfully seeded!")


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

_static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(_static_dir):
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
def create_requirement(requirement: RequirementCreate, background_tasks: BackgroundTasks, session: Session = Depends(get_session), user: dict = Depends(require_role("hotel", "admin"))):
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
def accept_requirement(id: uuid.UUID, session: Session = Depends(get_session), user: dict = Depends(require_role("supplier", "admin"))):
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
def fulfill_requirement(id: uuid.UUID, session: Session = Depends(get_session), user: dict = Depends(require_role("supplier", "admin"))):
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

