from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.security import hash_password, verify_password
from app.db.models import User
from app.schemas import LoginRequest, SignupRequest


router = APIRouter(tags=["authentication"])


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


@router.post("/signup", status_code=201)
def signup(data: SignupRequest, db: Session = Depends(get_db)):
    email = normalize_email(data.email)
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    user = User(
        username=data.username.strip(),
        email=email,
        password_hash=hash_password(data.password),
        tier="free",
        subscription_status=None,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")
    db.refresh(user)

    return {
        "user_id": user.id,
        "username": user.username,
        "tier": user.tier,
        "subscription_status": user.subscription_status,
    }


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    email = normalize_email(data.email)
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {
        "user_id": user.id,
        "username": user.username,
        "tier": user.tier or "free",
        "subscription_status": user.subscription_status,
    }
