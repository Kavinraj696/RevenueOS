import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import settings
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.models.merchant import Merchant
from app.synthetic.generator import SyntheticDataGenerator

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health checks
@app.get("/health", tags=["Health"])
@app.get(f"{settings.API_V1_STR}/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "environment": "development" if settings.DEBUG else "production"
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
app.include_router(audit_router, prefix="/api/audit", tags=["Audit System"])
app.include_router(audit_router, prefix=f"{settings.API_V1_STR}/audit", tags=["Audit System"])
app.add_api_route("/audit", serve_audit_ui, methods=["GET"], response_class=HTMLResponse, include_in_schema=False)
app.include_router(merchants_router, prefix=f"{settings.API_V1_STR}/merchants", tags=["Merchants"])
app.include_router(transactions_router, prefix=f"{settings.API_V1_STR}/merchants", tags=["Transactions & Failures"])
app.include_router(subscriptions_router, prefix=f"{settings.API_V1_STR}/merchants", tags=["Subscriptions"])
app.include_router(checkout_sessions_router, prefix=f"{settings.API_V1_STR}/merchants", tags=["Checkout Sessions"])
app.include_router(demo_router, prefix=f"{settings.API_V1_STR}/demo", tags=["Demo Management"])

