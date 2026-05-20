from fastapi import APIRouter, HTTPException
from db import get_db_connection, client

router = APIRouter()

# 🧠 【機能4：自動商品説明生成API】
@router.post("/api/ai/suggest-description")
def suggest_description(data: dict):
    item_name = data.get("name")
    if not item_name: raise HTTPException(status_code=400, detail="商品名が必要です")
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert copywriter for a global fashion e-commerce marketplace.\n"
                        "Generate a professional, appealing, and clean English product description based on the product name provided.\n"
                        "Include sections like [Overview], [Features], and [Styling Tips] if applicable.\n"
                        "Output ONLY the generated description. No markdown block wrappers (like ```), no conversational text."
                    )
                },
                {"role": "user", "content": f"Product Name: {item_name}"}
            ],
            temperature=0.7,
        )
        return {"status": "success", "description": response.choices[0].message.content.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 🧠 【機能5：AI価格査定API】
@router.post("/api/ai/suggest-price")
def suggest_price(data: dict):
    item_name = data.get("name")
    if not item_name: raise HTTPException(status_code=400, detail="商品名が必要です")
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an AI price valuation engine for a fashion marketplace.\n"
                        "Analyze the given product name and estimate its fair market value in US Dollars (USD).\n"
                        "Output ONLY a single integer representing the dollar amount. Do not include '$', text, or any punctuation.\n"
                        "Example: if you think it's worth $45, output '45'."
                    )
                },
                {"role": "user", "content": f"Product Name: {item_name}"}
            ],
            temperature=0.3,
        )
        usd_price = int(response.choices[0].message.content.strip())
        # デモ用に1ドル=150円換算の日本円にしてフロントに返す
        jpy_price = usd_price * 150
        return {"status": "success", "suggested_price": jpy_price}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 🛍️ 【商品新規出品API（ニックネーム・発送日対応版）】
@router.post("/api/items")
def create_item(item_data: dict):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 🆕 SQL文に seller_nickname と shipping_days を追加
            # ※まだDBのマイグレーション（カラム追加）が終わっていない場合でも
            # フロント側からのデータを受け取れるようにしています
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
                item_data.get("seller_nickname", "名無しさん"), # 🆕 ニックネームを追加（デフォルト値設定）
                item_data.get("shipping_days", "1〜2日で発送") # 🆕 発送日を追加（デフォルト値設定）
            ))
            connection.commit()
            return {"status": "success", "message": "商品が出品されました！"}
    finally:
        connection.close()


# 🛒 【商品一覧取得API（ニックネーム・発送日取得版）】
@router.get("/api/items")
def get_items():
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 🆕 SELECT句に i.seller_nickname, i.shipping_days を追加
            sql = """
                SELECT i.id, i.name, i.description, i.price, i.image_url, i.seller_id, i.tags, i.status, 
                       COALESCE(i.seller_nickname, u.name, '名無しさん') AS seller_name, i.shipping_days
                FROM items i LEFT JOIN users u ON i.seller_id = u.id ORDER BY i.id DESC
            """
            cursor.execute(sql)
            return cursor.fetchall()
    finally:
        connection.close()


# 🛍️ 【商品購入処理API】
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


# ❤️ 【いいね登録・解除トグルAPI】
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


# ❤️ 【いいねした商品一覧取得API】
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


# 👁️ 【閲覧履歴記録API】
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


# ユーザーの閲覧履歴（最新20件）を取得するAPI
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

# ユーザーの購入履歴を取得するAPI
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

# 🆕 【追加：ユーザー個人の出品履歴を取得するAPI】
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