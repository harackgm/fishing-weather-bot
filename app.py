import os
import time
import random
import requests
import traceback
import difflib
from bs4 import BeautifulSoup
from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from supabase import create_client, Client

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
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '').strip()

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

ADMIN_USER_ID = os.getenv('ADMIN_USER_ID', '').strip()
IS_TEST_MODE = True  # テストモード（Trueの場合、ADMIN_USER_IDのみに通知送信）
MAX_LIMIT = 5        # 大量通知ストッパー（1回の処理上限数）

# Supabase接続初期化
SUPABASE_URL = os.getenv('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '').strip()

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"[Supabase初期化エラー] {e}")

# ==========================================
# 3. 釣り場URLおよび表記揺れ（エイリアス）辞書
# ==========================================
# url: スクレイピング先URL
# aliases: ユーザーが入力しそうな表記揺れ（ひらがな、略称、正式名称など）
SPOT_WEATHER_DATA = {
    "東山湖": {
        "url": "https://weathernews.jp/onebox/35.296739/138.955925/",
        "aliases": ["東山湖", "東山湖フィッシングエリア", "ひがしやまこ", "ひがしやま", "東山"]
    },
    "キングフィッシャー": {
        "url": "https://weathernews.jp/onebox/36.907054/140.078650/",
        "aliases": ["キングフィッシャー", "キング", "キングフィッシャ", "きんぐふぃっしゃー"]
    },
    "加賀": {
        "url": "https://weathernews.jp/onebox/36.388609/139.537247/",
        "aliases": ["加賀", "加賀フィッシングエリア", "加賀FA", "かが", "加賀FA"]
    },
    "すその": {
        "url": "https://weathernews.jp/onebox/35.166667/138.899162/",
        "aliases": ["すその", "すそのフィッシングパーク", "すそのFP", "裾野"]
    },
    "朝霞": {
        "url": "https://weathernews.jp/onebox/35.813481/139.604736/",
        "aliases": ["朝霞", "朝霞ガーデン", "あさか", "あさかガーデン"]
    },
    "開成": {
        "url": "https://weathernews.jp/onebox/35.334342/139.130344/",
        "aliases": ["開成", "開成水辺フォレストスプリングス", "開成FS", "かいせい"]
    },
    "王禅寺": {
        "url": "https://weathernews.jp/onebox/35.587020/139.524309/",
        "aliases": ["王禅寺", "ベリーパーク in 王禅寺", "おうぜんじ", "王禅寺ベリーパーク"]
    },
    "白河": {
        "url": "https://weathernews.jp/onebox/37.127955/140.081827/",
        "aliases": ["白河", "白河フォレストスプリングス", "白河FS", "しらかわ"]
    },
    "発光路": {
        "url": "https://weathernews.jp/onebox/36.580281/139.532829/",
        "aliases": ["発光路", "発光路の森", "発光路の森ファアルクス", "ほっこうじ"]
    },
    "鹿島槍": {
        "url": "https://weathernews.jp/onebox/36.548940/137.809757/",
        "aliases": ["鹿島槍", "鹿島槍ガーデン", "かしまやり"]
    },
    "平谷湖": {
        "url": "https://weathernews.jp/onebox/35.332243/137.632213/",
        "aliases": ["平谷湖", "平谷湖フィッシングスポット", "ひらやこ"]
    },
    "サンクチュアリ": {
        "url": "https://weathernews.jp/onebox/35.187504/136.457803/",
        "aliases": ["サンクチュアリ", "サンク", "さんくちゅあり"]
    },
    "不忘": {
        "url": "https://weathernews.jp/onebox/38.042491/140.554478/",
        "aliases": ["不忘", "グリーンコンプラザ不忘", "ふぼう"]
    },
    "上浜": {
        "url": "https://weathernews.jp/onebox/39.142616/139.945938/",
        "aliases": ["上浜", "上浜釣り場", "かみはま"]
    },
    "ほのぼの": {
        "url": "https://weathernews.jp/onebox/36.837687/140.472433/",
        "aliases": ["ほのぼの", "ほのぼのプール", "ほのぼの"]
    },
    "WaDoNa": {
        "url": "https://weathernews.jp/onebox/36.877372/140.540954/",
        "aliases": ["WaDoNa", "ワドナ", "わどな"]
    },
    "鬼怒川": {
        "url": "https://weathernews.jp/onebox/36.617621/139.937106/",
        "aliases": ["鬼怒川", "鬼怒川フィッシングエリア", "鬼怒川FA", "きぬがわ"]
    }
}

# 簡易互換用の辞書（既存のコード構造を壊さないためのマッピング）
SPOT_WEATHER_URLS = {spot: data["url"] for spot, data in SPOT_WEATHER_DATA.items()}


def find_best_match_spot(user_text):
    """ユーザー入力から最適な釣り場名を推完・検索する高度なゆらぎ検索判定"""
    text = user_text.strip().lower()

    # 1. エイリアス完全・部分一致検索
    for spot_key, data in SPOT_WEATHER_DATA.items():
        for alias in data["aliases"]:
            alias_lower = alias.lower()
            if alias_lower in text or text in alias_lower:
                return spot_key, data["url"]

    # 2. あいまい類似度検索 (difflib)
    all_aliases = []
    alias_to_spot = {}
    for spot_key, data in SPOT_WEATHER_DATA.items():
        for alias in data["aliases"]:
            all_aliases.append(alias.lower())
            alias_to_spot[alias.lower()] = (spot_key, data["url"])

    matches = difflib.get_close_matches(text, all_aliases, n=1, cutoff=0.5)
    if matches:
        matched_alias = matches[0]
        return alias_to_spot[matched_alias]

    return None, None

# ==========================================
# 4. Supabase データベース管理関数
# ==========================================
def get_user_setting(user_id):
    if not supabase:
        return ('ウェザーニュース', '')
    try:
        res = supabase.table('user_settings').select('*').eq('user_id', user_id).execute()
        if not res.data:
            supabase.table('user_settings').insert({
                'user_id': user_id,
                'weather_source': 'ウェザーニュース',
                'favorite_spots': ''
            }).execute()
            return ('ウェザーニュース', '')
        row = res.data[0]
        return (row.get('weather_source', 'ウェザーニュース'), row.get('favorite_spots', ''))
    except Exception as e:
        print(f"[Supabase取得エラー] {e}")
        return ('ウェザーニュース', '')

def add_favorite_spot(user_id, spot_name):
    if not supabase: return False, "DB接続未完了です。"
    
    # 追加時もゆらぎ検索を通して正しい正式名称に変換
    matched_spot, _ = find_best_match_spot(spot_name)
    target_name = matched_spot if matched_spot else spot_name

    _, favorites = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    if target_name in fav_list:
        return False, f"「{target_name}」はすでに登録されています。"
    if len(fav_list) >= 5:
        return False, "お気に入り釣り場は最大5箇所まで登録可能です。"
    
    fav_list.append(target_name)
    try:
        supabase.table('user_settings').update({'favorite_spots': ','.join(fav_list)}).eq('user_id', user_id).execute()
        return True, f"「{target_name}」をお気に入りに追加しました。"
    except Exception as e:
        return False, f"保存に失敗しました: {e}"

def remove_favorite_spot(user_id, spot_name):
    if not supabase: return False, "DB接続未完了です。"
    
    matched_spot, _ = find_best_match_spot(spot_name)
    target_name = matched_spot if matched_spot else spot_name

    _, favorites = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    if target_name not in fav_list:
        return False, f"「{target_name}」は登録されていません。"
    
    fav_list.remove(target_name)
    try:
        supabase.table('user_settings').update({'favorite_spots': ','.join(fav_list)}).eq('user_id', user_id).execute()
        return True, f"「{target_name}」をお気に入りから削除しました。"
    except Exception as e:
        return False, f"削除に失敗しました: {e}"

# ==========================================
# 5. ウェザーニュース 実データスクレイピング関数
# ==========================================
def fetch_spot_1hour_data(url):
    """指定されたURLから現在時刻以降の予報を取得（6〜21時抽出版）"""
    time.sleep(random.uniform(1.0, 2.5))  # ゆらぎ待機
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    try:
        response = requests.get(url, headers=headers, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        flick_list = soup.find('div', id='flick_list_1hour')
        if not flick_list: return None

        weather_by_date = {}
        groups = flick_list.find_all('div', class_='group')

        for group in groups:
            date_tag = group.find('div', class_='date')
            if not date_tag: continue
            date_str = date_tag.text.strip()
            
            daily_list = []
            lists = group.find_all('ul', class_='list')
            for item in lists:
                if 'past' in item.get('class', []):
                    continue
                
                time_tag = item.find('li', class_='time')
                hour_str = time_tag.text.strip() if time_tag else ""
                if not hour_str.isdigit(): continue
                
                hour_int = int(hour_str)
                if not (6 <= hour_int <= 21): 
                    continue
                    
                hour = f"{hour_int:02d}時"
                
                img_url = "https://gvs.weathernews.jp/onebox/img/wxicon/200.png"
                weather_tag = item.find('li', class_='weather')
                img_tag = weather_tag.find('img') if weather_tag else None
                if img_tag and 'src' in img_tag.attrs:
                    src = img_tag['src']
                    if src.startswith('//'): img_url = "https:" + src
                    elif src.startswith('/'): img_url = "https://weathernews.jp" + src
                    else: img_url = src
                img_url = img_url.replace("http://", "https://")

                rain = item.find('li', class_='rain').text.strip().replace("ミリ", "mm") if item.find('li', class_='rain') else "-"
                temp = item.find('li', class_='temp').text.strip() if item.find('li', class_='temp') else "-"
                wind_p = item.find('li', class_='wind').find('p') if item.find('li', class_='wind') else None
                wind = wind_p.text.strip() if wind_p else "-"

                daily_list.append({
                    "time": hour,
                    "img_url": img_url,
                    "temp": temp,
                    "rain": rain,
                    "wind": wind
                })
            
            if daily_list:
                weather_by_date[date_str] = daily_list
            
            if len(weather_by_date) >= 4:
                break
            
        return weather_by_date
    except Exception as e:
        print(f"[スクレイピングエラー] {e}")
        return None

def build_grid_flex_message(spot_name, weather_by_date):
    """田の字型（2行×2列）グリッドレイアウト"""
    dates = list(weather_by_date.keys())
    
    def create_day_column(date_str):
        if not date_str:
            return {
                "type": "box", "layout": "vertical", "flex": 1, 
                "contents": [{"type": "text", "text": "-", "color": "#cccccc", "align": "center", "size": "xs"}]
            }
            
        daily_data = weather_by_date[date_str]
        rows = [
            {
                "type": "box", "layout": "horizontal", "margin": "none",
                "contents": [
                    {"type": "text", "text": "時", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "天", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "℃", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "mm", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "m", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"}
                ]
            },
            {"type": "separator", "margin": "xs"}
        ]
        
        for data in daily_data:
            t_val = data.get('temp', '').replace("℃", "").strip() or "-"
            r_val = data.get('rain', '').replace("mm", "").strip() or "-"
            w_val = data.get('wind', '').replace("m/s", "").replace("m", "").strip() or "-"
            time_str = data.get('time', '').replace("時", "").strip() or "-"
            img_url = data.get('img_url', '') or "https://gvs.weathernews.jp/onebox/img/wxicon/200.png"
            
            temp_color = "#ff0000" if t_val.isdigit() and int(t_val) >= 25 else "#333333"
            rain_color = "#0000ff" if r_val.isdigit() and int(r_val) > 0 else "#333333"
            if r_val == "-": rain_color = "#333333"

            rows.append({
                "type": "box", "layout": "horizontal", "margin": "xs", "alignItems": "center",
                "contents": [
                    {"type": "text", "text": time_str, "size": "xs", "flex": 1, "align": "center", "weight": "bold"},
                    {"type": "image", "url": img_url, "size": "xs", "flex": 1, "align": "center"},
                    {"type": "text", "text": t_val, "size": "xs", "flex": 1, "align": "center", "color": temp_color},
                    {"type": "text", "text": r_val, "size": "xs", "flex": 1, "align": "center", "color": rain_color},
                    {"type": "text", "text": w_val, "size": "xs", "flex": 1, "align": "center"}
                ]
            })
            
        return {
            "type": "box", "layout": "vertical", "flex": 1,
            "contents": [
                {
                    "type": "box", "layout": "vertical", "backgroundColor": "#e6f2ff", "paddingAll": "4px", "margin": "sm",
                    "contents": [
                        {"type": "text", "text": date_str, "weight": "bold", "size": "sm", "align": "center", "color": "#0066cc"}
                    ]
                }
            ] + [{"type": "box", "layout": "vertical", "spacing": "none", "margin": "sm", "contents": rows}]
        }

    body_contents = []

    # 1行目（上段）
    row1 = {
        "type": "box", "layout": "horizontal", "spacing": "sm",
        "contents": [
            create_day_column(dates[0] if len(dates) > 0 else None),
            {"type": "separator"},
            create_day_column(dates[1] if len(dates) > 1 else None)
        ]
    }
    body_contents.append(row1)

    # 2行目（下段）
    if len(dates) > 2:
        body_contents.append({"type": "separator", "margin": "md"})
        row2 = {
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "contents": [
                create_day_column(dates[2] if len(dates) > 2 else None),
                {"type": "separator"},
                create_day_column(dates[3] if len(dates) > 3 else None)
            ]
        }
        body_contents.append(row2)

    bubble = {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#0066cc", "paddingAll": "12px",
            "contents": [
                {"type": "text", "text": f"📍 {spot_name}", "color": "#ffffff", "weight": "bold", "size": "md"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "8px",
            "contents": body_contents
        }
    }
    return FlexSendMessage(alt_text=f"{spot_name}の天気予報(4日間)", contents=bubble)

# ==========================================
# 6. Webサーバーのエンドポイント
# ==========================================
@app.route("/", methods=['GET'])
def top_page():
    return "LINE Reply Bot Server (Supabase DB) is running!", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK', 200

# ==========================================
# 7. LINEメッセージ受信処理（ゆらぎ検索統合版）
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        user_message = event.message.text.strip()
        user_id = event.source.user_id

        print(f"[受信] ユーザー({user_id}): {user_message}")

        # 1. ユーザーコマンド優先判定
        if user_message == "設定":
            user_setting = get_user_setting(user_id)
            source, favorites = user_setting
            fav_list = [s for s in favorites.split(',') if s]
            fav_display = "\n".join([f"・{spot}" for spot in fav_list]) if fav_list else "・未登録"
            reply_text = (
                "⚙️ 【現在の設定状況】\n\n"
                "■ 天気詳細度: 常に最詳細モード\n"
                f"■ 参照ソース: {source}\n"
                f"■ お気に入り釣り場:\n{fav_display}\n\n"
                "【設定変更コマンド】\n"
                "・「追加:釣り場名」\n"
                "・「削除:釣り場名」"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        elif user_message.startswith("追加:"):
            spot_name = user_message.replace("追加:", "").strip()
            success, msg = add_favorite_spot(user_id, spot_name) if spot_name else (False, "⚠️ 釣り場名を入力してください。")
            reply_text = f"✅ {msg}" if success else f"⚠️ {msg}"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        elif user_message.startswith("削除:"):
            spot_name = user_message.replace("削除:", "").strip()
            success, msg = remove_favorite_spot(user_id, spot_name) if spot_name else (False, "⚠️ 削除する釣り場名を入力してください。")
            reply_text = f"✅ {msg}" if success else f"⚠️ {msg}"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        # 2. ゆらぎ検索（エイリアス＋あいまい一致）で釣り場判定
        target_spot_name, target_url = find_best_match_spot(user_message)

        if target_url:
            weather_by_date = fetch_spot_1hour_data(target_url)
            if weather_by_date:
                flex_msg = build_grid_flex_message(target_spot_name, weather_by_date)
                line_bot_api.reply_message(event.reply_token, flex_msg)
                print(f"[送信] {target_spot_name}の Grid FlexMessage応答を完了しました。")
            else:
                error_msg = f"⚠️ 【{target_spot_name}】の天気データの取得に失敗しました。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=error_msg))
            return
            
        # 3. 該当なしの場合
        reply_text = (
            "🔍 その釣り場は現在対応していません、もしくは名前が間違っています。\n\n"
            "【対応済みの主な釣り場】\n"
            "東山湖 / キングフィッシャー / 加賀 / すその / 朝霞 / 開成 / 王禅寺 / 白河...などに対応！\n\n"
            "※略称やひらがなでも検索できます（例: 「ひがしやまこ」「加賀FA」など）"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

    except Exception as e:
        print("\n=== システムエラー詳細 ===")
        traceback.print_exc()
        print("==========================\n")
        try:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 処理中にエラーが発生しました。時間を置いて再度お試しください。"))
        except Exception:
            pass

# ==========================================
# 8. 定期トリガーエンドポイント（Cron自動通知用）
# ==========================================
@app.route("/cron_trigger", methods=['GET', 'POST'])
def cron_trigger():
    print("\n--- 定期トリガーを受信しました ---")
    if not supabase:
        return jsonify({"status": "error", "reason": "DB_NOT_CONNECTED"}), 500

    try:
        res = supabase.table('user_settings').select('*').execute()
        users = res.data or []

        # テストモード安全ガード: IS_TEST_MODE が True の場合は ADMIN_USER_ID のみに絞り込み
        if IS_TEST_MODE:
            print(f"[テストモード有効] 送信対象を管理者({ADMIN_USER_ID})のみに絞り込みます。")
            users = [u for u in users if u.get('user_id') == ADMIN_USER_ID]
            if not users and ADMIN_USER_ID:
                users = [{'user_id': ADMIN_USER_ID, 'favorite_spots': ''}]

        # 大量通知ストッパー（安全装置）
        if len(users) > MAX_LIMIT:
            print(f"[安全装置作動] 対象件数({len(users)}件)が上限({MAX_LIMIT}件)を超えたためスキップします。")
            return jsonify({"status": "skipped", "reason": "MAX_LIMIT_EXCEEDED"}), 200

        print(f"配信対象件数: {len(users)}件")

        for user in users:
            uid = user.get('user_id')
            _, favorites = get_user_setting(uid)
            fav_list = [s for s in favorites.split(',') if s]

            if not fav_list:
                print(f"ユーザー({uid}): お気に入り未登録のためスキップ")
                continue

            for spot_name in fav_list:
                # ゆらぎ検索を通してURLを取得
                matched_spot, url = find_best_match_spot(spot_name)
                if not url:
                    continue

                print(f"ユーザー({uid}) へ 「{matched_spot}」 の定期通知を処理中...")
                weather_data = fetch_spot_1hour_data(url)
                if weather_data:
                    flex_msg = build_grid_flex_message(matched_spot, weather_data)
                    line_bot_api.push_message(uid, flex_msg)
                    print(f"-> 「{matched_spot}」 のPush送信成功")
                
                time.sleep(random.uniform(1.5, 3.0))

        return jsonify({"status": "success", "processed_users": len(users)}), 200

    except Exception as e:
        print("\n=== Cron処理エラー ===")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
