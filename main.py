import os
import pymysql
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

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
            cursor.execute("SELECT id, name, email FROM users")
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


# 商品出品 API
@app.post("/api/items")
def create_item(item_data: dict):
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
            sql = """
                SELECT 
                    i.id, 
                    i.name, 
                    i.description, 
                    i.price, 
                    i.image_url, 
                    i.seller_id, 
                    i.status,
                    u.name AS seller_name
                FROM items i
                LEFT JOIN users u ON i.seller_id = u.id
                ORDER BY i.id DESC
            """
            cursor.execute(sql)
            result = cursor.fetchall()
            return result
    finally:
        connection.close()


# 商品購入 API
@app.post("/api/items/{item_id}/purchase")
def purchase_item(item_id: int, buyer_data: dict):
    buyer_id = buyer_data.get("buyer_id")
    if not buyer_id:
        raise HTTPException(status_code=400, detail="購入者のID（buyer_id）が必要です")
        
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT status FROM items WHERE id = %s", (item_id,))
            item = cursor.fetchone()
            if not item:
                raise HTTPException(status_code=404, detail="商品が見つかりません")
            if item["status"] == "sold_out":
                raise HTTPException(status_code=400, detail="この商品は既に売り切れています")
            
            sql_purchase = "INSERT INTO purchases (item_id, buyer_id) VALUES (%s, %s)"
            cursor.execute(sql_purchase, (item_id, buyer_id))
            
            sql_update_item = "UPDATE items SET status = 'sold_out' WHERE id = %s"
            cursor.execute(sql_update_item, (item_id,))
            
            connection.commit()
            return {"status": "success", "message": "商品の購入が完了しました！"}
    except Exception as e:
        connection.rollback()
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
            cursor.execute("SELECT id FROM users WHERE firebase_uid = %s", (data.firebase_uid,))
            user = cursor.fetchone()
            
            if user:
                return {"status": "success", "id": user["id"]}
            
            cursor.execute("SELECT id FROM users WHERE email = %s", (data.email,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                update_sql = "UPDATE users SET firebase_uid = %s WHERE id = %s"
                cursor.execute(update_sql, (data.firebase_uid, existing_user["id"]))
                connection.commit()
                return {"status": "success", "id": existing_user["id"]}
            
            sql = "INSERT INTO users (name, email, firebase_uid, password_hash) VALUES (%s, %s, %s, %s)"
            cursor.execute(sql, (data.name, data.email, data.firebase_uid, ""))
            connection.commit()
            
            new_id = cursor.lastrowid
            return {"status": "success", "id": new_id}
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        connection.close()


# 🚀 【1000件大増量・日本語検索ハック対応版】メルカリデータインポートAPI
@app.get("/api/admin/import-merrec")
def import_merrec_to_cloud_sql():
    print("⏳ クラウド上で1000件のデータを高度加工中...")
    
    try:
        preset_images = [
            "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?w=600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1583391733956-3750e0ff4e8b?w=600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1544816155-12df9643f363?w=600&auto=format&fit=crop",
            "https://images.unsplash.com/photo-1608231387042-66d1773070a5?w=600&auto=format&fit=crop"
        ]

        url = "https://huggingface.co/datasets/mercari-us/merrec/resolve/main/20230501/000000000000.parquet"
        df = pd.read_parquet(url, engine="pyarrow")
        df_sampled = df.head(30000) # 1000件のユニークデータを確保するため多めにロード
        unique_items = df_sampled.drop_duplicates(subset=['item_id']).copy()

        connection = get_db_connection()
        inserted_count = 0
        
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("DELETE FROM items WHERE seller_id = 1")

            img_idx = 0
            # 🌟 100件から1000件の大ボリュームへ増量！
            for _, row in unique_items.head(1000).iterrows():
                raw_brand = str(row['brand_name']).strip() if pd.notna(row['brand_name']) else ""
                brand = raw_brand if raw_brand and raw_brand.lower() != "nan" else "ノーブランド"
                
                c0 = str(row['c0_name'])
                c1 = str(row['c1_name'])
                c2 = row['c2_name'] if pd.notna(row['c2_name']) else ""
                
                # 🆕 【日本語化ハック】英語テキストから日本語の検索用ハッシュタグを自動錬成
                ja_tags = []
                text_to_scan = f"{row['name']} {c0} {c1} {c2} {brand}".lower()
                if "gold" in text_to_scan: ja_tags.append("#ゴールド #金")
                if "silver" in text_to_scan: ja_tags.append("#シルバー #銀")
                if "necklace" in text_to_scan: ja_tags.append("#ネックレス #首飾り")
                if "ring" in text_to_scan: ja_tags.append("#リング #指輪")
                if "earring" in text_to_scan: ja_tags.append("#イヤリング #ピアス")
                if "bag" in text_to_scan or "tote" in text_to_scan: ja_tags.append("#バッグ #カバン")
                if "shoes" in text_to_scan or "sneaker" in text_to_scan: ja_tags.append("#スニーカー #靴")
                if "women" in text_to_scan: ja_tags.append("#レディース #女性用")
                if "men" in text_to_scan: ja_tags.append("#メンズ #男性用")
                if "vintage" in text_to_scan: ja_tags.append("#ビンテージ #古着")
                
                ja_tags_str = " ".join(ja_tags)
                description = f"【カテゴリ】{c0} > {c1} > {c2}\n【ブランド】{brand}\n【商品の状態】{row['item_condition_name']}\n{ja_tags_str}"
                
                sql = """
                    INSERT INTO items (name, description, price, image_url, seller_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                
                raw_price = row['price'] if pd.notna(row['price']) else 10
                price = int(raw_price * 150) if raw_price > 0 else 1500
                
                image_url = preset_images[img_idx % len(preset_images)]
                img_idx += 1
                
                cursor.execute(sql, (row['name'], description, price, image_url, 1, "on_sale"))
                inserted_count += 1
                
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
            connection.commit()
            
        connection.close()
        return {"status": "success", "message": f"🎉 日本語対応ハック＆1000件の大増量インポートが完了しました！"}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
    

# 🆕 フロントエンドの「モード選択トグル」を乗せる注文票ルール
class RecommendRequest(BaseModel):
    user_id: int
    mood_text: str
    mode: str # "mood" (気分重視), "history" (過去重視), "both" (ミックス)

# 🧠 【Two-Tower進化版】気分・履歴をフロント側から自在に制御する推薦API
@app.post("/api/recommend")
def get_recommendations(req: RecommendRequest):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 1. 全商品（1000件）を取得
            cursor.execute("SELECT id, name, description, price, image_url, seller_id, status FROM items")
            items = cursor.fetchall()
            
            if not items:
                return []

            # 2. 過去の購入履歴を取得
            cursor.execute("""
                SELECT i.name, i.description 
                FROM purchases p
                JOIN items i ON p.item_id = i.id
                WHERE p.buyer_id = %s
            """, (req.user_id,))
            past_purchases = cursor.fetchall()
            history_text = " ".join([f"{p['name']} {p['description']}" for p in past_purchases])

            # 🆕 3. フロントからの指示（mode）に応じて計算元のUserテキストを数理スイッチ！
            if req.mode == "mood":
                combined_user_text = req.mood_text
            elif req.mode == "history":
                combined_user_text = history_text
            else: # "both" (ミックス)
                combined_user_text = f"{req.mood_text} {history_text}".strip()

            # もし気分も履歴も完全に空っぽな場合は、取り急ぎ先頭10件を返す
            if not combined_user_text:
                return items[:10]

            # 4. 高次元ベクトル空間モデルの構築
            item_texts = [f"{item['name']} {item['description']}" for item in items]
            all_texts = item_texts + [combined_user_text]

            # 🆕 日本語のハッシュタグ（漢字・カタカナ1文字から）も英語も両方数理的に分割できるよう正規表現パターンを最適化！
            vectorizer = TfidfVectorizer(token_pattern=r'(?u)\b\w+\b', stop_words='english')
            tfidf_matrix = vectorizer.fit_transform(all_texts)

            item_vectors = tfidf_matrix[:-1]
            user_vector = tfidf_matrix[-1]

            # 5. 行列の並列内積計算によるコサイン類似度一括算出
            similarities = cosine_similarity(user_vector, item_vectors).flatten()

            # 6. スコア付与と高効率ソート
            for idx, item in enumerate(items):
                item["score"] = float(similarities[idx])

            recommended_items = sorted(items, key=lambda x: x["score"], reverse=True)
            return recommended_items[:10]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()