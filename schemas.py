from pydantic import BaseModel
from typing import Optional

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
    # 💥 `mode: str` はフロントから消滅したため削除！
    filter_status: str = "both"