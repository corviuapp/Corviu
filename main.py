"""
CORVIU - Change Intelligence Platform for AEC
Simplified API for Railway Deployment
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime
import os
import json
import uuid

# Initialize FastAPI
app = FastAPI(
    title="CORVIU API",
    description="Change Intelligence Platform for AEC",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage (no database for now)
projects_db = {}
changes_db = {}

# ======================== MODELS ========================

class ChangeCreate(BaseModel):
    element_name: str
    change_type: str
    description: str
    cost_impact: float = 0
    schedule_impact: float = 0

class ChangeSummaryResponse(BaseModel):
    total_changes: int
    critical_changes: int
    total_cost_impact: float
    total_schedule_impact: float
    ai_summary: str
    changes: List[Dict]

# ======================== ENDPOINTS ========================

@app.get("/", response_class=HTMLResponse)
async def root():
    """CORVIU Landing Page"""
    return """
    <html>
        <head>
            <title>CORVIU API</title>
            <style>
                body { 
                    font-family: -apple-system, sans-serif;
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
                }
                h1 { font-size: 48px; margin: 0 0 10px 0; }
                p { font-size: 20px; opacity: 0.9; }
                .status { 
                    margin-top: 20px;
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
                <div class="status">✅ API Operational</div>
            </div>
        </body>
    </html>
    """

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "operational",
        "service": "CORVIU",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {
            "api": "healthy",
            "database": "in-memory",
            "autodesk": "configured" if os.getenv("AUTODESK_CLIENT_ID") else "not configured",
            "openai": "configured" if os.getenv("OPENAI_API_KEY") else "not configured"
        }
    }

@app.post("/api/demo/seed")
async def seed_demo_data():
    """Create demo project with sample data"""
    project_id = str(uuid.uuid4())[:8]
    
    # Create demo project
    projects_db[project_id] = {
        "id": project_id,
        "name": "Tower Block A - Demo",
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Create demo changes
    demo_changes = [
        {
            "id": str(uuid.uuid4())[:8],
            "project_id": project_id,
            "element_name": "Level 2 Slab",
            "change_type": "structural",
            "description": "Slab moved 75mm north",
            "cost_impact": 45000,
            "schedule_impact": 3,
            "priority": "critical",
            "affected_trades": ["MEP", "Structural"],
            "detected_at": datetime.utcnow().isoformat()
        },
        {
            "id": str(uuid.uuid4())[:8],
            "project_id": project_id,
            "element_name": "Conference Room Lighting",
            "change_type": "mep",
            "description": "12 new light fixtures added",
            "cost_impact": 8400,
            "schedule_impact": 1,
            "priority": "high",
            "affected_trades": ["Electrical"],
            "detected_at": datetime.utcnow().isoformat()
        },
        {
            "id": str(uuid.uuid4())[:8],
            "project_id": project_id,
            "element_name": "Interior Walls",
            "change_type": "architectural",
            "description": "3 walls relocated",
            "cost_impact": 3200,
            "schedule_impact": 0.5,
            "priority": "medium",
            "affected_trades": ["Drywall", "Electrical"],
            "detected_at": datetime.utcnow().isoformat()
        }
    ]
    
    # Store changes
    changes_db[project_id] = demo_changes
    
    return {
        "success": True,
        "project_id": project_id,
        "message": "Demo project created successfully",
        "demo_url": f"/api/projects/{project_id}/changes"
    }

@app.get("/api/projects/{project_id}/changes")
async def get_changes(project_id: str) -> ChangeSummaryResponse:
    """Get changes for a project"""
    
    changes = changes_db.get(project_id, [])
    
    if not changes:
        return ChangeSummaryResponse(
            total_changes=0,
            critical_changes=0,
            total_cost_impact=0,
            total_schedule_impact=0,
            ai_summary="No changes detected. Create a demo project first.",
            changes=[]
        )
    
    # Calculate summary
    critical_count = len([c for c in changes if c.get("priority") == "critical"])
    total_cost = sum(c.get("cost_impact", 0) for c in changes)
    max_schedule = max((c.get("schedule_impact", 0) for c in changes), default=0)
    
    # Generate summary text
    summary = f"{len(changes)} changes detected • {critical_count} critical items • ${total_cost:,.0f} cost impact"
    
    return ChangeSummaryResponse(
        total_changes=len(changes),
        critical_changes=critical_count,
        total_cost_impact=total_cost,
        total_schedule_impact=max_schedule,
        ai_summary=summary,
        changes=changes
    )

@app.get("/api/projects/{project_id}/roi")
async def get_roi_metrics(project_id: str):
    """Get ROI metrics for a project"""
    
    changes = changes_db.get(project_id, [])
    
    # Calculate simple ROI metrics
    meetings_saved = len(changes) // 2
    hours_saved = len(changes) * 0.5
    cost_saved = hours_saved * 155
    decisions_accelerated = len([c for c in changes if c.get("priority") in ["critical", "high"]])
    
    return {
        "project_id": project_id,
        "meetings_saved": meetings_saved,
        "hours_saved": round(hours_saved, 1),
        "cost_saved": round(cost_saved, 2),
        "decisions_accelerated": decisions_accelerated,
        "message": f"CORVIU saved your team ${cost_saved:,.0f} this week"
    }

@app.get("/auth/login")
async def login():
    """Initiate Autodesk OAuth"""
    client_id = os.getenv("AUTODESK_CLIENT_ID", "not_configured")
    callback_url = os.getenv("AUTODESK_CALLBACK_URL", "http://localhost:8000/auth/callback")
    
    auth_url = (
        f"https://developer.api.autodesk.com/authentication/v1/authorize"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={callback_url}"
        f"&scope=data:read data:write"
    )
    
    return {"auth_url": auth_url, "configured": client_id != "not_configured"}

@app.get("/api/docs")
async def docs_redirect():
    """Redirect to FastAPI docs"""
    return {"message": "Visit /docs for API documentation"}

# ======================== STARTUP ========================

@app.on_event("startup")
async def startup_event():
    """Initialize CORVIU"""
    print("""
    ╔═══════════════════════════════════╗
    ║       CORVIU API v1.0.0          ║
    ║   Running in Simplified Mode      ║
    ╚═══════════════════════════════════╝
    """)
    print("✅ API Started Successfully")
    print("📝 Using in-memory storage (no database)")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8080"))
    print(f"Starting CORVIU on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)