import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import vertexai
from vertexai.vision_models import ImageGenerationModel

# 💡 ルートディレクトリの db.py から get_db_connection と 検証済みの client を同時にハント
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from db import get_db_connection, client
from google.cloud import storage

# ==========================================
# ⚙️ 設定パラメータ
# ==========================================
PROJECT_ID = "term9-shota-kita"
LOCATION = "us-central1"
BUCKET_NAME = "term9-shota-kita-images" 
MAX_WORKERS = 2 

BACKGROUNDS = [
    "light-colored wooden flooring",
    "dark brown oak wooden floor",
    "soft beige fabric carpet",
    "minimalist white bed sheet linen",
    "clean modern concrete floor"
]

def init_services():
    """Imagen 3 と GCS クライアントの初期化（Geminiはdb.pyのclientを使用）"""
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    imagen_model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-002")
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)
    return imagen_model, bucket

def generate_english_prompt(name, description):
    """【防弾ハック】items.pyと同じ実績を持つgemini-2.5-flashでプロンプトを錬金する"""
    prompt_for_gemini = (
        f"Convert the following Japanese product name and description into a clean, "
        f"highly detailed English prompt for an image generation model (Imagen 3). "
        f"The prompt MUST describe a realistic, casual product photography suitable for a flea market app like Mercari. "
        f"Do NOT use marketing buzzwords like 'photorealistic'. Focus only on descriptive visual elements.\n\n"
        f"Product Name: {name}\n"
        f"Description: {description}\n"
        f"Output ONLY the final English prompt string, nothing else."
    )
    try:
        # 💡 検証済みの共通clientから最新モデルをスナイプ
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_for_gemini
        )
        return response.text.strip()
    except Exception as e:
        print(f"⚠️ Geminiプロンプト生成エラー: {e}")
        return None

def process_single_item(item, imagen_model, bucket):
    item_id = item["id"]
    name = item["name"]
    description = item.get("description", "") or "公式カタログの良質な商品です。"
    
    print(f"🚀 [ID: {item_id}] 処理開始: {name[:15]}...")
    
    # 1. 修正された関数で英語プロンプトを生成
    eng_prompt = generate_english_prompt(name, description)
    if not eng_prompt:
        return item_id, "FAILED_PROMPT"
    
    # 2. フリマ味のエッセンスをブレンド
    bg_style = BACKGROUNDS[item_id % len(BACKGROUNDS)]
    final_prompt = (
        f"{eng_prompt}. A natural casual product photo for a marketplace listing, showing the item neatly arranged. "
        f"Placed on a {bg_style} background. Soft natural light from a side window with gentle shadows. "
        f"Authentic smartphone photography style, clean and relatable composition."
    )
    
    # 3. Imagen 3 で画像生成
    try:
        response = imagen_model.generate_images(
            prompt=final_prompt,
            number_of_images=1,
            aspect_ratio="1:1",
            language="en"
        )
        if not response.images:
            return item_id, "FAILED_IMAGEN_EMPTY"
        
        image_bytes = response.images[0]._image_bytes
    except Exception as e:
        print(f"❌ [ID: {item_id}] Imagen生成エラー: {e}")
        return item_id, "FAILED_IMAGEN_API"
    
    # 4. GCSへ高速アップロード
    try:
        filename = f"products/generated_{item_id}.png"
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type="image/png")
        gcs_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
    except Exception as e:
        print(f"❌ [ID: {item_id}] GCSアップロードエラー: {e}")
        return item_id, "FAILED_GCS"
    
    # 5. データベースの ai_image_url を更新
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE products SET ai_image_url = %s WHERE id = %s", (gcs_url, item_id))
        connection.commit()
        connection.close()
        print(f"✨ [ID: {item_id}] データベース新カラム更新完了！ -> {gcs_url}")
        return item_id, "SUCCESS"
    except Exception as e:
        print(f"❌ [ID: {item_id}] DB更新エラー: {e}")
        return item_id, "FAILED_DB"

def main():
    imagen_model, bucket = init_services()
    
    connection = get_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, name, description FROM products 
            WHERE ai_image_url IS NULL OR ai_image_url NOT LIKE %s
            ORDER BY id ASC
        """, (f"%storage.googleapis.com/{BUCKET_NAME}%",))
        items_to_process = cursor.fetchall()
    connection.close()
    
    total_count = len(items_to_process)
    print(f"📊 未処理の対象データが {total_count} 件見つかりました。一括変換パイプラインを起動します。")
    if total_count == 0:
        print("🎉 すべてのデータがすでにAI画像に置き換わっています！処理を終了します。")
        return

    success_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_single_item, item, imagen_model, bucket): item 
            for item in items_to_process
        }
        
        for future in as_completed(futures):
            item_id, status = future.result()
            if status == "SUCCESS":
                success_count += 1
            time.sleep(1.5)

    print(f"成功: {success_count} / 対象: {total_count}")

if __name__ == "__main__":
    main()