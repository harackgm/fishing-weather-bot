import os
import time
from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# ==========================================
# 1. 日本時間（JST）設定と初期化
# ==========================================
os.environ['TZ'] = 'Asia/Tokyo'
if hasattr(time, 'tzset'):
    time.tzset()

app = Flask(__name__)

# ==========================================
# 2. LINE API設定
# ==========================================
# 環境変数から取得、未設定時はダミー文字列
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ==========================================
# 3. Webサーバーのエンドポイント（受付口）
# ==========================================

@app.route("/", methods=['GET'])
def top_page():
    """サーバー稼働確認用トップページ"""
    return "LINE Reply Bot Server is running!", 200

@app.route("/callback", methods=['POST'])
def callback():
    """
    LINEからのチャットメッセージ（Webhook）を受信するエンドポイント
    """
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("[エラー] LINEからの署名検証に失敗しました。")
        abort(400)

    return 'OK', 200

# ==========================================
# 4. LINEメッセージ受信時の処理（リプライ）
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """
    ユーザーからテキストメッセージを受け取った際の処理
    ※プッシュ通知（課金対象）ではなく、リプライ（無料）で返信します
    """
    user_message = event.message.text
    user_id = event.source.user_id
    
    print(f"[受信] ユーザー({user_id})からのメッセージ: {user_message}")

    # 現在はテストとして、受け取った言葉に応じた仮の返答をするエコーボットとして機能させます
    # （最終的にはここでGemini APIを呼び出し、天気データを返します）
    reply_text = f"【テスト返信】\n「{user_message}」と送信されました。\n※将来的にここにGeminiが生成した天気予報が入ります。"

    # リプライメッセージの送信（無料）
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )
    print("[送信] リプライメッセージを送信しました。")

# ==========================================
# 5. 定期データ更新用エンドポイント（通知はしない）
# ==========================================
@app.route("/cron_trigger", methods=['GET', 'POST'])
def cron_trigger():
    """
    cron-job.org から定期的に呼び出されるエンドポイント
    ※プッシュ通知は行わず、天気データの最新化（裏側のDB更新）のみを行います
    """
    print("\n--- cron-job.org からの定期トリガーを受信しました ---")
    print("[処理] 最新の天気予報データを取得し、データベースを更新します...（ダミー処理）")
    
    # サーバー負荷軽減のゆらぎ処理（1.0〜3.0秒のランダム待機）
    time.sleep(2.0)
    
    print("[完了] データベースの更新が完了しました。ユーザーへの通知は行いません。")
    return jsonify({"status": "success", "message": "DB update completed without push notification."}), 200

# ==========================================
# 6. 実行処理
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Webサーバーを起動します (Port: {port})...")
    app.run(host="0.0.0.0", port=port)
