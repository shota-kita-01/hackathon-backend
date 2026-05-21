from fastapi import APIRouter, HTTPException
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from db import client # get_db_connection は一時的に使わない
from schemas import RecommendRequest

router = APIRouter()

@router.post("/api/recommend")
def get_recommendations(req: RecommendRequest):
    try:
        filter_status = getattr(req, "filter_status", "both")
        actual_mode = req.mode
        if actual_mode in ["mood", "both"] and not req.mood_text.strip():
            actual_mode = "history"

        # 🤖 1. OpenAIによるテキストの英語キーワード化
        english_keywords = ""
        if actual_mode in ["mood", "both"] and req.mood_text.strip():
            try:
                print(f"🔮 [DEBUG] OpenAIに送信する生テキスト: '{req.mood_text}'")
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a semantic processing engine for a fashion e-commerce search. Convert the user input into a space-separated list of optimal English search keywords. Output ONLY the space-separated lowercase keywords. No punctuation."},
                        {"role": "user", "content": f'User input: "{req.mood_text}"'}
                    ],
                    temperature=0.2,
                )
                english_keywords = response.choices[0].message.content.strip().lower()
                print(f"✨ [DEBUG] OpenAIから返ってきた英語キーワード: '{english_keywords}'")
            except Exception as e:
                # 🔴 ここでエラーが出たらターミナルに理由が100%出力されます
                print(f"🔥 [ERROR] OpenAIのAPI呼び出しでクラッシュしました: {e}")
                english_keywords = req.mood_text

        # 📦 2. データベースの代わりに、検証用の固定ダミーデータを直書き（モック）
        items = [
            {"id": 4213, "name": "Chanel Wallet", "description": "Luxury black leather wallet from Chanel.", "price": 26550, "image_url": "", "seller_id": 1, "status": "on_sale"},
            {"id": 3468, "name": "Vintage Avon earrings", "description": "Beautiful red elements vintage earrings.", "price": 1350, "image_url": "", "seller_id": 2, "status": "on_sale"},
            {"id": 9999, "name": "Nike Air Max Sneaker", "description": "Sporty white running sneakers from Nike.", "price": 12000, "image_url": "", "seller_id": 3, "status": "on_sale"}
        ]

        # 閲覧履歴やいいねも空のダミーとして安全に処理
        history_text = "Chanel Wallet" # 過去に財布を見たことがあるというダミー履歴

        safe_history = history_text if history_text.strip() else "dummy_history_empty"
        safe_mood = english_keywords if english_keywords.strip() else "dummy_mood_empty"

        item_texts = [f"{item.get('name', '')} {item.get('description', '')}" for item in items]
        all_texts = item_texts + [safe_history, safe_mood]

        vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words='english')
        tfidf_matrix = vectorizer.fit_transform(all_texts)

        item_vectors = tfidf_matrix[:-2]
        history_vector = tfidf_matrix[-2]
        mood_vector = tfidf_matrix[-1]

        sim_history = cosine_similarity(history_vector, item_vectors).flatten()
        sim_mood = cosine_similarity(mood_vector, item_vectors).flatten()

        # ─── 🆕 スコア計算 ＆ キーワード・ブースティング処理 ───
        for idx, item in enumerate(items):
            if actual_mode == "history":
                base_score = float(sim_history[idx])
            elif actual_mode == "mood":
                base_score = float(sim_mood[idx])
            elif actual_mode == "both":
                base_score = (float(sim_mood[idx]) * 0.8) + (float(sim_history[idx]) * 0.2)
            else:
                base_score = 0.0

            # 🟢 【追加ロジック】商品名と説明文を合体させて小文字化
            item_text_lower = f"{item.get('name', '')} {item.get('description', '')}".lower()
            
            bonus = 0.0
            if english_keywords.strip():
                # OpenAIが書き出したキーワードをスペースで分解して単語ごとにループ
                kw_list = english_keywords.split()
                for kw in kw_list:
                    # "in" や "to" などの極端に短い不要単語の誤ヒットを防ぐ安全弁（3文字以上）
                    # かつ、その単語が商品のテキストに含まれている場合
                    if len(kw) > 2 and (kw in item_text_lower):
                        # 強力な加算ボーナスを付与してTF-IDFの薄まりをねじ伏せる
                        bonus += 0.5 

            # 数理ベースのコサイン類似度に、キーワード一致の特大ボーナスをマージ
            item["score"] = base_score + bonus

        recommended_items = sorted(items, key=lambda x: (x.get("score", 0), x.get("id", 0)), reverse=True)
        return recommended_items
            
    except Exception as e:
        print(f"🔥 Recommend API Critical Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))