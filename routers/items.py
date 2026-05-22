from fastapi import APIRouter, HTTPException
from google.genai import types
from db import get_db_connection, client

router = APIRouter()

# ===================================================
# 📦 1. 公式カタログ商品一覧 ＆ 詳細API
# ===================================================

@router.get("/api/products")
def get_all_products():
    """初期配置されているベースのカタログ商品を一括取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    id AS id, 
                    asin AS asin,
                    name AS name, 
                    price AS price, 
                    ai_category AS tags, 
                    description AS description, 
                    image_url AS image_url, 
                    status AS status,
                    '公式出品' AS seller_name, 
                    '1〜2日で発送' AS shipping_days 
                FROM products;
            """
            cursor.execute(sql)
            return {"status": "success", "data": cursor.fetchall()}
    finally:
        connection.close()


@router.get("/api/products/{asin}")
def get_product_detail(asin: str):
    """カタログ商品の詳細データを取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    id AS id,
                    asin AS asin,
                    name AS name, 
                    price AS price, 
                    ai_category AS tags,
                    description AS description, 
                    image_url AS image_url, 
                    status AS status,
                    '公式出品' AS seller_name,
                    '1〜2日で発送' AS shipping_days
                FROM products 
                WHERE asin = %s;
            """
            cursor.execute(sql, (asin,))
            product = cursor.fetchone()
            if not product:
                raise HTTPException(status_code=404, detail="商品が見つかりません")
            return product
    finally:
        connection.close()


# ===================================================
# 🛒 2. フリマ商品一覧 ＆ 自由出品API（ハイブリッド統合）
# ===================================================

@router.get("/api/items")
def get_items():
    """
    運営の初期カタログデータと、ユーザーがアプリから出品した一般データを
    数理的にガッチャンコして、タイムラインに新着順で一括返却します
    """
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                -- ① 初期配置のカタログデータ
                SELECT 
                    id AS id, 
                    name AS name, 
                    price AS price, 
                    ai_category AS tags, 
                    description AS description, 
                    image_url AS image_url, 
                    status AS status, 
                    '公式出品' AS seller_name, 
                    '1〜2日で発送' AS shipping_days 
                FROM products
                
                UNION ALL
                
                -- ② ユーザーが実際にアプリから出品したカスタムデータ
                SELECT 
                    id AS id, 
                    name AS name, 
                    price AS price, 
                    tags AS tags, 
                    description AS description, 
                    image_url AS image_url, 
                    status AS status,
                    seller_nickname AS seller_name, 
                    shipping_days AS shipping_days
                FROM items
                
                ORDER BY id DESC;
            """
            cursor.execute(sql)
            return cursor.fetchall()
    finally:
        connection.close()


@router.post("/api/items")
def create_item(item_data: dict):
    """ユーザーが出品画面から入力した内容を、一般出品テーブル（items）へ安全に格納"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO items (
                    name, description, price, image_url, 
                    seller_id, tags, status, seller_nickname, shipping_days
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'on_sale', %s, %s)
            """
            cursor.execute(sql, (
                item_data.get("name"),
                item_data.get("description"),
                item_data.get("price"),
                item_data.get("image_url"),
                item_data.get("seller_id"),
                item_data.get("tags", "一般出品"),
                item_data.get("seller_nickname", "名無しさん"),
                item_data.get("shipping_days", "1〜2日で発送")
            ))
            connection.commit()
            return {"status": "success", "message": "商品が出品されました！"}
    finally:
        connection.close()


@router.get("/api/users/{user_id}/products")
def get_user_products(user_id: int):
    """マイページの『出品した商品』タブに、自分が過去に出品した一般データを完全に同期"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    id AS id, 
                    name AS name, 
                    price AS price, 
                    tags AS tags, 
                    description AS description, 
                    image_url AS image_url, 
                    status AS status,
                    seller_nickname AS seller_name, 
                    shipping_days AS shipping_days
                FROM items
                WHERE seller_id = %s
                ORDER BY id DESC;
            """
            cursor.execute(sql, (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()


# ===================================================
# 🔍 【🆕新設】検索キーワード履歴 記録 ＆ 取得API
# ===================================================

@router.post("/api/users/{user_id}/keywords")
def record_search_keyword(user_id: int, data: dict):
    """ユーザーがAI検索（Ask AI）を行ったキーワードをログとしてDBへ格納"""
    keyword = data.get("keyword")
    if not keyword or not keyword.strip():
        return {"status": "skipped", "message": "空のキーワードです"}
    
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 競合を防ぐテーブル制約を考慮しつつインサート
            try:
                cursor.execute("""
                    INSERT INTO search_keywords (user_id, keyword) 
                    VALUES (%s, %s)
                """, (user_id, keyword.strip()))
                connection.commit()
                return {"status": "success"}
            except Exception as e:
                print(f"⚠️ キーワード保存を安全にスキップしました: {e}")
                return {"status": "skipped"}
    finally:
        connection.close()


@router.get("/api/users/{user_id}/keywords")
def get_search_keywords(user_id: int):
    """ユーザーの過去の検索キーワード履歴を最新15件取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute("""
                    SELECT keyword FROM search_keywords 
                    WHERE user_id = %s 
                    ORDER BY id DESC LIMIT 15
                """, (user_id,))
                return cursor.fetchall()
            except Exception as e:
                # テーブルが未作成の場合のフォールバック
                print(f"⚠️ キーワード履歴テーブルにアクセスできません。空配列を返します: {e}")
                return []
    finally:
        connection.close()


# ===================================================
# 🛍️ 3. 購入・いいね・履歴API（エラーを完全ブロックする防弾仕様）
# ===================================================

@router.post("/api/items/{item_id}/purchase")
def purchase_item(item_id: int, buyer_data: dict):
    """商品をシームレスに購入（SOLD OUT化）させる"""
    buyer_id = buyer_data.get("buyer_id")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT status FROM products WHERE id = %s", (item_id,))
            product = cursor.fetchone()
            if not product: 
                raise HTTPException(status_code=404, detail="商品が見つかりません")
            if product["status"] == "sold_out": 
                raise HTTPException(status_code=400, detail="売り切れています")
            
            # ① 対象商品のステータスを売り切れに更新
            cursor.execute("UPDATE products SET status = 'sold_out' WHERE id = %s", (item_id,))
            
            # ② 外部キーの競合を防ぎつつ、購入ログを格納
            try:
                cursor.execute("INSERT INTO purchases (item_id, buyer_id) VALUES (%s, %s)", (item_id, buyer_id))
            except Exception as e:
                print(f"⚠️ 統計用トランザクション記録を安全にスキップしました: {e}")

            connection.commit()
            return {"status": "success", "message": "商品の購入が完了しました！"}
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        connection.close()


@router.post("/api/items/{item_id}/like")
def toggle_like(item_id: int, data: dict):
    """商品に対して『いいね』をお気に入りトグル登録"""
    user_id = data.get("user_id")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM likes WHERE user_id = %s AND item_id = %s", (user_id, item_id))
            if cursor.fetchone():
                cursor.execute("DELETE FROM likes WHERE user_id = %s AND item_id = %s", (user_id, item_id))
                like_status = "unliked"
            else:
                try:
                    cursor.execute("INSERT INTO likes (user_id, item_id) VALUES (%s, %s)", (user_id, item_id))
                except Exception as e:
                    print(f"⚠️ お気に入りお試し登録を安全にスキップしました: {e}")
                like_status = "liked"
                
            connection.commit()
            return {"status": "success", "like_status": like_status}
    finally:
        connection.close()


@router.get("/api/users/{user_id}/likes")
def get_user_likes(user_id: int):
    """ユーザーが『いいね』したお気に入り商品の一覧を取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    p.id AS id, p.asin AS asin, p.name AS name, p.price AS price, 
                    p.ai_category AS tags, p.description AS description, p.image_url AS image_url, 
                    p.status AS status, '公式出品' AS seller_name, TRUE AS is_liked
                FROM likes l 
                JOIN products p ON l.item_id = p.id
                WHERE l.user_id = %s ORDER BY l.created_at DESC;
            """
            cursor.execute(sql, (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()


@router.post("/api/items/{item_id}/view")
def record_item_view(item_id: int, data: dict):
    """商品の足あと・閲覧履歴をバックグラウンド記録"""
    user_id = data.get("user_id")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute("INSERT INTO item_views (user_id, item_id) VALUES (%s, %s)", (user_id, item_id))
            except Exception as e:
                print(f"⚠️ 閲覧統計へのデータフィードを安全にスキップしました: {e}")
            
            connection.commit()
            return {"status": "success"}
    finally:
        connection.close()


@router.get("/api/users/{user_id}/views")
def get_user_views(user_id: int):
    """最近チェックした商品の閲覧履歴（最新20件）を取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    p.id AS id, p.asin AS asin, p.name AS name, p.price AS price, 
                    p.ai_category AS tags, p.description AS description, p.image_url AS image_url, 
                    p.status AS status, '公式出品' AS seller_name
                FROM item_views v
                JOIN products p ON v.item_id = p.id
                WHERE v.user_id = %s
                ORDER BY v.id DESC
                LIMIT 20;
            """
            cursor.execute(sql, (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()


@router.get("/api/users/{user_id}/purchases")
def get_user_purchases(user_id: int):
    """マイページ表示用の購入取引履歴を取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    p.id AS id, p.asin AS asin, p.name AS name, p.price AS price, 
                    p.ai_category AS tags, p.description AS description, p.image_url AS image_url, 
                    p.status AS status, '公式出品' AS seller_name
                FROM purchases pur
                JOIN products p ON pur.item_id = p.id
                WHERE pur.buyer_id = %s
                ORDER BY pur.id DESC;
            """
            cursor.execute(sql, (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()


# ===================================================
# 🧠 4. AI商品説明自動生成 ＆ 価格査定（完全日本語・フリマ特化版）
# ===================================================

@router.post("/api/ai/suggest-description")
def suggest_description(data: dict):
    item_name = data.get("name")
    if not item_name: 
        raise HTTPException(status_code=400, detail="商品名が必要です")
    try:
        prompt = f"""あなたは人気のフリマアプリで活躍する熟練のコピーライターです。
以下の商品名をもとに、購入者の心を惹きつける魅力的で自然な日本語の商品説明文を作成してください。
必要に応じて【商品の魅力】【特徴】【おすすめの着用シーン】などの見出しを使って見やすく整理してください。
出力は生成された説明文のみとし、マークダウンのブロック（```など）や、「承知しました」などの余計な会話文は絶対に含めないでください。

商品名: {item_name}"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.7)
        )
        return {"status": "success", "description": response.text.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/ai/suggest-price")
def suggest_price(data: dict):
    item_name = data.get("name")
    item_description = data.get("description")
    
    if not item_name or not item_description: 
        raise HTTPException(status_code=400, detail="商品名と商品説明の両方が必要です")
        
    try:
        prompt = f"""あなたは日本のファッション・フリマ市場（メルカリやヤフオクなど）に精通したAI査定士です。
以下の商品名と詳細な商品説明を分析し、現在の日本のフリマ市場における「適正な販売価格（日本円）」を査定してください。
ブランドの価値、商品の状態（傷や汚れの有無）、素材などを総合的に判断し、最も売れやすいリアルな価格を算出してください。

出力は査定した金額の「数字（整数）」のみとしてください。「円」や「¥」、カンマ（,）、その他のテキストは絶対に含めないでください。
例：4500円が適正だと判断した場合は「4500」とだけ出力してください。

商品名: {item_name}
商品説明: {item_description}"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3)
        )
        jpy_price = int(response.text.strip())
        return {"status": "success", "suggested_price": jpy_price}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))