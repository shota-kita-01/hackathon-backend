from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# 各ルーターモジュールのインポート
from routers import auth, items, recommend, admin

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 各ルーターの登録（インクルード）
app.include_router(auth.router)
app.include_router(items.router)
app.include_router(recommend.router)
app.include_router(admin.router)

@app.get("/")
def read_root():
    return {"message": "Hello from Modularized Cloud Run API!"}