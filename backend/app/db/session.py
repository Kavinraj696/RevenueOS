import json
from decimal import Decimal
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings

def custom_json_serializer(obj):
    return json.dumps(obj, default=lambda o: str(o) if isinstance(o, Decimal) else str(o))

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    json_serializer=custom_json_serializer
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

def ensure_schema_compatibility(bind_engine):
    """
    Safely ensures that all Stage 4 and Stage 5 tables and columns exist
    without dropping or recreating any existing tables.
    """
    try:
        from app.db.base import Base
        import app.models  # Ensure all models are registered
        Base.metadata.create_all(bind=bind_engine)

        with bind_engine.connect() as conn:
            from sqlalchemy import text
            if bind_engine.name == "sqlite":
                # 1. recovery_opportunities
                res = conn.execute(text("PRAGMA table_info(recovery_opportunities)")).fetchall()
                cols = {r[1] for r in res}
                if cols:
                    if "model_version" not in cols:
                        conn.execute(text("ALTER TABLE recovery_opportunities ADD COLUMN model_version VARCHAR(50);"))
                    if "feature_version" not in cols:
                        conn.execute(text("ALTER TABLE recovery_opportunities ADD COLUMN feature_version VARCHAR(50);"))
                    if "prediction_time" not in cols:
                        conn.execute(text("ALTER TABLE recovery_opportunities ADD COLUMN prediction_time DATETIME;"))

                # 2. recovery_actions
                res_act = conn.execute(text("PRAGMA table_info(recovery_actions)")).fetchall()
                cols_act = {r[1] for r in res_act}
                if cols_act:
                    if "idempotency_key" not in cols_act:
                        conn.execute(text("ALTER TABLE recovery_actions ADD COLUMN idempotency_key VARCHAR(128);"))
                    if "causal_trace_id" not in cols_act:
                        conn.execute(text("ALTER TABLE recovery_actions ADD COLUMN causal_trace_id VARCHAR(64);"))
                    if "verified_status" not in cols_act:
                        conn.execute(text("ALTER TABLE recovery_actions ADD COLUMN verified_status VARCHAR(50);"))
                    if "verified_at" not in cols_act:
                        conn.execute(text("ALTER TABLE recovery_actions ADD COLUMN verified_at DATETIME;"))
                    if "actual_recovered_amount" not in cols_act:
                        conn.execute(text("ALTER TABLE recovery_actions ADD COLUMN actual_recovered_amount NUMERIC(14,2);"))

                # 3. payments (Stage 6 provider references & reconciliation)
                res_pay = conn.execute(text("PRAGMA table_info(payments)")).fetchall()
                cols_pay = {r[1] for r in res_pay}
                if cols_pay:
                    if "provider_payment_id" not in cols_pay:
                        conn.execute(text("ALTER TABLE payments ADD COLUMN provider_payment_id VARCHAR(100);"))
                    if "provider_order_id" not in cols_pay:
                        conn.execute(text("ALTER TABLE payments ADD COLUMN provider_order_id VARCHAR(100);"))
                    if "reconciliation_status" not in cols_pay:
                        conn.execute(text("ALTER TABLE payments ADD COLUMN reconciliation_status VARCHAR(50);"))

                # 4. webhook_events (Stage 6 processing status & hashes)
                res_wh = conn.execute(text("PRAGMA table_info(webhook_events)")).fetchall()
                cols_wh = {r[1] for r in res_wh}
                if cols_wh:
                    if "merchant_id" not in cols_wh:
                        conn.execute(text("ALTER TABLE webhook_events ADD COLUMN merchant_id CHAR(36);"))
                    if "processing_status" not in cols_wh:
                        conn.execute(text("ALTER TABLE webhook_events ADD COLUMN processing_status VARCHAR(50);"))
                    if "payload_hash" not in cols_wh:
                        conn.execute(text("ALTER TABLE webhook_events ADD COLUMN payload_hash VARCHAR(64);"))
                    if "processing_error" not in cols_wh:
                        conn.execute(text("ALTER TABLE webhook_events ADD COLUMN processing_error VARCHAR(500);"))

                conn.commit()
    except Exception:
        pass

ensure_schema_compatibility(engine)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

