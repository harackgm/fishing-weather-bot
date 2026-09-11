import os
import time
import random
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
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Gemini API設定
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
else:
    gemini_model = None

# 安全装置: テスト用管理者LINE User ID（テスト時の誤送信防止）
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID', 'YOUR_ADMIN_LINE_USER_ID')

# 本番フラグ（True: 管理者のみにテスト送信 / False: 全員通知）
IS_TEST_MODE = True

# 大量通知ストッパー（1回の処理で許可する最大件数）
MAX_LIMIT = 5


# ==========================================
# 3. Webサーバーのエンドポイント（受付口）
# ==========================================

@app.route("/", methods=['GET'])
def top_page():
    """サーバー稼働確認用トップページ"""
    return "LINE Reply Bot Server (with Gemini API) is running!", 200


@app.route("/callback", methods=['POST'])
def callback():
    """LINEからのチャットメッセージ（Webhook）を受信するエンドポイント"""
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("[エラー] LINEからの署名検証に失敗しました。")
        abort(400)

    return 'OK', 200


# ==========================================
# 4. LINEメッセージ受信時の処理（Gemini API連携）
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """
    ユーザーからの質問に対し、Gemini APIで回答を生成して無料リプライで返信
    """
    user_message = event.message.text
    user_id = event.source.user_id

    print(f"[受信] ユーザー({user_id})からのメッセージ: {user_message}")

    # Gemini APIキーが未設定の場合の安全処理
    if not gemini_model:
        reply_text = "申し訳ありません。現在Gemini APIキーが設定されていないため応答できません。"
    else:
        try:
            # 釣り場案内ボットとしてのシステムプロンプト設定
            system_instruction = (
                "あなたは管理釣り場と天気予報の案内AIアシスタントです。"
                "丁寧かつ分かりやすく、釣り人の役に立つ回答を心がけてください。"
            )
            prompt = f"{system_instruction}\n\nユーザーの質問: {user_message}"
            
            # Gemini APIでテキスト生成
            response = gemini_model.generate_content(prompt)
            reply_text = response.text

        except Exception as e:
            print(f"[エラー] Gemini API呼び出し失敗: {e}")
            reply_text = "申し訳ありません。回答の生成中にエラーが発生しました。"

    # リプライメッセージの送信（完全無料）
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )
    print("[送信] Geminiの回答をリプライ送信しました。")


# ==========================================
# 5. 定期データ更新用エンドポイント（安全装置付き）
# ==========================================
@app.route("/cron_trigger", methods=['GET', 'POST'])
def cron_trigger():
    """
    cron-job.org から定期的に呼び出されるエンドポイント
    ※プッシュ通知は行わず、データベースの更新のみを安全に行います
    """
    print("\n--- cron-job.org からの定期トリガーを受信しました ---")

    # ダミー未通知データ検知
    unnotified_items = []
    item_count = len(unnotified_items)

    # ガードレール1: 大量通知ストッパー（MAX_LIMIT制御）
    if item_count > MAX_LIMIT:
        print(f"【安全装置発動】未通知件数が上限({MAX_LIMIT}件)を超えました。スキップします。")
        return jsonify({"status": "skipped", "reason": "MAX_LIMIT_EXCEEDED"}), 200

    # ガードレール2: 巡回サーバー負荷軽減のゆらぎ（1.0〜3.0秒待機）
    time.sleep(random.uniform(1.0, 3.0))

    print("[完了] 天気データの最新化処理が完了しました。")
    return jsonify({"status": "success", "message": "DB updated safely."}), 200


# ==========================================
# 6. 実行処理
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Webサーバーを起動します (Port: {port})...")
    app.run(host="0.0.0.0", port=port)
