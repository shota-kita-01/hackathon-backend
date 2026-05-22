from fastapi import APIRouter, Request, HTTPException
from schemas import RecommendRequest
from db import get_db_connection  # 💡 データベース接続をインポート

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
        
        # まずはAIに少し多め（50件）に類似商品を計算してもらう
        recommended_products = engine.get_products_by_mood(data.mood_text, top_n=50)
        
        # フロントからの絞り込み（filter_status）を適用！
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


# ===================================================
# 🏠 3. ホーム画面用：3段パーソナライズ統合エンドポイント（🆕 新設！）
# ===================================================
@router.get("/api/home/{user_id}")
def get_home_dashboard(user_id: int):
    """
    ホーム画面用に「あなたへのおすすめ」「あなたの好きカテゴリ」「市場トレンドカテゴリ」
    の3種類のデータをDBの行動履歴から数理的に算出して一括返却するAPI
    """
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
            
            # 行動履歴があればその1位を、新規ユーザーの場合はデフォルトで "Shoes" をセット
            user_top_cat = user_cats[0]['ai_category'] if user_cats else "Shoes"
            
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

            # 🛠️ ヘルパー関数: 指定カテゴリーからランダムに5件取得（毎回新鮮なリロード感！）
            def get_items_by_cat(category, limit=5):
                cursor.execute("""
                    SELECT id, asin, name, price, ai_category AS tags, description, image_url, status, '公式出品' AS seller_name
                    FROM products
                    WHERE ai_category = %s AND status = 'on_sale'
                    ORDER BY RAND() LIMIT %s
                """, (category, limit))
                return cursor.fetchall()

            # 🥇 Tier 1: あなたへのおすすめ (Top 5)
            # ユーザーの好き上位3カテゴリーを混ぜて5件抽出。新規の場合は全体からランダム。
            if user_cats:
                top_3_cats = [c['ai_category'] for c in user_cats[:3]]
                format_strings = ','.join(['%s'] * len(top_3_cats))
                cursor.execute(f"""
                    SELECT id, asin, name, price, ai_category AS tags, description, image_url, status, '公式出品' AS seller_name
                    FROM products
                    WHERE ai_category IN ({format_strings}) AND status = 'on_sale'
                    ORDER BY RAND() LIMIT 5
                """, tuple(top_3_cats))
                personalized_top5 = cursor.fetchall()
            else:
                cursor.execute("""
                    SELECT id, asin, name, price, ai_category AS tags, description, image_url, status, '公式出品' AS seller_name
                    FROM products WHERE status = 'on_sale' ORDER BY RAND() LIMIT 5
                """)
                personalized_top5 = cursor.fetchall()

            # 🥈 Tier 2: あなたに人気のカテゴリー
            user_top_cat_items = get_items_by_cat(user_top_cat, 5)

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
                        "title": f"👤 あなたに人気のカテゴリー ({user_top_cat})",
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