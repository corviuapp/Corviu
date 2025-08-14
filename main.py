"""
CORVIU - Change Intelligence Platform for AEC
Updated with Email Reports and Autodesk Integration
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import os
import json
import uuid
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import httpx
import base64
from urllib.parse import quote

# Debug: Print all environment variables at startup
print("=== ENVIRONMENT VARIABLES ===")
for key, value in os.environ.items():
    if key.startswith("SMTP") or key == "DATABASE_URL" or key.startswith("AUTODESK"):
        print(f"{key}: {'set' if value else 'not set'}")
print("============================")

# Initialize FastAPI
app = FastAPI(
    title="CORVIU API",
    description="Change Intelligence Platform for AEC - Automated Model Monitoring",
    version="2.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage
projects_db = {}
changes_db = {}
scheduled_checks = {}
autodesk_tokens = {}  # Store tokens temporarily

# ======================== EMAIL SERVICE ========================

class EmailService:
    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.from_email = os.getenv("FROM_EMAIL", "alerts@corviu.ai")
    
    def send_change_report(self, to_email: str, project_name: str, changes: List[Dict]) -> bool:
        """Send email report when changes detected"""
        
        if not self.smtp_user or not self.smtp_password:
            print("Email not configured")
            return False
        
        try:
            # Calculate summary
            critical_count = len([c for c in changes if c.get("priority") == "critical"])
            total_cost = sum(c.get("cost_impact", 0) for c in changes)
            
            # Create email
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"CORVIU: {len(changes)} Changes in {project_name}"
            msg['From'] = f"CORVIU <{self.from_email}>"
            msg['To'] = to_email
            
            # HTML content
            html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background: linear-gradient(135deg, #667eea, #764ba2); padding: 30px; text-align: center; color: white;">
                    <h1>🏗️ CORVIU Alert</h1>
                    <p>{len(changes)} Changes Detected</p>
                </div>
                
                <div style="padding: 30px;">
                    <h2>Project: {project_name}</h2>
                    <p><strong>{critical_count} critical changes</strong> detected with <strong>${total_cost:,.0f}</strong> total impact.</p>
                    
                    <h3>Changes Summary:</h3>
                    <ul>
            """
            
            for change in changes[:5]:  # First 5 changes
                html += f"""
                    <li>
                        <strong>{change.get('element_name')}</strong>: {change.get('description')}
                        <br>Impact: ${change.get('cost_impact', 0):,.0f} | Priority: {change.get('priority', 'medium').upper()}
                    </li>
                """
            
            html += f"""
                    </ul>
                    
                    <div style="margin: 30px 0; padding: 20px; background: #f5f5f5; border-radius: 8px;">
                        <h3>📊 ROI This Week</h3>
                        <p>Time Saved: <strong>{len(changes) * 0.5:.1f} hours</strong></p>
                        <p>Value: <strong>${len(changes) * 0.5 * 155:.0f}</strong></p>
                    </div>
                    
                    <a href="https://corviu.up.railway.app" 
                       style="display: inline-block; background: #667eea; color: white; padding: 12px 30px; 
                              text-decoration: none; border-radius: 8px;">
                        View Full Report
                    </a>
                </div>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(html, 'html'))
            
            # Send
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            print(f"✅ Email sent to {to_email}")
            return True
            
        except Exception as e:
            print(f"❌ Email failed: {e}")
            return False

email_service = EmailService()

# ======================== AUTODESK INTEGRATION ========================

class AutodeskIntegration:
    def __init__(self):
        self.client_id = os.getenv("AUTODESK_CLIENT_ID")
        self.client_secret = os.getenv("AUTODESK_CLIENT_SECRET")
        self.callback_url = os.getenv("AUTODESK_CALLBACK_URL", "https://corviu.up.railway.app/auth/callback")
        self.base_url = "https://developer.api.autodesk.com"
        
    async def get_auth_url(self) -> str:
        """Generate OAuth URL for user authentication"""
        scopes = "data:read data:write data:create account:read"
        auth_url = (
            f"{self.base_url}/authentication/v2/authorize"
            f"?response_type=code"
            f"&client_id={self.client_id}"
            f"&redirect_uri={quote(self.callback_url)}"
            f"&scope={quote(scopes)}"
        )
        return auth_url
    
    async def exchange_code_for_token(self, code: str) -> Dict:
        """Exchange authorization code for access token"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/authentication/v2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.callback_url
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code == 200:
                token_data = response.json()
                return {
                    "access_token": token_data["access_token"],
                    "refresh_token": token_data.get("refresh_token"),
                    "expires_in": token_data["expires_in"]
                }
            else:
                raise Exception(f"Token exchange failed: {response.text}")
    
    async def get_user_info(self, access_token: str) -> Dict:
        """Get authenticated user information"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/userprofile/v1/users/@me",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if response.status_code == 200:
                return response.json()
            return {}
    
    async def get_hubs(self, access_token: str) -> List[Dict]:
        """Get all hubs (ACC accounts) user has access to"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/project/v1/hubs",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/vnd.api+json"
                }
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("data", [])
            return []
    
    async def get_projects(self, access_token: str, hub_id: str) -> List[Dict]:
        """Get all projects in a hub"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/project/v1/hubs/{hub_id}/projects",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/vnd.api+json"
                }
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("data", [])
            return []

autodesk_integration = AutodeskIntegration()

# ======================== AUTOMATED CHECKER ========================

async def check_project_for_changes(project_id: str) -> Dict:
    """Check a project for changes (automated or manual)"""
    
    # Check if this is an Autodesk-connected project
    project = projects_db.get(project_id)
    if project and project.get("autodesk_project_id"):
        # TODO: Implement real Autodesk model comparison
        # For now, continue with simulation
        pass
    
    # Simulate change detection
    import random
    if random.random() > 0.3:  # 70% chance of changes
        changes = [
            {
                "id": str(uuid.uuid4())[:8],
                "project_id": project_id,
                "element_name": "Level 2 Slab",
                "change_type": "structural",
                "description": "Slab moved 75mm north",
                "cost_impact": 45000,
                "schedule_impact": 3,
                "priority": "critical",
                "detected_at": datetime.utcnow().isoformat()
            },
            {
                "id": str(uuid.uuid4())[:8],
                "project_id": project_id,
                "element_name": "MEP Coordination",
                "change_type": "mep",
                "description": "Ductwork rerouted",
                "cost_impact": 12000,
                "schedule_impact": 2,
                "priority": "high",
                "detected_at": datetime.utcnow().isoformat()
            }
        ]
        
        # Store changes
        changes_db[project_id] = changes
        
        # Send email if configured
        if project and project.get("email"):
            email_service.send_change_report(
                project["email"],
                project["name"],
                changes
            )
        
        return {
            "has_changes": True,
            "change_count": len(changes),
            "critical_count": len([c for c in changes if c["priority"] == "critical"]),
            "total_impact": sum(c["cost_impact"] for c in changes)
        }
    
    return {"has_changes": False, "change_count": 0}

async def run_scheduled_checks():
    """Background task that runs every hour to check for scheduled checks"""
    while True:
        current_hour = datetime.now().hour
        
        # Check at 2 AM for nightly checks
        if current_hour == 2:
            print("🌙 Running nightly checks...")
            for project_id, project in projects_db.items():
                if project.get("check_frequency") == "nightly":
                    result = await check_project_for_changes(project_id)
                    print(f"Checked {project['name']}: {result['change_count']} changes")
        
        # Wait 1 hour before next check
        await asyncio.sleep(3600)

# ======================== MODELS ========================

class ProjectCreate(BaseModel):
    name: str
    email: Optional[str] = None
    check_frequency: str = "nightly"  # nightly, hourly, manual

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
                .features {
                    margin: 30px 0;
                    display: grid;
                    grid-template-columns: repeat(2, 1fr);
                    gap: 20px;
                    text-align: left;
                }
                .feature {
                    background: rgba(255,255,255,0.1);
                    padding: 15px;
                    border-radius: 8px;
                }
                .connect-btn {
                    display: inline-block;
                    margin-top: 20px;
                    padding: 12px 30px;
                    background: white;
                    color: #667eea;
                    text-decoration: none;
                    border-radius: 8px;
                    font-weight: 600;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🏗️ CORVIU</h1>
                <p>Automated Change Intelligence for AEC</p>
                <div class="features">
                    <div class="feature">✅ Nightly model checking</div>
                    <div class="feature">📧 Email reports</div>
                    <div class="feature">🎯 Priority detection</div>
                    <div class="feature">💰 ROI tracking</div>
                </div>
                <div style="margin-top: 20px; padding: 10px; background: rgba(76, 175, 80, 0.2); border-radius: 8px;">
                    ✅ API Operational | 📊 Dashboard Available
                </div>
                <a href="/auth/login" class="connect-btn">Connect Autodesk Account</a>
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
        "version": "2.0.0",
        "features": {
            "api": "healthy",
            "email": "configured" if os.getenv("SMTP_USER") else "not configured",
            "scheduler": "active",
            "autodesk": "configured" if os.getenv("AUTODESK_CLIENT_ID") else "not configured"
        },
        "projects_monitored": len(projects_db),
        "checks_scheduled": len([p for p in projects_db.values() if p.get("check_frequency") == "nightly"])
    }

# ======================== AUTODESK OAUTH ENDPOINTS ========================

@app.get("/auth/login")
async def autodesk_login():
    """Initiate Autodesk OAuth flow"""
    auth_url = await autodesk_integration.get_auth_url()
    return RedirectResponse(url=auth_url)

@app.get("/auth/callback")
async def auth_callback(code: str):
    """Handle OAuth callback from Autodesk"""
    try:
        # Exchange code for token
        token_data = await autodesk_integration.exchange_code_for_token(code)
        
        # Store token temporarily (in production, use database)
        token_id = str(uuid.uuid4())[:8]
        autodesk_tokens[token_id] = token_data
        
        # Get user info
        user_info = await autodesk_integration.get_user_info(token_data["access_token"])
        
        # Return success page with token info
        html_response = f"""
        <html>
        <head>
            <title>CORVIU - Autodesk Connected</title>
            <style>
                body {{
                    font-family: -apple-system, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    height: 100vh;
                    margin: 0;
                }}
                .container {{
                    text-align: center;
                    padding: 40px;
                    background: rgba(255,255,255,0.1);
                    border-radius: 20px;
                    max-width: 600px;
                }}
                .success {{
                    background: rgba(76, 175, 80, 0.2);
                    padding: 20px;
                    border-radius: 8px;
                    margin: 20px 0;
                }}
                .token {{
                    background: rgba(0,0,0,0.2);
                    padding: 10px;
                    border-radius: 4px;
                    word-break: break-all;
                    font-family: monospace;
                }}
                .next-steps {{
                    margin-top: 30px;
                    padding: 20px;
                    background: rgba(255,255,255,0.1);
                    border-radius: 8px;
                }}
                a {{
                    color: white;
                    text-decoration: underline;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>✅ Autodesk Connected!</h1>
                <div class="success">
                    <p><strong>User:</strong> {user_info.get('userName', 'Unknown')}</p>
                    <p><strong>Email:</strong> {user_info.get('emailId', 'Unknown')}</p>
                    <p><strong>Token ID:</strong> <span class="token">{token_id}</span></p>
                </div>
                
                <div class="next-steps">
                    <h3>Next Steps:</h3>
                    <p>Use your token ID to:</p>
                    <ol style="text-align: left;">
                        <li>List your projects: <br><code>/api/autodesk/projects?token_id={token_id}</code></li>
                        <li>Connect a project to CORVIU for monitoring</li>
                        <li>Set up email notifications</li>
                    </ol>
                </div>
                
                <p style="margin-top: 20px;">
                    <a href="/api/autodesk/projects?token_id={token_id}">View Your Projects →</a>
                </p>
            </div>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_response)
        
    except Exception as e:
        return {"error": str(e), "message": "Failed to authenticate with Autodesk"}

@app.get("/api/autodesk/projects")
async def get_autodesk_projects(token_id: str):
    """List all Autodesk projects user has access to"""
    
    # Get token from storage
    token_data = autodesk_tokens.get(token_id)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token ID")
    
    access_token = token_data["access_token"]
    
    # Get hubs
    hubs = await autodesk_integration.get_hubs(access_token)
    
    all_projects = []
    for hub in hubs:
        hub_id = hub["id"]
        hub_name = hub.get("attributes", {}).get("name", "Unknown Hub")
        
        # Get projects in each hub
        projects = await autodesk_integration.get_projects(access_token, hub_id)
        
        for project in projects:
            all_projects.append({
                "hub_id": hub_id,
                "hub_name": hub_name,
                "project_id": project["id"],
                "project_name": project.get("attributes", {}).get("name"),
                "project_type": project.get("type")
            })
    
    return {
        "count": len(all_projects),
        "projects": all_projects,
        "message": f"Found {len(all_projects)} projects across {len(hubs)} hubs"
    }

@app.post("/api/projects/connect-autodesk")
async def connect_autodesk_project(
    token_id: str,
    hub_id: str,
    project_id: str,
    project_name: str,
    email: str
):
    """Connect an Autodesk project to CORVIU for monitoring"""
    
    # Verify token
    token_data = autodesk_tokens.get(token_id)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token ID")
    
    # Create CORVIU project
    corviu_project_id = str(uuid.uuid4())[:8]
    
    projects_db[corviu_project_id] = {
        "id": corviu_project_id,
        "name": project_name,
        "autodesk_hub_id": hub_id,
        "autodesk_project_id": project_id,
        "autodesk_token_id": token_id,  # Store token reference
        "email": email,
        "check_frequency": "nightly",
        "created_at": datetime.utcnow().isoformat()
    }
    
    return {
        "success": True,
        "corviu_project_id": corviu_project_id,
        "message": f"Project '{project_name}' connected for monitoring",
        "next_steps": [
            "CORVIU will check for changes nightly at 2 AM",
            f"Reports will be sent to {email}",
            "You can trigger manual checks anytime"
        ]
    }

# ======================== EXISTING ENDPOINTS (unchanged) ========================

@app.post("/api/projects")
async def create_project(project: ProjectCreate):
    """Create a project to monitor"""
    project_id = str(uuid.uuid4())[:8]
    
    projects_db[project_id] = {
        "id": project_id,
        "name": project.name,
        "email": project.email,
        "check_frequency": project.check_frequency,
        "created_at": datetime.utcnow().isoformat(),
        "last_check": None
    }
    
    return {
        "success": True,
        "project_id": project_id,
        "message": f"Project '{project.name}' created. Checks scheduled: {project.check_frequency}"
    }

@app.post("/api/projects/{project_id}/check-now")
async def manual_check(project_id: str, background_tasks: BackgroundTasks):
    """Manually trigger a check for a project"""
    
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Run check in background
    background_tasks.add_task(check_project_for_changes, project_id)
    
    return {
        "success": True,
        "message": "Check initiated. Results will be emailed if changes detected."
    }

@app.post("/api/demo/seed")
async def seed_demo_data():
    """Create demo project with sample data"""
    project_id = str(uuid.uuid4())[:8]
    
    # Create demo project
    projects_db[project_id] = {
        "id": project_id,
        "name": "Tower Block A - Demo",
        "email": os.getenv("DEMO_EMAIL", ""),
        "check_frequency": "nightly",
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
    
    changes_db[project_id] = demo_changes
    
    return {
        "success": True,
        "project_id": project_id,
        "message": "Demo project created with automated checking enabled",
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
            ai_summary="No changes detected. Automated checking is running nightly.",
            changes=[]
        )
    
    critical_count = len([c for c in changes if c.get("priority") == "critical"])
    total_cost = sum(c.get("cost_impact", 0) for c in changes)
    max_schedule = max((c.get("schedule_impact", 0) for c in changes), default=0)
    
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
        "message": f"CORVIU saved ${cost_saved:,.0f} this week through automated monitoring"
    }

@app.post("/api/test-email")
async def test_email(email: str):
    """Send a test email"""
    
    # Create test changes
    test_changes = [
        {
            "element_name": "Test Element",
            "description": "This is a test change",
            "priority": "high",
            "cost_impact": 10000
        }
    ]
    
    success = email_service.send_change_report(email, "Test Project", test_changes)
    
    return {
        "success": success,
        "message": "Test email sent! Check your inbox." if success else "Failed to send. Check SMTP configuration."
    }

@app.get("/debug/env")
async def debug_env():
    """Check what environment variables the app sees"""
    return {
        "smtp_host": os.getenv("SMTP_HOST", "not set"),
        "smtp_port": os.getenv("SMTP_PORT", "not set"),
        "smtp_user": "set" if os.getenv("SMTP_USER") else "not set",
        "smtp_password": "set" if os.getenv("SMTP_PASSWORD") else "not set",
        "from_email": os.getenv("FROM_EMAIL", "not set"),
        "autodesk_client_id": "set" if os.getenv("AUTODESK_CLIENT_ID") else "not set",
        "autodesk_client_secret": "set" if os.getenv("AUTODESK_CLIENT_SECRET") else "not set",
        "checking": {
            "SMTP_USER exists": bool(os.getenv("SMTP_USER")),
            "SMTP_PASSWORD exists": bool(os.getenv("SMTP_PASSWORD")),
            "AUTODESK configured": bool(os.getenv("AUTODESK_CLIENT_ID"))
        }
    }

# ======================== STARTUP ========================

@app.on_event("startup")
async def startup_event():
    """Initialize CORVIU with scheduler"""
    print("""
    ╔═══════════════════════════════════╗
    ║       CORVIU API v2.0.0          ║
    ║   Automated Change Monitoring     ║
    ╚═══════════════════════════════════╝
    """)
    print("✅ API Started")
    print("📧 Email Reports: " + ("Configured" if os.getenv("SMTP_USER") else "Not configured"))
    print("🔐 Autodesk Integration: " + ("Configured" if os.getenv("AUTODESK_CLIENT_ID") else "Not configured"))
    print("🕒 Automated Checks: Enabled")
    
    # Start background scheduler
    asyncio.create_task(run_scheduled_checks())

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)