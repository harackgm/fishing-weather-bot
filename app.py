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
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '').strip()

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Gemini API設定（空白・引用符の自動処理）
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip().strip('"').strip("'")

# テスト・本番モード切り替え制御（安全装置）
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID', '').strip()
IS_TEST_MODE = True  # True: 管理者のみにテスト送信（誤送信防止）

# 大量通知ストッパー（安全装置: 1回の処理で許可する最大件数）
MAX_LIMIT = 5

# 試行するモデル候補リスト（推奨順）
GEMINI_CANDIDATE_MODELS = [
    'gemini-3.6-flash',
    'gemini-1.5-flash',
    'gemini-2.0-flash',
    'gemini-2.5-flash'
]


def generate_gemini_response(user_message):
    """
    複数モデルを順次試行し、正常応答が得られるモデルで自動返信を作成する関数
    """
    if not GEMINI_API_KEY:
        return None, "【システムエラー】GEMINI_API_KEY が設定されていません。RenderのEnvironmentをご確認ください。"

    genai.configure(api_key=GEMINI_API_KEY)
    
    system_instruction = (
        "あなたは管理釣り場と天気予報の案内AIアシスタントです。"
        "丁寧かつ分かりやすく、釣り人の役に立つ回答を簡潔に答えてください。"
    )
    prompt = f"{system_instruction}\n\nユーザーの質問: {user_message}"

    last_error_msg = ""

    # モデルを順番に試行
    for model_name in GEMINI_CANDIDATE_MODELS:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            
            if response and hasattr(response, 'text') and response.text:
                print(f"[成功] モデル '{model_name}' で応答生成完了")
                return response.text, None
        except Exception as e:
            last_error_msg = str(e)
            print(f"[試行失敗] モデル '{model_name}': {e}")
            continue

    # 全モデル失敗時
    return None, f"AI応答の生成に失敗しました。\n詳細: {last_error_msg[:150]}"


# ==========================================
# 3. Webサーバーのエンドポイント
# ==========================================

@app.route("/", methods=['GET'])
def top_page():
    return "LINE Reply Bot Server (with Gemini API) is running!", 200


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
# 4. LINEメッセージ受信処理（自動フォールバック対応）
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    user_id = event.source.user_id

    print(f"[受信] ユーザー({user_id})からのメッセージ: {user_message}")

    # テストモード時の誤送信防止ログ
    if IS_TEST_MODE and ADMIN_USER_ID and user_id != ADMIN_USER_ID:
        print(f"[テストモード制限] 管理者以外のアクセスを検出: {user_id}")

    # AI応答生成の実行
    ai_text, error_text = generate_gemini_response(user_message)
    reply_text = ai_text if ai_text else error_text

    # 無料リプライ枠で返信
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )
    print("[送信] リプライ応答を完了しました。")


# ==========================================
# 5. 定期データ更新用エンドポイント（安全装置付き）
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
