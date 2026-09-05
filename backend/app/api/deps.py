import uuid
from typing import Generator, Optional, Dict, Any
from fastapi import Depends, HTTPException, status, Request, Header
from sqlalchemy.orm import Session
from app.db.session import SessionLocal, get_db
from app.models.merchant import Merchant
from app.config import settings
from app.security import verify_access_token, verify_merchant_authorization


def get_current_user_claims(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """
    Resolves authenticated user and tenant claims.
    Validates Bearer token if present. If auth is strictly enforced and missing, raises 401.
    """
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_api_key:
        token = x_api_key.strip()

    if token:
        # Strictly validates signature, format, and expiration
        return verify_access_token(token)

    if settings.ENFORCE_AUTH:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: missing Bearer token or API key",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # Prototype / Demo fallback when no auth header is provided
    return {
        "sub": "demo_operator",
        "merchant_id": None,
        "role": "superadmin",
        "is_authenticated": False
    }


def get_merchant_or_404(
    merchant_id: uuid.UUID,
    db: Session = Depends(get_db),
    claims: Dict[str, Any] = Depends(get_current_user_claims)
) -> Merchant:
    """
    Validates merchant existence AND enforces tenant authorization if authenticated.
    """
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Merchant with id {merchant_id} not found"
        )

    # If user has a merchant_id claim bound in their token, enforce tenant match (403 on mismatch)
    if claims.get("merchant_id"):
        verify_merchant_authorization(claims, merchant.id)

    return merchant
