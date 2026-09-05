import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.config import settings
from app.db.base import Base
from app.db.session import engine, SessionLocal, get_db
from app.models.merchant import Merchant
from app.synthetic.generator import SyntheticDataGenerator
from app.security import SECURITY_HEADERS
from app.api.v1.auth import router as auth_router

from app.api.v1.merchants import router as merchants_router
from app.api.v1.transactions import router as transactions_router
from app.api.v1.subscriptions import router as subscriptions_router
from app.api.v1.checkout_sessions import router as checkout_sessions_router
from app.api.v1.demo import router as demo_router
from app.api.v1.leaks import router as leaks_router
from app.api.v1.ml import router as ml_router
from app.api.v1.opportunities import router as opportunities_router
from app.api.v1.agent import router as agent_router
from app.api.v1.policy import router as policy_router
from app.api.v1.webhooks import router as webhooks_router
from app.api.v1.providers import router as providers_router
from app.api.v1.recovery import router as recovery_router
from app.api.v1.audit import router as audit_router, serve_audit_ui
from app.api.v1.analytics import router as analytics_router
from app.api.v1.evaluation import router as evaluation_router
from app.api.v1.security_audit import router as security_router
from pathlib import Path



DASHBOARD_HTML_PATH = Path(__file__).resolve().parent / "static" / "dashboard.html"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("revenueos")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure tables exist
    logger.info("Initializing database schema...")
    Base.metadata.create_all(bind=engine)
    
    # Auto-seed if database is empty
    db = SessionLocal()
    try:
        merchant_count = db.query(Merchant).count()
        if merchant_count == 0:
            logger.info("Database is empty. Seeding initial demo scenarios...")
            generator = SyntheticDataGenerator(seed=42)
            generator.generate_all(db)
            generator.generate_audit_trails(db)
            logger.info("Initial demo scenarios and audit trails successfully seeded.")
    except Exception as e:
        logger.error(f"Error checking/seeding initial data: {e}")
    finally:
        db.close()
    
    yield
    # Shutdown
    logger.info("Shutting down RevenueOS backend.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan
)

# CORS configuration
cors_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",")] if isinstance(settings.ALLOWED_ORIGINS, str) else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if "*" not in cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_and_limits_middleware(request: Request, call_next):
    # Phase 14: Request payload size limit (e.g. 1MB max)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.MAX_REQUEST_SIZE_BYTES:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={
                        "detail": f"Payload Too Large: Request body exceeds maximum allowed limit of {settings.MAX_REQUEST_SIZE_BYTES} bytes (1MB)."
                    }
                )
        except ValueError:
            pass

    response = await call_next(request)

    # Phase 45: Inject standard production security headers
    for header_name, header_val in SECURITY_HEADERS.items():
        response.headers[header_name] = header_val

    return response


# Register Auth router
app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(auth_router, prefix=f"{settings.API_V1_STR}/auth", tags=["Authentication"])

# Health checks
@app.get("/health", tags=["Health"])
@app.get(f"{settings.API_V1_STR}/health", tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "service": settings.PROJECT_NAME,
                "environment": "development" if settings.DEBUG else "production",
                "database": "disconnected",
                "error": "Database connectivity check failed"
            }
        )
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "environment": "development" if settings.DEBUG else "production",
        "database": db_status
    }

# Register API routers
app.include_router(leaks_router, prefix="/api/revenue-leaks", tags=["Revenue Leaks"])
app.include_router(leaks_router, prefix=f"{settings.API_V1_STR}/revenue-leaks", tags=["Revenue Leaks"])
app.include_router(leaks_router, prefix=f"{settings.API_V1_STR}/leaks", tags=["Revenue Leaks"])
app.include_router(ml_router, prefix="/api/ml", tags=["Machine Learning"])
app.include_router(ml_router, prefix=f"{settings.API_V1_STR}/ml", tags=["Machine Learning"])
app.include_router(opportunities_router, prefix="/api/recovery-opportunities", tags=["Recovery Opportunities"])
app.include_router(opportunities_router, prefix=f"{settings.API_V1_STR}/recovery-opportunities", tags=["Recovery Opportunities"])
app.include_router(agent_router, prefix="/api/agent", tags=["AI Recovery Agent"])
app.include_router(agent_router, prefix=f"{settings.API_V1_STR}/agent", tags=["AI Recovery Agent"])
app.include_router(policy_router, prefix="/api/policy", tags=["Financial Action Policy Engine"])
app.include_router(policy_router, prefix=f"{settings.API_V1_STR}/policy", tags=["Financial Action Policy Engine"])
app.include_router(webhooks_router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(webhooks_router, prefix=f"{settings.API_V1_STR}/webhooks", tags=["Webhooks"])
app.include_router(providers_router, prefix="/api/payment-provider", tags=["Payment Providers"])
app.include_router(providers_router, prefix=f"{settings.API_V1_STR}/payment-provider", tags=["Payment Providers"])
app.include_router(recovery_router, prefix="/api/recovery", tags=["Recovery Execution Pipeline"])
app.include_router(recovery_router, prefix=f"{settings.API_V1_STR}/recovery", tags=["Recovery Execution Pipeline"])
app.include_router(recovery_router, prefix="/api", tags=["Recovery Actions Direct"])
app.include_router(audit_router, prefix="/api/audit", tags=["Audit System"])
app.include_router(audit_router, prefix=f"{settings.API_V1_STR}/audit", tags=["Audit System"])
app.add_api_route("/audit", serve_audit_ui, methods=["GET"], response_class=HTMLResponse, include_in_schema=False)

def serve_dashboard():
    if not DASHBOARD_HTML_PATH.exists():
        return HTMLResponse("<h1>RevenueOS Dashboard Loading...</h1>", status_code=200)
    with open(DASHBOARD_HTML_PATH, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), status_code=200)

app.add_api_route("/", serve_dashboard, methods=["GET"], response_class=HTMLResponse, include_in_schema=False)
app.add_api_route("/dashboard", serve_dashboard, methods=["GET"], response_class=HTMLResponse, include_in_schema=False)
app.include_router(analytics_router, prefix="/api/analytics", tags=["Analytics & ROI"])
app.include_router(analytics_router, prefix=f"{settings.API_V1_STR}/analytics", tags=["Analytics & ROI"])
app.include_router(evaluation_router, prefix="/api/evaluation", tags=["Evaluation Framework"])
app.include_router(evaluation_router, prefix=f"{settings.API_V1_STR}/evaluation", tags=["Evaluation Framework"])
app.include_router(security_router, prefix="/api/security", tags=["Security Audit"])
app.include_router(security_router, prefix=f"{settings.API_V1_STR}/security", tags=["Security Audit"])

app.include_router(merchants_router, prefix=f"{settings.API_V1_STR}/merchants", tags=["Merchants"])
app.include_router(transactions_router, prefix=f"{settings.API_V1_STR}/merchants", tags=["Transactions & Failures"])
app.include_router(subscriptions_router, prefix=f"{settings.API_V1_STR}/merchants", tags=["Subscriptions"])
app.include_router(checkout_sessions_router, prefix=f"{settings.API_V1_STR}/merchants", tags=["Checkout Sessions"])
app.include_router(demo_router, prefix=f"{settings.API_V1_STR}/demo", tags=["Demo Management"])
