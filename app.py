import os
import json
import logging
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
)
import spots

app = Flask(__name__)

# LINE API認証情報（環境変数より取得）
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ユーザーお気に入りデータ保存用JSONファイル
FAVORITES_FILE = 'user_favorites.json'

def load_user_favorites():
    """ユーザーのお気に入りデータをファイルから読み込む"""
    if os.path.exists(FAVORITES_FILE):
        try:
            with open(FAVORITES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"お気に入りデータの読み込み失敗: {e}")
            return {}
    return {}

def save_user_favorites(data):
    """ユーザーのお気に入りデータをファイルへ保存する"""
    try:
        with open(FAVORITES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"お気に入りデータの保存失敗: {e}")

def resolve_spot_name(query):
    """入力キーワードから正式な釣り場名を解決する（エイリアス対応）"""
    query_clean = query.strip()
    if not query_clean:
        return None
    # 正式名称に直接合致
    if query_clean in spots.ALL_SPOT_DATA:
        return query_clean
    # エイリアス（ゆらぎ・略称）照合
    for formal_name, data in spots.ALL_SPOT_DATA.items():
        aliases = data.get('aliases', [])
        if query_clean.lower() in [a.lower() for a in aliases]:
            return formal_name
    return None

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()
    
    # お気に入り追加コマンド処理
    if text.startswith("追加"):
        parts = text.replace(' ', ' ').split()[1:]
        if not parts:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="⚠️ 追加したい釣り場名または都道府県名（例: 追加 埼玉）を入力してください。")
            )
            return

        # エリア（都道府県）展開と釣り場名の解決
        expanded_queries = []
        for p in parts:
            if p in spots.AREA_MAPPING:
                expanded_queries.extend(spots.AREA_MAPPING[p])
            else:
                expanded_queries.append(p)

        resolved_spots = []
        failed_queries = []
        for q in expanded_queries:
            formal_name = resolve_spot_name(q)
            if formal_name:
                if formal_name not in resolved_spots:
                    resolved_spots.append(formal_name)
            else:
                failed_queries.append(q)

        all_favs = load_user_favorites()
        user_favs = all_favs.get(user_id, [])

        # 重複を除く新規追加対象
        to_add = [s for s in resolved_spots if s not in user_favs]
        
        # 登録上限（30件）チェック - パターンA（安全ストップ型）
        current_count = len(user_favs)
        total_after_add = current_count + len(to_add)

        if total_after_add > 30:
            msg = (
                "⚠️ 登録上限（30箇所）を超えるため、追加処理を中断しました。\n"
                "━━━━━━━━━━━━━━━\n"
                f"現在の登録数: {current_count}/30箇所\n"
                f"追加対象数: {len(to_add)}箇所\n"
                f"追加後の合計: {total_after_add}箇所（上限超え）\n"
                "━━━━━━━━━━━━━━━\n"
                "お気に入りを削除してから再度実行してください。"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
            return

        # 30件以下の場合は正常追加
        user_favs.extend(to_add)
        all_favs[user_id] = user_favs
        save_user_favorites(all_favs)

        res_msg = f"✅ {len(to_add)}箇所追加しました: {', '.join(to_add) if to_add else 'なし'}\n"
        if failed_queries:
            res_msg += f"⚠️ スキップ・失敗: {', '.join(failed_queries)}\n"
        res_msg += f"📊 現在の登録数: {len(user_favs)}/30箇所"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res_msg))
        return

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
