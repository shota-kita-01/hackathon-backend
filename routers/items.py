from fastapi import APIRouter, HTTPException
from google.genai import types
# db.py から新しくなった Gemini の client と接続関数をインポート
from db import get_db_connection, client

router = APIRouter()

# ===================================================
# 📦 1. AIカタログ商品API（Amazon 320件データ用 / 構造統一版）
# ===================================================

@router.get("/api/products")
def get_all_products():
    """
    今回インポートした320件のAI特権データを、
    フリマ商品（items）と100%同じデータ構造に化けさせて一括取得するAPI
    """
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 💡 喜多さんの指定したルール通りにSQLの「AS（エイリアス）」を使ってデータを整形
            sql = """
                SELECT 
                    id AS id,                         -- Cloud SQL側で自動生成した本物の通し番号id
                    asin AS asin,                     -- 元のASINも連携用に残します
                    name AS name, 
                    price AS price, 
                    ai_category AS tags,              -- カテゴリを tags にマッピング
                    description AS description, 
                    image_url AS image_url, 
                    'on_sale' AS status,              -- 常に 'on_sale' を動的に生成
                    'Amazon公式' AS seller_name,       -- 出品者名を固定文字で生成
                    '1〜2日で発送' AS shipping_days     -- 発送日数も生成
                FROM products;
            """
            cursor.execute(sql)
            products = cursor.fetchall()
            
            return {
                "status": "success",
                "count": len(products),
                "data": products
            }
    except Exception as e:
        print(f"🔥 AI Products API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


@router.get("/api/products/{asin}")
def get_product_detail(asin: str):
    """
    商品詳細画面へ遷移したときに、そのASINの商品情報を
    フリマ商品と100%同じデータ構造に化けさせて単件取得するAPI
    """
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 💡 🆕 詳細画面でも一覧と全く同じキー名で返却するようにSQLを最適化！
            sql = """
                SELECT 
                    id AS id,
                    asin AS asin,
                    name AS name, 
                    price AS price, 
                    ai_category AS tags,
                    description AS description, 
                    image_url AS image_url, 
                    'on_sale' AS status,
                    'Amazon公式' AS seller_name,
                    '1〜2日で発送' AS shipping_days
                FROM products 
                WHERE asin = %s;
            """
            cursor.execute(sql, (asin,))
            product = cursor.fetchone()
            if not product:
                raise HTTPException(status_code=404, detail="指定された商品が見つかりません")
            return product
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()


# ===================================================
# 🧠 2. 既存機能：AI自動生成 ＆ 価格査定API（完全維持）
# ===================================================

@router.post("/api/ai/suggest-description")
def suggest_description(data: dict):
    item_name = data.get("name")
    if not item_name: raise HTTPException(status_code=400, detail="商品名が必要です")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Product Name: {item_name}",
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are an expert copywriter for a global fashion e-commerce marketplace.\n"
                    "Generate a professional, appealing, and clean English product description based on the product name provided.\n"
                    "Include sections like [Overview], [Features], and [Styling Tips] if applicable.\n"
                    "Output ONLY the generated description. No markdown block wrappers (like ```), no conversational text."
                ),
                temperature=0.7,
            )
        )
        return {"status": "success", "description": response.text.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/ai/suggest-price")
def suggest_price(data: dict):
    item_name = data.get("name")
    if not item_name: raise HTTPException(status_code=400, detail="商品名が必要です")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Product Name: {item_name}",
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are an AI price valuation engine for a fashion marketplace.\n"
                    "Analyze the given product name and estimate its fair market value in US Dollars (USD).\n"
                    "Output ONLY a single integer representing the dollar amount. Do not include '$', text, or any punctuation.\n"
                    "Example: if you think it's worth $45, output '45'."
                ),
                temperature=0.3,
            )
        )
        usd_price = int(response.text.strip())
        jpy_price = usd_price * 150
        return {"status": "success", "suggested_price": jpy_price}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===================================================
# 🛍️ 3. 既存機能：C2C ユーザー出品・売買・履歴API（完全維持）
# ===================================================

@router.post("/api/items")
def create_item(item_data: dict):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO items (name, description, price, image_url, seller_id, tags, status, seller_nickname, shipping_days)
                VALUES (%s, %s, %s, %s, %s, %s, 'on_sale', %s, %s)
            """
            cursor.execute(sql, (
                item_data.get("name"),
                item_data.get("description"),
                item_data.get("price"),
                item_data.get("image_url"),
                item_data.get("seller_id"),
                item_data.get("tags", ""), 
                item_data.get("seller_nickname", "名無しさん"),
                item_data.get("shipping_days", "1〜2日で発送")
            ))
            connection.commit()
            return {"status": "success", "message": "商品が出品されました！"}
    finally:
        connection.close()


@router.get("/api/items")
def get_items():
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 💡 フロントのために、Amazonデータと完全に同じカラム名・同じ順番で並び替えて返却！
            sql = """
                SELECT 
                    i.id AS id,                                                     -- フリマの通し番号id
                    i.name AS name, 
                    i.price AS price, 
                    i.tags AS tags, 
                    i.description AS description, 
                    i.image_url AS image_url, 
                    i.status AS status, 
                    COALESCE(i.seller_nickname, u.name, '名無しさん') AS seller_name, -- 出品者名
                    i.shipping_days AS shipping_days                                -- 発送日数
                FROM items i 
                LEFT JOIN users u ON i.seller_id = u.id 
                ORDER BY i.id DESC;
            """
            cursor.execute(sql)
            return cursor.fetchall()
    finally:
        connection.close()

@router.post("/api/items/{item_id}/purchase")
def purchase_item(item_id: int, buyer_data: dict):
    buyer_id = buyer_data.get("buyer_id")
    if not buyer_id: raise HTTPException(status_code=400, detail="購入者のIDが必要です")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT status FROM items WHERE id = %s", (item_id,))
            item = cursor.fetchone()
            if not item: raise HTTPException(status_code=404, detail="商品が見つかりません")
            if item["status"] == "sold_out": raise HTTPException(status_code=400, detail="売り切れています")
            
            cursor.execute("INSERT INTO purchases (item_id, buyer_id) VALUES (%s, %s)", (item_id, buyer_id))
            cursor.execute("UPDATE items SET status = 'sold_out' WHERE id = %s", (item_id,))
            connection.commit()
            return {"status": "success", "message": "商品の購入が完了しました！"}
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        connection.close()

@router.post("/api/items/{item_id}/like")
def toggle_like(item_id: int, data: dict):
    user_id = data.get("user_id")
    if not user_id: raise HTTPException(status_code=400, detail="user_idが必要です")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM likes WHERE user_id = %s AND item_id = %s", (user_id, item_id))
            if cursor.fetchone():
                cursor.execute("DELETE FROM likes WHERE user_id = %s AND item_id = %s", (user_id, item_id))
                like_status = "unliked"
            else:
                cursor.execute("INSERT INTO likes (user_id, item_id) VALUES (%s, %s)", (user_id, item_id))
                like_status = "liked"
            connection.commit()
            return {"status": "success", "like_status": like_status}
    finally:
        connection.close()

@router.get("/api/users/{user_id}/likes")
def get_user_likes(user_id: int):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT i.*, COALESCE(i.seller_nickname, u.name, '名無しさん') AS seller_name, TRUE AS is_liked
                FROM likes l JOIN items i ON l.item_id = i.id
                LEFT JOIN users u ON i.seller_id = u.id WHERE l.user_id = %s ORDER BY l.created_at DESC
            """
            cursor.execute(sql, (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()

@router.post("/api/items/{item_id}/view")
def record_item_view(item_id: int, data: dict):
    user_id = data.get("user_id")
    if not user_id: raise HTTPException(status_code=400, detail="user_idが必要です")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO item_views (user_id, item_id) VALUES (%s, %s)", (user_id, item_id))
            connection.commit()
            return {"status": "success"}
    finally:
        connection.close()

@router.get("/api/users/{user_id}/views")
def get_user_views(user_id: int):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT i.*, COALESCE(i.seller_nickname, u.name, '名無しさん') AS seller_name
                FROM item_views v
                JOIN items i ON v.item_id = i.id
                LEFT JOIN users u ON i.seller_id = u.id
                WHERE v.user_id = %s
                ORDER BY v.id DESC
                LIMIT 20
            """
            cursor.execute(sql, (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()

@router.get("/api/users/{user_id}/purchases")
def get_user_purchases(user_id: int):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT i.*, COALESCE(i.seller_nickname, u.name, '名無しさん') AS seller_name
                FROM purchases p
                JOIN items i ON p.item_id = i.id
                LEFT JOIN users u ON i.seller_id = u.id
                WHERE p.buyer_id = %s
                ORDER BY p.id DESC
            """
            cursor.execute(sql, (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()

@router.get("/api/users/{user_id}/products")
def get_user_products(user_id: int):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT i.*, COALESCE(i.seller_nickname, '名無しさん') AS seller_name
                FROM items i
                WHERE i.seller_id = %s
                ORDER BY i.id DESC
            """
            cursor.execute(sql, (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()