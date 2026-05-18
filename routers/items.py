from fastapi import APIRouter, HTTPException
from db import get_db_connection

router = APIRouter()

@router.post("/api/items")
def create_item(item_data: dict):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO items (name, description, price, image_url, seller_id, status)
                VALUES (%s, %s, %s, %s, %s, 'on_sale')
            """
            cursor.execute(sql, (
                item_data.get("name"), item_data.get("description"),
                item_data.get("price"), item_data.get("image_url"), item_data.get("seller_id")
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
            sql = """
                SELECT i.id, i.name, i.description, i.price, i.image_url, i.seller_id, i.status, u.name AS seller_name
                FROM items i LEFT JOIN users u ON i.seller_id = u.id ORDER BY i.id DESC
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
                SELECT i.*, u.name AS seller_name, TRUE AS is_liked
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