import uuid
from decimal import Decimal
from typing import Dict, Any
from sqlalchemy import String, Numeric, JSON, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

class ModelPrediction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "model_predictions"

    model_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    input_features_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    prediction: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    input_reference: Mapped[str] = mapped_column(String(255), nullable=True, index=True)

    @property
    def timestamp(self):
        return self.created_at

    __table_args__ = (
        Index("ix_model_pred_name_version", "model_name", "model_version"),
        Index("ix_model_pred_entity", "entity_type", "entity_id"),
    )
