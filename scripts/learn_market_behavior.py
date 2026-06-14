import json
import numpy as np
import pandas as pd

# ログを動的にカテゴリ数を出すように修正
print("マルコフ遷移確率行列の学習を開始...")

# 1. 収穫済みの行動ログ（CSV）を読み込む
df = pd.read_csv("amazon_review_samples.csv")
all_categories = sorted(df["ai_category"].unique())

print(f"   ➔ 検出されたカテゴリー数: {len(all_categories)}")

# 2. 擬似タイムラインの合成
df["pseudo_user"] = df["user_id"].apply(lambda x: f"user_{abs(hash(str(x))) % 100:03d}")

# ユーザーごと、タイムスタンプ順（古い順）に厳密ソート
df = df.sort_values(by=["pseudo_user", "timestamp"]).reset_index(drop=True)

# 3. 現在のアクションと「次のアクション」「次の時間」をシフト
df["current_cat"] = df["ai_category"]
df["next_cat"] = df.groupby("pseudo_user")["ai_category"].shift(-1)
df["next_timestamp"] = df.groupby("pseudo_user")["timestamp"].shift(-1)

# 次の行動がない行（終端）をドロップ
df_transitions = df.dropna(subset=["next_cat", "next_timestamp"]).copy()

# 4. 時間窓（Time Window）フィルターの適用
ONE_WEEK_SECONDS = 7 * 24 * 60 * 60
df_transitions["time_diff"] = df_transitions["next_timestamp"] - df_transitions["timestamp"]

# 1週間以内の連続した回遊行動のみを「真の遷移」として抽出
df_valid_transitions = df_transitions[df_transitions["time_diff"] <= ONE_WEEK_SECONDS].copy()

# 6,600件の固定表示を、実際のCSV行数（len(df)）に書き換えて動的化！
print(f"   ➔  {len(df)} 件の行動ログから、1週間以内の結びつきを {len(df_valid_transitions)} 件検出")

# 5. 22×22 の遷移カウントマトリクスの作成
count_matrix = pd.crosstab(
    df_valid_transitions["current_cat"], 
    df_valid_transitions["next_cat"]
).reindex(index=all_categories, columns=all_categories, fill_value=0).astype(float)

# 6. 尖らせるための極小ラプラス平滑化 (α = 0.005)
alpha = 0.005
smoothed_counts = count_matrix + alpha

# 行ごとに確率の和が1になるよう正規化
transition_matrix = smoothed_counts.div(smoothed_counts.sum(axis=1), axis=0)

# 7. 保存
matrix_dict = transition_matrix.to_dict(orient="index")
with open("markov_transition_matrix.json", "w", encoding="utf-8") as f:
    json.dump(matrix_dict, f, ensure_ascii=False, indent=2)

print("\n" + "="*50)
print("時間窓補正済みマルコフ行動モデルが完成")
print("="*50)

# プレビュー表示
print("[学習した上位の買い回りルート]:")
for current, rows in matrix_dict.items():
    top_next = sorted([(prob, cat) for cat, prob in rows.items() if cat != current], reverse=True)[0]
    if top_next[0] > (1.0 / len(all_categories)):
        print(f"  ・ [{current}] ➔ 1週間以内に [{top_next[1]}] へ回遊しやすい (確率: {top_next[0]:.1%})")