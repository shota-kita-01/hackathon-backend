from pydantic import BaseModel

class UserRegister(BaseModel):
    name: str
    email: str
    password: str

class LoginData(BaseModel):
    firebase_uid: str
    name: str
    email: str

class RecommendRequest(BaseModel):
    user_id: int
    mood_text: str
    mode: str
    filter_status: str = "both"