-- 1. ユーザーテーブルの作成
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL
);

-- 2. 商品テーブルの作成
CREATE TABLE IF NOT EXISTS items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    price INT NOT NULL,
    image_url VARCHAR(511) NOT NULL,
    seller_id INT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'on_sale',
    FOREIGN KEY (seller_id) REFERENCES users(id)
);

-- 3. 購入履歴テーブルの作成
CREATE TABLE IF NOT EXISTS purchases (
    id INT AUTO_INCREMENT PRIMARY KEY,
    item_id INT NOT NULL,
    buyer_id INT NOT NULL,
    purchased_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (item_id) REFERENCES items(id),
    FOREIGN KEY (buyer_id) REFERENCES users(id)
);

-- 4. AIレコメンドテーブルの作成
CREATE TABLE IF NOT EXISTS recommendations (
    user_id INT NOT NULL,
    item_id INT NOT NULL,
    score FLOAT NOT NULL,
    PRIMARY KEY (user_id, item_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (item_id) REFERENCES items(id)
);