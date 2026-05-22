from fastapi import APIRouter, Request, HTTPException
from schemas import RecommendRequest  # 💡 作成した型定義をインポート

router = APIRouter()

# ===================================================
# 🧠 1. 検索画面用：AI Mood ベクトル検索 ＆ 絞り込み
# ===================================================
@router.post("/api/recommend")
def get_mood_recommendations(data: RecommendRequest, request: Request):
    """
    フロントの『Ask AI ✨』から mood_text と filter_status を受け取り、
    ベクトル検索した上で、ステータス絞り込みを行って返す最強の窓口
    """
    if not data.mood_text:
        raise HTTPException(status_code=400, detail="mood_textが必要です")
        
    try:
        if not hasattr(request.app.state, "recommend_engine") or request.app.state.recommend_engine is None:
            raise HTTPException(status_code=500, detail="レコメンドエンジンが初期化されていません")
            
        engine = request.app.state.recommend_engine
        
        # 💡 まずはAIに少し多め（50件）に類似商品を計算してもらう
        recommended_products = engine.get_products_by_mood(data.mood_text, top_n=50)
        
        # 💡 フロントからの絞り込み（filter_status）を適用！
        if data.filter_status == "active":
            recommended_products = [p for p in recommended_products if p["status"] == "on_sale"]
        elif data.filter_status == "sold_out":
            recommended_products = [p for p in recommended_products if p["status"] == "sold_out"]
            
        # 最終的に上位20件をフロントへ返却
        return recommended_products[:20]

    except Exception as e:
        print(f"🔥 Mood Recommend Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================================================
# 🛰️ 2. 詳細画面用：確率的時間遷移 ＆ 空間的類似
# ===================================================
@router.get("/api/recommendations/{asin}")
def get_hybrid_recommendations(asin: str, request: Request, top_n: int = 4):
    """詳細画面のカルーセル用データ（変更なし）"""
    try:
        if not hasattr(request.app.state, "recommend_engine") or request.app.state.recommend_engine is None:
            raise HTTPException(status_code=500, detail="レコメンドエンジンが初期化されていません")
            
        engine = request.app.state.recommend_engine
        
        carousel_1, carousel_2 = engine.get_recommendations(asin, top_n=top_n)
        
        if carousel_1 is None or carousel_2 is None:
            raise HTTPException(status_code=404, detail=f"指定された商品（ASIN: {asin}）が存在しません")
            
        return {
            "target_asin": asin,
            "carousel_space_similarity": {
                "title": "この商品と似ているアイテム（空間的類似）",
                "items": carousel_1
            },
            "carousel_time_transition": {
                "title": "次にこれを買い回る人が多いジャンル（確率的時間遷移）",
                "items": carousel_2
            }
        }
        
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"🔥 Recommend API Critical Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))