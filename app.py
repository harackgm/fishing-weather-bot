import time
import random
import re
from datetime import datetime
import pytz
import requests
from bs4 import BeautifulSoup

# ==========================================
# 1. 日本時間（JST）設定および安全設定
# ==========================================
JST = pytz.timezone('Asia/Tokyo')
now_jst = datetime.now(JST)

# 天気アイコンIDから文字列への簡易変換マップ
WEATHER_ICON_MAP = {
    "100": "晴れ",
    "101": "晴れ時々くもり",
    "103": "晴れ時々雨",
    "200": "くもり",
    "201": "くもり時々晴れ",
    "202": "くもり一時雨",
    "203": "くもり時々雨",
    "300": "雨",
    "301": "雨時々晴れ",
    "302": "雨時々止む",
    "313": "雨時々くもり",
    "600": "晴れ間あり"
}

# 巡回サーバー負荷軽減のためのゆらぎ（1.0〜2.5秒待機）
time.sleep(random.uniform(1.0, 2.5))

# ==========================================
# 2. スクレイピング実行
# ==========================================
URL = "https://weathernews.jp/onebox/35.332243/137.632213/q=%E9%95%B7%E9%87%8E%E7%9C%8C%E4%B8%8B%E4%BC%8A%E9%82%A3%E9%83%A1%E5%B9%B3%E8%B0%B7%E6%9D%91%E5%B9%B3%E8%B0%B7%E6%9D%91%E4%B8%80%E5%86%86&v=faf7b174776bf3f82a649d0b9e178580b4814dd1bac1307f4459eeaba6254e66&temp=c&lang=ja"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

try:
    response = requests.get(URL, headers=headers, timeout=10)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    # 1時間毎予報のコンテナを取得
    flick_list = soup.find('div', id='flick_list_1hour')

    if not flick_list:
        print("エラー: 1時間毎の予報データエリアが見つかりませんでした。")
        exit()

    print(f"=== 平谷湖 1時間毎天気予報 ({now_jst.strftime('%Y-%m-%d %H:%M:%S')} JST取得) ===\n")

    # 日付グループ（.group）ごとにループ
    groups = flick_list.find_all('div', class_='group')

    for group in groups:
        date_tag = group.find('div', class_='date')
        date_str = date_tag.text.strip() if date_tag else "日付不明"
        
        print(f"【{date_str}】")
        print(" 時間 |   天気   | 降水量 | 気温 | 風速")
        print("-" * 42)

        # 時間ごとのリスト項目（ul.list）をループ
        lists = group.find_all('ul', class_='list')
        for item in lists:
            # 時間
            time_tag = item.find('li', class_='time')
            hour = time_tag.text.strip().zfill(2) + "時" if time_tag else "--時"

            # 天気（画像URLからID抽出）
            weather_tag = item.find('li', class_='weather')
            img_tag = weather_tag.find('img') if weather_tag else None
            weather_str = "不明"
            if img_tag and 'src' in img_tag.attrs:
                src = img_tag['src']
                match = re.search(r'/wxicon/(\d+)\.png', src)
                if match:
                    icon_id = match.group(1)
                    weather_str = WEATHER_ICON_MAP.get(icon_id, f"コード:{icon_id}")

            # 降水量
            rain_tag = item.find('li', class_='rain')
            rain = rain_tag.text.strip() if rain_tag else "--"

            # 気温
            temp_tag = item.find('li', class_='temp')
            temp = temp_tag.text.strip() if temp_tag else "--"

            # 風速
            wind_tag = item.find('li', class_='wind')
            wind_p = wind_tag.find('p') if wind_tag else None
            wind = wind_p.text.strip() + "m/s" if wind_p else "--"

            print(f" {hour} | {weather_str:^8} | {rain:>6} | {temp:>4} | {wind:>5}")
        
        print("\n")

except Exception as e:
    print(f"スクレイピング実行中にエラーが発生しました: {e}")
