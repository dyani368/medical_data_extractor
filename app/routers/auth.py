from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import Annotated

from fastapi.security import OAuth2PasswordRequestForm

from app.models.user_model import User
from app.schemas import user_schema
from app.core.database import get_db
from app.core import security 

from sqlalchemy.exc import IntegrityError

router = APIRouter()

@router.post("/register", response_model=user_schema.UserResponse, status_code=status.HTTP_201_CREATED)
def register(new_user: user_schema.UserCreate, db: Annotated[Session, Depends(get_db)]):

    result1 = db.execute(select(User).where(User.username == new_user.username)).scalars().first()

    if result1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username already registered")
    
    result2 = db.execute(select(User).where(User.email == new_user.email)).scalars().first()

    if result2:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")

    user = User(username=new_user.username, email=new_user.email, hashed_password=security.get_password_hash(new_user.password))
    db.add(user)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already registered",
        )

    db.refresh(user)
    return user

@router.post("/token", response_model=user_schema.Token)
def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: Annotated[Session, Depends(get_db)]):

    result1 = db.execute(select(User).where(User.username==form_data.username)).scalars().first()
    
    if not result1 or not security.verify_password(form_data.password,result1.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    data = {
        "sub" : str(result1.id)
    }

    token = security.create_access_token(data)

    return {"access_token": token, "token_type": "bearer"}

@router.get("/me", response_model=user_schema.UserResponse)
def get_me(current_user: Annotated[User, Depends(security.get_current_user)]):
    return current_user

    



    


