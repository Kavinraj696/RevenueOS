from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Body, HTTPException, Path
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.api.deps import get_db
from app.db.base import Base
from app.synthetic.scenarios import SCENARIO_CONFIGS
from app.synthetic.generator import SyntheticDataGenerator
from app.services.demo_scenario_engine import DemoScenarioEngine
from app.schemas.demo import (
    DemoScenarioCatalogResponse,
    DemoScenarioRunResponse,
    DemoScenarioMeta,
)

router = APIRouter()

class ResetDemoRequest(BaseModel):
    seed: int = 42

@router.get("/scenarios", response_model=List[Dict[str, Any]])
def list_demo_scenarios():
    """List all available predefined merchant scenarios."""
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "description": c["description"],
            "customer_count": c["customer_count"],
            "payment_count": c["payment_count"],
            "baseline_failure_rate": c.get("baseline_failure_rate"),
        }
        for c in SCENARIO_CONFIGS
    ]

@router.get("/scenarios/catalog", response_model=DemoScenarioCatalogResponse)
def get_scenario_engine_catalog():
    """Retrieve the full catalog of the 5 interactive demo scenarios."""
    scenarios = DemoScenarioEngine.get_catalog()
    return DemoScenarioCatalogResponse(scenarios=scenarios)

@router.post("/scenarios/run/{scenario_id}", response_model=DemoScenarioRunResponse)
def execute_demo_scenario(
    scenario_id: str = Path(..., description="Scenario ID to run: payment_degradation, checkout_abandonment, subscription_failures, recovery_failure, unsafe_action"),
    db: Session = Depends(get_db)
):
    """
    Execute one of the 5 interactive demonstration scenarios.
    Returns full step-by-step forensic execution trace and audit causality linkages.
    """
    engine = DemoScenarioEngine(db)
    try:
        result = engine.run_scenario(scenario_id)
        return result
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Scenario execution failed: {str(err)}")

@router.post("/reset")
def reset_demo_database(
    payload: ResetDemoRequest = Body(...),
    db: Session = Depends(get_db)
):
    """Reset database and regenerate synthetic data deterministically."""
    bind_engine = db.get_bind()
    Base.metadata.create_all(bind=bind_engine)
    if bind_engine.dialect.name == "postgresql":
        from sqlalchemy import text
        table_names = [f'"{table.name}"' for table in Base.metadata.sorted_tables]
        if table_names:
            db.execute(text(f"TRUNCATE TABLE {', '.join(table_names)} RESTART IDENTITY CASCADE;"))
            db.commit()
    else:
        Base.metadata.drop_all(bind=bind_engine)
        Base.metadata.create_all(bind=bind_engine)

    generator = SyntheticDataGenerator(seed=payload.seed)
    results = generator.generate_all(db)

    return {
        "status": "success",
        "message": f"Reset and seeded {len(results)} scenarios with seed={payload.seed}",
        "scenarios": results
    }

