from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.api.deps import get_db
from app.db.base import Base
from app.db.session import engine
from app.synthetic.scenarios import SCENARIO_CONFIGS
from app.synthetic.generator import SyntheticDataGenerator

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

@router.post("/reset")
def reset_demo_database(
    payload: ResetDemoRequest = Body(...),
    db: Session = Depends(get_db)
):
    """Reset database and regenerate synthetic data deterministically."""
    bind_engine = db.get_bind()
    Base.metadata.drop_all(bind=bind_engine)
    Base.metadata.create_all(bind=bind_engine)

    generator = SyntheticDataGenerator(seed=payload.seed)
    results = generator.generate_all(db)

    return {
        "status": "success",
        "message": f"Reset and seeded {len(results)} scenarios with seed={payload.seed}",
        "scenarios": results
    }
