from fastapi import APIRouter, HTTPException
from google.genai import types
from db import get_db_connection, client
import json
import math
import time
import io
from google.cloud import storage 
import uuid

router = APIRouter()


# 1. 公式カタログ商品一覧 ＆ 詳細API

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
                    COALESCE(ai_image_url, image_url) AS image_url, 
                    status AS status,
                    '新品・未使用' AS item_condition, 
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
                    COALESCE(ai_image_url, image_url) AS image_url, 
                    status AS status,
                    '新品・未使用' AS item_condition, 
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


# 2. フリマ商品一覧 ＆ 自由出品API（ハイブリッド統合）

@router.get("/api/items")
def get_items():
    """
    公式データと一般出品を合流。
    💡ID衝突を防群するため、一般出品のIDに一律 100000 を加算してフロントへ出荷します。
    """
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                -- ① 初期配置のカタログデータ (IDはそのまま)
                SELECT 
                    id AS id, 
                    asin AS asin, 
                    name AS name, 
                    price AS price, 
                    ai_category AS tags, 
                    description AS description, 
                    COALESCE(ai_image_url, image_url) AS image_url,
                    status AS status, 
                    '新品・未使用' AS item_condition, 
                    '公式出品' AS seller_name, 
                    '1〜2日で発送' AS shipping_days,
                    NULL AS seller_id,
                    NULL AS seller_stance -- 💡 カタログデータ用にはNULLを補完して列数を合わせる
                FROM products
                
                UNION ALL
                
                -- ② ユーザーが出品したカスタムデータ (💡 id + 100000 で仮想空間化！)
                SELECT 
                    id + 100000 AS id, 
                    NULL AS asin, 
                    name AS name, 
                    price AS price, 
                    tags AS tags, 
                    description AS description, 
                    image_url AS image_url, 
                    status AS status,
                    item_condition AS item_condition, 
                    seller_nickname AS seller_name, 
                    shipping_days AS shipping_days,
                    seller_id AS seller_id,
                    seller_stance AS seller_stance 
                FROM items
                
                ORDER BY id DESC;
            """
            cursor.execute(sql)
            return cursor.fetchall()
    finally:
        connection.close()


@router.post("/api/items/check")
def check_item_safety(item_data: dict):
    """出品前にGeminiで商品が規約違反でないかリアルタイム審査するエンドポイント"""
    try:
        moderation_prompt = f"""あなたは日本の大手フリマアプリの、実用的でバランス感覚に優れたコンプライアンス審査官です。
以下の出品申請された商品の「商品名」と「商品説明」を精査し、**明らかに規約違反である明確な出品禁止物**（本物の武器、違法薬物、処方箋医薬品、偽ブランド品・スーパーコピー、詐欺・情報商材、成人向けコンテンツなど）に該当する場合のみ、不合格（is_safe: false）としてください。

商品名: {item_data.get("name")}
商品説明: {item_data.get("description")}

出力は、必ず以下のキーを持つJSONフォーマットのみとしてください。
{{
  "is_safe": true または false,
  "reason": "違反と判定した具体的な理由（日本語）。安全な場合は空文字にしてください。"
}}

【判定の超重要ルール（過剰検知の防止）】
1. 「早い者勝ち」「奇跡の入荷」「最高の一足」「極上のフィット感」といった、一般的なフリマで日常的に使われるマーケティング的・誇張的な売り文句は、明確な違反品（偽ブランド品や詐欺など）の確証がない限り、すべて「安全（is_safe: true）」と判定してください。表現が少し大げさという理由だけで不合格にしてはなりません。
2. 完全にアウトな犯罪・違法行為、あるいはプラットフォームの治安を崩壊させるような「真っ黒（ブラック）な商品」のみを狙い撃ちで弾いてください。

【厳格な掟】
プログラムで直接パースするため、前置きや解説テキストは1文字も含めてはなりません。
必ず最初の「{{」から始めて、最後の「}}」で美しく閉じてください。"""

        mod_res = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=moderation_prompt,
            config=types.GenerateContentConfig(
                temperature=0.0
            )
        )
        
        raw_text = mod_res.text.strip()
        
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_text = "\n".join(lines).strip()
        
        mod_data = json.loads(raw_text)
        return {
            "status": "success",
            "is_safe": mod_data.get("is_safe", True),
            "reason": mod_data.get("reason", "")
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"AI審査中にエラーが発生しました: {str(e)}"
        }


@router.post("/api/items")
def create_item(item_data: dict):
    """ユーザーが出品画面から入力した内容を、一般出品テーブル（items）へ格納 ＆ 潜在空間逆マッチングアラート"""
    item_name = item_data.get("name")
    item_description = item_data.get("description")
    raw_image_url = item_data.get("image_url")

    # 🛡️ 【ガチガチ判定ハック】フロントから "null" や "undefined" などの文字列が届いても確実に検知する
    is_empty_image = False
    if raw_image_url is None:
        is_empty_image = True
    elif isinstance(raw_image_url, str):
        clean_url = raw_image_url.strip().lower()
        if clean_url in ["", "null", "undefined", "none"]:
            is_empty_image = True

    image_url = raw_image_url

    if is_empty_image:
        print(f"[AI画像生成トリガー発動] 商品名: {item_name}")
        try:
            # 1. 日本語のコンテキストから英語プロンプトを錬金（これは既存のAI Studio経由のままでOK）
            prompt_alchemy = f"""
        Based on the following Japanese flea market product title and description, 
        generate a highly detailed and optimized English prompt for a text-to-image model (Imagen 3).

        【STRICT RULES】
        1. The main subject of the image MUST be the physical object explicitly stated in the "Title" below. 
           Do NOT be confused by poetic, abstract, or emotional marketing words in the "Description". 
           (e.g., If Title is "ヘッドホン", the image MUST be a physical pair of headphones, never anything else.)
        2. The prompt must describe a realistic marketplace photo of that item, neatly placed on a wooden table or clean carpet, natural lighting, looking like a real smartphone photo taken by a seller.
        3. Do not include any background talk or markdown, return only the prompt text.

        Title: {item_name}
        Description: {item_description}
        """
            
            prompt_res = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt_alchemy
            )
            imagen_prompt = prompt_res.text.strip()
            print(f"   ➔ 錬金されたプロンプト: {imagen_prompt}")

            # 🚀【Vertex AI専用クライアントの召喚】404エラーを完全に打破
            from google import genai
            vertex_client = genai.Client(
                vertexai=True,
                project="term9-shota-kita",
                location="us-central1"
            )

            # 2. Imagen 3 を召喚（AI Studioではなく、昨日実績のあったVertex AIのルートでスナイプ）
            imagen_res = vertex_client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=imagen_prompt,
                config=types.GenerateImagesConfig(  # 💡 sの付いた複数形で完全防弾化
                    number_of_images=1,
                    output_mime_type="image/png",
                    aspect_ratio="4:3"
                )
            )
            
            # 3. GCSバケットへ直接アップロード
            generated_image = imagen_res.generated_images[0]
            image_bytes = generated_image.image.image_bytes
            
            storage_client = storage.Client()
            bucket_name = "term9-shota-kita-images"
            bucket = storage_client.bucket(bucket_name)
            
            # 宇宙が滅びるまで衝突しない完全防弾ファイル名（タイムスタンプ + UUIDハッシュ）
            import uuid
            filename = f"products/user_generated_{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
            blob = bucket.blob(filename)
            
            blob.upload_from_file(io.BytesIO(image_bytes), content_type="image/png")
            
            # 最終的な公開URLで上書き
            image_url = f"https://storage.googleapis.com/{bucket_name}/{filename}"
            print(f"   ➔ AI画像生成・アップロード成功: {image_url}")
            
        except Exception as ai_img_err:
            # 💡 【重要】ハッカソンのCloud Runログ（Log Viewer）で何のエラーか一発で特定するためにログを強化！
            print(f"【AI画像生成コアエラー】内部で致命的なクラッシュが発生しました: {str(ai_img_err)}")
            import traceback
            traceback.print_exc()  # エラーの発生源（スタックトレース）をログに全吐き出しする
            
            # 安全弁として既存のダミー画像をセット
            image_url = "https://storage.googleapis.com/term9-shota-kita-images/products/generated_1.png"

    structured_text = f"""
    Product Characteristics:
    - Title: {item_name}
    - Category: {item_data.get("tags")}
    - Core Context: {item_description}
    """
    try:
        embed_res = client.models.embed_content(
            model="gemini-embedding-2",
            contents=structured_text,
            config=types.EmbedContentConfig(output_dimensionality=768)
        )
        embedding_vector = embed_res.embeddings[0].values
        embedding_json = json.dumps(embedding_vector)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"【AI空間配置エラー】ベクトルの生成に失敗しました: {str(e)}")

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO items (
                    name, description, price, min_acceptable_price, seller_stance, image_url, 
                    seller_id, tags, status, item_condition, seller_nickname, shipping_days, embedding
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'on_sale', %s, %s, %s, %s)
            """
            
            current_price = int(item_data.get("price", 0))
            min_price = item_data.get("min_acceptable_price")
            min_acceptable_price = int(min_price) if min_price else current_price
            seller_stance = item_data.get("seller_stance", "急いでいない")

            cursor.execute(sql, (
                item_name,
                item_description,
                current_price,
                min_acceptable_price,
                seller_stance,
                image_url,  
                item_data.get("seller_id"),
                item_data.get("tags", "一般出品"),
                item_data.get("item_condition", "目立った傷や汚れなし"),
                item_data.get("seller_nickname", "名無しさん"),
                item_data.get("shipping_days", "1〜2日で発送"),
                embedding_json
            ))

            new_item_raw_id = cursor.lastrowid
            new_item_hybrid_id = new_item_raw_id + 100000

            # 【潜在空間逆マッチング】全ユーザーの入荷待ちベクトルと高速内積計算
            cursor.execute("SELECT user_id, keywords, embedding FROM wishlists")
            all_wishes = cursor.fetchall()

            for wish in all_wishes:
                try:
                    wish_vector = json.loads(wish["embedding"])
                    dot = sum(a * b for a, b in zip(embedding_vector, wish_vector))
                    norm1 = math.sqrt(sum(a * a for a in embedding_vector))
                    norm2 = math.sqrt(sum(b * b for b in wish_vector))
                    sim = dot / (norm1 * norm2 + 1e-9)

                    if sim >= 0.50:
                        match_percent = round(sim * 100, 1)
                        cursor.execute("""
                            INSERT INTO notifications (user_id, title, message, item_id) VALUES (%s, %s, %s, %s)
                        """, (wish["user_id"], "✨ 脳内イメージにマッチする商品が入荷しました！", 
                              f"入荷待ち登録「{wish['keywords']}」に {match_percent}% 一致する「{item_data.get('name')}」が出品されました！", new_item_hybrid_id))
                except Exception as wish_err:
                    print(f"マッチング演算スキップ: {wish_err}")

            connection.commit()
            return {"status": "success", "message": "商品が出品されました！"}
    finally:
        connection.close()


@router.get("/api/users/{user_id}/products")
def get_user_products(user_id: int):
    """マイページの出品一覧。ここも仮想ID空間（+100000）に合わせて同期"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    id + 100000 AS id, 
                    name AS name, 
                    price AS price, 
                    tags AS tags, 
                    description AS description, 
                    image_url AS image_url, 
                    status AS status,
                    item_condition AS item_condition, 
                    seller_nickname AS seller_name, 
                    shipping_days AS shipping_days,
                    seller_id AS seller_id
                FROM items
                WHERE seller_id = %s
                ORDER BY id DESC;
            """
            cursor.execute(sql, (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()



# 検索キーワード履歴 記録 ＆ 取得API（変更なし）

@router.post("/api/users/{user_id}/keywords")
def record_search_keyword(user_id: int, data: dict):
    keyword = data.get("keyword")
    if not keyword or not keyword.strip():
        return {"status": "skipped", "message": "空のキーワードです"}
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute("INSERT INTO search_keywords (user_id, keyword) VALUES (%s, %s)", (user_id, keyword.strip()))
                connection.commit()
                return {"status": "success"}
            except Exception as e:
                return {"status": "skipped"}
    finally:
        connection.close()


@router.get("/api/users/{user_id}/keywords")
def get_search_keywords(user_id: int):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute("SELECT keyword FROM search_keywords WHERE user_id = %s ORDER BY id DESC LIMIT 15", (user_id,))
                return cursor.fetchall()
            except Exception as e:
                return []
    finally:
        connection.close()



#  購入・いいね・履歴API

@router.post("/api/items/{item_id}/purchase")
def purchase_item(item_id: int, buyer_data: dict):
    """購入時に取引管理（transactions）レコード ＆ 出品者への通知（または公式Bot初期メッセージ）を同時自動生成"""
    buyer_id = buyer_data.get("buyer_id")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            seller_id, product_id, db_item_id, item_name = None, None, None, ""

            if item_id >= 100000:
                raw_id = item_id - 100000
                db_item_id = raw_id
                cursor.execute("SELECT seller_id, status, name FROM items WHERE id = %s", (raw_id,))
                item = cursor.fetchone()
                if not item: raise HTTPException(status_code=404, detail="商品が見つかりません")
                if item["status"] == "sold_out": raise HTTPException(status_code=400, detail="売り切れています")
                seller_id, item_name = item["seller_id"], item["name"]
                cursor.execute("UPDATE items SET status = 'sold_out' WHERE id = %s", (raw_id,))
            else:
                product_id = item_id
                cursor.execute("SELECT status, name FROM products WHERE id = %s", (item_id,))
                product = cursor.fetchone()
                if not product: raise HTTPException(status_code=404, detail="商品が見つかりません")
                if product["status"] == "sold_out": raise HTTPException(status_code=400, detail="売り切れています")
                item_name = product["name"]
                cursor.execute("UPDATE products SET status = 'sold_out' WHERE id = %s", (item_id,))
            
            # ① 既存の購入ログ
            cursor.execute("SET FOREIGN_KEY_CHECKS=0;")
            cursor.execute("INSERT INTO purchases (item_id, buyer_id) VALUES (%s, %s)", (item_id, buyer_id))
            
            # ② 取引進行管理レコードの自動生成
            tx_sql = "INSERT INTO transactions (item_id, product_id, buyer_id, seller_id, status) VALUES (%s, %s, %s, %s, 'shipping_pending')"
            cursor.execute(tx_sql, (db_item_id, product_id, buyer_id, seller_id))
            tx_id = cursor.lastrowid
            
            # ③ 出品条件に応じた通知 ＆ メッセージの自動分岐処理
            if seller_id:
                # 一般出品：実在する出品者へ購入通知を送る
                cursor.execute("""
                    INSERT INTO notifications (user_id, title, message, item_id) VALUES (%s, %s, %s, %s)
                """, (seller_id, "🎉 商品が購入されました！", f"出品した「{item_name}」が購入されました。発送手続きを進めてください。", item_id))
            else:
                # 公式カタログ品：やり取り先がいないため、システムBot(sender_id=0)から安心アナウンス
                bot_msg = "🤖 ご購入ありがとうございます！本商品は公式カタログ品のため、出品者とのやり取りは不要です。倉庫より自動発送されますので、到着まで今しばらくお待ちください。"
                cursor.execute("""
                    INSERT INTO transaction_messages (transaction_id, sender_id, message) 
                    VALUES (%s, 0, %s)
                """, (tx_id, bot_msg))
            
            cursor.execute("SET FOREIGN_KEY_CHECKS=1;")
            connection.commit()
            return {"status": "success", "message": "購入が完了しました！", "transaction_id": tx_id}
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        connection.close()

        
@router.post("/api/items/{item_id}/like")
def toggle_like(item_id: int, data: dict):
    """【改修】10万以上のIDへのいいねインサート時、外部キーチェックを一時スルー"""
    user_id = data.get("user_id")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM likes WHERE user_id = %s AND item_id = %s", (user_id, item_id))
            if cursor.fetchone():
                cursor.execute("DELETE FROM likes WHERE user_id = %s AND item_id = %s", (user_id, item_id))
                like_status = "unliked"
            else:
                # 💡 いいねインサート時の外部キーチェックを一時スルー
                cursor.execute("SET FOREIGN_KEY_CHECKS=0;")
                cursor.execute("INSERT INTO likes (user_id, item_id) VALUES (%s, %s)", (user_id, item_id))
                cursor.execute("SET FOREIGN_KEY_CHECKS=1;")
                like_status = "liked"
                
            connection.commit()
            return {"status": "success", "like_status": like_status}
    finally:
        connection.close()


@router.get("/api/users/{user_id}/likes")
def get_user_likes(user_id: int):
    """マイページのいいね一覧を、公式と一般出品のハイブリッド縦積み構造へ拡張"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                -- ① 公式データのいいね
                SELECT 
                    p.id AS id, p.asin AS asin, p.name AS name, p.price AS price, 
                    p.ai_category AS tags, p.description AS description, COALESCE(p.ai_image_url, p.image_url) AS image_url, 
                    p.status AS status, '新品・未使用' AS item_condition, '公式出品' AS seller_name, TRUE AS is_liked, l.id AS like_log_id
                FROM likes l 
                JOIN products p ON l.item_id = p.id
                WHERE l.user_id = %s AND l.item_id < 100000
                
                UNION ALL
                
                -- ② 一般ユーザー出品データのいいね (IDを10万の仮想空間に戻す)
                SELECT 
                    i.id + 100000 AS id, NULL AS asin, i.name AS name, i.price AS price, 
                    i.tags AS tags, i.description AS description, i.image_url AS image_url, 
                    i.status AS status, i.item_condition AS item_condition, i.seller_nickname AS seller_name, TRUE AS is_liked, l.id AS like_log_id
                FROM likes l 
                JOIN items i ON (l.item_id - 100000) = i.id
                WHERE l.user_id = %s AND l.item_id >= 100000
                
                ORDER BY like_log_id DESC;
            """
            cursor.execute(sql, (user_id, user_id))
            return cursor.fetchall()
    finally:
        connection.close()


@router.post("/api/items/{item_id}/view")
def record_item_view(item_id: int, data: dict):
    """【改修】閲覧ログへのインサート時、外部キーチェックを一時スルーして500クラッシュを完全防御"""
    user_id = data.get("user_id")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS=0;")
            cursor.execute("INSERT INTO item_views (user_id, item_id) VALUES (%s, %s)", (user_id, item_id))
            cursor.execute("SET FOREIGN_KEY_CHECKS=1;")
            
            connection.commit()
            return {"status": "success"}
    finally:
        connection.close()


@router.get("/api/users/{user_id}/views")
def get_user_views(user_id: int):
    """最近チェックした履歴。公式とフリマデータをメモリに干渉させずに綺麗に合流"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT id, asin, name, price, tags, description, image_url, status, item_condition, seller_name
                FROM (
                    SELECT p.id AS id, p.asin AS asin, p.name AS name, p.price AS price, 
                           p.ai_category AS tags, p.description AS description, COALESCE(p.ai_image_url, p.image_url) AS image_url, 
                           p.status AS status, '新品・未使用' AS item_condition, '公式出品' AS seller_name,
                           MAX(v.id) as max_v_id
                    FROM item_views v JOIN products p ON v.item_id = p.id
                    WHERE v.user_id = %s AND v.item_id < 100000
                    GROUP BY p.id

                    UNION ALL

                    SELECT i.id + 100000 AS id, NULL AS asin, i.name AS name, i.price AS price, 
                           i.tags AS tags, i.description AS description, i.image_url AS image_url, 
                           i.status AS status, i.item_condition AS item_condition, i.seller_nickname AS seller_name,
                           MAX(v.id) as max_v_id
                    FROM item_views v JOIN items i ON (v.item_id - 100000) = i.id
                    WHERE v.user_id = %s AND v.item_id >= 100000
                    GROUP BY i.id
                ) as hybrid_views
                ORDER BY max_v_id DESC
                LIMIT 50;
            """
            cursor.execute(sql, (user_id, user_id))
            return cursor.fetchall()
    finally:
        connection.close()


@router.get("/api/users/{user_id}/purchases")
def get_user_purchases(user_id: int):
    """マイページの購入履歴。公式カタログ品、一般出品の双方を美しく同時レンダリング"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT p.id AS id, p.asin AS asin, p.name AS name, p.price AS price, 
                       p.ai_category AS tags, p.description AS description, COALESCE(p.ai_image_url, p.image_url) AS image_url, 
                       p.status AS status, '新品・未使用' AS item_condition, '公式出品' AS seller_name, pur.id as pur_id
                FROM purchases pur JOIN products p ON pur.item_id = p.id
                WHERE pur.buyer_id = %s AND pur.item_id < 100000
                
                UNION ALL
                
                SELECT i.id + 100000 AS id, NULL AS asin, i.name AS name, i.price AS price, 
                       i.tags AS tags, i.description AS description, i.image_url AS image_url, 
                       i.status AS status, i.item_condition AS item_condition, i.seller_nickname AS seller_name, pur.id as pur_id
                FROM purchases pur JOIN items i ON (pur.item_id - 100000) = i.id
                WHERE pur.buyer_id = %s AND pur.item_id >= 100000
                
                ORDER BY pur_id DESC;
            """
            cursor.execute(sql, (user_id, user_id))
            return cursor.fetchall()
    finally:
        connection.close()


# 4. AI商品説明自動生成 ＆ 価格査定

@router.post("/api/ai/suggest-description")
def suggest_description(data: dict):
    item_name = data.get("name")
    if not item_name: 
        raise HTTPException(status_code=400, detail="商品名が必要です")
    try:
        prompt = f"""あなたは日本の大人気フリマアプリ（メルカリなど）でクリーンに月商100万円を売り上げる、購入者から圧倒的信頼を得ている伝説のトップセラーです。
ユーザーが入力した商品名をもとに、購入者の物欲を刺激しつつも、規約違反にならない誠実で「そのままコピペして使える完成された商品説明文」を1つだけ作成してください。

【絶対に守るべき鉄の掟】
1. 「〇〇の説明文ですね！」などの前置き、挨拶、終わりの会話文は、1文字とも出力しないでください。
2. 「パターン1」「パターン2」などの複数提案や、キャッチコピーの箇条書きは絶対に禁止です。最初から最高の一着としての文章を1パターンだけ作成してください。
3. 出力するテキストは、フリマの「商品説明欄にそのまま貼り付けられる本文」のみとしてください。
4. 過大広告や偽ブランドの表示などは絶対にしないでください。
5. 「奇跡」「運命」「最高峰」「一級品」「早い者勝ち」といった表現は含めても構いませんが、購入を過度に煽る誇張表現を多用しないでください。
6. 文字数は200字程度とし、無駄に長く、冗長になることは避けてください。

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
    item_category = data.get("tags")            
    item_condition = data.get("item_condition")  

    if not item_name or not item_description or not item_category or not item_condition:
        raise HTTPException(
            status_code=400, 
            detail="【AI査定エラー】商品名、商品説明、出品ジャンル、商品の状態をすべて入力・選択してから、もう一度AI価格査定を押してください！"
        )
        
    try:
        prompt = f"""あなたは日本のフリマ市場（メルカリやヤフオクなど）の相場・価格決定メカニズムを完璧にハックしている超一流のAI査定士です。
以下の4つの情報をもとに、現在の日本のリアルなセカンドハンド市場で「最も買い手がつきやすく、かつ損をしない適正な販売価格（日本円）」を査定してください。

【査定における数理的重み付けのルール】
1. 「商品の状態」が『傷や汚れあり』や『全体的に状態が悪い』の場合は、ジャンルごとの標準相場から30%〜70%大幅に減額した、現実的に売れる価格にしてください。
2. 「商品の状態」が『新品・未使用』『未使用に近い』の場合でも、中古であることを考慮して、高すぎる値段をつけないようにしてください。
3. 出力は査定した金額の「数字（整数）」のみとし、「円」や「¥」、カンマ（,）、解説テキストは絶対に1文字も含めないでください。
   例：4500円が適正なら「4500」とだけ出力。

■ 被査定商品データ
商品名: {item_name}
商品説明: {item_description}
カテゴリ: {item_category}
商品の状態: {item_condition}"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3) 
        )
        
        jpy_price = int(response.text.strip())
        return {"status": "success", "suggested_price": jpy_price}
        
    except ValueError:
        raise HTTPException(status_code=500, detail="AIが有効な数値を生成できませんでした。もう一度お試しください。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    


# 5. 取引画面・メッセージ・通知・ウィッシュリスト用 新設API

@router.get("/api/transactions/{transaction_id}")
def get_transaction_detail(transaction_id: int):
    """特定の取引画面用の統合データ一括取得API"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT t.id AS transaction_id, t.status AS transaction_status, t.buyer_id, t.seller_id,
                       COALESCE(i.name, p.name) AS item_name, COALESCE(i.image_url, p.ai_image_url, p.image_url) AS item_image_url, COALESCE(i.price, p.price) AS item_price
                FROM transactions t LEFT JOIN items i ON t.item_id = i.id LEFT JOIN products p ON t.product_id = p.id
                WHERE t.id = %s;
            """
            cursor.execute(sql, (transaction_id,))
            tx = cursor.fetchone()
            if not tx: raise HTTPException(status_code=404, detail="取引が見つかりません")
            return tx
    finally:
        connection.close()


@router.post("/api/transactions/{transaction_id}/step")
def progress_transaction_status(transaction_id: int, data: dict):
    """発送通知 ➔ 受取評価の2段階状態遷移（ステートマシン）API"""
    current_action_user_id = data.get("user_id")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT status, buyer_id, seller_id, item_id, product_id FROM transactions WHERE id = %s", (transaction_id,))
            tx = cursor.fetchone()
            if not tx: raise HTTPException(status_code=404, detail="取引が存在しません")

            next_status = tx["status"]
            notif_target_user_id, notif_title, notif_message = None, "", ""

            if tx["status"] == "shipping_pending":
                if current_action_user_id != tx["seller_id"] and tx["seller_id"] is not None:
                    raise HTTPException(status_code=403, detail="出品者以外は発送通知を実行できません")
                next_status, notif_target_user_id = "shipped", tx["buyer_id"]
                notif_title, notif_message = "商品が発送されました！", "商品が発送されました。到着後、中身を確認して受取評価をしてください。"
            elif tx["status"] == "shipped":
                if current_action_user_id != tx["buyer_id"]:
                    raise HTTPException(status_code=403, detail="購入者以外は受取評価を完了できません")
                next_status, notif_target_user_id = "completed", tx["seller_id"]
                notif_title, notif_message = "取引がすべて完了しました！", "購入者が受取評価を完了しました。売上金が反映されます。"

            cursor.execute("UPDATE transactions SET status = %s WHERE id = %s", (next_status, transaction_id))
            
            if notif_target_user_id:
                item_hybrid_id = (tx["item_id"] + 100000) if tx["item_id"] else tx["product_id"]
                cursor.execute("""
                    INSERT INTO notifications (user_id, title, message, item_id, product_id) VALUES (%s, %s, %s, %s, %s)
                """, (notif_target_user_id, notif_title, notif_message, item_hybrid_id if tx["item_id"] else None, tx["product_id"] if tx["product_id"] else None))

            connection.commit()
            return {"status": "success", "next_status": next_status}
    finally:
        connection.close()


@router.post("/api/transactions/{transaction_id}/messages")
def send_transaction_message(transaction_id: int, data: dict):
    """取引画面専用チャットのメッセージ送信用エンドポイント"""
    sender_id, message = data.get("sender_id"), data.get("message")
    if not message or not message.strip(): raise HTTPException(status_code=400, detail="メッセージが空です")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO transaction_messages (transaction_id, sender_id, message) VALUES (%s, %s, %s)", (transaction_id, sender_id, message.strip()))
            connection.commit()
            return {"status": "success"}
    finally:
        connection.close()


@router.get("/api/transactions/{transaction_id}/messages")
def get_transaction_messages(transaction_id: int):
    """取引画面専用チャットの履歴全件取得API"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT sender_id, message, created_at FROM transaction_messages WHERE transaction_id = %s ORDER BY id ASC", (transaction_id,))
            return cursor.fetchall()
    finally:
        connection.close()


@router.post("/api/wishlists")
def add_to_wishlist(data: dict):
    """曖昧な「欲しいイメージ」を多次元空間ベクトルへ圧縮して入荷待ちスタンドバイ"""
    user_id, keywords = data.get("user_id"), data.get("keywords")
    if not keywords or not keywords.strip(): raise HTTPException(status_code=400, detail="欲しいイメージを入力してください")
    try:
        embed_res = client.models.embed_content(
            model="gemini-embedding-2", contents=keywords.strip(), config=types.EmbedContentConfig(output_dimensionality=768)
        )
        wish_json = json.dumps(embed_res.embeddings[0].values)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI潜在空間展開に失敗: {str(e)}")

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO wishlists (user_id, keywords, embedding) VALUES (%s, %s, %s)", (user_id, keywords.strip(), wish_json))
            connection.commit()
            return {"status": "success", "message": "入荷待ちにAI登録されました！"}
    finally:
        connection.close()


@router.get("/api/users/{user_id}/notifications")
def get_user_notifications(user_id: int):
    """ユーザーごとの通知一覧を降順で一括取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, title, message, item_id, product_id, is_read, created_at FROM notifications WHERE user_id = %s ORDER BY id DESC", (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()


@router.post("/api/notifications/{notification_id}/read")
def mark_notification_as_read(notification_id: int):
    """通知を既読にするAPI"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE notifications SET is_read = TRUE WHERE id = %s", (notification_id,))
            connection.commit()
            return {"status": "success"}
    finally:
        connection.close()


@router.get("/api/users/{user_id}/transactions")
def get_user_active_transactions(user_id: int):
    """ユーザーが購入、または出品している『進行中（未完了）』の取引一覧を全件取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    t.id AS transaction_id, t.status AS transaction_status, t.buyer_id, t.seller_id,
                    COALESCE(i.name, p.name) AS item_name,
                    COALESCE(i.image_url, p.image_url) AS item_image_url,
                    COALESCE(i.price, p.price) AS item_price
                FROM transactions t
                LEFT JOIN items i ON t.item_id = i.id
                LEFT JOIN products p ON t.product_id = p.id
                WHERE (t.buyer_id = %s OR t.seller_id = %s) AND t.status != 'completed'
                ORDER BY t.id DESC;
            """
            cursor.execute(sql, (user_id, user_id))
            return cursor.fetchall()
    finally:
        connection.close()


@router.get("/api/users/{user_id}/transactions/completed")
def get_user_completed_transactions(user_id: int):
    """【新設】ユーザーが関わった『完了済み（completed）』の過去の取引履歴一覧を取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    t.id AS transaction_id, t.status AS transaction_status, t.buyer_id, t.seller_id,
                    COALESCE(i.name, p.name) AS item_name,
                    COALESCE(i.image_url, p.image_url) AS item_image_url,
                    COALESCE(i.price, p.price) AS item_price
                FROM transactions t
                LEFT JOIN items i ON t.item_id = i.id
                LEFT JOIN products p ON t.product_id = p.id
                WHERE (t.buyer_id = %s OR t.seller_id = %s) AND t.status = 'completed'
                ORDER BY t.id DESC;
            """
            cursor.execute(sql, (user_id, user_id))
            return cursor.fetchall()
    finally:
        connection.close()


@router.get("/api/users/{user_id}/wishlists")
def get_user_wishlists(user_id: int):
    """ユーザーが登録した入荷待ち（ウィッシュリスト）キーワードの一覧を取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, keywords, created_at FROM wishlists WHERE user_id = %s ORDER BY id DESC", (user_id,))
            return cursor.fetchall()
    finally:
        connection.close()


@router.delete("/api/wishlists/{wishlist_id}")
def delete_wishlist(wishlist_id: int):
    """不要になった入荷待ち登録を解除（削除）するAPI"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM wishlists WHERE id = %s", (wishlist_id,))
            connection.commit()
            return {"status": "success", "message": "入荷待ち登録を解除しました"}
    finally:
        connection.close()


# 6. AI代理交渉エージェント（利害調停数理インフラ）
@router.post("/api/items/{item_id}/negotiate")
def negotiate_item_price(item_id: int, data: dict):
    """購入者の希望価格と熱意文を、出品者の隠しデッドラインと照らし合わせてGeminiが3分岐調停するAPI"""
    if item_id < 100000:
        raise HTTPException(status_code=400, detail="公式カタログ商品は固定価格のため、価格交渉の対象外です。")
        
    raw_id = item_id - 100000
    buyer_id = data.get("buyer_id")
    wish_price = data.get("wish_price")
    buyer_message = data.get("message")
    
    if not wish_price or not buyer_message or not buyer_message.strip():
        raise HTTPException(status_code=400, detail="希望価格と熱意文を共に入力してください。")
        
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            # 売り手側の隠し条件をデータベースの潜在空間から密かにハント
            cursor.execute("SELECT name, price, min_acceptable_price, seller_stance, seller_id, status FROM items WHERE id = %s", (raw_id,))
            item = cursor.fetchone()
            if not item: raise HTTPException(status_code=404, detail="商品が見つかりません")
            if item["status"] == "sold_out": raise HTTPException(status_code=400, detail="この商品はすでに売り切れています。")
                
            current_price = item["price"]
            min_acceptable_price = item["min_acceptable_price"] if item["min_acceptable_price"] is not None else current_price
            seller_stance = item["seller_stance"] if item["seller_stance"] else "急いでいない"
            seller_id = item["seller_id"]
            item_name = item["name"]
            
            # 厳格な判定ルールを焼き付けたプロンプトをGeminiへ流し込む
            prompt = f"""あなたは一流のフリマアプリの仲裁AI（調停エージェント）です。
購入者から届いた「希望価格」と「熱意文」を、出品者の「販売条件」と照らし合わせて、経済学的かつ心理的に中立な立場から以下の3つの結論（status）のいずれかを下してください。

【販売条件】
・現在の出品価格: {current_price}円
・出品者が絶対に譲れない最低価格: {min_acceptable_price}円
・出品者のスタンス: {seller_stance}

【購入者からの提案】
・希望価格: {wish_price}円
・熱意文: {buyer_message}

【ジャッジの鉄則】
1. 希望価格が出品者の最低価格({min_acceptable_price}円)を1円でも下回っている場合は、無条件で [REJECT（拒否）] としてください。
2. 希望価格が最低価格以上であり、且つ購入者の熱意文が非常に丁寧で誠実である、または出品者のスタンスが「売り切りたい」の場合は、買い手の希望価格をそのまま適用し [ACCEPT（一発成立）] としてください。
3. 希望価格が最低価格以上ではあるが、出品者のスタンスが「急いでいない」場合、または熱意文がシンプルすぎる場合は、現在の価格と希望価格のちょうど中間付近（出品者の最低価格を下回らない範囲）の価格を計算し [COUNTER（妥協案提示）] としてください。

出力は必ず以下のJSONフォーマットのみとしてください。
{{
  "status": "ACCEPT" または "REJECT" または "COUNTER",
  "settlement_price": 最終決定した金額（整数）,
  "ai_message": "購入者と出品者の双方を納得させる、AIからの丁寧な仲裁メッセージ文（日本語）"
}}"""

            res = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1)
            )

            raw_text = res.text.strip()
            
            backticks = "`" * 3
            if raw_text.startswith(backticks):
                lines = raw_text.splitlines()
                if lines[0].startswith(backticks): lines = lines[1:]
                if lines[-1].startswith(backticks): lines = lines[:-1]
                raw_text = "\n".join(lines).strip()
                
            ai_decision = json.loads(raw_text)
            status = ai_decision.get("status", "REJECT")
            settlement_price = int(ai_decision.get("settlement_price", current_price))
            ai_message = ai_decision.get("ai_message", "交渉が整いませんでした。")
            
            if status == "ACCEPT" and settlement_price < min_acceptable_price:
                status = "REJECT"
                
            transaction_id = None
            
            # ⚡ 【ACCEPT（一発成立）の場合の裏側自動決済＆取引生成】
            if status == "ACCEPT":
                cursor.execute("SET FOREIGN_KEY_CHECKS=0;")
                cursor.execute("UPDATE items SET price = %s, status = 'sold_out' WHERE id = %s", (settlement_price, raw_id))
                cursor.execute("INSERT INTO purchases (item_id, buyer_id) VALUES (%s, %s)", (item_id, buyer_id))
                
                tx_sql = "INSERT INTO transactions (item_id, product_id, buyer_id, seller_id, status) VALUES (%s, NULL, %s, %s, 'shipping_pending')"
                cursor.execute(tx_sql, (raw_id, buyer_id, seller_id))
                transaction_id = cursor.lastrowid
                
                if seller_id:
                    cursor.execute("""
                        INSERT INTO notifications (user_id, title, message, item_id) VALUES (%s, %s, %s, %s)
                    """, (seller_id, "AI代理交渉により商品が即時売却されました！", 
                          f"出品した「{item_name}」が、AI調停エージェントの仲裁により {settlement_price}円 で合意に達し、自動決済されました。取引画面を確認してください。", item_id))
                
                cursor.execute("SET FOREIGN_KEY_CHECKS=1;")
                connection.commit()
                
            return {
                "status": status,
                "settlement_price": settlement_price,
                "ai_message": ai_message,
                "transaction_id": transaction_id
            }
    except Exception as e:
        if 'connection' in locals(): connection.rollback()
        return {"status": "ERROR", "ai_message": f"AI調停中にシステムエラーが発生しました: {str(e)}"}
    finally:
        if 'connection' in locals(): connection.close()


@router.post("/api/items/{item_id}/negotiate/confirm")
def confirm_counter_price(item_id: int, data: dict):
    """AIが提示した妥協案を購入者が「その価格で承諾する」と決断した瞬間の最終決済API"""
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            raw_id = item_id - 100000
            buyer_id = data.get("buyer_id")
            settlement_price = data.get("settlement_price")

            cursor.execute("SELECT name, seller_id, status FROM items WHERE id = %s", (raw_id,))
            item = cursor.fetchone()
            if not item or item["status"] == "sold_out":
                raise HTTPException(status_code=400, detail="商品がすでに売り切れているか、見つかりません。")
                
            cursor.execute("SET FOREIGN_KEY_CHECKS=0;")
            cursor.execute("UPDATE items SET price = %s, status = 'sold_out' WHERE id = %s", (settlement_price, raw_id))
            cursor.execute("INSERT INTO purchases (item_id, buyer_id) VALUES (%s, %s)", (item_id, buyer_id))
            
            tx_sql = "INSERT INTO transactions (item_id, product_id, buyer_id, seller_id, status) VALUES (%s, NULL, %s, %s, 'shipping_pending')"
            cursor.execute(tx_sql, (raw_id, buyer_id, item["seller_id"]))
            tx_id = cursor.lastrowid
            
            if item["seller_id"]:
                cursor.execute("""
                    INSERT INTO notifications (user_id, title, message, item_id) VALUES (%s, %s, %s, %s)
                """, (item["seller_id"], "AI妥協案により価格交渉が成立しました！", 
                      f"出品した「{item['name']}」が、AI提示の妥協案（{settlement_price}円）で購入者により承諾され、取引が成立しました。", item_id))
                
            cursor.execute("SET FOREIGN_KEY_CHECKS=1;")
            connection.commit()
            return {"status": "success", "transaction_id": tx_id}
    except Exception as e:
        if 'connection' in locals(): connection.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'connection' in locals(): connection.close()

@router.put("/api/items/{item_id}")
def update_item_detail(item_id: int, item_data: dict):
    """【新設】出品者が既存の商品内容を訂正（上書き保存）するAPI（ステータスガード ＆ 潜在空間ベクトル自動再計算）"""
    if item_id < 100000:
        raise HTTPException(status_code=400, detail="公式カタログ商品は編集できません。")
        
    raw_id = item_id - 100000 

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT status FROM items WHERE id = %s", (raw_id,))
            item = cursor.fetchone()
            
            if not item:
                raise HTTPException(status_code=404, detail="対象の商品が存在しません。")
            
            if item["status"] != "on_sale":
                raise HTTPException(status_code=400, detail="販売中以外の商品は、安全上の理由から内容の訂正ができません。")

            structured_text = f"""
            Product Characteristics:
            - Title: {item_data.get("name")}
            - Category: {item_data.get("tags")}
            - Core Context: {item_data.get("description")}
            """
            try:
                embed_res = client.models.embed_content(
                    model="gemini-embedding-2",
                    contents=structured_text,
                    config=types.EmbedContentConfig(output_dimensionality=768)
                )
                embedding_vector = embed_res.embeddings[0].values
                embedding_json = json.dumps(embedding_vector)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"更新に失敗しました: {str(e)}")

            # 🛠️ すべてのメタデータとAI数理調停パラメータを一括UPDATE
            sql = """
                UPDATE items 
                SET 
                    name = %s, 
                    description = %s, 
                    price = %s, 
                    min_acceptable_price = %s, 
                    seller_stance = %s, 
                    image_url = %s, 
                    tags = %s, 
                    item_condition = %s, 
                    seller_nickname = %s, 
                    shipping_days = %s,
                    embedding = %s
                WHERE id = %s
            """
            
            current_price = int(item_data.get("price", 0))
            min_price = item_data.get("min_acceptable_price")
            min_acceptable_price = int(min_price) if min_price else current_price
            seller_stance = item_data.get("seller_stance", "急いでいない")

            cursor.execute(sql, (
                item_data.get("name"),
                item_data.get("description"),
                current_price,
                min_acceptable_price,
                seller_stance,
                item_data.get("image_url"),
                item_data.get("tags"),
                item_data.get("item_condition"),
                item_data.get("seller_nickname"),
                item_data.get("shipping_days"),
                embedding_json,
                raw_id  # WHERE句の指定
            ))
            
            connection.commit()
            return {"status": "success", "message": "商品の出品内容が上書き保存されました！"}
            
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        connection.close()

@router.delete("/api/items/{item_id}")
def delete_on_sale_item(item_id: int):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 1. 該当商品が本当に「販売中（on_sale）」か、数理的チェック
            cursor.execute("SELECT status FROM items WHERE id = %s", (item_id,))
            item = cursor.fetchone()
            
            if not item:
                raise HTTPException(status_code=404, detail="商品が見つかりません。")
            if item["status"] != "on_sale":
                raise HTTPException(status_code=400, detail="販売中の商品のみ削除可能です。")
            
            # 2. 安全装置を一時オフにして、likesやviewsの居残りを無視して一撃で物理削除
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("DELETE FROM items WHERE id = %s", (item_id,))
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
            
        connection.commit()
        return {"status": "success", "message": "出品を削除しました。"}
    except Exception as e:
        connection.rollback()
        raise HTTPException(status_code=500, detail=f"削除エラー: {str(e)}")
    finally:
        connection.close()