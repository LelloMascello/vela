from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field
from passlib.context import CryptContext
from typing import List, Optional
from datetime import datetime
from bson import ObjectId  # Aggiunto per gestire gli ID di MongoDB
import os

# --- 1. SQLITE CONFIGURATION (AUTH) ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./auth.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DBUser(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- 2. MONGODB CONFIGURATION (CHATS) ---
MONGO_DETAILS = "mongodb://localhost:27017"
mongo_client = AsyncIOMotorClient(MONGO_DETAILS)
mongo_db = mongo_client.aichat_database
chat_collection = mongo_db.get_collection("chats")

# --- 3. PYDANTIC MODELS ---
class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class ChatExchange(BaseModel):
    question: str
    response: str
    timestamp: Optional[datetime] = Field(default_factory=datetime.utcnow)

class ChatSessionSave(BaseModel):
    user_id: int
    exchanges: List[ChatExchange]

# --- 4. FASTAPI APP & ROUTES ---
app = FastAPI()

# Mount static files folder
app.mount("/static", StaticFiles(directory="static"), name="static")

# HTML Page Routes
@app.get("/")
def read_login():
    return FileResponse("templates/login.html")

@app.get("/signup")
def read_signup():
    return FileResponse("templates/signup.html")

@app.get("/home")
def read_home():
    return FileResponse("templates/home.html")

# API Auth Routes
@app.post("/api/signup")
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(DBUser).filter((DBUser.username == user.username) | (DBUser.email == user.email)).first()
    if db_user: raise HTTPException(status_code=400, detail="Username or Email already exists")
    
    hashed_password = pwd_context.hash(user.password)
    new_user = DBUser(username=user.username, email=user.email, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    return {"message": "User created"}

@app.post("/api/login")
def login_user(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(DBUser).filter(DBUser.username == user.username).first()
    if not db_user or not pwd_context.verify(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"user_id": db_user.id, "username": db_user.username}

# API Chat Routes (MongoDB)
@app.post("/api/chats/save")
async def save_chat_session(chat_data: ChatSessionSave):
    chat_dict = chat_data.model_dump()
    result = await chat_collection.insert_one(chat_dict)
    if result.inserted_id:
        return {"message": "Saved", "chat_id": str(result.inserted_id)}
    raise HTTPException(status_code=500, detail="Failed to save")

# GET Route con paginazione (skip, limit) e ordinamento decrescente
@app.get("/api/chats/{user_id}")
async def get_user_chats(user_id: int, skip: int = 0, limit: int = 10):
    chats = []
    # Ordina per _id decrescente (-1) che equivale cronologicamente al più recente
    cursor = chat_collection.find({"user_id": user_id}).sort("_id", -1).skip(skip).limit(limit)
    async for document in cursor:
        document["_id"] = str(document["_id"])
        chats.append(document)
    return {"chats": chats}

# DELETE Route per eliminare una chat specifica tramite il suo ObjectId
@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str):
    try:
        obj_id = ObjectId(chat_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID chat non valido")
        
    result = await chat_collection.delete_one({"_id": obj_id})
    if result.deleted_count == 1:
        return {"message": "Chat eliminata con successo"}
    raise HTTPException(status_code=404, detail="Chat non trovata")