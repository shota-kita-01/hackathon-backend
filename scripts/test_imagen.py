import os
import vertexai
from vertexai.vision_models import ImageGenerationModel

def run_experiment():
    PROJECT_ID = "term9-shota-kita"
    LOCATION = "us-central1"
    
    print("Vertex AIを初期化中...")
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    
    print("Imagen 3 モデルをロード中")
    model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-002")
    
    # デモ用のプロンプト
    prompt = (
        "A high-quality casual product photo for a flea market marketplace listing, "
        "showing a pair of premium red running sneakers neatly arranged next to each other. "
        "Placed on a light-colored wooden flooring background. "
        "Soft natural light coming from a side window, casting realistic gentle shadows. "
        "Authentic smartphone photography style, detailed fabric texture, clean and relatable."
    )
    
    print("Imagen 3 で画像を生成中...")
    try:
        response = model.generate_images(
            prompt=prompt,
            number_of_images=1,
            aspect_ratio="1:1",
            language="en",
        )
        
        if response.images:
            output_path = os.path.join(os.path.dirname(__file__), "../test_generated_sneaker.png")
            
            response.images[0].save(location=output_path, include_generation_parameters=False)
            print(f"成功しました。画像は以下に保存されました:\n {os.path.abspath(output_path)}")
        else:
            print("画像の生成結果が空でした")
            
    except Exception as e:
        print(f"エラーが発生しました: {str(e)}")

if __name__ == "__main__":
    run_experiment()