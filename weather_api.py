import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone

# 既に分割済みのline_flex_main.pyから日付計算関数を拝借します
from line_flex_main import guess_date_from_string

# 全国47都道府県のコードマッピング
PREF_TO_JMA = {
    "1": "016000", "2": "014100", "3": "012000", "4": "011000",
    "5": "020000", "6": "030000", "7": "040000", "8": "050000", "9": "060000", "10": "070000",
    "11": "080000", "12": "090000", "13": "100000", "14": "110000", "15": "120000", "16": "130000", "17": "140000",
    "18": "150000", "19": "160000", "20": "170000", "21": "180000", "22": "190000", "23": "200000",
    "24": "210000", "25": "220000", "26": "230000", "27": "240000", "28": "250000", "29": "260000",
    "30": "270000", "31": "280000", "32": "290000", "33": "300000", "34": "310000", "35": "320000",
    "36": "330000", "37": "340000", "38": "350000", "39": "360000", "40": "370000", "41": "380000",
    "42": "390000", "43": "400000", "44": "410000", "45": "420000", "46": "430000", "47": "440000",
    "48": "450000", "49": "460100", "50": "471000"
}

PREF_NAMES = {
    "011000": "北海道", "012000": "北海道", "014100": "北海道", "016000": "北海道",
    "020000": "青森", "030000": "岩手", "040000": "宮城", "050000": "秋田", "060000": "山形", "070000": "福島",
    "080000": "茨城", "090000": "栃木", "100000": "群馬", "110000": "埼玉", "120000": "千葉", "130000": "東京", "140000": "神奈川",
    "150000": "新潟", "160000": "富山", "170000": "石川", "180000": "福井", "190000": "山梨", "200000": "長野",
    "210000": "岐阜", "220000": "静岡", "230000": "愛知", "240000": "三重",
    "250000": "滋賀", "260000": "京都", "270000": "大阪", "280000": "兵庫", "290000": "奈良", "300000": "和歌山",
    "310000": "鳥取", "320000": "島根", "330000": "岡山", "340000": "広島", "350000": "山口",
    "360000": "徳島", "370000": "香川", "380000": "愛媛", "390000": "高知",
    "400000": "福岡", "410000": "佐賀", "420000": "長崎", "430000": "大分", "450000": "宮崎", "460100": "鹿児島",
    "471000": "沖縄"
}

def extract_lat_lon(url):
    m = re.search(r'onebox/([0-9.]+)/([0-9.]+)', url)
    if m: return m.group(1), m.group(2)
    return None, None

def fetch_weekly_data_from_jma(tenki_url, raw_exclude_dates):
    if not tenki_url: return []
    m = re.search(r'forecast/\d+/(\d+)/', tenki_url)
    if not m: return []
    pref_id = m.group(1)
    jma_code = PREF_TO_JMA.get(pref_id)
    if not jma_code: return []

    try:
        url = f"https://www.jma.go.jp/bosai/forecast/data/forecast/{jma_code}.json"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, headers=headers, timeout=5.0)
        res.raise_for_status()
        data = res.json()

        forecast_dict = {}

        for part in data:
            for ts in part.get('timeSeries', []):
                times = ts.get('timeDefines', [])
                areas = ts.get('areas', [])
                if not times or not areas: continue

                target_area = areas[0]
                for a in areas:
                    name = a.get("area", {}).get("name", "")
                    if name in ["北部", "大田原", "西部", "秩父", "北部の山沿い", "飛騨地方", "長野", "塩尻", "松本"]:
                        target_area = a
                        break

                for i, dt_str in enumerate(times):
                    dt_only = dt_str[:10]
                    try: 
                        dt = datetime.strptime(dt_only, "%Y-%m-%d").date()
                    except: 
                        continue

                    if dt not in forecast_dict:
                        forecast_dict[dt] = {"code": 100, "pop": "-", "t_min": "-", "t_max": "-"}

                    if "weatherCodes" in target_area and i < len(target_area["weatherCodes"]):
                        if target_area["weatherCodes"][i]:
                            forecast_dict[dt]["code"] = target_area["weatherCodes"][i]
                    
                    if "pops" in target_area and i < len(target_area["pops"]):
                        val = target_area["pops"][i]
                        if val not in ["", None]:
                            val_str = str(val).replace('%','')
                            if val_str.isdigit(): forecast_dict[dt]["pop"] = f"{val_str}%"
                    
                    if "tempsMin" in target_area and i < len(target_area["tempsMin"]):
                        val = target_area["tempsMin"][i]
                        if val not in ["", None]: forecast_dict[dt]["t_min"] = str(val)
                        
                    if "tempsMax" in target_area and i < len(target_area["tempsMax"]):
                        val = target_area["tempsMax"][i]
                        if val not in ["", None]: forecast_dict[dt]["t_max"] = str(val)
                        
                    if "temps" in target_area and i < len(target_area["temps"]):
                        val = target_area["temps"][i]
                        if val not in ["", None]:
                            try:
                                temp_val = int(val)
                                c_min = forecast_dict[dt]["t_min"]
                                c_max = forecast_dict[dt]["t_max"]
                                if c_min == "-" or temp_val < int(c_min):
                                    forecast_dict[dt]["t_min"] = str(temp_val)
                                if c_max == "-" or temp_val > int(c_max):
                                    forecast_dict[dt]["t_max"] = str(temp_val)
                            except: pass

        now_jst_date = datetime.now(timezone(timedelta(hours=9))).date()
        last_wn_date = guess_date_from_string(raw_exclude_dates[-1], now_jst_date) if raw_exclude_dates else None

        weekly_data = []
        for dt in sorted(forecast_dict.keys()):
            if last_wn_date and dt <= last_wn_date: continue

            day_data = forecast_dict[dt]
            w_str = ["(月)", "(火)", "(水)", "(木)", "(金)", "(土)", "(日)"][dt.weekday()]
            date_label = f"{dt.day}{w_str}"

            try: code = int(day_data["code"])
            except: code = 100

            if code < 200: final_img = "https://gvs.weathernews.jp/onebox/img/wxicon/100.png"
            elif code < 300: final_img = "https://gvs.weathernews.jp/onebox/img/wxicon/200.png"
            elif code < 400: final_img = "https://gvs.weathernews.jp/onebox/img/wxicon/300.png"
            else: final_img = "https://gvs.weathernews.jp/onebox/img/wxicon/400.png"

            weekly_data.append({
                "date": date_label,
                "img_url": final_img,
                "temp_max": day_data["t_max"],
                "temp_min": day_data["t_min"],
                "rain_prob": day_data["pop"]
            })
            if len(weekly_data) >= 8: break

        return weekly_data
    except Exception as e:
        print(f"[JMA API Error] {e}")
        return []

def fetch_disaster_info(tenki_url):
    if not tenki_url: return {}
    m = re.search(r'forecast/\d+/(\d+)/', tenki_url)
    if not m: return {}
    pref_id = m.group(1)
    jma_code = PREF_TO_JMA.get(pref_id)
    if not jma_code: return {}

    pref_name = PREF_NAMES.get(jma_code, "")

    warnings_list = []
    quake_str = None
    volcano_str = None

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    try:
        url = f"https://www.jma.go.jp/bosai/warning/data/warning/{jma_code}.json"
        res = requests.get(url, headers=headers, timeout=2.0)
        if res.status_code == 200:
            data = res.json()
            code_map = {
                "02": "暴風雪警報", "03": "大雨警報", "04": "洪水警報", "05": "暴風警報",
                "06": "大雪警報", "07": "波浪警報", "08": "高潮警報", "10": "大雨注意報",
                "12": "大雪注意報", "13": "風雪注意報", "14": "雷注意報", "15": "強風注意報",
                "16": "波浪注意報", "17": "融雪注意報", "18": "洪水注意報", "19": "高潮注意報",
                "20": "濃霧注意報", "21": "乾燥注意報", "22": "なだれ注意報", "23": "低温注意報",
                "24": "霜注意報", "25": "着氷注意報", "26": "着雪注意報", "32": "暴風雪特別警報",
                "33": "大雨特別警報", "35": "暴風特別警報", "36": "大雪特別警報", "37": "波浪特別警報",
                "38": "高潮特別警報"
            }
            if "areaTypes" in data and len(data["areaTypes"]) > 0:
                areas = data["areaTypes"][0].get("areas", [])
                if areas:
                    warnings = areas[0].get("warnings", [])
                    for w in warnings:
                        if w.get("status") != "解除" and w.get("code") in code_map:
                            warnings_list.append(code_map[w["code"]])
            warnings_list = list(dict.fromkeys(warnings_list))
    except: pass

    try:
        url = "https://www.jma.go.jp/bosai/quake/data/list.json"
        res = requests.get(url, headers=headers, timeout=2.0)
        if res.status_code == 200:
            data = res.json()
            for eq in data:
                anm = eq.get("anm", "")
                full_text = str(eq)
                if pref_name and (pref_name in anm or pref_name in full_text):
                    dt_str = eq.get("at", eq.get("rdt", ""))
                    if dt_str:
                        dt = datetime.fromisoformat(dt_str)
                        dt_formatted = f"{dt.month}/{dt.day} {dt.hour}:{dt.minute:02d}"
                        mag = eq.get("mag", "")
                        maxi = eq.get("maxi", "")
                        quake_str = f"{dt_formatted} {anm} (震度{maxi}/M{mag})"
                        break
    except: pass

    try:
        url = "https://www.jma.go.jp/bosai/volcano/data/list.json"
        res = requests.get(url, headers=headers, timeout=2.0)
        if res.status_code == 200:
            data = res.json()
            for v in data:
                tit = v.get("tit", "")
                full_text = str(v)
                if pref_name and (pref_name in tit or pref_name in full_text):
                    volcano_str = tit
                    if len(volcano_str) > 15: volcano_str = volcano_str[:14] + "…"
                    break
    except: pass

    return {"warnings": warnings_list, "quake": quake_str, "volcano": volcano_str}

def fetch_spot_1hour_data(url, tenki_url=None):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=3.8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        weather_by_date = {}
        flick_list = soup.find('div', id='flick_list_1hour') or soup.find('div', id='flick_list_3hour')
            
        if flick_list:
            groups = flick_list.find_all('div', class_='group')
            for group in groups:
                date_tag = group.find('div', class_='date')
                if not date_tag: continue
                date_str = date_tag.text.strip()
                
                daily_list = []
                lists = group.find_all('ul', class_='list')
                for item in lists:
                    if 'past' in item.get('class', []): continue
                    time_tag = item.find('li', class_='time')
                    hour_str = time_tag.text.strip() if time_tag else ""
                    if not hour_str.isdigit(): continue
                    hour_int = int(hour_str)
                    if not (3 <= hour_int <= 20): continue
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
                    if not img_url.startswith("https://"): img_url = "https://gvs.weathernews.jp/onebox/img/wxicon/200.png"

                    rain = item.find('li', class_='rain').text.strip().replace("ミリ", "mm") if item.find('li', class_='rain') else "-"
                    temp = item.find('li', class_='temp').text.strip() if item.find('li', class_='temp') else "-"
                    wind_p = item.find('li', class_='wind').find('p') if item.find('li', class_='wind') else None
                    wind = wind_p.text.strip() if wind_p else "-"

                    daily_list.append({"time": hour, "img_url": img_url, "temp": temp, "rain": rain, "wind": wind})
                
                if daily_list: weather_by_date[date_str] = daily_list
                if len(weather_by_date) >= 4: break

        if not weather_by_date:
            return None

        raw_exclude_dates = list(weather_by_date.keys())
        weekly_data = []

        if tenki_url:
            weekly_data = fetch_weekly_data_from_jma(tenki_url, raw_exclude_dates)

        weather_by_date["__weekly__"] = weekly_data
        weather_by_date["__disaster__"] = fetch_disaster_info(tenki_url)
        return weather_by_date
    except requests.exceptions.Timeout: return None
    except Exception as e:
        print(f"[1hour Data Fetch Error] {e}")
        return None

def get_cached_weather(spot_name, supabase_client, memory_cache):
    now = datetime.now(timezone.utc)
    if spot_name in memory_cache:
        data, updated_time = memory_cache[spot_name]
        if now - updated_time <= timedelta(hours=2):
            if isinstance(data, dict):
                weekly = data.get("__weekly__", [])
                if data.get("_version") != "settings_shortcut_v129": return None
                if not weekly: return None
                dates = [d for d in data.keys() if d != "__weekly__" and d != "_version" and d != "__is_dummy__" and d != "__disaster__"]
                if not dates: return None
            return data
            
    if not supabase_client: return None
    try:
        res = supabase_client.table('weather_cache').select('*').eq('spot_name', spot_name).execute()
        if res.data and len(res.data) > 0:
            row = res.data[0]
            updated_at_str = row.get('updated_at')
            if updated_at_str:
                try:
                    updated_time = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                    if now - updated_time <= timedelta(hours=2):
                        weather_data = row.get('weather_data')
                        if isinstance(weather_data, dict):
                            weekly = weather_data.get("__weekly__", [])
                            if weather_data.get("_version") != "settings_shortcut_v129": return None
                            if not weekly: return None
                            dates = [d for d in weather_data.keys() if d != "__weekly__" and d != "_version" and d != "__is_dummy__" and d != "__disaster__"]
                            if not dates: return None
                        memory_cache[spot_name] = (weather_data, updated_time)
                        return weather_data
                except: pass
        return None
    except Exception as e:
        print(f"[Cache GET Error] {e}")
        return None

def save_cached_weather(spot_name, weather_data, supabase_client, memory_cache):
    if weather_data.get("__is_dummy__"):
        return
    
    now = datetime.now(timezone.utc)
    weather_data["_version"] = "settings_shortcut_v129"
    memory_cache[spot_name] = (weather_data, now)
    if not supabase_client: return
    try:
        supabase_client.table('weather_cache').upsert({'spot_name': spot_name, 'weather_data': weather_data, 'updated_at': now.isoformat()}).execute()
    except Exception as e: print(f"[Cache SAVE Error] {e}")
