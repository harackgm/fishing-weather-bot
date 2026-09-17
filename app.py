import os
import time
import random
import requests
import traceback
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
IS_TEST_MODE = True  # 自動一斉通知（Cron）時のみ使用するテスト制限フラグ
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
# 3. ウェザーニュース 釣り場URL辞書 (全国網羅版)
# ==========================================
SPOT_WEATHER_URLS = {
    # 北海道・東北
    "上浜": "https://weathernews.jp/onebox/39.142616/139.945938/",
    "不忘": "https://weathernews.jp/onebox/38.042491/140.554478/",
    "白河": "https://weathernews.jp/onebox/37.127955/140.081827/",
    "ほのぼの": "https://weathernews.jp/onebox/36.837687/140.472433/",
    "WaDoNa": "https://weathernews.jp/onebox/36.877372/140.540954/",
    "鶴沼川": "https://weathernews.jp/onebox/37.255460/139.872256/",
    "オーパ": "https://weathernews.jp/onebox/37.314342/140.449245/",
    "あいづ": "https://weathernews.jp/onebox/37.204977/139.729681/",
    # 関東（栃木・群馬・茨城）
    "キングフィッシャー": "https://weathernews.jp/onebox/36.907054/140.078650/",
    "みどり": "https://weathernews.jp/onebox/36.834975/140.002410/",
    "那須高原": "https://weathernews.jp/onebox/37.001929/140.104991/",
    "尚仁沢": "https://weathernews.jp/onebox/37.001929/140.104991/",
    "つり天国": "https://weathernews.jp/onebox/37.073444/140.044452/",
    "関根": "https://weathernews.jp/onebox/36.851308/139.979065/",
    "408": "https://weathernews.jp/onebox/36.763055/139.858269/",
    "308": "https://weathernews.jp/onebox/36.824828/139.896229/",
    "蛇尾川": "https://weathernews.jp/onebox/36.981351/139.901534/",
    "なら山沼": "https://weathernews.jp/onebox/36.373741/139.802713/",
    "大芦川": "https://weathernews.jp/onebox/36.590732/139.693652/",
    "加賀": "https://weathernews.jp/onebox/36.388609/139.537247/",
    "発光路": "https://weathernews.jp/onebox/36.580281/139.532829/",
    "上永野": "https://weathernews.jp/onebox/36.511884/139.573442/",
    "柏倉": "https://weathernews.jp/onebox/36.398276/139.660428/",
    "遊水園": "https://weathernews.jp/onebox/36.342013/139.863541/",
    "アルクス宇都宮": "https://weathernews.jp/onebox/36.566488/139.960060/",
    "エリア21": "https://weathernews.jp/onebox/36.496150/139.899522/",
    "ベアーズパーク": "https://weathernews.jp/onebox/36.513221/139.956989/",
    "鬼怒川": "https://weathernews.jp/onebox/36.617621/139.937106/",
    "名草": "https://weathernews.jp/onebox/36.418930/139.466355/",
    "川場": "https://weathernews.jp/onebox/36.690767/139.121662/",
    "おくとね": "https://weathernews.jp/onebox/36.663005/139.163750/",
    "イワナセンター": "https://weathernews.jp/onebox/36.610095/139.243740/",
    "黒保根": "https://weathernews.jp/onebox/36.515041/139.252324/",
    "迦葉山": "https://weathernews.jp/onebox/36.685419/139.071387/",
    "片品": "https://weathernews.jp/onebox/36.624564/139.046703/",
    "中之沢": "https://weathernews.jp/onebox/36.492057/139.195293/",
    "宮城": "https://weathernews.jp/onebox/36.483735/139.188251/",
    "大崎": "https://weathernews.jp/onebox/36.463209/139.164867/",
    "赤城": "https://weathernews.jp/onebox/36.463209/139.164867/",
    "けん太": "https://weathernews.jp/onebox/36.386648/138.960021/",
    "フック": "https://weathernews.jp/onebox/36.457699/139.173191/",
    "赤久縄": "https://weathernews.jp/onebox/36.160894/138.895355/",
    "太田": "https://weathernews.jp/onebox/36.357774/139.330830/",
    "東山道": "https://weathernews.jp/onebox/36.323047/139.280989/",
    "榛名": "https://weathernews.jp/onebox/36.443570/138.898498/",
    "水戸南": "https://weathernews.jp/onebox/36.326377/140.501362/",
    "高萩": "https://weathernews.jp/onebox/36.788035/140.577243/",
    "つくば園": "https://weathernews.jp/onebox/36.224122/140.144261/",
    "FAJ": "https://weathernews.jp/onebox/36.081494/140.164360/",
    "ユザキ": "https://weathernews.jp/onebox/36.314550/140.335285/",
    "笠間": "https://weathernews.jp/onebox/36.412866/140.208145/",
    "DoDoo": "https://weathernews.jp/onebox/36.187994/140.216734/",
    "若栗": "https://weathernews.jp/onebox/36.779644/140.633185/",
    "ミッドクリーク": "https://weathernews.jp/onebox/36.192975/140.164058/",
    # 関東（埼玉・東京・千葉・神奈川）
    "長瀞": "https://weathernews.jp/onebox/36.084376/139.104604/",
    "彩の国": "https://weathernews.jp/onebox/35.992469/139.473372/",
    "朝霞": "https://weathernews.jp/onebox/35.813481/139.604736/",
    "しらこばと": "https://weathernews.jp/onebox/35.917970/139.752203/",
    "川越": "https://weathernews.jp/onebox/35.907152/139.444046/",
    "はなさき": "https://weathernews.jp/onebox/36.096192/139.636601/",
    "多摩湖": "https://weathernews.jp/onebox/35.780248/139.440732/",
    "中里": "https://weathernews.jp/onebox/36.163896/139.176567/",
    "伊古": "https://weathernews.jp/onebox/36.071547/139.339037/",
    "座間": "https://weathernews.jp/onebox/35.843581/140.010676/",
    "ジョイバレー": "https://weathernews.jp/onebox/35.744779/140.417401/",
    "ウォルトン": "https://weathernews.jp/onebox/35.863326/140.290525/",
    "NOIKE": "https://weathernews.jp/onebox/35.576969/140.234786/",
    "パラダイス": "https://weathernews.jp/onebox/35.653330/140.338663/",
    "いなプー": "https://weathernews.jp/onebox/35.619254/140.074365/",
    "足柄": "https://weathernews.jp/onebox/35.319275/139.042723/",
    "中津川": "https://weathernews.jp/onebox/35.521698/139.285609/",
    "早戸川": "https://weathernews.jp/onebox/35.543063/139.216090/",
    "王禅寺": "https://weathernews.jp/onebox/35.587020/139.524309/",
    "開成": "https://weathernews.jp/onebox/35.334342/139.130344/",
    "浅川": "https://weathernews.jp/onebox/35.641903/139.231262/",
    # 甲信越・東海・関西
    "鹿留": "https://weathernews.jp/onebox/35.512350/138.887160/",
    "小菅": "https://weathernews.jp/onebox/35.760330/138.940529/",
    "シルフ": "https://weathernews.jp/onebox/35.778458/138.316489/",
    "竜華池": "https://weathernews.jp/onebox/35.681978/138.576164/",
    "平谷湖": "https://weathernews.jp/onebox/35.332243/137.632213/",
    "ハーブ": "https://weathernews.jp/onebox/36.403436/137.890526/",
    "ニレ池": "https://weathernews.jp/onebox/36.712669/137.845826/",
    "鹿島槍": "https://weathernews.jp/onebox/36.548940/137.809757/",
    "槻の池": "https://weathernews.jp/onebox/36.011582/138.197271/",
    "あずみ野": "https://weathernews.jp/onebox/36.337699/137.885455/",
    "東山湖": "https://weathernews.jp/onebox/35.296739/138.955925/",
    "すその": "https://weathernews.jp/onebox/35.166667/138.899162/",
    "須川": "https://weathernews.jp/onebox/35.359818/138.977710/",
    "アルクス焼津": "https://weathernews.jp/onebox/34.789110/138.294771/",
    "浜名湖": "https://weathernews.jp/onebox/34.712749/137.629457/",
    "五頭": "https://weathernews.jp/onebox/37.819471/139.238518/",
    "瑞浪": "https://weathernews.jp/onebox/35.433516/137.295266/",
    "サンクチュアリ": "https://weathernews.jp/onebox/35.187504/136.457803/",
    "醒井": "https://weathernews.jp/onebox/35.303671/136.349914/",
    "高島": "https://weathernews.jp/onebox/35.348308/136.052288/",
    "千早川": "https://weathernews.jp/onebox/34.417118/135.647482/"
}

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

def update_user_source(user_id, source):
    if not supabase: return
    try:
        supabase.table('user_settings').update({'weather_source': source}).eq('user_id', user_id).execute()
    except Exception as e:
        print(f"[Supabase更新エラー] {e}")

def add_favorite_spot(user_id, spot_name):
    if not supabase: return False, "DB接続未完了です。"
    _, favorites = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    if spot_name in fav_list:
        return False, "すでに登録されている釣り場です。"
    if len(fav_list) >= 5:
        return False, "お気に入り釣り場は最大5箇所まで登録可能です。"
    fav_list.append(spot_name)
    try:
        supabase.table('user_settings').update({'favorite_spots': ','.join(fav_list)}).eq('user_id', user_id).execute()
        return True, f"「{spot_name}」をお気に入りに追加しました。"
    except Exception as e:
        return False, f"保存に失敗しました: {e}"

def remove_favorite_spot(user_id, spot_name):
    if not supabase: return False, "DB接続未完了です。"
    _, favorites = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    if spot_name not in fav_list:
        return False, "登録されていない釣り場です。"
    fav_list.remove(spot_name)
    try:
        supabase.table('user_settings').update({'favorite_spots': ','.join(fav_list)}).eq('user_id', user_id).execute()
        return True, f"「{spot_name}」をお気に入りから削除しました。"
    except Exception as e:
        return False, f"削除に失敗しました: {e}"

# ==========================================
# 5. ウェザーニュース 実データスクレイピング関数
# ==========================================
def fetch_spot_1hour_data(url):
    """指定されたURLから現在時刻以降の予報を取得（6〜21時抽出テスト版）"""
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
                
                # 【テスト】6時〜21時の1時間毎に抽出
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
    """田の字型（2行×2列）グリッドレイアウト（横読み・Z字順修正版）"""
    dates = list(weather_by_date.keys())
    
    def create_day_column(date_str):
        if not date_str:
            # 空枠でLINEから拒否されないよう、目立たないダミーテキストを配置
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
            # 万が一空文字になった場合は強制的に "-" にする安全処理
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

    # === 【並び順の変更】 横読み（Z字）になるよう配置 ===
    # 左列： 1日目(dates[0]) と 3日目(dates[2])
    col1_boxes = [create_day_column(dates[0] if len(dates) > 0 else None)]
    if len(dates) > 2:
        col1_boxes.append({"type": "separator", "margin": "md"})
        col1_boxes.append(create_day_column(dates[2]))

    # 右列： 2日目(dates[1]) と 4日目(dates[3])
    col2_boxes = [create_day_column(dates[1] if len(dates) > 1 else None)]
    if len(dates) > 3:
        col2_boxes.append({"type": "separator", "margin": "md"})
        col2_boxes.append(create_day_column(dates[3]))
    # =======================================================

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
            "type": "box", "layout": "horizontal", "spacing": "sm", "paddingAll": "8px",
            "contents": [
                {"type": "box", "layout": "vertical", "flex": 1, "contents": col1_boxes},
                {"type": "separator"},
                {"type": "box", "layout": "vertical", "flex": 1, "contents": col2_boxes}
            ]
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
# 7. LINEメッセージ受信処理
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        user_message = event.message.text.strip()
        user_id = event.source.user_id

        print(f"[受信] ユーザー({user_id}): {user_message}")

        # 1. ユーザーコマンドを「最優先」で判定（追加・削除・設定など）
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

        # 2. コマンド以外の場合は「天気検索」として判定
        target_spot_name = None
        target_url = None
        for spot_key, url in SPOT_WEATHER_URLS.items():
            if spot_key in user_message or user_message in spot_key:
                target_spot_name = spot_key
                target_url = url
                break

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
            
        # 3. どちらにも該当しない場合
        reply_text = (
            "🔍 その釣り場は現在対応していません、もしくは名前が間違っています。\n\n"
            "【対応済みの主な釣り場】\n"
            "不忘 / 白河 / 朝霞 / 加賀 / 鬼怒川 / 鹿島槍 / 平谷湖 / 東山湖 / すその / サンクチュアリ...など、全国60箇所以上に対応！\n\n"
            "※部分一致で検索できます（例: 「キング」と送信すると「キングフィッシャー」の天気が表示されます）"
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
# 8. 定期トリガーエンドポイント（一斉通知ガードレール）
# ==========================================
@app.route("/cron_trigger", methods=['GET', 'POST'])
def cron_trigger():
    print("\n--- 定期トリガーを受信 ---")
    
    # 1. 大量通知ストッパー（安全装置）
    detect_count = 0
    if detect_count > MAX_LIMIT:
        print("[安全装置作動] 上限を超えたため送信スキップ")
        return jsonify({"status": "skipped", "reason": "MAX_LIMIT_EXCEEDED"}), 200

    # 2. テストモード制御（本番環境以外の誤送信防止）
    if IS_TEST_MODE and ADMIN_USER_ID:
        print(f"[テストモード] 管理者({ADMIN_USER_ID})のみに制限して処理実行")

    time.sleep(random.uniform(1.0, 3.0))  # サーバ負荷軽減のゆらぎ
    return jsonify({"status": "success", "message": "Trigger processed safely."}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
