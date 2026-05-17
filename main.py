import os
import pymysql
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# --- 1. 画面から届くデータの形（注文票のルール）を定義 ---
class UserRegister(BaseModel):
    name: str
    email: str
    password: str

# --- 2. データベースへの接続設定 ---
def get_db_connection():
    user = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PWD")
    db_name = os.getenv("MYSQL_DATABASE")
    host_env = os.getenv("MYSQL_HOST", "")
    
    if host_env.startswith("unix("):
        socket_path = host_env.replace("unix(", "").rstrip(")")
        return pymysql.connect(
            user=user,
            password=password,
            database=db_name,
            unix_socket=socket_path,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    else:
        return pymysql.connect(
            host=host_env or "127.0.0.1",
            user=user,
            password=password,
            database=db_name,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

# --- 3. API（エンドポイント）の実装 ---

@app.get("/")
def read_root():
    return {"message": "Hello from Cloud Run (Python)!"}

# 【新機能】ユーザー登録 API
@app.post("/api/register")
def register_user(user_data: UserRegister):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 同じメールアドレスが既に登録されていないかチェック
            cursor.execute("SELECT id FROM users WHERE email = %s", (user_data.email,))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="このメールアドレスは既に登録されています")
            
            # 新しいユーザーをデータベースに保存
            # ※ハッカソンの初期実装のため、一旦プレーンテキストで保存（後からハッシュ化にトッピング可能！）
            sql = "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)"
            cursor.execute(sql, (user_data.name, user_data.email, user_data.password))
            connection.commit() # データベースの変更を確定させる
            
            return {"status": "success", "message": "ユーザー登録が完了しました！"}
    finally:
        connection.close()

# 【修正版】ユーザー一覧取得 API（新しいテーブル構造に対応）
@app.get("/api/users")
def get_users():
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 新しく作った「users」テーブルからデータを取ってくる
            cursor.execute("SELECT id, name, email FROM users")
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


# 【新機能】商品出品 API
@app.post("/api/items")
def create_item(item_data: dict):
    # item_data の中身: {"name": "...", "description": "...", "price": 1000, "image_url": "...", "seller_id": 1}
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO items (name, description, price, image_url, seller_id, status)
                VALUES (%s, %s, %s, %s, %s, 'on_sale')
            """
            cursor.execute(sql, (
                item_data.get("name"),
                item_data.get("description"),
                item_data.get("price"),
                item_data.get("image_url"),
                item_data.get("seller_id")
            ))
            connection.commit()
            return {"status": "success", "message": "商品が出品されました！"}
    finally:
        connection.close()

# 【新機能】商品一覧取得 API（ホーム画面用）
@app.get("/api/items")
def get_items():
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # まだ売れ残っている（on_sale）の商品を最新順に取得する
            cursor.execute("SELECT id, name, description, price, image_url, seller_id FROM items WHERE status = 'on_sale' ORDER BY id DESC")
            result = cursor.fetchall()
            return result
    finally:
        connection.close()