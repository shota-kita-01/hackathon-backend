from fastapi import APIRouter, HTTPException
from google.genai import types
from db import get_db_connection, client
import uuid

router = APIRouter()

# ===================================================
# 📦 1. AIカタログ商品一覧 ＆ 詳細API（Amazon完全特化）
# ===================================================

@router.get("/api/products")
def get_all_products():
    """Amazonの特権データをフリマと同じ綺麗な構造で一括取得"""
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
                    'Amazon公式' AS seller_name, 
                    '1〜2日で発送' AS shipping_days 
                FROM products;
            """
            cursor.execute(sql)
            return {"status": "success", "data": cursor.fetchall()}
    finally:
        connection.close()


@router.get("/api/products/{asin}")
def get_product_detail(asin: str):
    """詳細画面用データ取得"""
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
                    'Amazon公式' AS seller_name,
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
# 🛒 2. 既存のフリマ用URL（/api/items）の形骸化（中身はAmazon）
# ===================================================

@router.get("/api/items")
def get_items():
    """フロントの fetchAllItems() がここを叩きにきてもAmazonのデータを返して安全に保つ"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    id AS id, 
                    name AS name, 
                    price AS price, 
                    ai_category AS tags, 
                    description AS description, 
                    image_url AS image_url, 
                    status AS status, 
                    'Amazon公式' AS seller_name, 
                    '1〜2日で発送' AS shipping_days 
                FROM products
                ORDER BY id DESC;
            """
            cursor.execute(sql)
            return cursor.fetchall()
    finally:
        connection.close()


@router.post("/api/items")
def create_item(item_data: dict):
    """フロントからもし新規出品（擬似出品）されたら、AmazonカタログにダミーASINで追加する"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO products (asin, name, description, price, ai_category, image_url, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'on_sale')
            """
            dummy_asin = f"CUSTOM_{uuid.uuid4().hex[:8].upper()}"
            cursor.execute(sql, (
                dummy_asin,
                item_data.get("name"),
                item_data.get("description"),
                item_data.get("price"),
                item_data.get("tags", "カスタム"),
                item_data.get("image_url")
            ))
            connection.commit()
            return {"status": "success", "message": "Amazonカタログに商品が追加されました！"}
    finally:
        connection.close()


# ===================================================
# 🛍️ 3. 購入・いいね・履歴APIを「Amazonデータ（products）」へ完全最適化
# ===================================================

@router.post("/api/items/{item_id}/purchase")
def purchase_item(item_id: int, buyer_data: dict):
    """Amazon商品を本気で購入（SOLD OUT化）させる"""
    buyer_id = buyer_data.get("buyer_id")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 💡 productsテーブルを見にいくように修正！
            cursor.execute("SELECT status FROM products WHERE id = %s", (item_id,))
            product = cursor.fetchone()
            if not product: raise HTTPException(status_code=404, detail="商品が見つかりません")
            if product["status"] == "sold_out": raise HTTPException(status_code=400, detail="売り切れています")
            
            cursor.execute("INSERT INTO purchases (item_id, buyer_id) VALUES (%s, %s)", (item_id, buyer_id))
            cursor.execute("UPDATE products SET status = 'sold_out' WHERE id = %s", (item_id,))
            connection.commit()
            return {"status": "success", "message": "商品の購入が完了しました！"}
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        connection.close()


@router.post("/api/items/{item_id}/like")
def toggle_like(item_id: int, data: dict):
    """Amazon商品に対して『いいね』を登録・解除する"""
    user_id = data.get("user_id")
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
    """ユーザーが『いいね』したAmazon商品の一覧を取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    p.id AS id, p.asin AS asin, p.name AS name, p.price AS price, 
                    p.ai_category AS tags, p.description AS description, p.image_url AS image_url, 
                    p.status AS status, 'Amazon公式' AS seller_name, TRUE AS is_liked
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
    """Amazon商品の閲覧履歴を記録"""
    user_id = data.get("user_id")
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
    """Amazon商品の閲覧履歴（最新20件）を取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    p.id AS id, p.asin AS asin, p.name AS name, p.price AS price, 
                    p.ai_category AS tags, p.description AS description, p.image_url AS image_url, 
                    p.status AS status, 'Amazon公式' AS seller_name
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
    """Amazon商品の購入履歴を取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    p.id AS id, p.asin AS asin, p.name AS name, p.price AS price, 
                    p.ai_category AS tags, p.description AS description, p.image_url AS image_url, 
                    p.status AS status, 'Amazon公式' AS seller_name
                FROM purchases pur
                JOIN products p ON pur.item_id = p.id
                WHERE pur.buyer_id = %s
                ORDER BY pur.id DESC;
            """
            cursor.execute(sql, (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()


@router.get("/api/users/{user_id}/products")
def get_user_products(user_id: int):
    """個人出品の履歴タブ用（空配列を返却して画面のクラッシュを防ぐ）"""
    return []


# ===================================================
# 🧠 4. AI商品説明自動生成 ＆ 価格査定（完全維持）
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
        return {"status": "success", "suggested_price": usd_price * 150}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))