from fastapi import APIRouter, Request, HTTPException

router = APIRouter()

@router.get("/api/recommendations/{asin}")
def get_hybrid_recommendations(asin: str, request: Request, top_n: int = 4):
    """
    フロントエンドから商品のID(asin)を受け取り、
    空間的類似（コサイン類似度）と確率的時間遷移（マルコフ連鎖）の
    2つの独立したレコメンド・カルーセルデータを返す神エンドポイント
    """
    try:
        # main.py の lifespan でグローバルステートに仕込んだエンジンを安全に召喚
        # 💡 万が一の初期化漏れを防ぐセーフティを追加
        if not hasattr(request.app.state, "recommend_engine") or request.app.state.recommend_engine is None:
            raise HTTPException(
                status_code=500,
                detail="レコメンドエンジンがアプリケーションのステートに初期化されていません。main.pyのlifespanを確認してください。"
            )
            
        engine = request.app.state.recommend_engine
        
        # 推薦エンジンから2つのカルーセルを動的に計算
        carousel_1, carousel_2 = engine.get_recommendations(asin, top_n=top_n)
        
        if carousel_1 is None or carousel_2 is None:
            raise HTTPException(
                status_code=404, 
                detail=f"指定された商品（ASIN: {asin}）がマスターデータに存在しません。"
            )
            
        # 喜多さんの指定したフロントエンドが喜ぶネスト構造のまま綺麗なJSONでリターン
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