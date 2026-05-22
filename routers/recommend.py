from fastapi import APIRouter, Request, HTTPException

router = APIRouter()

# ===================================================
# 🧠 1. 検索画面用：AI Mood ベクトル検索エンドポイント（🆕 追加）
# ===================================================
@router.post("/api/recommend")
def get_mood_recommendations(data: dict, request: Request):
    """
    フロントの『Ask AI ✨』から mood_text を受け取り、
    Geminiでベクトル化して、Amazonデータ320件とコサイン類似度検索を行う窓口
    """
    mood_text = data.get("mood_text")
    if not mood_text:
        raise HTTPException(status_code=400, detail="mood_textが必要です")
        
    try:
        # 常駐しているエンジンを召喚
        if not hasattr(request.app.state, "recommend_engine") or request.app.state.recommend_engine is None:
            raise HTTPException(status_code=500, detail="レコメンドエンジンが初期化されていません")
            
        engine = request.app.state.recommend_engine
        
        # 💡 エンジンのテキスト検索メソッドを呼び出す
        # ※もしエンジン側のメソッド名が異なる場合は、ここの関数名を微調整してください（例: query_by_text など）
        recommended_products = engine.get_products_by_mood(mood_text, top_n=20)
        
        # フロントがそのままループ（map）で回せるように、商品の配列をそのまま返却します
        return recommended_products

    except Exception as e:
        print(f"🔥 Mood Recommend Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================================================
# 🛰️ 2. 詳細画面用：確率的時間遷移 ＆ 空間的類似エンドポイント
# ===================================================
@router.get("/api/recommendations/{asin}")
def get_hybrid_recommendations(asin: str, request: Request, top_n: int = 4):
    """
    商品詳細画面で、空間的類似（コサイン類似度）と確率的時間遷移（マルコフ連鎖）の
    2つの独立したレコメンド・カルーセルデータを返すエンドポイント
    """
    try:
        if not hasattr(request.app.state, "recommend_engine") or request.app.state.recommend_engine is None:
            raise HTTPException(status_code=500, detail="レコメンドエンジンが初期化されていません")
            
        engine = request.app.state.recommend_engine
        
        # 💡 こちらはASIN（商品）を起点にした回遊・類似検索
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