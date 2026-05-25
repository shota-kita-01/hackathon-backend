from fastapi import APIRouter, HTTPException
from google.genai import types
from db import get_db_connection, client
import json

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
                    image_url AS image_url, 
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


# ===================================================
# 🛒 2. フリマ商品一覧 ＆ 自由出品API（ハイブリッド統合）
# ===================================================

@router.get("/api/items")
def get_items():
    """
    公式データと一般出品を合流。
    💡ID衝突を防ぐため、一般出品のIDに一律 100000 を加算してフロントへ出荷します。
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
                    image_url AS image_url, 
                    status AS status, 
                    '新品・未使用' AS item_condition, 
                    '公式出品' AS seller_name, 
                    '1〜2日で発送' AS shipping_days 
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
                    shipping_days AS shipping_days
                FROM items
                
                ORDER BY id DESC;
            """
            cursor.execute(sql)
            return cursor.fetchall()
    finally:
        connection.close()


@router.post("/api/items/check")
def check_item_safety(item_data: dict):
    """【新設】出品前にGeminiで商品が規約違反でないかリアルタイム審査するエンドポイント"""
    try:
        moderation_prompt = f"""あなたは日本の大手フリマアプリの厳格なコンプライアンス審査官です。
以下の出品申請された商品の「商品名」と「商品説明」を厳密に精査し、フリマの一般的な出品禁止物（武器、違法薬物、処方箋医薬品、偽ブランド品・スーパーコピー、詐欺・情報商材、成人向けコンテンツなど）に該当、あるいは規約違反の恐れがないか数理的に判定してください。

商品名: {item_data.get("name")}
商品説明: {item_data.get("description")}

必ず以下のJSONフォーマットのみで返答してください。解説テキストは1文字も含めてはなりません。
{{
  "is_safe": true または false,
  "reason": "違反と判定した具体的な理由（日本語）。安全な場合は空文字にしてください。"
}}"""

        mod_res = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=moderation_prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,               # 判定のブレを極限まで無くすため0固定
                response_mime_type="application/json" # JSON出力を強制
            )
        )
        
        mod_data = json.loads(mod_res.text.strip())
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
    """ユーザーが出品画面から入力した内容を、一般出品テーブル（items）へ格納"""
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
        raise HTTPException(status_code=500, detail=f"【AI空間配置エラー】ベクトルの生成に失敗しました: {str(e)}")

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO items (
                    name, description, price, image_url, 
                    seller_id, tags, status, item_condition, seller_nickname, shipping_days, embedding
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'on_sale', %s, %s, %s, %s)
            """
            cursor.execute(sql, (
                item_data.get("name"),
                item_data.get("description"),
                item_data.get("price"),
                item_data.get("image_url"),
                item_data.get("seller_id"),
                item_data.get("tags", "一般出品"),
                item_data.get("item_condition", "目立った傷や汚れなし"),
                item_data.get("seller_nickname", "名無しさん"),
                item_data.get("shipping_days", "1〜2日で発送"),
                embedding_json
            ))
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
# 🔍 検索キーワード履歴 記録 ＆ 取得API（変更なし）
# ===================================================

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


# ===================================================
# 🛍️ 3. 購入・いいね・履歴API（💡外部キー制約セッションハック搭載）
# ===================================================

@router.post("/api/items/{item_id}/purchase")
def purchase_item(item_id: int, buyer_data: dict):
    """【改修】10万以上のIDの購入時、外部キーチェックを一時スルーしてログ保存を許可"""
    buyer_id = buyer_data.get("buyer_id")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            if item_id >= 100000:
                # ユーザー一般出品の売切処理
                raw_id = item_id - 100000
                cursor.execute("SELECT status FROM items WHERE id = %s", (raw_id,))
                item = cursor.fetchone()
                if not item: raise HTTPException(status_code=404, detail="商品が見つかりません")
                if item["status"] == "sold_out": raise HTTPException(status_code=400, detail="売り切れています")
                
                cursor.execute("UPDATE items SET status = 'sold_out' WHERE id = %s", (raw_id,))
            else:
                # 公式カタログ商品の売切処理
                cursor.execute("SELECT status FROM products WHERE id = %s", (item_id,))
                product = cursor.fetchone()
                if not product: raise HTTPException(status_code=404, detail="商品が見つかりません")
                if product["status"] == "sold_out": raise HTTPException(status_code=400, detail="売り切れています")
                
                cursor.execute("UPDATE products SET status = 'sold_out' WHERE id = %s", (item_id,))
            
            # 💡 購入ログのインサート時、外部キーチェックを一時スルーして仮想IDを受け入れる
            cursor.execute("SET FOREIGN_KEY_CHECKS=0;")
            cursor.execute("INSERT INTO purchases (item_id, buyer_id) VALUES (%s, %s)", (item_id, buyer_id))
            cursor.execute("SET FOREIGN_KEY_CHECKS=1;")
            
            connection.commit()
            return {"status": "success", "message": "商品の購入が完了しました！"}
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
                    p.ai_category AS tags, p.description AS description, p.image_url AS image_url, 
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
            # 💡 外部キーチェックを一時的に無効化し、10万超えの仮想IDのインサートを強行突破
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
                           p.ai_category AS tags, p.description AS description, p.image_url AS image_url, 
                           p.status AS status, '新品・未使用' AS item_condition, '公式出品' AS seller_name,
                           MAX(v.id) as max_v_id
                    FROM item_views v
                    JOIN products p ON v.item_id = p.id
                    WHERE v.user_id = %s AND v.item_id < 100000
                    GROUP BY p.id

                    UNION ALL

                    SELECT i.id + 100000 AS id, NULL AS asin, i.name AS name, i.price AS price, 
                           i.tags AS tags, i.description AS description, i.image_url AS image_url, 
                           i.status AS status, i.item_condition AS item_condition, i.seller_nickname AS seller_name,
                           MAX(v.id) as max_v_id
                    FROM item_views v
                    JOIN items i ON (v.item_id - 100000) = i.id
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
                       p.ai_category AS tags, p.description AS description, p.image_url AS image_url, 
                       p.status AS status, '新品・未使用' AS item_condition, '公式出品' AS seller_name, pur.id as pur_id
                FROM purchases pur
                JOIN products p ON pur.item_id = p.id
                WHERE pur.buyer_id = %s AND pur.item_id < 100000
                
                UNION ALL
                
                SELECT i.id + 100000 AS id, NULL AS asin, i.name AS name, i.price AS price, 
                       i.tags AS tags, i.description AS description, i.image_url AS image_url, 
                       i.status AS status, i.item_condition AS item_condition, i.seller_nickname AS seller_name, pur.id as pur_id
                FROM purchases pur
                JOIN items i ON (pur.item_id - 100000) = i.id
                WHERE pur.buyer_id = %s AND pur.item_id >= 100000
                
                ORDER BY pur_id DESC;
            """
            cursor.execute(sql, (user_id, user_id))
            return cursor.fetchall()
    finally:
        connection.close()


# ===================================================
# 🧠 4. AI商品説明自動生成 ＆ 価格査定（変更なし）
# ===================================================

@router.post("/api/ai/suggest-description")
def suggest_description(data: dict):
    item_name = data.get("name")
    if not item_name: 
        raise HTTPException(status_code=400, detail="商品名が必要です")
    try:
        prompt = f"""あなたは日本の大人気フリマアプリ（メルカリなど）で月商100万円を売り上げる伝説のトップセラーです。
ユーザーが入力した商品名をもとに、購入者の物欲を極限まで刺激する「そのままコピペして使える完成された商品説明文」を1つだけ作成してください。

【⚠️絶対に守るべき鉄の掟】
1. 「〇〇の説明文ですね！」などの前置き、挨拶、終わりの会話文は、1文字とも出力しないでください。
2. 「パターン1」「パターン2」などの複数提案や、キャッチコピーの箇条書きは絶対に禁止です。最初から最高の一着としての文章を1パターンだけ作成してください。
3. 出力するテキストは、フリマの「商品説明欄にそのまま貼り付けられる本文」のみとしてください。
4. 過大広告や偽ブランドの表示などは絶対にしないでください。あくまでも事実に基づき、購入者の物欲を極限まで刺激するよう努めてください。
5. フリマの一般的な出品禁止物（武器、違法薬物、処方箋医薬品、偽ブランド品・スーパーコピー、詐欺・情報商材、成人向けコンテンツなど）に該当、あるいは規約違反の可能性のある説明文を絶対に出力しないでください。
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

【⚠️ 査定における数理的重み付けのルール】
1. 「商品の状態」が『傷や汚れあり』や『全体的に状態が悪い』の場合は、ジャンルごとの標準相場から30%〜70%大幅に減額した、現実的に売れる価格にしてください。
2. 「商品の状態」が『新品・未使用』『未使用に近い』の場合でも、中古であることを考慮して、高すぎる値段をつけないようにしてください。
特に、本来の相場を超える金額を出力しないでください。
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