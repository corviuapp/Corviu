"""
CORVIU - Change Intelligence Platform for AEC
Updated with Email Reports and Autodesk Integration
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
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
        
    async def send_change_report(self, to_email: str, project_name: str, changes: List[Dict]):
        """Send formatted change report email"""
        try:
            # Calculate summary metrics
            total_changes = len(changes)
            critical_count = len([c for c in changes if c.get("priority") == "critical"])
            total_cost = sum(c.get("cost_impact", 0) for c in changes)
            
            # Create HTML email
            html_content = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: -apple-system, sans-serif; background: #f5f5f5; }}
                    .container {{ max-width: 600px; margin: 0 auto; background: white; padding: 20px; }}
                    .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; }}
                    .metrics {{ display: flex; justify-content: space-around; margin: 20px 0; }}
                    .metric {{ text-align: center; }}
                    .metric-value {{ font-size: 24px; font-weight: bold; color: #667eea; }}
                    .changes-list {{ margin: 20px 0; }}
                    .change-item {{ border-left: 4px solid #667eea; padding: 10px; margin: 10px 0; background: #f9f9f9; }}
                    .critical {{ border-left-color: #e74c3c; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🏗️ CORVIU Change Report</h1>
                        <p>Project: {project_name}</p>
                    </div>
                    
                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-value">{total_changes}</div>
                            <div>Total Changes</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{critical_count}</div>
                            <div>Critical</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">${total_cost:,.0f}</div>
                            <div>Cost Impact</div>
                        </div>
                    </div>
                    
                    <div class="changes-list">
                        <h3>Change Details:</h3>
            """
            
            for change in changes[:10]:  # Limit to top 10 changes
                priority_class = "critical" if change.get("priority") == "critical" else ""
                html_content += f"""
                    <div class="change-item {priority_class}">
                        <strong>{change.get('element_name')}</strong>: {change.get('description')}
                        <br>Impact: ${change.get('cost_impact', 0):,.0f} | Priority: {change.get('priority', 'medium').upper()}
                    </div>
                """
            
            html_content += """
                    </div>
                    <p style="text-align: center; color: #666; margin-top: 30px;">
                        Generated by CORVIU • Change Intelligence Platform
                    </p>
                </div>
            </body>
            </html>
            """
            
            # Send email
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"🚨 CORVIU Alert: {total_changes} changes in {project_name}"
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            msg.attach(MIMEText(html_content, 'html'))
            
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            return True
        except Exception as e:
            print(f"Email send error: {str(e)}")
            return False

email_service = EmailService()

# ======================== AUTODESK INTEGRATION ========================
class AutodeskIntegration:
    def __init__(self):
        self.client_id = os.getenv("AUTODESK_CLIENT_ID")
        self.client_secret = os.getenv("AUTODESK_CLIENT_SECRET")
        self.callback_url = os.getenv("AUTODESK_CALLBACK_URL", "https://corviu.up.railway.app/auth/callback")
        self.auth_url = "https://developer.api.autodesk.com/authentication/v2"
        self.base_url = "https://developer.api.autodesk.com"
        
    async def get_auth_url(self) -> str:
        """Generate Autodesk OAuth URL"""
        # Make sure we're requesting the right scopes
        scopes = "data:read data:write data:create data:search bucket:create bucket:read bucket:update bucket:delete account:read account:write"
        
        auth_url = (
            f"{self.auth_url}/authorize"
            f"?response_type=code"
            f"&client_id={self.client_id}"
            f"&redirect_uri={quote(self.callback_url)}"
            f"&scope={quote(scopes)}"  # Add comprehensive scopes
        )
        print(f"[DEBUG] OAuth URL generated with scopes: {scopes}")
        return auth_url
    
    async def exchange_code_for_token(self, code: str) -> Dict:
        """Exchange authorization code for access token"""
        async with httpx.AsyncClient() as client:
            # Create Basic Auth header
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            response = await client.post(
                f"{self.auth_url}/token",
                headers={
                    "Authorization": f"Basic {encoded_credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json"
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.callback_url
                }
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"[ERROR] Token exchange failed: {response.status_code}")
                print(f"[ERROR] Response: {response.text}")
                raise HTTPException(status_code=400, detail="Failed to exchange code for token")
    
    async def refresh_token(self, refresh_token: str) -> Dict:
        """Refresh access token"""
        async with httpx.AsyncClient() as client:
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            response = await client.post(
                f"{self.auth_url}/token",
                headers={
                    "Authorization": f"Basic {encoded_credentials}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token
                }
            )
            return response.json() if response.status_code == 200 else None
    
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
        print(f"[DEBUG] Getting hubs with token: {access_token[:20]}...")
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/project/v1/hubs",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/vnd.api+json"
                    }
                )
                
                print(f"[DEBUG] Hubs response status: {response.status_code}")
                print(f"[DEBUG] Hubs response headers: {dict(response.headers)}")
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"[DEBUG] Hubs response data: {json.dumps(data, indent=2)}")
                    hubs = data.get("data", [])
                    print(f"[DEBUG] Found {len(hubs)} hubs")
                    
                    # Print hub details
                    for hub in hubs:
                        print(f"[DEBUG] Hub: {hub.get('attributes', {}).get('name', 'Unknown')} (ID: {hub.get('id')})")
                    
                    return hubs
                elif response.status_code == 401:
                    print(f"[ERROR] Authentication failed - token may be expired")
                    print(f"[ERROR] Response: {response.text}")
                elif response.status_code == 403:
                    print(f"[ERROR] Forbidden - check OAuth scopes")
                    print(f"[ERROR] Response: {response.text}")
                else:
                    print(f"[ERROR] Unexpected status: {response.status_code}")
                    print(f"[ERROR] Response: {response.text}")
                    
            except Exception as e:
                print(f"[ERROR] Exception getting hubs: {str(e)}")
                
        return []
    
    async def get_projects(self, access_token: str, hub_id: str) -> List[Dict]:
        """Get all projects in a hub"""
        print(f"[DEBUG] Getting projects for hub: {hub_id}")
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/project/v1/hubs/{hub_id}/projects",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/vnd.api+json"
                    }
                )
                
                print(f"[DEBUG] Projects response status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    projects = data.get("data", [])
                    print(f"[DEBUG] Found {len(projects)} projects in hub {hub_id}")
                    
                    # Print project details
                    for project in projects:
                        print(f"[DEBUG] Project: {project.get('attributes', {}).get('name', 'Unknown')} (ID: {project.get('id')})")
                    
                    return projects
                else:
                    print(f"[ERROR] Failed to get projects: {response.status_code}")
                    print(f"[ERROR] Response: {response.text}")
                    
            except Exception as e:
                print(f"[ERROR] Exception getting projects: {str(e)}")
                
        return []

autodesk_integration = AutodeskIntegration()

# ======================== AUTOMATED CHECKER ========================
async def check_project_for_changes(project_id: str):
    """Simulate checking a project for changes"""
    project = projects_db.get(project_id)
    if not project:
        return
    
    # Simulate finding changes (in production, this would compare models)
    mock_changes = [
        {
            "id": str(uuid.uuid4()),
            "element_name": "Level 2 Slab",
            "description": "Moved 75mm north",
            "cost_impact": 12500,
            "priority": "critical",
            "detected_at": datetime.now().isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "element_name": "Light Fixtures",
            "description": "12 new fixtures added",
            "cost_impact": 3200,
            "priority": "medium",
            "detected_at": datetime.now().isoformat()
        }
    ]
    
    # Store changes
    changes_db[project_id] = mock_changes
    
    # Send email if configured
    if project.get("email_notifications") and project.get("notification_email"):
        await email_service.send_change_report(
            project["notification_email"],
            project["name"],
            mock_changes
        )
    
    return mock_changes

async def schedule_checks():
    """Background task to check projects periodically"""
    while True:
        try:
            for project_id, project in projects_db.items():
                if project.get("check_frequency") == "nightly":
                    await check_project_for_changes(project_id)
            
            # Wait 24 hours (in production)
            await asyncio.sleep(86400)
        except Exception as e:
            print(f"Scheduler error: {str(e)}")
            await asyncio.sleep(3600)  # Retry in 1 hour

# ======================== API ENDPOINTS ========================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Landing page with CORVIU branding"""
    html_content = """
    <html>
    <head>
        <title>CORVIU - Change Intelligence Platform</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                margin: 0;
                padding: 0;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
            }
            .container {
                text-align: center;
                padding: 40px;
                max-width: 800px;
            }
            h1 {
                font-size: 4em;
                margin-bottom: 20px;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
            }
            .tagline {
                font-size: 1.5em;
                margin-bottom: 40px;
                opacity: 0.9;
            }
            .features {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin: 40px 0;
            }
            .feature {
                background: rgba(255,255,255,0.1);
                padding: 20px;
                border-radius: 10px;
                backdrop-filter: blur(10px);
            }
            .cta {
                margin-top: 40px;
            }
            .btn {
                display: inline-block;
                padding: 15px 30px;
                background: white;
                color: #667eea;
                text-decoration: none;
                border-radius: 30px;
                font-weight: bold;
                margin: 10px;
                transition: transform 0.3s;
            }
            .btn:hover {
                transform: translateY(-2px);
            }
            .status {
                margin-top: 60px;
                padding: 20px;
                background: rgba(0,0,0,0.2);
                border-radius: 10px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🏗️ CORVIU</h1>
            <p class="tagline">Change Intelligence Platform for AEC</p>
            
            <div class="features">
                <div class="feature">
                    <h3>⚡ 10-Min Setup</h3>
                    <p>Connect to Autodesk ACC instantly</p>
                </div>
                <div class="feature">
                    <h3>🔍 Smart Detection</h3>
                    <p>AI-powered change analysis</p>
                </div>
                <div class="feature">
                    <h3>💰 ROI Tracking</h3>
                    <p>Quantified savings metrics</p>
                </div>
                <div class="feature">
                    <h3>📧 Email Alerts</h3>
                    <p>Automated change reports</p>
                </div>
            </div>
            
            <div class="cta">
                <a href="/auth/login" class="btn">Connect Autodesk Account</a>
                <a href="/api/demo/seed" class="btn">Try Demo</a>
            </div>
            
            <div class="status">
                <h3>System Status</h3>
                <p>✅ API: Operational | 📊 Projects Monitored: """ + str(len(projects_db)) + """</p>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "operational",
        "service": "CORVIU API",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "projects_monitored": len(projects_db),
        "checks_scheduled": len([p for p in projects_db.values() if p.get("check_frequency") == "nightly"])
    }

# ======================== AUTODESK AUTH ENDPOINTS ========================

@app.get("/auth/login")
async def login():
    """Redirect to Autodesk OAuth"""
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

# ======================== PROJECT MANAGEMENT ENDPOINTS ========================

@app.get("/api/autodesk/projects")
async def get_autodesk_projects(request: Request, token_id: str):
    """List all Autodesk projects user has access to"""
    
    if token_id not in autodesk_tokens:
        raise HTTPException(status_code=404, detail="Token not found")
    
    token_data = autodesk_tokens[token_id]
    access_token = token_data["access_token"]
    
    # Get hubs
    hubs = await autodesk_integration.get_hubs(access_token)
    
    all_projects = []
    for hub in hubs:
        hub_id = hub.get("id", "")
        hub_name = hub.get("attributes", {}).get("name", "Unknown Hub")
        
        # Get projects in each hub
        projects = await autodesk_integration.get_projects(access_token, hub_id)
        
        for project in projects:
            all_projects.append({
                "hub_id": hub_id,
                "hub_name": hub_name,
                "project_id": project.get("id"),
                "project_name": project.get("attributes", {}).get("name", "Unknown Project"),
                "scopes": project.get("attributes", {}).get("scopes", [])
            })
    
    # Check if request is from a browser
    accept_header = request.headers.get("accept", "")
    if "text/html" in accept_header:
        # Return HTML view for browser
        html_response = f"""
        <html>
        <head>
            <title>CORVIU - Your Autodesk Projects</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 40px 20px;
                    margin: 0;
                    min-height: 100vh;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                }}
                h1 {{
                    text-align: center;
                    font-size: 3em;
                    margin-bottom: 10px;
                    text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
                }}
                .stats {{
                    text-align: center;
                    margin: 30px 0;
                    font-size: 1.2em;
                    opacity: 0.9;
                }}
                .stats-badge {{
                    display: inline-block;
                    background: rgba(255,255,255,0.2);
                    padding: 8px 16px;
                    border-radius: 20px;
                    margin: 0 10px;
                }}
                .projects-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
                    gap: 25px;
                    margin-top: 40px;
                }}
                .project-card {{
                    background: rgba(255,255,255,0.1);
                    padding: 25px;
                    border-radius: 16px;
                    backdrop-filter: blur(10px);
                    border: 1px solid rgba(255,255,255,0.2);
                    transition: transform 0.3s, box-shadow 0.3s;
                }}
                .project-card:hover {{
                    transform: translateY(-5px);
                    box-shadow: 0 10px 30px rgba(0,0,0,0.3);
                }}
                .project-icon {{
                    font-size: 2em;
                    margin-bottom: 15px;
                }}
                .project-name {{
                    font-size: 1.3em;
                    font-weight: bold;
                    margin-bottom: 12px;
                    line-height: 1.3;
                }}
                .project-info {{
                    opacity: 0.8;
                    font-size: 0.9em;
                    margin: 5px 0;
                }}
                .btn {{
                    display: inline-block;
                    padding: 12px 24px;
                    background: white;
                    color: #667eea;
                    text-decoration: none;
                    border-radius: 8px;
                    margin-top: 15px;
                    font-weight: 600;
                    transition: all 0.3s;
                    text-align: center;
                }}
                .btn:hover {{
                    background: #f0f0f0;
                    transform: scale(1.05);
                }}
                .back-link {{
                    text-align: center;
                    margin-top: 40px;
                }}
                .back-link a {{
                    color: white;
                    text-decoration: none;
                    opacity: 0.8;
                    transition: opacity 0.3s;
                }}
                .back-link a:hover {{
                    opacity: 1;
                }}
                .empty-state {{
                    text-align: center;
                    padding: 60px 20px;
                    background: rgba(255,255,255,0.1);
                    border-radius: 16px;
                    margin-top: 40px;
                }}
                .empty-state h2 {{
                    font-size: 2em;
                    margin-bottom: 20px;
                }}
                .hub-label {{
                    display: inline-block;
                    background: rgba(255,255,255,0.15);
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-size: 0.8em;
                    margin-top: 8px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🏗️ Your Autodesk Projects</h1>
                <div class="stats">
                    <span class="stats-badge">📁 {len(hubs)} Hub{'s' if len(hubs) != 1 else ''}</span>
                    <span class="stats-badge">📐 {len(all_projects)} Project{'s' if len(all_projects) != 1 else ''}</span>
                </div>
        """
        
        if all_projects:
            html_response += '<div class="projects-grid">'
            
            # Define icons for different project types
            project_icons = ["🏢", "🏗️", "🏛️", "🌉"]
            
            for i, project in enumerate(all_projects):
                icon = project_icons[i % len(project_icons)]
                # URL encode the project name for the connect endpoint
                encoded_name = quote(project['project_name'])
                
                html_response += f"""
                    <div class="project-card">
                        <div class="project-icon">{icon}</div>
                        <div class="project-name">{project['project_name']}</div>
                        <div class="project-info">📍 Hub: {project['hub_name']}</div>
                        <div class="hub-label">ID: {project['project_id'][:20]}...</div>
                        <a href="/api/projects/connect-autodesk?token_id={token_id}&autodesk_project_id={project['project_id']}&project_name={encoded_name}" class="btn">
                            ⚡ Connect to CORVIU
                        </a>
                    </div>
                """
            
            html_response += '</div>'
        else:
            html_response += """
                <div class="empty-state">
                    <h2>📭 No Projects Found</h2>
                    <p>We couldn't find any projects in your Autodesk account.</p>
                    <p style="margin-top: 20px;">Make sure you have:</p>
                    <ul style="text-align: left; display: inline-block; margin-top: 20px;">
                        <li>Active projects in ACC or BIM 360</li>
                        <li>Proper permissions to access projects</li>
                        <li>Authorized the CORVIU app in your ACC account</li>
                    </ul>
                </div>
            """
        
        html_response += """
                <div class="back-link">
                    <a href="/">← Back to Home</a>
                </div>
            </div>
        </body>
        </html>
        """
        
        return HTMLResponse(content=html_response)
    
    # Return JSON for API calls
    return {
        "count": len(all_projects),
        "projects": all_projects,
        "message": f"Found {len(all_projects)} projects across {len(hubs)} hubs"
    }

@app.post("/api/projects/connect-autodesk")
async def connect_autodesk_project(
    token_id: str,
    autodesk_project_id: str,
    project_name: str,
    check_frequency: str = "nightly",
    email_notifications: bool = False,
    notification_email: Optional[str] = None
):
    """Connect an Autodesk project to CORVIU for monitoring"""
    
    if token_id not in autodesk_tokens:
        raise HTTPException(status_code=404, detail="Token not found")
    
    # Create CORVIU project linked to Autodesk
    corviu_project_id = str(uuid.uuid4())
    projects_db[corviu_project_id] = {
        "id": corviu_project_id,
        "name": project_name,
        "autodesk_project_id": autodesk_project_id,
        "check_frequency": check_frequency,
        "email_notifications": email_notifications,
        "notification_email": notification_email,
        "created_at": datetime.now().isoformat(),
        "last_checked": None
    }
    
    return {
        "corviu_project_id": corviu_project_id,
        "message": f"Project '{project_name}' connected successfully"
    }

@app.post("/api/projects")
async def create_project(
    name: str,
    check_frequency: str = "nightly",
    email_notifications: bool = False,
    notification_email: Optional[str] = None
):
    """Create a new project for monitoring"""
    project_id = str(uuid.uuid4())
    projects_db[project_id] = {
        "id": project_id,
        "name": name,
        "check_frequency": check_frequency,
        "email_notifications": email_notifications,
        "notification_email": notification_email,
        "created_at": datetime.now().isoformat(),
        "last_checked": None
    }
    
    return {"project_id": project_id, "message": f"Project '{name}' created successfully"}

@app.post("/api/projects/{project_id}/check-now")
async def trigger_check(project_id: str, background_tasks: BackgroundTasks):
    """Manually trigger a check for changes"""
    
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    background_tasks.add_task(check_project_for_changes, project_id)
    return {"message": "Check initiated", "project_id": project_id}

@app.post("/api/demo/seed")
async def seed_demo_data():
    """Create demo project with sample data"""
    # Create demo project
    project_id = str(uuid.uuid4())
    projects_db[project_id] = {
        "id": project_id,
        "name": "Downtown Tower - Level 2",
        "check_frequency": "nightly",
        "email_notifications": True,
        "notification_email": "pm@construction.com",
        "created_at": datetime.now().isoformat(),
        "last_checked": datetime.now().isoformat()
    }
    
    # Add demo changes
    changes_db[project_id] = [
        {
            "id": str(uuid.uuid4()),
            "element_name": "Level 2 Slab",
            "description": "Moved 75mm north",
            "cost_impact": 12500,
            "priority": "critical",
            "detected_at": datetime.now().isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "element_name": "MEP Coordination",
            "description": "12 new light fixtures added",
            "cost_impact": 3200,
            "priority": "medium",
            "detected_at": datetime.now().isoformat()
        },
        {
            "id": str(uuid.uuid4()),
            "element_name": "Structural Column",
            "description": "Column size increased",
            "cost_impact": 8900,
            "priority": "high",
            "detected_at": datetime.now().isoformat()
        }
    ]
    
    return {
        "success": True,
        "project_id": project_id,
        "demo_url": f"/api/projects/{project_id}/changes"
    }

@app.get("/api/projects/{project_id}/changes")
async def get_project_changes(project_id: str):
    """Get all changes for a project"""
    
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project = projects_db[project_id]
    changes = changes_db.get(project_id, [])
    
    return {
        "project": project,
        "changes": changes,
        "summary": {
            "total_changes": len(changes),
            "critical_count": len([c for c in changes if c.get("priority") == "critical"]),
            "total_cost_impact": sum(c.get("cost_impact", 0) for c in changes)
        }
    }

@app.get("/api/projects/{project_id}/roi")
async def get_roi_metrics(project_id: str):
    """Calculate ROI metrics for a project"""
    
    if project_id not in projects_db:
        raise HTTPException(status_code=404, detail="Project not found")
    
    changes = changes_db.get(project_id, [])
    
    # Calculate metrics (simplified)
    meetings_saved = len(changes) // 3  # Assume 1 meeting per 3 changes
    hours_saved = meetings_saved * 2  # 2 hours per meeting
    cost_saved = hours_saved * 150  # $150/hour average rate
    
    return {
        "meetings_saved": meetings_saved,
        "hours_saved": hours_saved,
        "cost_saved": cost_saved,
        "decisions_accelerated": len(changes),
        "message": f"This week CORVIU saved you {meetings_saved} meetings → ${cost_saved:,.0f}"
    }

@app.post("/api/test-email")
async def test_email(to_email: str):
    """Test email configuration"""
    
    # Create test changes
    test_changes = [
        {
            "element_name": "Test Element",
            "description": "This is a test change",
            "cost_impact": 1000,
            "priority": "medium"
        }
    ]
    
    success = await email_service.send_change_report(
        to_email,
        "Test Project",
        test_changes
    )
    
    return {"success": success, "message": "Test email sent" if success else "Email failed"}

@app.get("/api/debug/test-autodesk")
async def debug_test_autodesk(token_id: str):
    """Debug endpoint to test Autodesk API calls"""
    
    if token_id not in autodesk_tokens:
        raise HTTPException(status_code=404, detail="Token not found")
    
    token_data = autodesk_tokens[token_id]
    access_token = token_data["access_token"]
    
    # Test user info
    print("\n[DEBUG] Testing user info endpoint...")
    user_info = await autodesk_integration.get_user_info(access_token)
    
    # Test hubs
    print("\n[DEBUG] Testing hubs endpoint...")
    hubs = await autodesk_integration.get_hubs(access_token)
    
    # Test projects for each hub
    all_projects = []
    for hub in hubs:
        hub_id = hub.get("id", "")
        print(f"\n[DEBUG] Testing projects for hub {hub_id}...")
        projects = await autodesk_integration.get_projects(access_token, hub_id)
        all_projects.extend(projects)
    
    return {
        "user_info": user_info,
        "hubs_count": len(hubs),
        "hubs": hubs,
        "projects_count": len(all_projects),
        "projects": all_projects,
        "debug_info": {
            "token_first_chars": access_token[:20],
            "token_length": len(access_token),
            "client_id": autodesk_integration.client_id[:10] + "..." if autodesk_integration.client_id else "NOT SET"
        }
    }

@app.get("/debug/env")
async def debug_env():
    """Debug endpoint to check environment variables"""
    return {
        "smtp_configured": bool(os.getenv("SMTP_USER")),
        "autodesk_configured": bool(os.getenv("AUTODESK_CLIENT_ID")),
        "callback_url": os.getenv("AUTODESK_CALLBACK_URL"),
        "environment": "production" if os.getenv("DATABASE_URL") else "development"
    }

# ======================== STARTUP TASKS ========================

@app.on_event("startup")
async def startup_event():
    """Initialize background tasks on startup"""
    print("🚀 CORVIU API Starting...")
    print(f"📧 Email Service: {'Configured' if email_service.smtp_user else 'Not configured'}")
    print(f"🏗️ Autodesk Integration: {'Configured' if autodesk_integration.client_id else 'Not configured'}")
    
    # Start background scheduler
    asyncio.create_task(schedule_checks())
    
    print("✅ CORVIU API Ready!")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)