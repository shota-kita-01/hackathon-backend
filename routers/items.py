from fastapi import APIRouter, HTTPException
from google.genai import types
from db import get_db_connection, client

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
                    '新品・未使用' AS item_condition, -- 💡 公式データは一律「新品」として擬似生成
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
                    '新品・未使用' AS item_condition, -- 💡 ここにも追加
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
    運営の初期カタログデータと、ユーザーがアプリから出品した一般データを
    数理的にガッチャンコして、タイムラインに新着順で一括返却します
    """
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                -- ① 初期配置のカタログデータ
                SELECT 
                    id AS id, 
                    name AS name, 
                    price AS price, 
                    ai_category AS tags, 
                    description AS description, 
                    image_url AS image_url, 
                    status AS status, 
                    '新品・未使用' AS item_condition, -- 💡 カタログ側は一律新品扱い
                    '公式出品' AS seller_name, 
                    '1〜2日で発送' AS shipping_days 
                FROM products
                
                UNION ALL
                
                -- ② ユーザーが実際にアプリから出品したカスタムデータ
                SELECT 
                    id AS id, 
                    name AS name, 
                    price AS price, 
                    tags AS tags, 
                    description AS description, 
                    image_url AS image_url, 
                    status AS status,
                    item_condition AS item_condition, -- 💡 ユーザー出品のリアルな状態を取得
                    seller_nickname AS seller_name, 
                    shipping_days AS shipping_days
                FROM items
                
                ORDER BY id DESC;
            """
            cursor.execute(sql)
            return cursor.fetchall()
    finally:
        connection.close()


@router.post("/api/items")
def create_item(item_data: dict):
    """ユーザーが出品画面から入力した内容を、一般出品テーブル（items）へ安全に格納"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            # 💡 item_condition を INSERT カラムと VALUES に追加！
            sql = """
                INSERT INTO items (
                    name, description, price, image_url, 
                    seller_id, tags, status, item_condition, seller_nickname, shipping_days
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'on_sale', %s, %s, %s)
            """
            cursor.execute(sql, (
                item_data.get("name"),
                item_data.get("description"),
                item_data.get("price"),
                item_data.get("image_url"),
                item_data.get("seller_id"),
                item_data.get("tags", "一般出品"),
                item_data.get("item_condition", "目立った傷や汚れなし"), # 💡 フロントから送られてくる状態データを格納
                item_data.get("seller_nickname", "名無しさん"),
                item_data.get("shipping_days", "1〜2日で発送")
            ))
            connection.commit()
            return {"status": "success", "message": "商品が出品されました！"}
    finally:
        connection.close()


@router.get("/api/users/{user_id}/products")
def get_user_products(user_id: int):
    """マイページの『出品した商品』タブに、自分が過去に出品した一般データを完全に同期"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    id AS id, 
                    name AS name, 
                    price AS price, 
                    tags AS tags, 
                    description AS description, 
                    image_url AS image_url, 
                    status AS status,
                    item_condition AS item_condition, -- 💡 追加
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
# 🛍️ 3. 購入・いいね・履歴API
# ===================================================

@router.post("/api/items/{item_id}/purchase")
def purchase_item(item_id: int, buyer_data: dict):
    buyer_id = buyer_data.get("buyer_id")
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT status FROM products WHERE id = %s", (item_id,))
            product = cursor.fetchone()
            if not product: 
                raise HTTPException(status_code=404, detail="商品が見つかりません")
            if product["status"] == "sold_out": 
                raise HTTPException(status_code=400, detail="売り切れています")
            
            cursor.execute("UPDATE products SET status = 'sold_out' WHERE id = %s", (item_id,))
            cursor.execute("INSERT INTO purchases (item_id, buyer_id) VALUES (%s, %s)", (item_id, buyer_id))
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
                SELECT 
                    p.id AS id, p.asin AS asin, p.name AS name, p.price AS price, 
                    p.ai_category AS tags, p.description AS description, p.image_url AS image_url, 
                    p.status AS status, '新品・未使用' AS item_condition, '公式出品' AS seller_name, TRUE AS is_liked
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
    """最近チェックした商品の閲覧履歴（重複なし・最新50件）を取得"""
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT 
                    p.id AS id, p.asin AS asin, p.name AS name, p.price AS price, 
                    p.ai_category AS tags, p.description AS description, p.image_url AS image_url, 
                    p.status AS status, '新品・未使用' AS item_condition, '公式出品' AS seller_name
                FROM item_views v
                JOIN products p ON v.item_id = p.id
                WHERE v.user_id = %s
                GROUP BY p.id
                ORDER BY MAX(v.id) DESC
                LIMIT 50;
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
                SELECT 
                    p.id AS id, p.asin AS asin, p.name AS name, p.price AS price, 
                    p.ai_category AS tags, p.description AS description, p.image_url AS image_url, 
                    p.status AS status, '新品・未使用' AS item_condition, '公式出品' AS seller_name
                FROM purchases pur
                JOIN products p ON pur.item_id = p.id
                WHERE pur.buyer_id = %s
                ORDER BY pur.id DESC;
            """
            cursor.execute(sql, (user_id,))
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
1. 「〇〇の説明文ですね！」などの前置き、挨拶、終わりの会話文は、1文字たりとも出力しないでください。
2. 「パターン1」「パターン2」などの複数提案や、キャッチコピーの箇条書きは絶対に禁止です。最初から最高の一着としての文章を1パターンだけ作成してください。
3. 出力するテキストは、フリマの「商品説明欄にそのまま貼り付けられる本文」のみとしてください。
4. 文字数は200字程度とし、無駄に長く、冗長になることは避けてください。

商品名: {item_name}"""
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.7)
        )
        return {"status": "success", "description": response.text.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===================================================
# 💰 改修版：AI価格査定API
# ===================================================
@router.post("/api/ai/suggest-price")
def suggest_price(data: dict):
    # 💡 4つの必須パラメーターをすべてハントする
    item_name = data.get("name")
    item_description = data.get("description")
    item_category = data.get("tags")            # 選択された22ジャンルの英名
    item_condition = data.get("item_condition")  # 「新品」「傷あり」などの状態

    # 🛑 【条件分岐】どれか1つでも空、または存在しない場合は即座に親切な指示を返してブロック！
    if not item_name or not item_description or not item_category or not item_condition:
        raise HTTPException(
            status_code=400, 
            detail="【AI査定エラー】商品名、商品説明、出品ジャンル、商品の状態をすべて入力・選択してから、もう一度AI価格査定を押してください！"
        )
        
    try:
        # 🧠 カテゴリと状態の重みを加味させる最強のプロンプト
        prompt = f"""あなたは日本のフリマ市場（メルカリやヤフオクなど）の相場・価格決定メカニズムを完璧にハックしている超一流のAI査定士です。
以下の4つの情報をもとに、現在の日本のリアルなセカンドハンド市場で「最も買い手がつきやすく、かつ損をしない適正な販売価格（日本円）」を査定してください。

【⚠️ 査定における数理的重み付けのルール】
1. 「商品の状態」が『傷や汚れあり』や『全体的に状態が悪い』の場合は、ジャンルごとの標準相場から30%〜70%大幅に減額した、現実的に売れる価格にしてください。
2. 「商品の状態」が『新品・未使用』『未使用に近い』の場合は、強気なプレミア価格を設定してください。
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
            config=types.GenerateContentConfig(temperature=0.3) # 査定のブレをなくすため低めの温度に設定
        )
        
        jpy_price = int(response.text.strip())
        return {"status": "success", "suggested_price": jpy_price}
        
    except ValueError:
        # 万が一AIが数字以外を返してきた場合のセーフティネット
        raise HTTPException(status_code=500, detail="AIが有効な数値を生成できませんでした。もう一度お試しください。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))