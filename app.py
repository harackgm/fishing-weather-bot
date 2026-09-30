import os, time, random, requests, traceback, difflib, re, threading, unicodedata, jpholiday
from urllib.parse import quote, urlparse, parse_qsl
from bs4 import BeautifulSoup
from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage, PostbackEvent
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone

# --- 外部ファイルインポート ---
try:
    from spots import SPOT_WEATHER_DATA, BASS_SPOT_WEATHER_DATA, COLOR_GROUPS, BASS_COLOR_GROUPS, ALL_SPOT_DATA, AREA_MAPPING
except ImportError:
    from spots import SPOT_WEATHER_DATA, BASS_SPOT_WEATHER_DATA, COLOR_GROUPS, BASS_COLOR_GROUPS, ALL_SPOT_DATA
    AREA_MAPPING = {}

# --- UIレイアウト生成モジュール（line_flex.py）の読み込み ---
from line_flex import (
    guess_date_from_string,
    build_delete_confirm_message,
    build_delete_all_confirm_message,
    build_settings_flex_message,
    build_spot_list_carousel_horizontal,
    build_grid_flex_message
)
# --------------------------------------------------

os.environ['TZ'] = 'Asia/Tokyo'
if hasattr(time, 'tzset'): time.tzset()

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '').strip()
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

MAX_FAVORITES = 30
SUPABASE_URL = os.getenv('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '').strip()

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try: supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e: print(f"[Supabase初期化エラー] {e}")

MEMORY_CACHE = {}

# 連打防止用：排他制御ロックとリクエスト時刻管理
USER_LAST_REQUEST = {}
REQUEST_LOCK = threading.Lock()

def is_throttled(user_id, cooldown=2.5):
    """高速連打（競合状態）を排他ロックで完全に防ぐ判定関数"""
    now_ts = time.time()
    with REQUEST_LOCK:
        last_ts = USER_LAST_REQUEST.get(user_id, 0)
        if now_ts - last_ts < cooldown:
            return True
        USER_LAST_REQUEST[user_id] = now_ts
        return False

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

def normalize_name(name_str):
    if not name_str: return ""
    return unicodedata.normalize('NFKC', name_str).lower()

def clean_url(url_str):
    if not url_str: return ""
    cleaned = url_str.strip().replace(" ", "").replace("\t", "")
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")): return ""
    if "#" in cleaned: cleaned = cleaned.split("#")[0]
    return cleaned

def convert_to_10days_url(url_str):
    if not url_str: return None
    cleaned = clean_url(url_str)
    if '1hour.html' in cleaned: return cleaned.replace('1hour.html', '10days.html')
    if cleaned.endswith('/'): return cleaned + '10days.html'
    return cleaned

def get_spot_details(spot_key):
    data = ALL_SPOT_DATA.get(spot_key)
    if not data: return spot_key, None, "", "", "", "", "", "", "", "", "", None
    map_url = data.get("map_url")
    if not map_url:
        search_q = data.get('search_name', spot_key)
        map_url = f"https://www.google.com/maps/search/?api=1&query={quote(search_q)}"
    tenki_10days_url = convert_to_10days_url(data.get("tenki_url"))
    return (
        spot_key, data["url"], clean_url(data.get("hp_url", "")), clean_url(data.get("hp2_url", "")), 
        map_url, data.get("tel", ""), clean_url(data.get("x_url", "")), clean_url(data.get("fb_url", "")),
        clean_url(data.get("insta_url", "")), clean_url(data.get("blog_url", "")), clean_url(data.get("yt_url", "")),
        tenki_10days_url
    )

def get_user_setting(user_id):
    if not supabase: return ('ウェザーニュース', '', 'trout')
    try:
        res = supabase.table('user_settings').select('*').eq('user_id', user_id).execute()
        if res.data and len(res.data) > 0:
            row = res.data[0]
            favs = row.get('favorite_spots') or ''
            try:
                fishing_mode = row.get('fishing_mode') or 'trout'
            except KeyError:
                fishing_mode = 'trout'
            
            rename_map = {
                "七色ダム": "池原七色ダム", "キング": "キングフィッシャー", "ツガネ": "JF in Tsugane",
                "キングダム": "川場キングダム", "イワセン": "イワナセンター", "鹿島やり": "鹿島槍",
                "アルクス宇宇都宮": "アルクス宇宇都宮", "片仓ダム": "片倉ダム", "多田良沼": "多々良沼",
                "那須烏山": "那須鳥山", "柏崎": "霞ケ浦柏崎", "霞ケ浦西浦": "土浦港", "ＭＡＶ": "宮城", "GP不忘": "不忘"
            }
            
            raw_favs = [s.strip() for s in favs.split(',')]
            favs_list = []
            for s in raw_favs:
                if s in rename_map: s = rename_map[s]
                if s not in ["多摩湖", "いなプー"] and s: favs_list.append(s)
                    
            return (row.get('weather_source', 'ウェザーニュース'), ','.join(favs_list), fishing_mode)
        return ('ウェザーニュース', '', 'trout')
    except Exception as e:
        print(f"[Supabase取得エラー] {e}")
        return ('ウェザーニュース', '', 'trout')

def get_mode_fav_count(favorites, fishing_mode):
    active_group = COLOR_GROUPS if fishing_mode == "trout" else BASS_COLOR_GROUPS
    active_spots = []
    for group in active_group:
        for sg in group["sub_groups"]:
            active_spots.extend(sg["spots"])
    return len([s for s in favorites.split(',') if s in active_spots])

def add_favorite_spots(user_id, spot_names):
    if not supabase: return False, [], ["DB接続未完了です。"]
    source, favorites, fishing_mode = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    
    added = []
    errors = []
    for spot_name in spot_names:
        target_name = None
        norm_input = normalize_name(spot_name)
        
        for spot_key, data in ALL_SPOT_DATA.items():
            norm_key = normalize_name(spot_key)
            norm_aliases = [normalize_name(a) for a in data.get("aliases", [])]
            if norm_input == norm_key or norm_input in norm_aliases:
                target_name = spot_key
                break
        
        if not target_name:
            errors.append(f"{spot_name}(不明)")
            continue
            
        is_trout = False
        for g in COLOR_GROUPS:
            for sg in g["sub_groups"]:
                if target_name in sg["spots"]:
                    is_trout = True
                    break
            if is_trout: break
            
        target_active_group = COLOR_GROUPS if is_trout else BASS_COLOR_GROUPS
        target_active_spots = []
        for g in target_active_group:
            for sg in g["sub_groups"]:
                target_active_spots.extend(sg["spots"])
                
        target_mode_favs = [s for s in fav_list if s in target_active_spots]

        if target_name in fav_list:
            errors.append(f"{target_name}(登録済)")
            continue
        if len(target_mode_favs) >= MAX_FAVORITES:
            errors.append(f"{target_name}(上限{MAX_FAVORITES}件超過)")
            continue
            
        fav_list.append(target_name)
        added.append(target_name)
        
    if added:
        try:
            supabase.table('user_settings').upsert({
                'user_id': user_id, 'weather_source': source, 'favorite_spots': ','.join(fav_list), 'fishing_mode': fishing_mode
            }).execute()
        except Exception as e:
            return False, [], [f"DB保存エラー: fishing_mode列の設定をご確認ください"]
    return True, added, errors

def remove_favorite_spots(user_id, spot_names):
    if not supabase: return False, [], ["DB接続未完了です。"]
    source, favorites, fishing_mode = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    
    removed = []
    errors = []
    for spot_name in spot_names:
        target_name = None
        norm_input = normalize_name(spot_name)
        
        for spot_key, data in ALL_SPOT_DATA.items():
            norm_key = normalize_name(spot_key)
            norm_aliases = [normalize_name(a) for a in data.get("aliases", [])]
            if norm_input == norm_key or norm_input in norm_aliases:
                target_name = spot_key
                break
        
        if not target_name: target_name = spot_name 
        if target_name not in fav_list:
            errors.append(f"{target_name}(未登録)")
            continue
            
        fav_list.remove(target_name)
        removed.append(target_name)
        
    if removed:
        try:
            supabase.table('user_settings').upsert({
                'user_id': user_id, 'weather_source': source, 'favorite_spots': ','.join(fav_list), 'fishing_mode': fishing_mode
            }).execute()
        except Exception as e:
            return False, [], [f"DB保存エラー: fishing_mode列の設定をご確認ください"]
    return True, removed, errors

def clear_favorite_spots(user_id, mode="trout"):
    if not supabase: return False, "DB接続未完了です。"
    source, favorites, fishing_mode = get_user_setting(user_id)
    raw_fav_list = [s for s in favorites.split(',') if s]

    active_group = COLOR_GROUPS if mode == "trout" else BASS_COLOR_GROUPS
    active_spots = []
    for group in active_group:
        for sg in group["sub_groups"]:
            active_spots.extend(sg["spots"])

    other_mode_favs = [s for s in raw_fav_list if s not in active_spots]

    try:
        supabase.table('user_settings').upsert({
            'user_id': user_id, 'weather_source': source, 'favorite_spots': ','.join(other_mode_favs), 'fishing_mode': fishing_mode
        }).execute()
        return True, "表示中のすべてのお気に入りを削除しました。"
    except Exception as e:
        return False, f"削除に失敗しました: DB設定をご確認ください。詳細:{e}"

def move_favorite_spot(user_id, spot_name, direction, mode="trout"):
    if not supabase: return False, "DB接続未完了です。"
    source, favorites, fishing_mode = get_user_setting(user_id)
    raw_fav_list = [s for s in favorites.split(',') if s]
    
    if spot_name not in raw_fav_list:
        return False, "登録されていません。"

    active_group = COLOR_GROUPS if mode == "trout" else BASS_COLOR_GROUPS
    active_spots = []
    for group in active_group:
        for sg in group["sub_groups"]:
            active_spots.extend(sg["spots"])

    current_mode_favs = [s for s in raw_fav_list if s in active_spots]
    other_mode_favs = [s for s in raw_fav_list if s not in active_spots]

    if spot_name not in current_mode_favs:
         return False, "モードが違います。"

    idx = current_mode_favs.index(spot_name)
    
    if direction == "up" and idx > 0:
        current_mode_favs[idx - 1], current_mode_favs[idx] = current_mode_favs[idx], current_mode_favs[idx - 1]
    elif direction == "down" and idx < len(current_mode_favs) - 1:
        current_mode_favs[idx + 1], current_mode_favs[idx] = current_mode_favs[idx], current_mode_favs[idx + 1]
    elif direction == "top" and idx > 0:
        current_mode_favs.insert(0, current_mode_favs.pop(idx))
    elif direction == "bottom" and idx < len(current_mode_favs) - 1:
        current_mode_favs.append(current_mode_favs.pop(idx))
    elif direction == "cell_top":
        chunk_start = (idx // 10) * 10
        if idx > chunk_start:
            current_mode_favs.insert(chunk_start, current_mode_favs.pop(idx))
    elif direction == "cell_bottom":
        chunk_end = min(((idx // 10) + 1) * 10 - 1, len(current_mode_favs) - 1)
        if idx < chunk_end:
            current_mode_favs.insert(chunk_end, current_mode_favs.pop(idx))
    else:
        return True, "移動不要"
        
    new_fav_list = current_mode_favs + other_mode_favs

    try:
        supabase.table('user_settings').upsert({
            'user_id': user_id, 'weather_source': source, 'favorite_spots': ','.join(new_fav_list), 'fishing_mode': fishing_mode
        }).execute()
        return True, "移動しました"
    except Exception as e:
        return False, f"移動失敗: DB設定をご確認ください。詳細:{e}"

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

def get_cached_weather(spot_name):
    now = datetime.now(timezone.utc)
    if spot_name in MEMORY_CACHE:
        data, updated_time = MEMORY_CACHE[spot_name]
        if now - updated_time <= timedelta(hours=2):
            if isinstance(data, dict):
                weekly = data.get("__weekly__", [])
                if data.get("_version") != "settings_shortcut_v129": return None
                if not weekly: return None
                dates = [d for d in data.keys() if d != "__weekly__" and d != "_version" and d != "__is_dummy__" and d != "__disaster__"]
                if not dates: return None
            return data
            
    if not supabase: return None
    try:
        res = supabase.table('weather_cache').select('*').eq('spot_name', spot_name).execute()
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
                        MEMORY_CACHE[spot_name] = (weather_data, updated_time)
                        return weather_data
                except: pass
        return None
    except Exception as e:
        print(f"[Cache GET Error] {e}")
        return None

def save_cached_weather(spot_name, weather_data):
    if weather_data.get("__is_dummy__"):
        return
    
    now = datetime.now(timezone.utc)
    weather_data["_version"] = "settings_shortcut_v129"
    MEMORY_CACHE[spot_name] = (weather_data, now)
    if not supabase: return
    try:
        supabase.table('weather_cache').upsert({'spot_name': spot_name, 'weather_data': weather_data, 'updated_at': now.isoformat()}).execute()
    except Exception as e: print(f"[Cache SAVE Error] {e}")

@app.route("/", methods=['GET'])
def top_page():
    if supabase:
        try: supabase.table('user_settings').select('user_id').limit(1).execute()
        except Exception as e: print(f"[Supabase Wakeup Error] {e}")
    return "LINE Reply Bot Server is running!", 200

@app.route("/debug/cache", methods=['GET'])
def debug_cache():
    now = datetime.now(timezone.utc)
    cache_info = {}
    for spot, (data, updated_time) in MEMORY_CACHE.items():
        elapsed = now - updated_time
        remaining = timedelta(hours=2) - elapsed
        if remaining.total_seconds() > 0:
            remaining_str = f"{int(remaining.total_seconds() // 60)}分{int(remaining.total_seconds() % 60)}秒"
            status = "有効"
        else:
            remaining_str = "期限切れ"
            status = "無効"
        
        jst_time = updated_time.astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S')
        
        cache_info[spot] = {
            "status": status,
            "updated_at": jst_time,
            "remaining_time": remaining_str,
            "version": data.get("_version", "unknown") if isinstance(data, dict) else "unknown"
        }
    
    return jsonify({
        "total_cached": len(MEMORY_CACHE),
        "active_caches": sum(1 for v in cache_info.values() if v["status"] == "有効"),
        "details": cache_info
    }), 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK', 200

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        raw_msg = event.message.text.strip()
        user_id = event.source.user_id

        if is_throttled(user_id, cooldown=2.5):
            return

        source, favorites, fishing_mode = get_user_setting(user_id)

        if raw_msg in ["お気に入り1", "お気に入り2"]:
            active_group = COLOR_GROUPS if fishing_mode == "trout" else BASS_COLOR_GROUPS
            active_spots = []
            for group in active_group:
                for sg in group["sub_groups"]: active_spots.extend(sg["spots"])
                    
            raw_fav_list = [s.strip() for s in favorites.split(',') if s.strip()]
            fav_list = [s for s in raw_fav_list if s in active_spots]
            
            target_spot = None
            if raw_msg == "お気に入り1" and len(fav_list) > 0: target_spot = fav_list[0]
            elif raw_msg == "お気に入り2" and len(fav_list) > 1: target_spot = fav_list[1]
                
            if target_spot:
                target_spot_name, target_url, hp_url, hp2_url, map_url, tel, x_url, fb_url, insta_url, blog_url, yt_url, tenki_url = get_spot_details(target_spot)
                if not target_url:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ 【{target_spot}】のデータが見つかりません。"))
                    return

                is_fav = True
                weather_data = get_cached_weather(target_spot_name)
                if not weather_data:
                    weather_data = fetch_spot_1hour_data(target_url, tenki_url)
                    if weather_data: save_cached_weather(target_spot_name, weather_data)

                if weather_data:
                    flex_msg = build_grid_flex_message(target_spot_name, weather_data, hp_url, hp2_url, map_url, tel, x_url, fb_url, insta_url, blog_url, yt_url, is_favorite=is_fav)
                    line_bot_api.reply_message(event.reply_token, flex_msg)
                else:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ 【{target_spot_name}】の天気データの取得に失敗しました。少し時間をおいてから再度お試しください。"))
            else:
                msg = "⚠️ お気に入りが登録されていないか、件数が足りません。" + chr(10) + "「一覧」から釣り場を探して「⭐️ 登録」してください。"
                fav_list_pass = [s.strip() for s in favorites.split(',') if s.strip()]
                flex_msg = build_spot_list_carousel_horizontal(fav_list_pass, mode=fishing_mode)
                line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])
            return

        add_match = re.match(r'^追加[\s:：]+(.+)$', raw_msg, re.DOTALL)
        if add_match:
            spots_str = add_match.group(1).strip()
            spot_names = [s for s in re.split(r'[\s,、]+', spots_str) if s and s not in ["追加", "削除"]]
            
            # --- エリア一括展開ロジック ---
            expanded_queries = []
            for p in spot_names:
                if p in AREA_MAPPING:
                    expanded_queries.extend(AREA_MAPPING[p])
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
            
            _, favorites, _ = get_user_setting(user_id)
            fav_list = [s for s in favorites.split(',') if s]
            
            to_add = [s for s in resolved_spots if s not in fav_list]
            
            current_count = get_mode_fav_count(favorites, fishing_mode)
            total_after_add = current_count + len(to_add)

            if total_after_add > MAX_FAVORITES:
                msg_lines = [
                    f"⚠️ 登録上限（{MAX_FAVORITES}箇所）を超えるため、追加処理を中断しました。",
                    "━━━━━━━━━━━━━━━",
                    f"現在の登録数: {current_count}/{MAX_FAVORITES}箇所",
                    f"追加対象数: {len(to_add)}箇所",
                    f"追加後の合計: {total_after_add}箇所（上限超え）",
                    "━━━━━━━━━━━━━━━",
                    "お気に入りを削除してから再度実行してください。"
                ]
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=chr(10).join(msg_lines)))
                return
            
            success, added, errors = add_favorite_spots(user_id, expanded_queries)
            _, favorites_after, _ = get_user_setting(user_id)
            total_count_after = get_mode_fav_count(favorites_after, fishing_mode)
            
            reply_lines = []
            if added: reply_lines.append(f"✅ {len(added)}件追加しました: {', '.join(added)}")
            if errors or failed_queries: 
                all_err = errors + [f"{f}(不明)" for f in failed_queries]
                reply_lines.append(f"⚠️ スキップ・失敗: {', '.join(all_err)}")
            if added or errors or failed_queries: 
                reply_lines.append(f"📊 現在の登録数: {total_count_after}/{MAX_FAVORITES}箇所")
            else: 
                reply_lines.append("⚠️ 釣り場名が認識できませんでした。")
                
            fav_list_after = [s.strip() for s in favorites_after.split(',') if s.strip()]
            flex_msg = build_spot_list_carousel_horizontal(fav_list_after, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=chr(10).join(reply_lines)), flex_msg])
            return

        del_match = re.match(r'^削除[\s:：]+(.+)$', raw_msg, re.DOTALL)
        if del_match:
            spots_str = del_match.group(1).strip()
            spot_names = [s for s in re.split(r'[\s,、]+', spots_str) if s and s not in ["追加", "削除"]]
            
            # --- 削除時もエリア一括展開に対応 ---
            expanded_queries = []
            for p in spot_names:
                if p in AREA_MAPPING:
                    expanded_queries.extend(AREA_MAPPING[p])
                else:
                    expanded_queries.append(p)

            success, removed, errors = remove_favorite_spots(user_id, expanded_queries)
            _, favorites_after, _ = get_user_setting(user_id)
            total_count = get_mode_fav_count(favorites_after, fishing_mode)
            
            reply_lines = []
            if removed: reply_lines.append(f"✅ {len(removed)}件削除しました: {', '.join(removed)}")
            if errors: reply_lines.append(f"⚠️ スキップ・失敗: {', '.join(errors)}")
            if removed or errors: 
                reply_lines.append(f"📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所")
            else: 
                reply_lines.append("⚠️ 釣り場名が認識できませんでした。")
                
            fav_list_after = [s.strip() for s in favorites_after.split(',') if s.strip()]
            flex_msg = build_spot_list_carousel_horizontal(fav_list_after, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=chr(10).join(reply_lines)), flex_msg])
            return

        if raw_msg in ["一覧", "リスト", "釣り場一覧", "エリア", "📋 一覧", "📋一覧"]:
            fav_list_pass = [s.strip() for s in favorites.split(',') if s.strip()]
            flex_msg = build_spot_list_carousel_horizontal(fav_list_pass, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        if raw_msg in ["設定", "⚙️設定", "⚙️ 設定", "設定（並び替え・削除）", "⚙️ 設定（並び替え・削除）"]:
            fav_list = [s.strip() for s in favorites.split(',') if s.strip()]
            flex_msg = build_settings_flex_message(fav_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        fav_list_pass = [s.strip() for s in favorites.split(',') if s.strip()]
        flex_msg = build_spot_list_carousel_horizontal(fav_list_pass, mode=fishing_mode)
        line_bot_api.reply_message(event.reply_token, flex_msg)
    except Exception as e:
        print("\n=== システムエラー詳細 ===")
        traceback.print_exc()

@handler.add(PostbackEvent)
def handle_postback(event):
    try:
        user_id = event.source.user_id
        data_dict = dict(parse_qsl(event.postback.data))

        if is_throttled(user_id, cooldown=2.5):
            return

        action = data_dict.get("action")
        spot_name = data_dict.get("spot")
        source, favorites, fishing_mode = get_user_setting(user_id)
        
        if action == "dummy": return

        if "w" in data_dict:
            action = "show_weather"
            spot_name = data_dict["w"]

        if action == "switch_mode":
            target_mode = data_dict.get("mode", "trout")
            if supabase:
                try: supabase.table('user_settings').upsert({'user_id': user_id, 'weather_source': source, 'favorite_spots': favorites, 'fishing_mode': target_mode}).execute()
                except: pass
            mode_name = "🐟 ブラックバス" if target_mode == "bass" else "🐟 エリアトラウト"
            fav_list_pass = [s.strip() for s in favorites.split(',') if s.strip()]
            flex_msg = build_spot_list_carousel_horizontal(fav_list_pass, mode=target_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=f"{mode_name} モードに切り替えました！"), flex_msg])
            return

        elif action in ["show_top_selector", "show_cell_top_selector", "show_cell_bottom_selector"]:
            fav_list = [s.strip() for s in favorites.split(',') if s.strip()]
            active_group = COLOR_GROUPS if fishing_mode == "trout" else BASS_COLOR_GROUPS
            active_spots = []
            for group in active_group:
                for sg in group["sub_groups"]: active_spots.extend(sg["spots"])
            filtered_favs = [s for s in fav_list if s in active_spots]
            if not filtered_favs: return

            chunk_idx_str = data_dict.get("chunk")
            is_top = (action == "show_top_selector")
            is_cell_top = (action == "show_cell_top_selector")
            target_action = "fav_top" if is_top else ("fav_cell_top" if is_cell_top else "fav_cell_bottom")
            header_text = "🥇 1番目に設定する釣り場を選択" if is_top else ("🔝 枠の先頭へ移動" if is_cell_top else "⏬ 枠の最後尾へ移動")
            bg_color = "#d4af37" if is_top else ("#64b5f6" if is_cell_top else "#78909c")
            
            selector_bubbles = []
            if is_top: loop_chunks = [(i, filtered_favs[i:i+10]) for i in range(0, len(filtered_favs), 10)]
            else:
                c_idx = int(chunk_idx_str) if chunk_idx_str else 0
                loop_chunks = [(c_idx, filtered_favs[c_idx:c_idx+10])]
            
            for start_idx, chunk in loop_chunks:
                if not chunk: continue
                btns = []
                for spot in chunk:
                    btns.append({"type": "button", "action": {"type": "postback", "label": f"{spot}", "data": f"action={target_action}&spot={spot}"}, "style": "secondary", "margin": "xs", "height": "sm", "color": "#f8f9fa"})
                btns.append({"type": "separator", "margin": "md"})
                btns.append({"type": "button", "action": {"type": "postback", "label": "🔙 戻る（キャンセル）", "data": "action=show_settings"}, "style": "secondary", "margin": "md", "height": "sm", "color": "#e0e0e0"})

                selector_bubbles.append({"type": "bubble", "size": "kilo", "header": {"type": "box", "layout": "vertical", "backgroundColor": bg_color, "paddingAll": "10px", "contents": [{"type": "text", "text": header_text, "color": "#ffffff", "weight": "bold", "size": "sm"}]}, "body": {"type": "box", "layout": "vertical", "paddingAll": "10px", "contents": btns}})
            flex_msg = FlexSendMessage(alt_text="移動する釣り場の選択", contents={"type": "carousel", "contents": selector_bubbles})
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        elif action == "show_list":
            fav_list_pass = [s.strip() for s in favorites.split(',') if s.strip()]
            flex_msg = build_spot_list_carousel_horizontal(fav_list_pass, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return
            
        elif action == "show_settings":
            fav_list = [s.strip() for s in favorites.split(',') if s.strip()]
            flex_msg = build_settings_flex_message(fav_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        elif action == "show_weather":
            target_spot_name, target_url, hp_url, hp2_url, map_url, tel, x_url, fb_url, insta_url, blog_url, yt_url, tenki_url = get_spot_details(spot_name)
            if not target_url: return
            fav_list = [s.strip() for s in favorites.split(',') if s.strip()]
            is_fav = target_spot_name in fav_list

            weather_data = get_cached_weather(target_spot_name)
            if not weather_data:
                weather_data = fetch_spot_1hour_data(target_url, tenki_url)
                if weather_data: save_cached_weather(target_spot_name, weather_data)

            if weather_data:
                flex_msg = build_grid_flex_message(target_spot_name, weather_data, hp_url, hp2_url, map_url, tel, x_url, fb_url, insta_url, blog_url, yt_url, is_favorite=is_fav)
                line_bot_api.reply_message(event.reply_token, flex_msg)
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ 【{target_spot_name}】の天気データの取得に失敗しました。少し時間を置いてから再度お試しください。"))
            return

        elif action == "fav_add_and_list":
            success, added, errors = add_favorite_spots(user_id, [spot_name])
            _, favorites_after, _ = get_user_setting(user_id)
            total_count = get_mode_fav_count(favorites_after, fishing_mode)
            msg = f"✅ 追加しました: {added[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所" if added else f"⚠️ {errors[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所"
            fav_list_pass = [s.strip() for s in favorites_after.split(',') if s.strip()]
            flex_msg = build_spot_list_carousel_horizontal(fav_list_pass, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_confirm_and_list":
            flex_msg = build_delete_confirm_message(spot_name, "list")
            line_bot_api.reply_message(event.reply_token, flex_msg)

        elif action == "fav_del_confirm_and_settings":
            flex_msg = build_delete_confirm_message(spot_name, "settings")
            line_bot_api.reply_message(event.reply_token, flex_msg)

        elif action == "fav_del_execute_and_list":
            success, removed, errors = remove_favorite_spots(user_id, [spot_name])
            _, favorites_after, _ = get_user_setting(user_id)
            total_count = get_mode_fav_count(favorites_after, fishing_mode)
            msg = f"✅ 削除しました: {removed[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所" if removed else f"⚠️️ {errors[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所"
            fav_list_pass = [s.strip() for s in favorites_after.split(',') if s.strip()]
            flex_msg = build_spot_list_carousel_horizontal(fav_list_pass, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_execute_and_settings":
            success, removed, errors = remove_favorite_spots(user_id, [spot_name])
            _, favorites_after, _ = get_user_setting(user_id)
            fav_list = [s.strip() for s in favorites_after.split(',') if s.strip()]
            total_count = get_mode_fav_count(favorites_after, fishing_mode)
            msg = f"✅ 削除しました: {removed[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所" if removed else f"⚠️ {errors[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所"
            flex_msg = build_settings_flex_message(fav_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_cancel_and_list":
            fav_list_pass = [s.strip() for s in favorites.split(',') if s.strip()]
            flex_msg = build_spot_list_carousel_horizontal(fav_list_pass, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="キャンセルしました。"), flex_msg])

        elif action == "fav_del_cancel_and_settings":
            fav_list = [s.strip() for s in favorites.split(',') if s.strip()]
            flex_msg = build_settings_flex_message(fav_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="キャンセルしました。"), flex_msg])

        elif action == "fav_del_all_confirm":
            flex_msg = build_delete_all_confirm_message()
            line_bot_api.reply_message(event.reply_token, flex_msg)

        elif action == "fav_del_all_execute":
            success, msg = clear_favorite_spots(user_id, mode=fishing_mode)
            _, favorites_after, _ = get_user_setting(user_id)
            fav_list_pass = [s.strip() for s in favorites_after.split(',') if s.strip()]
            flex_msg = build_spot_list_carousel_horizontal(fav_list_pass, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=f"✅ {msg}"), flex_msg])

        elif action in ["fav_up", "fav_down", "fav_top", "fav_bottom", "fav_cell_top", "fav_cell_bottom"]:
            direction = action.replace("fav_", "")
            move_favorite_spot(user_id, spot_name, direction, mode=fishing_mode)
            _, favorites_after, _ = get_user_setting(user_id)
            fav_list = [s.strip() for s in favorites_after.split(',') if s.strip()]
            flex_msg = build_settings_flex_message(fav_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            
    except Exception as e:
        print(f"Postback Error: {e}")
        traceback.print_exc()

def get_top_favorite_spots(trout_limit=24, bass_limit=12):
    if not supabase: return [], []
    try:
        res = supabase.table('user_settings').select('favorite_spots').execute()
        trout_counts = {}
        bass_counts = {}
        
        trout_spots_list = []
        for g in COLOR_GROUPS:
            for sg in g["sub_groups"]:
                trout_spots_list.extend(sg["spots"])

        bass_spots_list = []
        for g in BASS_COLOR_GROUPS:
            for sg in g["sub_groups"]:
                bass_spots_list.extend(sg["spots"])
                
        if res.data:
            for row in res.data:
                favs = row.get('favorite_spots', '')
                if not favs: continue
                spots = [s.strip() for s in favs.split(',') if s.strip()]
                for s in spots: 
                    if s in trout_spots_list:
                        trout_counts[s] = trout_counts.get(s, 0) + 1
                    elif s in bass_spots_list:
                        bass_counts[s] = bass_counts.get(s, 0) + 1
                        
        sorted_trout = sorted(trout_counts.items(), key=lambda x: x[1], reverse=True)
        top_trout = [spot for spot, count in sorted_trout[:trout_limit]]
        
        sorted_bass = sorted(bass_counts.items(), key=lambda x: x[1], reverse=True)
        top_bass = [spot for spot, count in sorted_bass[:bass_limit]]
        
        return top_trout, top_bass
    except Exception as e:
        print(f"[Top Favs Error] {e}")
        return [], []

def run_background_update():
    if not supabase: return
    try:
        top_trout, top_bass = get_top_favorite_spots(trout_limit=24, bass_limit=12)
        
        trout_targets = []
        if top_trout:
            trout_cache_times = {}
            for spot in top_trout:
                res = supabase.table('weather_cache').select('updated_at').eq('spot_name', spot).execute()
                if res.data and len(res.data) > 0:
                    try: trout_cache_times[spot] = datetime.fromisoformat(res.data[0].get('updated_at').replace('Z', '+00:00'))
                    except: trout_cache_times[spot] = datetime.min.replace(tzinfo=timezone.utc)
                else: trout_cache_times[spot] = datetime.min.replace(tzinfo=timezone.utc)
            sorted_trout = sorted(trout_cache_times.items(), key=lambda x: x[1])
            trout_targets = [spot for spot, time in sorted_trout[:5]]

        bass_targets = []
        if top_bass:
            bass_cache_times = {}
            for spot in top_bass:
                res = supabase.table('weather_cache').select('updated_at').eq('spot_name', spot).execute()
                if res.data and len(res.data) > 0:
                    try: bass_cache_times[spot] = datetime.fromisoformat(res.data[0].get('updated_at').replace('Z', '+00:00'))
                    except: bass_cache_times[spot] = datetime.min.replace(tzinfo=timezone.utc)
                else: bass_cache_times[spot] = datetime.min.replace(tzinfo=timezone.utc)
            sorted_bass = sorted(bass_cache_times.items(), key=lambda x: x[1])
            bass_targets = [spot for spot, time in sorted_bass[:3]]

        for spot_name in trout_targets:
            data = ALL_SPOT_DATA.get(spot_name)
            if not data: continue
            url = data["url"]
            tenki_url = convert_to_10days_url(data.get("tenki_url"))
            weather_data = fetch_spot_1hour_data(url, tenki_url)
            if weather_data: save_cached_weather(spot_name, weather_data)
            time.sleep(random.uniform(2.5, 4.0))

        if bass_targets:
            time.sleep(random.uniform(5.0, 10.0))
            
            for spot_name in bass_targets:
                data = ALL_SPOT_DATA.get(spot_name)
                if not data: continue
                url = data["url"]
                tenki_url = convert_to_10days_url(data.get("tenki_url"))
                weather_data = fetch_spot_1hour_data(url, tenki_url)
                if weather_data: save_cached_weather(spot_name, weather_data)
                time.sleep(random.uniform(2.5, 4.0))

    except Exception as e:
        print(f"[Cron Background Error] {e}")

@app.route("/cron_trigger", methods=['GET', 'POST'])
def cron_trigger():
    if not supabase: return jsonify({"status": "error", "reason": "DB_NOT_CONNECTED"}), 500
    try:
        thread = threading.Thread(target=run_background_update)
        thread.start()
        return jsonify({"status": "success", "message": "Background update started"}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
