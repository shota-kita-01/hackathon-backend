import os
import pymysql
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# ユーザー一覧取得 API（新しいテーブル構造に対応）
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


# 商品出品 API
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

# 商品一覧取得 API（ホーム画面用）
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


# 商品購入 API
@app.post("/api/items/{item_id}/purchase")
def purchase_item(item_id: int, buyer_data: dict):
    # buyer_data の中身: {"buyer_id": 1} などを想定
    buyer_id = buyer_data.get("buyer_id")
    if not buyer_id:
        raise HTTPException(status_code=400, detail="購入者のID（buyer_id）が必要です")
        
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 1. 商品がまだ存在し、かつ売り切れていないかチェック
            cursor.execute("SELECT status FROM items WHERE id = %s", (item_id,))
            item = cursor.fetchone()
            if not item:
                raise HTTPException(status_code=404, detail="商品が見つかりません")
            if item["status"] == "sold_out":
                raise HTTPException(status_code=400, detail="この商品は既に売り切れています")
            
            # 2. 購入履歴（purchases）テーブルに記録を追加
            sql_purchase = "INSERT INTO purchases (item_id, buyer_id) VALUES (%s, %s)"
            cursor.execute(sql_purchase, (item_id, buyer_id))
            
            # 3. 商品（items）テーブルのステータスを 'sold_out' に更新
            sql_update_item = "UPDATE items SET status = 'sold_out' WHERE id = %s"
            cursor.execute(sql_update_item, (item_id,))
            
            # 両方の処理が成功したら確定（コミット）する
            connection.commit()
            return {"status": "success", "message": "商品の購入が完了しました！"}
    except Exception as e:
        connection.rollback() # 万が一途中でエラーが起きたら、中途半端な状態にならないよう元に戻す
        raise e
    finally:
        connection.close()



# フロントから届くログインデータを受け止めるための型（Pydanticモデル）
class LoginData(BaseModel):
    firebase_uid: str
    name: str
    email: str

# Firebase認証連動・ログインAPI
@app.post("/api/auth/login")
def auth_login(data: LoginData):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 1. すでにこのFirebase UIDを持つユーザーがDBにいるかチェック
            cursor.execute("SELECT id FROM users WHERE firebase_uid = %s", (data.firebase_uid,))
            user = cursor.fetchone()
            
            if user:
                # 🌟 すでに登録済みのリピーターなら、MySQLの整数ID（例: 1）をそのまま返す
                return {"status": "success", "id": user["id"]}
            else:
                # 🌟 初めてアプリに登録したご新規さんなら、usersテーブルに新しいレコードを作る
                # （※メール＋パスワード認証の場合、最初はnameが空、またはemailの@より前などになるため、フロントから届いた名前をそのまま入れます）
                sql = "INSERT INTO users (name, email, firebase_uid) VALUES (%s, %s, %s)"
                cursor.execute(sql, (data.name, data.email, data.firebase_uid))
                connection.commit()
                
                # 今INSERTしたばかりの自動連番のID（例: 2）を取得して返す
                new_id = cursor.lastrowid
                return {"status": "success", "id": new_id}
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        connection.close()