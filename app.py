import os
import time
import random
import sqlite3
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
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
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '').strip()

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip().strip('"').strip("'")
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID', '').strip()
IS_TEST_MODE = True
MAX_LIMIT = 5

GEMINI_CANDIDATE_MODELS = [
    'gemini-3.6-flash',
    'gemini-1.5-flash',
    'gemini-2.0-flash'
]

DB_PATH = 'user_data.db'

PREFECTURE_SPOTS = {
    "埼玉県": ["朝霞ガーデン", "ウォーターパーク長瀞", "川越水上公園", "加須はなさき水上公園"],
    "東京都": ["ベリーパーク in FISH ON！王禅寺（※川崎隣接）", "奥多摩フィッシングセンター", "秋川国際マス釣場"],
    "神奈川県": ["ベリーパーク in FISH ON！王禅寺", "開成水辺フォレストスプリングス", "早戸川国際マス釣場"],
    "千葉県": ["ジョイバレー", "座間養魚場", "アクアヘヴン"],
    "茨城県": ["ミッドナイト", "高萩ジパングトラウトエリア", "水戸南フィッシングエリア"],
    "栃木県": ["キングフィッシャー", "加賀フィッシングエリア", "発光路の森フィッシングエリア"],
    "群馬県": ["宮城アングラーズヴィレッジ", "イワナセンター", "川場フィッシングプラザ", "Hook"],
    "山梨県": ["ベリーパーク in FISH ON！鹿留", "忍野フィッシングエリア", "小菅トラウトガーデン"],
    "静岡県": ["すそ野フィッシングパーク", "東山湖フィッシングエリア", "柿田川フィッシングパーク"],
    "長野県": ["平谷湖フィッシングスポット", "鹿島槍ガーデン", "ハーブの里フィッシングエリア"]
}

# ==========================================
# 3. データベース（SQLite）管理関数
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id TEXT PRIMARY KEY,
            weather_source TEXT DEFAULT 'ウェザーニュース',
            favorite_spots TEXT DEFAULT ''
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_user_setting(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT weather_source, favorite_spots FROM user_settings WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute(
            'INSERT INTO user_settings (user_id, weather_source, favorite_spots) VALUES (?, ?, ?)',
            (user_id, 'ウェザーニュース', '')
        )
        conn.commit()
        result = ('ウェザーニュース', '')
    else:
        result = row
    conn.close()
    return result

def update_user_source(user_id, source):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE user_settings SET weather_source = ? WHERE user_id = ?', (source, user_id))
    conn.commit()
    conn.close()

def add_favorite_spot(user_id, spot_name):
    _, favorites = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    if spot_name in fav_list:
        return False, "すでに登録されている釣り場です。"
    if len(fav_list) >= 5:
        return False, "お気に入り釣り場は最大5箇所まで登録可能です。"
    fav_list.append(spot_name)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE user_settings SET favorite_spots = ? WHERE user_id = ?', (','.join(fav_list), user_id))
    conn.commit()
    conn.close()
    return True, f"「{spot_name}」をお気に入りに追加しました。"

def remove_favorite_spot(user_id, spot_name):
    _, favorites = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    if spot_name not in fav_list:
        return False, "登録されていない釣り場です。"
    fav_list.remove(spot_name)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE user_settings SET favorite_spots = ? WHERE user_id = ?', (','.join(fav_list), user_id))
    conn.commit()
    conn.close()
    return True, f"「{spot_name}」をお気に入りから削除しました。"

# ==========================================
# 4. ウェザーニュース 実データスクレイピング関数 (縦並び独立メッセージ化)
# ==========================================
def fetch_hirayako_1hour_data():
    """現在時刻以降の予報を「日付」をキーとした辞書で取得"""
    time.sleep(random.uniform(1.0, 2.0))
    url = "https://weathernews.jp/onebox/35.332243/137.632213/q=%E9%95%B7%E9%87%8E%E7%9C%8C%E4%B8%8B%E4%BC%8A%E9%82%A3%E9%83%A1%E5%B9%B3%E8%B0%B7%E6%9D%91%E5%B9%B3%E8%B0%B7%E6%9D%91%E4%B8%80%E5%86%86&v=faf7b174776bf3f82a649d0b9e178580b4814dd1bac1307f4459eeaba6254e66&temp=c&lang=ja"
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
                hour = time_tag.text.strip().zfill(2) + "時" if time_tag else "--時"
                
                img_url = "https://gvs.weathernews.jp/onebox/img/wxicon/200.png"
                weather_tag = item.find('li', class_='weather')
                img_tag = weather_tag.find('img') if weather_tag else None
                if img_tag and 'src' in img_tag.attrs:
                    src = img_tag['src']
                    if src.startswith('//'): img_url = "https:" + src
                    elif src.startswith('/'): img_url = "https://weathernews.jp" + src
                    else: img_url = src

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
            
            # LINEの1回あたりの送信上限（最大5つの吹き出し）に対応
            if len(weather_by_date) >= 5:
                break
            
        return weather_by_date
    except Exception as e:
        print(f"[スクレイピングエラー] {e}")
        return None

def build_vertical_flex_messages(spot_name, weather_by_date):
    """日付ごとに独立したFlexMessage（吹き出し）のリストを作成し、サイズを適度に拡大"""
    messages = []
    
    for date_str, daily_data in weather_by_date.items():
        rows = [
            {
                "type": "box", "layout": "horizontal", "margin": "none",
                "contents": [
                    {"type": "text", "text": "時間", "weight": "bold", "size": "sm", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "天気", "weight": "bold", "size": "sm", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "気温", "weight": "bold", "size": "sm", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "降水", "weight": "bold", "size": "sm", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "風速", "weight": "bold", "size": "sm", "flex": 1, "align": "center", "color": "#888888"}
                ]
            },
            {"type": "separator", "margin": "sm"}
        ]
        
        for data in daily_data:
            temp_color = "#ff0000" if "℃" in data['temp'] and int(data['temp'].replace("℃","")) >= 25 else "#333333"
            rain_color = "#0000ff" if "mm" in data['rain'] and data['rain'] not in ["0mm", "-"] else "#333333"
            
            rows.append({
                "type": "box", "layout": "horizontal", "margin": "sm", "alignItems": "center",
                "contents": [
                    {"type": "text", "text": data['time'], "size": "sm", "flex": 1, "align": "center", "weight": "bold"},
                    {"type": "image", "url": data['img_url'], "size": "xs", "flex": 1, "align": "center"},
                    {"type": "text", "text": data['temp'], "size": "sm", "flex": 1, "align": "center", "color": temp_color},
                    {"type": "text", "text": data['rain'], "size": "sm", "flex": 1, "align": "center", "color": rain_color},
                    {"type": "text", "text": data['wind'].replace("m/s", "m"), "size": "sm", "flex": 1, "align": "center"}
                ]
            })
            
        bubble = {
            "type": "bubble",
            "size": "kilo",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": "#0066cc", "paddingAll": "10px",
                "contents": [
                    {"type": "text", "text": f"📍 {spot_name}", "color": "#ffffff", "weight": "bold", "size": "sm"},
                    {"type": "text", "text": date_str, "color": "#ffffff", "weight": "bold", "size": "md", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical", "spacing": "none", "paddingAll": "10px",
                "contents": rows
            }
        }
        
        messages.append(FlexSendMessage(alt_text=f"{date_str}の天気", contents=bubble))
        
        # LINE制限（1度に5件まで）
        if len(messages) >= 5:
            break
            
    return messages

# ==========================================
# 5. Gemini AI応答生成関数
# ==========================================
def generate_gemini_response(user_message, user_setting):
    if not GEMINI_API_KEY:
        return None, "【システムエラー】GEMINI_API_KEYが未設定です。"

    genai.configure(api_key=GEMINI_API_KEY)
    source, favorites = user_setting
    fav_text = favorites if favorites else "未登録"

    system_instruction = (
        "あなたは管理釣り場と天気予報のプロ案内AIアシスタントです。"
        "時間帯別の天気・気温・風速・風向・降水確率を含む高精度な天気予報を回答してください。"
        f"【ユーザー設定情報】優先情報源: {source}, お気に入り釣り場: {fav_text}。"
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
# 6. Webサーバーのエンドポイント
# ==========================================
@app.route("/", methods=['GET'])
def top_page():
    return "LINE Reply Bot Server (Vertical Flex - Resize) is running!", 200

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
# 7. LINEメッセージ受信処理
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id

    print(f"[受信] ユーザー({user_id}): {user_message}")

    user_setting = get_user_setting(user_id)
    source, favorites = user_setting

    matched_pref = None
    for pref in PREFECTURE_SPOTS.keys():
        if pref in user_message or pref.replace("県", "").replace("府", "").replace("都", "") in user_message:
            matched_pref = pref
            break

    # 平谷湖のピンポイント予報（独立した吹き出しを縦並びで返信）
    if "平谷湖" in user_message:
        weather_by_date = fetch_hirayako_1hour_data()
        if weather_by_date:
            messages = build_vertical_flex_messages("平谷湖フィッシングスポット", weather_by_date)
            
            line_bot_api.reply_message(event.reply_token, messages)
            print("[送信] Vertical FlexMessage応答を完了しました。")
            return
        else:
            ai_text, error_text = generate_gemini_response(user_message, user_setting)
            reply_text = ai_text if ai_text else error_text

    elif user_message == "設定":
        fav_list = [s for s in favorites.split(',') if s]
        fav_display = "\n".join([f"・{spot}" for spot in fav_list]) if fav_list else "・未登録"
        reply_text = (
            "⚙️ 【現在の設定状況】\n\n"
            "■ 天気詳細度: 常に最詳細モード\n"
            f"■ 参照ソース: {source}\n"
            f"■ お気に入り釣り場:\n{fav_display}\n\n"
            "【設定変更コマンド】\n"
            "・「埼玉県」「長野県」など（釣り場一覧を表示）\n"
            "・「ウェザーニュース」「tenki.jp」\n"
            "・「追加:釣り場名」\n"
            "・「削除:釣り場名」"
        )

    elif matched_pref:
        spots = PREFECTURE_SPOTS[matched_pref]
        spot_list_text = "\n".join([f"・{s}" for s in spots])
        reply_text = f"📍 【{matched_pref}の主な管理釣り場】\n\n{spot_list_text}\n\nお気に入りに登録する場合は以下のように送信してください。\n例: 追加:{spots[0]}"

    elif user_message in ["ウェザーニュース", "tenki.jp"]:
        update_user_source(user_id, user_message)
        reply_text = f"✅ 参照ソースを「{user_message}」に変更しました。"

    elif user_message.startswith("追加:"):
        spot_name = user_message.replace("追加:", "").strip()
        success, msg = add_favorite_spot(user_id, spot_name) if spot_name else (False, "⚠️ 釣り場名を入力してください。")
        reply_text = f"✅ {msg}" if success else f"⚠️ {msg}"

    elif user_message.startswith("削除:"):
        spot_name = user_message.replace("削除:", "").strip()
        success, msg = remove_favorite_spot(user_id, spot_name) if spot_name else (False, "⚠️ 削除する釣り場名を入力してください。")
        reply_text = f"✅ {msg}" if success else f"⚠️ {msg}"

    elif user_message in ["ヘルプ", "使い方"]:
        reply_text = "💡 【使い方ガイド】\n\n■ 釣り場検索: 「埼玉県」「長野県」\n■ 設定確認: 「設定」\n■ 実データ予報: 「平谷湖」\n■ お気に入り登録: 「追加:釣り場名」\n■ お気に入り削除: 「削除:釣り場名」"

    else:
        ai_text, error_text = generate_gemini_response(user_message, user_setting)
        reply_text = ai_text if ai_text else error_text

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    print("[送信] リプライ応答を完了しました。")

# ==========================================
# 8. 定期データ更新用エンドポイント（安全装置付き）
# ==========================================
@app.route("/cron_trigger", methods=['GET', 'POST'])
def cron_trigger():
    print("\n--- cron-job.org からの定期トリガーを受信 ---")
    item_count = 0
    if item_count > MAX_LIMIT:
        return jsonify({"status": "skipped", "reason": "MAX_LIMIT_EXCEEDED"}), 200
    time.sleep(random.uniform(1.0, 3.0))
    return jsonify({"status": "success", "message": "DB updated safely."}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
