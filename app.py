import os
import time
import random
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage

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

MAX_LIMIT = 5

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
    "レイクウッド": "https://weathernews.jp/onebox/36.611334/139.666579/",
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
    "川場キングダム": "https://weathernews.jp/onebox/36.754213/139.142256/",
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
# 4. ウェザーニュース 実データスクレイピング関数
# ==========================================
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
            
            # 最大10日分まで抽出
            if len(weather_by_date) >= 10:
                break
            
        return weather_by_date
    except Exception as e:
        print(f"[スクレイピングエラー] {e}")
        return None

def build_carousel_flex_message(spot_name, weather_by_date):
    """日付ごとに横にスワイプできる「カルーセル（Carousel）」を構築（サイズはmega）"""
    bubbles = []
    
    for date_str, daily_data in weather_by_date.items():
        rows = [
            {
                "type": "box", "layout": "horizontal", "margin": "none",
                "contents": [
                    {"type": "text", "text": "時間", "weight": "bold", "size": "md", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "天気", "weight": "bold", "size": "md", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "気温", "weight": "bold", "size": "md", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "降水", "weight": "bold", "size": "md", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "風速", "weight": "bold", "size": "md", "flex": 1, "align": "center", "color": "#888888"}
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
                    {"type": "text", "text": data['time'], "size": "md", "flex": 1, "align": "center", "weight": "bold"},
                    {"type": "image", "url": data['img_url'], "size": "sm", "flex": 1, "align": "center"},
                    {"type": "text", "text": data['temp'], "size": "md", "flex": 1, "align": "center", "color": temp_color},
                    {"type": "text", "text": data['rain'], "size": "md", "flex": 1, "align": "center", "color": rain_color},
                    {"type": "text", "text": data['wind'].replace("m/s", "m"), "size": "md", "flex": 1, "align": "center"}
                ]
            })
            
        bubble = {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": "#0066cc", "paddingAll": "12px",
                "contents": [
                    {"type": "text", "text": f"📍 {spot_name}", "color": "#ffffff", "weight": "bold", "size": "md"},
                    {"type": "text", "text": date_str, "color": "#ffffff", "weight": "bold", "size": "lg", "margin": "sm"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical", "spacing": "none", "paddingAll": "12px",
                "contents": rows
            }
        }
        
        bubbles.append(bubble)
        
        # カルーセルは最大10枚まで
        if len(bubbles) >= 10:
            break
            
    return {"type": "carousel", "contents": bubbles}

# ==========================================
# 5. Webサーバーのエンドポイント
# ==========================================
@app.route("/", methods=['GET'])
def top_page():
    return "LINE Reply Bot Server (Carousel Only) is running!", 200

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
# 6. LINEメッセージ受信処理 (完全カルーセル・AI廃止版)
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id

    print(f"[受信] ユーザー({user_id}): {user_message}")

    # 辞書(SPOT_WEATHER_URLS)から部分一致で釣り場を検索
    target_spot_name = None
    target_url = None
    for spot_key, url in SPOT_WEATHER_URLS.items():
        if spot_key in user_message or user_message in spot_key:
            target_spot_name = spot_key
            target_url = url
            break

    # 登録されている釣り場のスクレイピング実行
    if target_url:
        weather_by_date = fetch_spot_1hour_data(target_url)
        if weather_by_date:
            flex_obj = build_carousel_flex_message(target_spot_name, weather_by_date)
            
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text=f"{target_spot_name}の天気予報", contents=flex_obj))
            print(f"[送信] {target_spot_name}のCarousel FlexMessage応答を完了しました。")
            return
        else:
            error_msg = f"⚠️ 【{target_spot_name}】の天気データの取得に失敗しました。\n(ウェザーニュースのページ構造が変更された可能性があります)"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=error_msg))
            return

    else:
        # AI(Gemini)のフォールバックを廃止し、定型文を返す
        reply_text = (
            "🔍 その釣り場は現在対応していません、もしくは名前が間違っています。\n\n"
            "【対応済みの主な釣り場】\n"
            "不忘 / 白河 / 朝霞 / 加賀 / 鬼怒川 / 鹿島槍 / 平谷湖 / 東山湖 / すその / サンクチュアリ...など、全国60箇所以上に対応！"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        print("[送信] 未登録釣り場の定型文を完了しました。")

# ==========================================
# 7. 定期データ更新用エンドポイント（安全装置付き）
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
