from fastapi import APIRouter, HTTPException
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from db import get_db_connection, client
from schemas import RecommendRequest

router = APIRouter()

@router.post("/api/recommend")
def get_recommendations(req: RecommendRequest):
    connection = get_db_connection()
    try:
        english_keywords = ""
        if req.mode in ["mood", "both"] and req.mood_text.strip():
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a semantic processing engine for a fashion e-commerce search.\n"
                                "Convert the user input into a space-separated list of optimal English search keywords.\n"
                                "Crucially, preserve natural compound phrases like 'men sneakers', 'women bag', or 'gold necklace'.\n"
                                "Output ONLY the space-separated lowercase keywords. No punctuation, no markdown."
                            )
                        },
                        {"role": "user", "content": f'User input: "{req.mood_text}"'}
                    ],
                    temperature=0.2,
                )
                english_keywords = response.choices[0].message.content.strip().lower()
                print(f"🧠 [OpenAI LLM Expansion]: {req.mood_text} ➔ {english_keywords}")
            except Exception as openai_err:
                print(f"⚠️ OpenAI Error: {openai_err}")
                english_keywords = req.mood_text

        with connection.cursor() as cursor:
            cursor.execute("SELECT id, name, description, price, image_url, seller_id, status FROM items")
            items = cursor.fetchall()
            if not items: return []

            cursor.execute("""
                SELECT i.name, i.description FROM purchases p
                JOIN items i ON p.item_id = i.id WHERE p.buyer_id = %s
            """, (req.user_id,))
            past_purchases = cursor.fetchall()
            
            cursor.execute("""
                SELECT i.name, i.description FROM likes l
                JOIN items i ON l.item_id = i.id WHERE l.user_id = %s
            """, (req.user_id,))
            past_likes = cursor.fetchall()
            
            history_text = " ".join([f"{p['name']} {p['description']}" for p in past_purchases + past_likes])

            if req.mode == "mood":
                combined_user_text = english_keywords
            elif req.mode == "history":
                combined_user_text = history_text
            else:
                combined_user_text = f"{english_keywords} {history_text}".strip()

            if not combined_user_text:
                return items[:10]

            item_texts = [f"{item['name']} {item['description']}" for item in items]
            all_texts = item_texts + [combined_user_text]

            vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words='english')
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