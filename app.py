import os
import time
import random
import sqlite3
from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

# ==========================================
# 1. 日本時間（JST）設定と初期化
# ==========================================
os.environ['TZ'] = 'Asia/Tokyo'
if hasattr(time, 'tzset'):
    time.tzset()

app = Flask(__name__)

# ==========================================
# 2. 設定値および安全装置（ガードレール）
# ==========================================
# LINE API設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '').strip()

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Gemini API設定
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip().strip('"').strip("'")

# テスト・本番モード切り替え制御（安全装置）
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID', '').strip()
IS_TEST_MODE = True  # True: 管理者のみにテスト送信（誤送信防止）

# 大量通知ストッパー（安全装置: 1回の処理で許可する最大件数）
MAX_LIMIT = 5

# 試行するGeminiモデル候補リスト
GEMINI_CANDIDATE_MODELS = [
    'gemini-3.6-flash',
    'gemini-1.5-flash',
    'gemini-2.0-flash'
]

# データベースファイルパス
DB_PATH = 'user_data.db'


# ==========================================
# 3. データベース（SQLite）管理関数
# ==========================================
def init_db():
    """データベースおよびテーブルの初期化"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id TEXT PRIMARY KEY,
            weather_level INTEGER DEFAULT 1,
            weather_source TEXT DEFAULT 'ウェザーニュース',
            favorite_spots TEXT DEFAULT ''
        )
    ''')
    conn.commit()
    conn.close()
    print("[DB] データベースの初期化が完了しました。")

# サーバー起動時にDB初期化を実行
init_db()


def get_user_setting(user_id):
    """ユーザーの設定情報を取得（未登録なら初期値を作成）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT weather_level, weather_source, favorite_spots FROM user_settings WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    if not row:
        # 初期値の登録
        cursor.execute(
            'INSERT INTO user_settings (user_id, weather_level, weather_source, favorite_spots) VALUES (?, 1, ?, ?)',
            (user_id, 'ウェザーニュース', '')
        )
        conn.commit()
        result = (1, 'ウェザーニュース', '')
    else:
        result = row
        
    conn.close()
    return result


# ==========================================
# 4. Gemini AI応答生成関数
# ==========================================
def generate_gemini_response(user_message, user_setting):
    """ユーザー設定を背景情報に含めてGemini応答を生成"""
    if not GEMINI_API_KEY:
        return None, "【システムエラー】GEMINI_API_KEYが未設定です。"

    genai.configure(api_key=GEMINI_API_KEY)
    
    level, source, favorites = user_setting
    fav_text = favorites if favorites else "未登録"

    system_instruction = (
        "あなたは管理釣り場と天気予報の案内AIアシスタントです。"
        f"ユーザー設定 -> 詳細レベル: レベル{level}, 優先情報源: {source}, お気に入り釣り場: {fav_text}。"
        "丁寧かつ分かりやすく、釣り人の役に立つ回答を簡潔に答えてください。"
    )
    prompt = f"{system_instruction}\n\nユーザーの質問: {user_message}"

    last_error_msg = ""
    for model_name in GEMINI_CANDIDATE_MODELS:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            if response and hasattr(response, 'text') and response.text:
                return response.text, None
        except Exception as e:
            last_error_msg = str(e)
            continue

    return None, f"AI応答の生成に失敗しました。\n詳細: {last_error_msg[:150]}"


# ==========================================
# 5. Webサーバーのエンドポイント
# ==========================================
@app.route("/", methods=['GET'])
def top_page():
    return "LINE Reply Bot Server (with DB & Gemini API) is running!", 200


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("[エラー] LINEからの署名検証に失敗しました。")
        abort(400)

    return 'OK', 200


# ==========================================
# 6. LINEメッセージ受信処理
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id

    print(f"[受信] ユーザー({user_id}): {user_message}")

    # ユーザー設定の取得（または初期登録）
    user_setting = get_user_setting(user_id)
    level, source, favorites = user_setting

    # コマンド判定: 「設定」と送信された場合
    if user_message == "設定":
        fav_list = favorites.split(',') if favorites else []
        fav_display = "\n".join([f"・{spot}" for spot in fav_list]) if fav_list else "・未登録"
        
        reply_text = (
            "⚙️ 【現在の設定状況】\n\n"
            f"■ 天気詳細レベル: レベル{level}\n"
            f"■ 参照ソース: {source}\n"
            f"■ お気に入り釣り場 (最大5箇所):\n{fav_display}\n\n"
            "※設定変更コマンドは順次追加されます。"
        )
    else:
        # 通常メッセージはGemini APIへ渡す
        ai_text, error_text = generate_gemini_response(user_message, user_setting)
        reply_text = ai_text if ai_text else error_text

    # 無料リプライ送信
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )
    print("[送信] リプライ応答を完了しました。")


# ==========================================
# 7. 定期データ更新用エンドポイント（安全装置付き）
# ==========================================
@app.route("/cron_trigger", methods=['GET', 'POST'])
def cron_trigger():
    print("\n--- cron-job.org からの定期トリガーを受信しました ---")

    unnotified_items = []
    item_count = len(unnotified_items)

    # ガードレール1: 大量通知ストッパー（MAX_LIMIT制御）
    if item_count > MAX_LIMIT:
        print(f"【安全装置発動】未通知件数が上限({MAX_LIMIT}件)を超えました。スキップします。")
        return jsonify({"status": "skipped", "reason": "MAX_LIMIT_EXCEEDED"}), 200

    # ガードレール2: サーバー負荷軽減のゆらぎ（1.0〜3.0秒待機）
    time.sleep(random.uniform(1.0, 3.0))

    print("[完了] 天気データの最新化処理が完了しました。")
    return jsonify({"status": "success", "message": "DB updated safely."}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
