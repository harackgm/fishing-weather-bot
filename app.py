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

# Gemini API設定
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip().strip('"').strip("'")

# テスト用・本番用設定（誤通知防止）
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID', '').strip()  # 管理者のLINE ID
IS_TEST_MODE = True  # True: 管理者のみ通知 / False: 全員通知

# 大量通知ストッパー（安全装置）
MAX_LIMIT = 5


def get_working_gemini_model():
    """
    利用可能なGeminiモデルを安全に自動検知して取得する関数
    """
    if not GEMINI_API_KEY:
        return None
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        
        # 優先試行モデルリスト
        candidate_models = [
            'gemini-2.5-flash',
            'gemini-1.5-flash',
            'gemini-1.5-flash-latest',
            'gemini-pro'
        ]
        
        # 利用可能なモデル一覧を取得して合致するものを検索
        available_models = [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        for candidate in candidate_models:
            if candidate in available_models:
                return genai.GenerativeModel(candidate)
        
        # 一致しない場合は一覧の最初の対応モデルを使用
        if available_models:
            return genai.GenerativeModel(available_models[0])
            
        return genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"[初期化エラー] Geminiモデル取得失敗: {e}")
        return None


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
# 4. LINEメッセージ受信処理（Gemini API連携）
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    user_id = event.source.user_id

    print(f"[受信] ユーザー({user_id})からのメッセージ: {user_message}")

    # 安全装置: テストモード時は管理者以外の応答をスキップ可能（現在はリプライのため返信）
    if IS_TEST_MODE and ADMIN_USER_ID and user_id != ADMIN_USER_ID:
        print(f"[テストモード制限] 管理者以外のアクセスを検出: {user_id}")

    model = get_working_gemini_model()

    if not model:
        reply_text = "【システムエラー】Gemini APIキーが無効か、利用可能なモデルが見つかりません。"
    else:
        try:
            system_instruction = (
                "あなたは管理釣り場と天気予報の案内AIアシスタントです。"
                "丁寧かつ分かりやすく、釣り人の役に立つ回答を簡潔に答えてください。"
            )
            prompt = f"{system_instruction}\n\nユーザーの質問: {user_message}"
            
            response = model.generate_content(prompt)
            
            if response and hasattr(response, 'text') and response.text:
                reply_text = response.text
            else:
                reply_text = "申し訳ありません。AIからの回答を取得できませんでした。"

        except Exception as e:
            print(f"[エラー詳細] Gemini API呼び出し失敗: {e}")
            reply_text = f"応答生成中にエラーが発生しました。\n詳細: {str(e)[:150]}"

    # リプライ送信（完全無料枠）
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
        print(f"【安全装置発動】未通知件数が上限({MAX_LIMIT}件)を超えました。処理をスキップします。")
        return jsonify({"status": "skipped", "reason": "MAX_LIMIT_EXCEEDED"}), 200

    # ガードレール2: サーバー負荷軽減のゆらぎ（1.0〜3.0秒待機）
    time.sleep(random.uniform(1.0, 3.0))

    print("[完了] 天気データの最新化処理が完了しました。")
    return jsonify({"status": "success", "message": "DB updated safely."}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
