from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import recommend, items, auth, admin
from recommendation_engine import RecommendationEngine

# ==========================================
# 🔄 アプリ起動・終了時のライフサイクル管理
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ① サーバーが「いの一番」に起動した瞬間、24万行のベクトルデータをメモリ（RAM）に一度だけ展開
    print("🚀 アプリケーションを起動中: レコメンドエンジンを常駐メモリに展開します...")
    app.state.recommend_engine = RecommendationEngine()
    
    yield  # 💡 ここでサーバーが待機状態になり、リクエストを受け付け始めます
    
    # ② サーバーがシャットダウンする時の処理（必要なら）
    print("🛑 アプリケーションを停止中...")
    app.state.recommend_engine = None

# lifespanをアプリ本体に登録
app = FastAPI(title="Hackathon Hybrid Recommendation API", lifespan=lifespan)

# 🌐 CORSの完全開通（React/Next.jsとの通信を許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔌 ルーターの連結
app.include_router(recommend.router)
app.include_router(items.router)
app.include_router(auth.router)
app.include_router(admin.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to Hackathon Backend API v1"}