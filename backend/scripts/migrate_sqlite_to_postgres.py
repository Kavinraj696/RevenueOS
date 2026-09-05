#!/usr/bin/env python3
"""
RevenueOS — SQLite to PostgreSQL Data Migration Tool
Transfers all relational entities from revenueos.db (SQLite) to PostgreSQL
with strict foreign key ordering, exact numeric precision, and post-migration validation.
"""
import sys
import os
import uuid
from decimal import Decimal
from datetime import datetime, timezone
import dateutil.parser

# Ensure backend directory is in path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.base import Base
import app.models as models

# List of models in strict topological foreign-key order
TOPOLOGICAL_MODELS = [
    models.Merchant,
    models.Customer,
    models.Payment,
    models.PaymentAttempt,
    models.Subscription,
    models.SubscriptionAttempt,
    models.CheckoutSession,
    models.RevenueLeak,
    models.RecoveryOpportunity,
    models.AgentDecision,
    models.AgentRun,
    models.PolicyDecision,
    models.RecoveryAction,
    models.AuditEvent,
    models.WebhookEvent,
    models.ModelPrediction,
    models.Experiment,
]

def parse_uuid(val):
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    return uuid.UUID(str(val))

def parse_datetime(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    try:
        dt = dateutil.parser.parse(str(val))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def migrate(sqlite_url: str = None, pg_url: str = None):
    # Locate sqlite file
    if not sqlite_url:
        candidates = ["revenueos.db", "backend/revenueos.db", "../revenueos.db"]
        found = None
        for c in candidates:
            if os.path.exists(c):
                found = os.path.abspath(c)
                break
        if not found:
            raise FileNotFoundError("Could not locate revenueos.db in workspace!")
        sqlite_url = f"sqlite:///{found.replace(os.sep, '/')}"

    if not pg_url:
        pg_url = os.getenv("DATABASE_URL")
        if not pg_url or pg_url.startswith("sqlite"):
            env_paths = [os.path.join(backend_path, ".env"), ".env", "../backend/.env"]
            for ep in env_paths:
                if os.path.exists(ep):
                    with open(ep, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip().startswith("DATABASE_URL="):
                                cand = line.strip().split("DATABASE_URL=", 1)[1].strip()
                                if cand and not cand.startswith("sqlite"):
                                    pg_url = cand
                                    break
                if pg_url and not pg_url.startswith("sqlite"):
                    break
        if not pg_url:
            pg_url = settings.DATABASE_URL
        if pg_url.startswith("sqlite"):
            raise ValueError("PostgreSQL URL must be specified in settings, backend/.env, or argument!")

    print("=" * 65)
    print("REVENUEOS SQLITE -> POSTGRESQL DATA MIGRATION")
    print("=" * 65)
    print(f"Source (SQLite):     {sqlite_url}")
    print(f"Target (PostgreSQL): {pg_url.split('@')[-1] if '@' in pg_url else pg_url}")
    print("-" * 65)

    sqlite_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    pg_engine = create_engine(pg_url)

    # 1. Create PostgreSQL Schema
    print("[1/4] Ensuring all 17 tables exist in PostgreSQL...")
    Base.metadata.drop_all(bind=pg_engine)
    Base.metadata.create_all(bind=pg_engine)
    print("      [OK] PostgreSQL schema created/verified.")

    SqliteSession = sessionmaker(bind=sqlite_engine)
    PgSession = sessionmaker(bind=pg_engine)

    sqlite_session = SqliteSession()
    pg_session = PgSession()

    counts = {}

    try:
        # 2. Migrate each model in topological order
        print("\n[2/4] Transferring records in topological order...")
        for model in TOPOLOGICAL_MODELS:
            tbl_name = model.__tablename__
            rows = sqlite_session.query(model).all()
            row_count = len(rows)
            counts[tbl_name] = row_count

            if row_count == 0:
                print(f"  -> {tbl_name:25s}: 0 records (skipped)")
                continue

            # Check if target already has records
            existing_count = pg_session.query(model).count()
            if existing_count >= row_count:
                print(f"  -> {tbl_name:25s}: {existing_count} records already present in PostgreSQL")
                continue

            # Clean target table if partially populated
            if existing_count > 0:
                # Truncate / delete target table rows
                pg_session.query(model).delete()
                pg_session.flush()

            # Insert objects into PostgreSQL
            # Merge or create new detached instances
            for r in rows:
                # Extract clean dict of attributes
                data = {}
                for col in model.__table__.columns:
                    val = getattr(r, col.name)
                    type_name = col.type.__class__.__name__.lower()
                    if "uuid" in type_name:
                        val = parse_uuid(val)
                    elif "date" in type_name or "time" in type_name:
                        val = parse_datetime(val)
                    elif "numeric" in type_name or "decimal" in type_name:
                        val = Decimal(str(val)) if val is not None else None
                    
                    data[col.name] = val

                new_obj = model(**data)
                pg_session.add(new_obj)

            pg_session.commit()
            print(f"  -> {tbl_name:25s}: [OK] {row_count} records migrated")

        # 3. Post-Migration Verification
        print("\n[3/4] Validating record counts and data consistency...")
        all_matched = True
        for model in TOPOLOGICAL_MODELS:
            tbl_name = model.__tablename__
            s_cnt = counts[tbl_name]
            p_cnt = pg_session.query(model).count()
            matched = (s_cnt == p_cnt)
            if not matched:
                all_matched = False
            status = "[MATCH]" if matched else "[MISMATCH]"
            print(f"  {status} {tbl_name:25s} SQLite={s_cnt:<5d} PostgreSQL={p_cnt:<5d}")

        if not all_matched:
            raise RuntimeError("Record count mismatch detected between SQLite and PostgreSQL!")

        # 4. Financial Sum Aggregations Verification
        print("\n[4/4] Validating monetary precision & aggregate sums...")
        # Payments sum
        s_pmt_sum = sqlite_session.execute(text("SELECT COALESCE(SUM(amount), 0) FROM payments")).scalar()
        p_pmt_sum = pg_session.execute(text("SELECT COALESCE(SUM(amount), 0) FROM payments")).scalar()
        diff_pmt = abs(Decimal(str(s_pmt_sum)) - Decimal(str(p_pmt_sum)))
        print(f"  Payments Total:       SQLite={Decimal(str(s_pmt_sum)):,.2f}  |  PostgreSQL={Decimal(str(p_pmt_sum)):,.2f}  (diff={diff_pmt})")

        # Revenue leaks sum
        s_leak_sum = sqlite_session.execute(text("SELECT COALESCE(SUM(revenue_at_risk), 0) FROM revenue_leaks")).scalar()
        p_leak_sum = pg_session.execute(text("SELECT COALESCE(SUM(revenue_at_risk), 0) FROM revenue_leaks")).scalar()
        diff_leak = abs(Decimal(str(s_leak_sum)) - Decimal(str(p_leak_sum)))
        print(f"  Revenue At Risk:      SQLite={Decimal(str(s_leak_sum)):,.2f}  |  PostgreSQL={Decimal(str(p_leak_sum)):,.2f}  (diff={diff_leak})")

        # Opportunities expected recovery
        s_opp_sum = sqlite_session.execute(text("SELECT COALESCE(SUM(expected_recovered_value), 0) FROM recovery_opportunities")).scalar()
        p_opp_sum = pg_session.execute(text("SELECT COALESCE(SUM(expected_recovered_value), 0) FROM recovery_opportunities")).scalar()
        diff_opp = abs(Decimal(str(s_opp_sum)) - Decimal(str(p_opp_sum)))
        print(f"  Expected Recovery:    SQLite={Decimal(str(s_opp_sum)):,.2f}  |  PostgreSQL={Decimal(str(p_opp_sum)):,.2f}  (diff={diff_opp})")

        if diff_pmt > Decimal("0.01") or diff_leak > Decimal("0.01") or diff_opp > Decimal("0.01"):
            raise ValueError("Financial aggregate sum discrepancy detected!")

        print("\n" + "=" * 65)
        print("[SUCCESS] ALL SQLITE DATA HAS BEEN MIGRATED TO POSTGRESQL!")
        print("=" * 65)

    finally:
        sqlite_session.close()
        pg_session.close()

if __name__ == "__main__":
    migrate()
