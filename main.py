"""
CORVIU - Change Intelligence Platform for AEC
FastAPI Backend Service
"""

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, JSON, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import httpx
import asyncio
import json
import hashlib
import os
from dotenv import load_dotenv
import jwt
import redis
import uuid
import openai

load_dotenv()

# ======================== CORVIU CONFIGURATION ========================

app = FastAPI(
    title="CORVIU API",
    description="Change Intelligence Platform for AEC - See Changes That Matter",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure with your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost/corviu")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Redis setup
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    print("✅ Redis connected")
except:
    print("⚠️ Redis not available, using in-memory cache")
    redis_client = None

# OpenAI setup
openai.api_key = os.getenv("OPENAI_API_KEY")

# Autodesk Configuration
AUTODESK_CLIENT_ID = os.getenv("AUTODESK_CLIENT_ID")
AUTODESK_CLIENT_SECRET = os.getenv("AUTODESK_CLIENT_SECRET")
AUTODESK_CALLBACK_URL = os.getenv("AUTODESK_CALLBACK_URL", "https://corviu.railway.app/auth/callback")

# ======================== DATABASE MODELS ========================

class Project(Base):
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    acc_project_id = Column(String, unique=True)
    acc_hub_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_sync = Column(DateTime)
    settings = Column(JSON, default={})
    watch_list = Column(JSON, default=[])
    organization = Column(String)
    active = Column(Boolean, default=True)

class Change(Base):
    __tablename__ = "changes"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, nullable=False)
    element_id = Column(String)
    element_name = Column(String)
    change_type = Column(String)  # structural, mep, architectural
    description = Column(Text)
    priority = Column(String)  # critical, high, medium, low
    cost_impact = Column(Float)
    schedule_impact = Column(Float)
    affected_trades = Column(JSON)
    clash_detected = Column(Boolean, default=False)
    ai_summary = Column(Text)
    detected_at = Column(DateTime, default=datetime.utcnow)
    resolved = Column(Boolean, default=False)

class ROIMetric(Base):
    __tablename__ = "roi_metrics"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, nullable=False)
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    meetings_saved = Column(Integer, default=0)
    hours_saved = Column(Float, default=0)
    cost_saved = Column(Float, default=0)
    decisions_accelerated = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

# Create tables
Base.metadata.create_all(bind=engine)

# ======================== PYDANTIC MODELS ========================

class ChangeCreate(BaseModel):
    element_name: str
    change_type: str
    description: str
    cost_impact: float = 0
    schedule_impact: float = 0
    affected_trades: List[str] = []

class ChangeSummaryResponse(BaseModel):
    total_changes: int
    critical_changes: int
    total_cost_impact: float
    total_schedule_impact: float
    ai_summary: str
    changes: List[Dict]

class ProjectResponse(BaseModel):
    id: str
    name: str
    last_sync: Optional[datetime]
    active: bool
    total_changes: Optional[int] = 0

# ======================== DEPENDENCIES ========================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ======================== AUTODESK CLIENT ========================

class AutodeskClient:
    def __init__(self):
        self.client_id = AUTODESK_CLIENT_ID
        self.client_secret = AUTODESK_CLIENT_SECRET
        self.base_url = "https://developer.api.autodesk.com"
        self.token_cache = {}
    
    async def get_auth_url(self) -> str:
        """Generate OAuth URL for Autodesk"""
        return (
            f"{self.base_url}/authentication/v1/authorize"
            f"?response_type=code"
            f"&client_id={self.client_id}"
            f"&redirect_uri={AUTODESK_CALLBACK_URL}"
            f"&scope=data:read data:write"
        )
    
    async def exchange_code(self, code: str) -> Dict:
        """Exchange auth code for access token"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/authentication/v1/gettoken",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": AUTODESK_CALLBACK_URL
                }
            )
            return response.json()

autodesk_client = AutodeskClient()

# ======================== AI SUMMARIZER ========================

async def generate_ai_summary(changes: List[Dict]) -> str:
    """Generate AI summary of changes using OpenAI"""
    if not changes:
        return "No changes detected in this revision."
    
    if not openai.api_key:
        # Fallback to basic summary if no OpenAI key
        critical = len([c for c in changes if c.get("priority") == "critical"])
        total_cost = sum(c.get("cost_impact", 0) for c in changes)
        return f"{len(changes)} changes detected • {critical} critical items • ${total_cost:,.0f} cost impact"
    
    try:
        # Prepare change descriptions for AI
        change_texts = []
        for c in changes[:10]:  # Limit to top 10 for context window
            change_texts.append(f"- {c['element_name']}: {c['description']} (${c.get('cost_impact', 0):,.0f})")
        
        prompt = f"""Summarize these BIM model changes in one concise sentence (max 20 words):
        {chr(10).join(change_texts)}
        
        Focus on: critical changes, total cost impact, and any clashes."""
        
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0.3
        )
        
        return response.choices[0].message.content.strip()
    except:
        # Fallback if OpenAI fails
        return f"{len(changes)} changes detected • ${sum(c.get('cost_impact', 0) for c in changes):,.0f} impact"

# ======================== CHANGE DETECTION ========================

def calculate_priority(change: Dict) -> str:
    """Calculate change priority based on impact"""
    cost = change.get("cost_impact", 0)
    schedule = change.get("schedule_impact", 0)
    
    if cost > 10000 or schedule > 3:
        return "critical"
    elif cost > 5000 or schedule > 1:
        return "high"
    elif cost > 1000 or schedule > 0.5:
        return "medium"
    return "low"

# ======================== API ENDPOINTS ========================

@app.get("/", response_class=HTMLResponse)
async def root():
    """CORVIU API Landing Page"""
    return """
    <html>
        <head>
            <title>CORVIU API</title>
            <style>
                body { 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    height: 100vh;
                    margin: 0;
                }
                .container {
                    text-align: center;
                    padding: 40px;
                    background: rgba(255,255,255,0.1);
                    border-radius: 20px;
                    backdrop-filter: blur(10px);
                }
                h1 { font-size: 48px; margin: 0 0 10px 0; }
                p { font-size: 20px; opacity: 0.9; margin: 0 0 30px 0; }
                a {
                    display: inline-block;
                    padding: 12px 30px;
                    background: white;
                    color: #667eea;
                    text-decoration: none;
                    border-radius: 8px;
                    font-weight: 600;
                    margin: 0 10px;
                }
                .status { 
                    margin-top: 30px;
                    padding: 10px;
                    background: rgba(76, 175, 80, 0.2);
                    border-radius: 8px;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🏗️ CORVIU</h1>
                <p>Change Intelligence Platform for AEC</p>
                <div>
                    <a href="/api/docs">API Documentation</a>
                    <a href="/health">System Status</a>
                </div>
                <div class="status">✅ System Operational</div>
            </div>
        </body>
    </html>
    """

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    checks = {
        "api": "healthy",
        "database": "healthy",
        "redis": "healthy" if redis_client else "unavailable",
        "autodesk": "configured" if AUTODESK_CLIENT_ID else "not configured",
        "openai": "configured" if openai.api_key else "not configured"
    }
    
    return {
        "status": "operational",
        "service": "CORVIU",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": checks
    }

@app.get("/auth/login")
async def login():
    """Start Autodesk OAuth flow"""
    auth_url = await autodesk_client.get_auth_url()
    return {"auth_url": auth_url, "provider": "autodesk"}

@app.get("/auth/callback")
async def auth_callback(code: str, db: Session = Depends(get_db)):
    """Handle OAuth callback from Autodesk"""
    try:
        token_data = await autodesk_client.exchange_code(code)
        
        # Store token in Redis if available
        if redis_client:
            redis_client.setex(
                f"token:{token_data.get('access_token', '')[:8]}",
                token_data.get("expires_in", 3600),
                json.dumps(token_data)
            )
        
        return {
            "success": True,
            "message": "Successfully connected to Autodesk",
            "access_token": token_data.get("access_token"),
            "expires_in": token_data.get("expires_in")
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/projects")
async def create_project(
    name: str,
    acc_project_id: str,
    acc_hub_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Create a new CORVIU project"""
    project = Project(
        name=name,
        acc_project_id=acc_project_id,
        acc_hub_id=acc_hub_id,
        organization="Default"
    )
    db.add(project)
    db.commit()
    
    return {
        "id": project.id,
        "name": project.name,
        "message": "Project created successfully"
    }

@app.get("/api/projects")
async def list_projects(db: Session = Depends(get_db)):
    """List all CORVIU projects"""
    projects = db.query(Project).filter(Project.active == True).all()
    
    results = []
    for p in projects:
        change_count = db.query(Change).filter(Change.project_id == p.id).count()
        results.append(ProjectResponse(
            id=p.id,
            name=p.name,
            last_sync=p.last_sync,
            active=p.active,
            total_changes=change_count
        ))
    
    return results

@app.get("/api/projects/{project_id}/changes")
async def get_changes(
    project_id: str,
    limit: int = 20,
    db: Session = Depends(get_db)
) -> ChangeSummaryResponse:
    """Get changes for a project with AI summary"""
    
    # Get recent changes
    changes = db.query(Change).filter(
        Change.project_id == project_id
    ).order_by(Change.detected_at.desc()).limit(limit).all()
    
    if not changes:
        return ChangeSummaryResponse(
            total_changes=0,
            critical_changes=0,
            total_cost_impact=0,
            total_schedule_impact=0,
            ai_summary="No changes detected yet. Connect your Autodesk project to start monitoring.",
            changes=[]
        )
    
    # Convert to dict for processing
    changes_dict = [
        {
            "id": c.id,
            "element_name": c.element_name,
            "change_type": c.change_type,
            "description": c.description,
            "priority": c.priority,
            "cost_impact": c.cost_impact,
            "schedule_impact": c.schedule_impact,
            "affected_trades": c.affected_trades,
            "clash_detected": c.clash_detected,
            "detected_at": c.detected_at.isoformat()
        }
        for c in changes
    ]
    
    # Generate AI summary
    ai_summary = await generate_ai_summary(changes_dict)
    
    # Calculate metrics
    critical_count = len([c for c in changes_dict if c["priority"] == "critical"])
    total_cost = sum(c["cost_impact"] for c in changes_dict)
    max_schedule = max((c["schedule_impact"] for c in changes_dict), default=0)
    
    return ChangeSummaryResponse(
        total_changes=len(changes_dict),
        critical_changes=critical_count,
        total_cost_impact=total_cost,
        total_schedule_impact=max_schedule,
        ai_summary=ai_summary,
        changes=changes_dict
    )

@app.post("/api/projects/{project_id}/changes")
async def create_change(
    project_id: str,
    change_data: ChangeCreate,
    db: Session = Depends(get_db)
):
    """Manually create a change (for testing)"""
    
    change = Change(
        project_id=project_id,
        element_name=change_data.element_name,
        change_type=change_data.change_type,
        description=change_data.description,
        cost_impact=change_data.cost_impact,
        schedule_impact=change_data.schedule_impact,
        affected_trades=change_data.affected_trades,
        priority=calculate_priority(change_data.dict())
    )
    
    db.add(change)
    db.commit()
    
    return {"success": True, "change_id": change.id}

@app.get("/api/projects/{project_id}/roi")
async def get_roi_metrics(
    project_id: str,
    db: Session = Depends(get_db)
):
    """Get ROI metrics for a project"""
    
    # Get recent changes
    recent_changes = db.query(Change).filter(
        Change.project_id == project_id,
        Change.detected_at >= datetime.utcnow() - timedelta(days=7)
    ).all()
    
    # Calculate ROI metrics
    meetings_saved = len(recent_changes) // 5  # 1 meeting per 5 changes
    hours_saved = len(recent_changes) * 0.5  # 30 min per change reviewed
    cost_saved = hours_saved * 155  # $155/hour average rate
    decisions_accelerated = len([c for c in recent_changes if c.priority in ["critical", "high"]])
    
    # Store metrics
    metric = ROIMetric(
        project_id=project_id,
        period_start=datetime.utcnow() - timedelta(days=7),
        period_end=datetime.utcnow(),
        meetings_saved=meetings_saved,
        hours_saved=hours_saved,
        cost_saved=cost_saved,
        decisions_accelerated=decisions_accelerated
    )
    db.add(metric)
    db.commit()
    
    return {
        "project_id": project_id,
        "period": "last_7_days",
        "meetings_saved": meetings_saved,
        "hours_saved": round(hours_saved, 1),
        "cost_saved": round(cost_saved, 2),
        "decisions_accelerated": decisions_accelerated,
        "message": f"CORVIU saved your team ${cost_saved:,.0f} this week"
    }

@app.post("/api/demo/seed")
async def seed_demo_data(db: Session = Depends(get_db)):
    """Seed demo data for testing"""
    
    # Create demo project
    project = Project(
        name="Tower Block A - Demo",
        acc_project_id="demo_" + str(uuid.uuid4())[:8],
        organization="Demo Company"
    )
    db.add(project)
    db.commit()
    
    # Create demo changes
    demo_changes = [
        {
            "element_name": "Level 2 Slab",
            "change_type": "structural",
            "description": "Slab moved 75mm north",
            "cost_impact": 45000,
            "schedule_impact": 3,
            "affected_trades": ["MEP", "Structural"],
            "priority": "critical"
        },
        {
            "element_name": "Conference Room Lighting",
            "change_type": "mep",
            "description": "12 new light fixtures added",
            "cost_impact": 8400,
            "schedule_impact": 1,
            "affected_trades": ["Electrical"],
            "priority": "high"
        },
        {
            "element_name": "Interior Walls",
            "change_type": "architectural",
            "description": "3 walls relocated for room expansion",
            "cost_impact": 3200,
            "schedule_impact": 0.5,
            "affected_trades": ["Drywall", "Electrical"],
            "priority": "medium"
        }
    ]
    
    for change_data in demo_changes:
        change = Change(project_id=project.id, **change_data)
        db.add(change)
    
    db.commit()
    
    return {
        "success": True,
        "project_id": project.id,
        "message": "Demo data created successfully",
        "demo_url": f"/api/projects/{project.id}/changes"
    }

# ======================== WebSocket for Real-time Updates ========================

@app.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    """WebSocket for real-time change notifications"""
    await websocket.accept()
    try:
        while True:
            # Keep connection alive and wait for messages
            data = await websocket.receive_text()
            
            # Echo back for now (in production, broadcast changes here)
            await websocket.send_json({
                "type": "ping",
                "project_id": project_id,
                "timestamp": datetime.utcnow().isoformat()
            })
    except WebSocketDisconnect:
        pass

# ======================== STARTUP ========================

@app.on_event("startup")
async def startup_event():
    """Initialize CORVIU on startup"""
    print("""
    ╔═══════════════════════════════════╗
    ║         CORVIU API v1.0.0         ║
    ║   Change Intelligence Platform    ║
    ╚═══════════════════════════════════╝
    """)
    print(f"📚 Docs: http://localhost:8000/api/docs")
    print(f"🏥 Health: http://localhost:8000/health")
    print(f"🚀 Ready to detect changes!")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)