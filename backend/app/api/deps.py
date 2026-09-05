import uuid
from typing import Generator
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import SessionLocal, get_db
from app.models.merchant import Merchant

def get_merchant_or_404(merchant_id: uuid.UUID, db: Session = Depends(get_db)) -> Merchant:
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Merchant with id {merchant_id} not found"
        )
    return merchant
