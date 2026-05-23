from fastapi import APIRouter, Request, HTTPException
from schemas import RecommendRequest
from db import get_db_connection

router = APIRouter()

# ===================================================
# 🧠 1. 検索画面用：AI Mood ベクトル検索 ＆ 絞り込み（変更なし）
# ===================================================
@router.post("/api/recommend")
def get_mood_recommendations(data: RecommendRequest, request: Request):
    """
    フロントの『Ask AI ✨』から mood_text と filter_status を受け取り、
    ベクトル検索した上で、ステータス絞り込みを行って返す窓口
    """
    if not data.mood_text:
        raise HTTPException(status_code=400, detail="mood_textが必要です")
        
    try:
        if not hasattr(request.app.state, "recommend_engine") or request.app.state.recommend_engine is None:
            raise HTTPException(status_code=500, detail="レコメンドエンジンが初期化されていません")
            
        engine = request.app.state.recommend_engine
        
        # AIに少し多め（500件）に類似商品を計算してもらう
        recommended_products = engine.get_products_by_mood(data.mood_text, top_n=500)
        
        # フロントからの絞り込み（filter_status）を適用
        if data.filter_status == "active":
            recommended_products = [p for p in recommended_products if p["status"] == "on_sale"]
        elif data.filter_status == "sold_out":
            recommended_products = [p for p in recommended_products if p["status"] == "sold_out"]
            
        return recommended_products[:500]

    except Exception as e:
        print(f"🔥 Mood Recommend Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===================================================
# 🛰️ 2. 詳細画面用：確率的時間遷移 ＆ 空間的類似（変更なし）
# ===================================================
@router.get("/api/recommendations/{asin}")
def get_hybrid_recommendations(asin: str, request: Request, top_n: int = 4):
    """詳細画面のカルーセル用データ"""
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


# ===================================================
# 🏠 3. ホーム画面用：3段パーソナライズ統合エンドポイント
# ===================================================
@router.get("/api/home/{user_id}")
def get_home_dashboard(user_id: int):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 📊 分析1: ユーザーの行動（閲覧・いいね）からトップカテゴリーを抽出
            cursor.execute("""
                SELECT p.ai_category, COUNT(*) as weight
                FROM (
                    SELECT item_id FROM item_views WHERE user_id = %s
                    UNION ALL
                    SELECT item_id FROM likes WHERE user_id = %s
                ) as user_actions
                JOIN products p ON user_actions.item_id = p.id
                GROUP BY p.ai_category
                ORDER BY weight DESC
            """, (user_id, user_id))
            user_cats = cursor.fetchall()
            
            # 📊 分析2: 市場全体（全ユーザー）の閲覧履歴からトップカテゴリーを抽出
            cursor.execute("""
                SELECT p.ai_category, COUNT(*) as weight
                FROM item_views v
                JOIN products p ON v.item_id = p.id
                GROUP BY p.ai_category
                ORDER BY weight DESC
                LIMIT 1
            """)
            market_cat_row = cursor.fetchone()
            market_top_cat = market_cat_row['ai_category'] if market_cat_row else "Electronics"

            # 🛠️ ヘルパー関数: 指定カテゴリーからランダムに5件取得
            def get_items_by_cat(category, limit=5):
                # 💡 SELECT句に item_condition と shipping_days を追加！
                cursor.execute("""
                    SELECT id, asin, name, price, ai_category AS tags, description, image_url, status, 
                           '新品・未使用' AS item_condition,
                           '公式出品' AS seller_name,
                           '1〜2日で発送' AS shipping_days
                    FROM products
                    WHERE ai_category = %s AND status = 'on_sale'
                    ORDER BY RAND() LIMIT %s
                """, (category, limit))
                return cursor.fetchall()

            # 🥇 Tier 1: あなたへのおすすめ (Top 5)
            if user_cats:
                top_3_cats = [c['ai_category'] for c in user_cats[:3]]
                format_strings = ','.join(['%s'] * len(top_3_cats))
                # 💡 ここにも型を合わせるために追加！
                cursor.execute(f"""
                    SELECT id, asin, name, price, ai_category AS tags, description, image_url, status, 
                           '新品・未使用' AS item_condition,
                           '公式出品' AS seller_name,
                           '1〜2日で発送' AS shipping_days
                    FROM products
                    WHERE ai_category IN ({format_strings}) AND status = 'on_sale'
                    ORDER BY RAND() LIMIT 5
                """, tuple(top_3_cats))
                personalized_top5 = cursor.fetchall()
            else:
                # 💡 ここにも追加！
                cursor.execute("""
                    SELECT id, asin, name, price, ai_category AS tags, description, image_url, status, 
                           '新品・未使用' AS item_condition,
                           '公式出品' AS seller_name,
                           '1〜2日で発送' AS shipping_days
                    FROM products WHERE status = 'on_sale' ORDER BY RAND() LIMIT 5
                """)
                personalized_top5 = cursor.fetchall()

            # 🥈 Tier 2: あなたに人気のカテゴリー
            if user_cats:
                user_top_cat = user_cats[0]['ai_category']
                user_top_cat_items = get_items_by_cat(user_top_cat, 5)
                user_favorite_title = f"👤 あなたに人気のカテゴリー ({user_top_cat})"
            else:
                user_top_cat_items = []
                user_favorite_title = "👤 あなたに人気のカテゴリー"

            # 🥉 Tier 3: 市場全体で人気のカテゴリー
            market_top_cat_items = get_items_by_cat(market_top_cat, 5)

            return {
                "status": "success",
                "data": {
                    "personalized": {
                        "title": "✨ あなたへのおすすめ",
                        "items": personalized_top5
                    },
                    "user_favorite": {
                        "title": user_favorite_title,
                        "items": user_top_cat_items
                    },
                    "market_favorite": {
                        "title": f"🔥 市場で人気のカテゴリー ({market_top_cat})",
                        "items": market_top_cat_items
                    }
                }
            }
    finally:
        connection.close()