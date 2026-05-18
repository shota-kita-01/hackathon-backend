import os
import pymysql
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
# 🆕 OpenAIライブラリのインポート
from openai import OpenAI

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🧠 OpenAIクライアントの初期設定
# Cloud Runの環境変数に「OPENAI_API_KEY」をセットしておくと自動で読み込まれます
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class UserRegister(BaseModel):
    name: str
    email: str
    password: str

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

@app.get("/")
def read_root():
    return {"message": "Hello from Cloud Run (Python) with OpenAI Integration!"}

@app.post("/api/register")
def register_user(user_data: UserRegister):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE email = %s", (user_data.email,))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="このメールアドレスは既に登録されています")
            
            sql = "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)"
            cursor.execute(sql, (user_data.name, user_data.email, user_data.password))
            connection.commit()
            return {"status": "success", "message": "ユーザー登録が完了しました！"}
    finally:
        connection.close()

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

@app.get("/api/items")
def get_items():
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT i.id, i.name, i.description, i.price, i.image_url, i.seller_id, i.status, u.name AS seller_name
                FROM items i LEFT JOIN users u ON i.seller_id = u.id ORDER BY i.id DESC
            """
            cursor.execute(sql)
            result = cursor.fetchall()
            return result
    finally:
        connection.close()

@app.post("/api/items/{item_id}/purchase")
def purchase_item(item_id: int, buyer_data: dict):
    buyer_id = buyer_data.get("buyer_id")
    if not buyer_id:
        raise HTTPException(status_code=400, detail="購入者のIDが必要です")
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

class LoginData(BaseModel):
    firebase_uid: str
    name: str
    email: str

@app.post("/api/auth/login")
def auth_login(data: LoginData):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM users WHERE firebase_uid = %s", (data.firebase_uid,))
            user = cursor.fetchone()
            if user: return {"status": "success", "id": user["id"]}
            
            cursor.execute("SELECT id FROM users WHERE email = %s", (data.email,))
            existing_user = cursor.fetchone()
            if existing_user:
                cursor.execute("UPDATE users SET firebase_uid = %s WHERE id = %s", (data.firebase_uid, existing_user["id"]))
                connection.commit()
                return {"status": "success", "id": existing_user["id"]}
            
            cursor.execute("INSERT INTO users (name, email, firebase_uid, password_hash) VALUES (%s, %s, %s, %s)", (data.name, data.email, data.firebase_uid, ""))
            connection.commit()
            return {"status": "success", "id": cursor.lastrowid}
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        connection.close()


# 🚀 【完全クリーン版】メルカリデータ1000件インポートAPI
@app.get("/api/admin/import-merrec")
def import_merrec_to_cloud_sql():
    print("⏳ クラウド上で1000件のデータをピュアな状態でインポート中...")
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
        df_sampled = df.head(30000)
        unique_items = df_sampled.drop_duplicates(subset=['item_id']).copy()

        connection = get_db_connection()
        inserted_count = 0
        
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("DELETE FROM items WHERE seller_id = 1")

            img_idx = 0
            for _, row in unique_items.head(1000).iterrows():
                raw_brand = str(row['brand_name']).strip() if pd.notna(row['brand_name']) else ""
                brand = raw_brand if raw_brand and raw_brand.lower() != "nan" else "ノーブランド"
                
                c0 = str(row['c0_name'])
                c1 = str(row['c1_name'])
                c2 = str(row['c2_name']) if pd.notna(row['c2_name']) else ""
                
                # 🌟 付け焼き刃な日本語ハックを全削除！英語の記述のまま100%ピュアに保存
                description = f"【カテゴリ】{c0} > {c1} > {c2}\n【ブランド】{brand}\n【商品の状態】{row['item_condition_name']}"
                
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
        return {"status": "success", "message": f"🎉 1000件のクリーンな英語データをインポート完了しました！"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


class RecommendRequest(BaseModel):
    user_id: int
    mood_text: str
    mode: str

# 🧠 【OpenAI 概念拡張 × Two-Tower行列演算】最強のクロスオーバー推薦API
@app.post("/api/recommend")
def get_recommendations(req: RecommendRequest):
    connection = get_db_connection()
    try:
        # 🌟 1. ユーザーの曖昧な気分入力を、OpenAI (gpt-4o-mini) で英語の核心キーワード群へ超拡張！
        english_keywords = ""
        if req.mode in ["mood", "both"] and req.mood_text.strip():
            try:
                # 高速・格安・高性能な gpt-4o-mini を採用
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a semantic processing engine for a fashion e-commerce search.\n"
                                "Analyze the user's input request (in Japanese or English) and convert it into a "
                                "space-separated list of optimal English search keywords, categories, and attributes.\n"
                                "Focus heavily on extracting gender (men, women), item types (sneakers, shoes, bag, necklace, dress, top, skirt), "
                                "materials, brands, and style vibes.\n"
                                "Output ONLY the English keywords separated by spaces. Do not include any explanations, introduction, markdown, or punctuation."
                            )
                        },
                        {
                            "role": "user",
                            "content": f'User input: "{req.mood_text}"'
                        }
                    ],
                    temperature=0.3,
                )
                english_keywords = response.choices[0].message.content.strip().lower()
                print(f"🧠 [OpenAI LLM Expansion]: {req.mood_text} ➔ {english_keywords}")
            except Exception as openai_err:
                print(f"⚠️ OpenAI API Error, falling back to raw input: {openai_err}")
                english_keywords = req.mood_text

        with connection.cursor() as cursor:
            # 全商品（1000件）を取得
            cursor.execute("SELECT id, name, description, price, image_url, seller_id, status FROM items")
            items = cursor.fetchall()
            if not items: return []

            # 過去の購入履歴を取得
            cursor.execute("""
                SELECT i.name, i.description FROM purchases p
                JOIN items i ON p.item_id = i.id WHERE p.buyer_id = %s
            """, (req.user_id,))
            past_purchases = cursor.fetchall()
            history_text = " ".join([f"{p['name']} {p['description']}" for p in past_purchases])

            # 2. 選択されたモードに応じて User Tower のテキスト（英語の同一意味空間）を動的にスイッチ
            if req.mode == "mood":
                combined_user_text = english_keywords
            elif req.mode == "history":
                combined_user_text = history_text
            else: # "both" (ハイブリッド)
                combined_user_text = f"{english_keywords} {history_text}".strip()

            if not combined_user_text:
                return items[:10]

            # 3. 100%ピュアな英語テキスト同士のベクトル空間で、コサイン類似度（内積）を一括並列計算！
            item_texts = [f"{item['name']} {item['description']}" for item in items]
            all_texts = item_texts + [combined_user_text]

            # 英語同士の比較のため、標準的な英単語用TF-IDFモデルに回帰（数理的安定度が最大化）
            vectorizer = TfidfVectorizer(stop_words='english')
            tfidf_matrix = vectorizer.fit_transform(all_texts)

            item_vectors = tfidf_matrix[:-1]
            user_vector = tfidf_matrix[-1]

            similarities = cosine_similarity(user_vector, item_vectors).flatten()

            for idx, item in enumerate(items):
                item["score"] = float(similarities[idx])

            recommended_items = sorted(items, key=lambda x: x["score"], reverse=True)
            return recommended_items[:10]
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        connection.close()