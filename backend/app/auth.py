"""Password hashing, JWTs, and request authentication dependencies."""
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from .database import get_db
from .models import HouseholdMember, User


JWT_SECRET = os.getenv("JWT_SECRET", "development-only-secret-change-me")
JWT_ALGORITHM = "HS256"
TOKEN_LIFETIME_HOURS = 24
password_hash = PasswordHash.recommended()
bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user: User) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_LIFETIME_HOURS)
    return jwt.encode({"sub": user.id, "exp": expires_at}, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme), db: Session = Depends(get_db)
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired access token", {"WWW-Authenticate": "Bearer"})
    try:
        user_id = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM]).get("sub")
    except jwt.PyJWTError as error:
        raise unauthorized from error
    user = db.get(User, user_id)
    if not user:
        raise unauthorized
    return user


def get_current_household_id(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> str:
    membership = db.query(HouseholdMember).filter_by(user_id=user.id).first()
    if not membership:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is not assigned to a household")
    return membership.household_id
