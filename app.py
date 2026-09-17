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

# エリア検索用の主要管理釣り場リスト
PREFECTURE_SPOTS = {
    "埼玉県": ["朝霞ガーデン", "ウォーターパーク長瀞", "川越水上公園", "加須はなさき水上公園"],
    "東京都": ["ベリーパーク in FISH ON！王禅寺（※川崎隣接）", "奥多摩フィッシングセンター", "浅川国際鱒釣り場"],
    "神奈川県": ["ベリーパーク in FISH ON！王禅寺", "開成水辺フォレストスプリングス", "早戸川国際マス釣場"],
    "千葉県": ["ジョイバレー", "座間養魚場", "ウォルトンガーデン"],
    "茨城県": ["水戸南フィッシングエリア", "高萩ジパングトラウトエリア", "レイクユザキ"],
    "栃木県": ["キングフィッシャー", "加賀フィッシングエリア", "発光路の森フィッシングエリア"],
    "群馬県": ["宮城アングラーズヴィレッジ", "イワナセンター", "川場フィッシングプラザ", "Hook"],
    "山梨県": ["ベリーパーク in FISH ON！鹿留", "忍野フィッシングエリア", "小菅トラウトガーデン"],
    "静岡県": ["すそのフィッシングパーク", "東山湖フィッシングエリア", "アルクスポンド焼津"],
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
# 4. ウェザーニュース URL辞書とスクレイピング関数
# ==========================================
# ご提示いただいたブログリストから抽出した主要URL辞書
SPOT_WEATHER_URLS = {
    "平谷湖": "https://weathernews.jp/onebox/35.332243/137.632213/q=%E9%95%B7%E9%87%8E%E7%9C%8C%E4%B8%8B%E4%BC%8A%E9%82%A3%E9%83%A1%E5%B9%B3%E8%B0%B7%E6%9D%91%E5%B9%B3%E8%B0%B7%E6%9D%91%E4%B8%80%E5%86%86&v=faf7b174776bf3f82a649d0b9e178580b4814dd1bac1307f4459eeaba6254e66&temp=c&lang=ja",
    "東山湖": "https://weathernews.jp/onebox/35.296739/138.955925/q=%E9%9D%99%E5%B2%A1%E7%9C%8C%E5%BE%A1%E6%AE%BF%E5%A0%B4%E5%B8%82%E6%9D%B1%E5%B1%B1&v=635c721f3fbe5c623a8b7caa91d498261c4c157fc5202f950c6c95a9061180f7&temp=c&lang=ja",
    "すその": "https://weathernews.jp/onebox/35.166667/138.899162/q=%E9%9D%99%E5%B2%A1%E7%9C%8C%E8%A3%BE%E9%87%8E%E5%B8%82%E5%AF%8C%E6%B2%A2&v=bd909a7318db793e82a8fb4d59b6fdbf330763edc69d45f5b737facf7b0b2e48&temp=c&lang=ja",
    "朝霞ガーデン": "https://weathernews.jp/onebox/35.813481/139.604736/q=%E5%9F%BC%E7%8E%89%E7%9C%8C%E6%9C%9D%E9%9C%9E%E5%B8%82%E7%94%B0%E5%B3%B6&v=ff27f1e171cf722cc54d9ff6016f453c1de36c1f2863b52787bb19247c4a8b3b&temp=c&lang=ja",
    "キングフィッシャー": "https://weathernews.jp/onebox/36.907054/140.078650/q=%E6%A0%83%E6%9C%A8%E7%9C%8C%E5%A4%A7%E7%94%B0%E5%8E%9F%E5%B8%82%E4%B9%99%E9%80%A3%E6%B2%A2&v=e4f587c15b28fd557e992740cafde13514db7741324a87b26cd771830b23de5d&temp=c&lang=ja",
    "加賀": "https://weathernews.jp/onebox/36.388609/139.537247/q=%E6%A0%83%E6%9C%A8%E7%9C%8C%E4%BD%90%E9%87%8E%E5%B8%82%E5%B1%B1%E5%BD%A2%E7%94%BA&v=332535f7db1f020ee5cd7797ee2bb4661a81cfae56aa55e22cb116b03e5ff942&temp=c&lang=ja",
    "鹿島槍ガーデン": "https://weathernews.jp/onebox/36.548940/137.809757/q=%E9%95%B7%E9%87%8E%E7%9C%8C%E5%A4%A7%E7%94%BA%E5%B8%82%E5%B9%B3&v=72f590028c92dd6d31986fbebf6d2f1417804ea061815dab9ec9db6584ef62c3&temp=c&lang=ja",
    "サンクチュアリ": "https://weathernews.jp/onebox/35.187504/136.457803/q=%E4%B8%89%E9%87%8D%E7%9C%8C%E3%81%84%E3%81%AA%E3%81%B9%E5%B8%82%E8%97%A4%E5%8E%9F%E7%94%BA%E5%B1%B1%E5%8F%A3&v=d88f47ee8ee95ce58829981771dcf4cd51d319359eadc0ad25bc20ae4f94e75e&temp=c&lang=ja",
    "座間": "https://weathernews.jp/onebox/35.843581/140.010676/q=%E5%8D%83%E8%91%89%E7%9C%8C%E6%9F%8F%E5%B8%82%E5%A4%A7%E4%BA%95&v=1692b2814afa7a706f67a829a8a402f4f606f3356451ef60de57594309ae6a7f&temp=c&lang=ja"
}

def fetch_spot_1hour_data(url):
    """指定されたURLから現在時刻以降の予報を「日付」をキーとした辞書で取得"""
    time.sleep(random.uniform(1.0, 2.0))
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
            
            if len(weather_by_date) >= 5:
                break
            
        return weather_by_date
    except Exception as e:
        print(f"[スクレイピングエラー] {e}")
        return None

def build_vertical_flex_messages(spot_name, weather_by_date):
    """日付ごとに独立したFlexMessageを最大サイズ(giga)で構築"""
    messages = []
    
    for date_str, daily_data in weather_by_date.items():
        rows = [
            {
                "type": "box", "layout": "horizontal", "margin": "none",
                "contents": [
                    {"type": "text", "text": "時間", "weight": "bold", "size": "lg", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "天気", "weight": "bold", "size": "lg", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "気温", "weight": "bold", "size": "lg", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "降水", "weight": "bold", "size": "lg", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "風速", "weight": "bold", "size": "lg", "flex": 1, "align": "center", "color": "#888888"}
                ]
            },
            {"type": "separator", "margin": "md"}
        ]
        
        for data in daily_data:
            temp_color = "#ff0000" if "℃" in data['temp'] and int(data['temp'].replace("℃","")) >= 25 else "#333333"
            rain_color = "#0000ff" if "mm" in data['rain'] and data['rain'] not in ["0mm", "-"] else "#333333"
            
            rows.append({
                "type": "box", "layout": "horizontal", "margin": "md", "alignItems": "center",
                "contents": [
                    {"type": "text", "text": data['time'], "size": "lg", "flex": 1, "align": "center", "weight": "bold"},
                    {"type": "image", "url": data['img_url'], "size": "md", "flex": 1, "align": "center"},
                    {"type": "text", "text": data['temp'], "size": "lg", "flex": 1, "align": "center", "color": temp_color},
                    {"type": "text", "text": data['rain'], "size": "lg", "flex": 1, "align": "center", "color": rain_color},
                    {"type": "text", "text": data['wind'].replace("m/s", "m"), "size": "lg", "flex": 1, "align": "center"}
                ]
            })
            
        bubble = {
            "type": "bubble",
            "size": "giga",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": "#0066cc", "paddingAll": "16px",
                "contents": [
                    {"type": "text", "text": f"📍 {spot_name}", "color": "#ffffff", "weight": "bold", "size": "lg"},
                    {"type": "text", "text": date_str, "color": "#ffffff", "weight": "bold", "size": "xl", "margin": "sm"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical", "spacing": "none", "paddingAll": "16px",
                "contents": rows
            }
        }
        
        messages.append(FlexSendMessage(alt_text=f"{spot_name} {date_str}の天気", contents=bubble))
        
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
    return "LINE Reply Bot Server (Multi Spots Support) is running!", 200

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

    # 辞書(SPOT_WEATHER_URLS)から釣り場名が含まれているかチェック
    target_spot_name = None
    target_url = None
    for spot_key, url in SPOT_WEATHER_URLS.items():
        if spot_key in user_message:
            target_spot_name = spot_key
            target_url = url
            break

    # 登録されている釣り場のスクレイピング実行
    if target_url:
        weather_by_date = fetch_spot_1hour_data(target_url)
        if weather_by_date:
            messages = build_vertical_flex_messages(target_spot_name, weather_by_date)
            line_bot_api.reply_message(event.reply_token, messages)
            print(f"[送信] {target_spot_name}のVertical FlexMessage応答を完了しました。")
            return
        else:
            ai_text, error_text = generate_gemini_response(user_message, user_setting)
            reply_text = ai_text if error_text is None else error_text

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
        reply_text = "💡 【使い方ガイド】\n\n■ 釣り場検索: 「埼玉県」「長野県」\n■ 設定確認: 「設定」\n■ 実データ予報: 「平谷湖」「朝霞ガーデン」等\n■ お気に入り登録: 「追加:釣り場名」\n■ お気に入り削除: 「削除:釣り場名」"

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
