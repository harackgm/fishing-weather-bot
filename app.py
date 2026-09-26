import os, time, random, requests, traceback, difflib, re, threading, unicodedata, jpholiday
from urllib.parse import quote, urlparse, parse_qsl
from bs4 import BeautifulSoup
from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage, PostbackEvent
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone

# --- 外部ファイル(spots.py)からデータをインポート ---
from spots import SPOT_WEATHER_DATA, BASS_SPOT_WEATHER_DATA, COLOR_GROUPS, BASS_COLOR_GROUPS, ALL_SPOT_DATA
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

def guess_date_from_string(date_str, now_date):
    if not date_str: return now_date
    m = re.search(r'(?:(\d{1,2})[月/-])?\s*(\d{1,2})日?', date_str)
    if not m: return now_date
    month_str, day_str = m.group(1), m.group(2)
    day = int(day_str)
    month = int(month_str) if month_str else now_date.month
    try: target = now_date.replace(month=month, day=day)
    except ValueError: return now_date
    if (now_date - target).days > 15:
        try: target = target.replace(year=now_date.year + 1)
        except ValueError: pass
    elif (target - now_date).days > 15:
        try: target = target.replace(year=now_date.year - 1)
        except ValueError: pass
    return target

def build_delete_confirm_message(spot_name, source):
    execute_action = f"fav_del_execute_and_{source}"
    cancel_action = f"fav_del_cancel_and_{source}"
    bubble = {
        "type": "bubble", "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "15px",
            "contents": [
                {"type": "text", "text": "⚠️ 削除の確認", "weight": "bold", "color": "#ff0000", "size": "md"},
                {"type": "text", "text": f"「{spot_name}」をお気に入りから削除しますか？", "wrap": True, "size": "sm", "color": "#333333"}
            ]
        },
        "footer": {
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "secondary", "height": "sm", "flex": 1, "action": {"type": "postback", "label": "キャンセル", "data": f"action={cancel_action}"}},
                {"type": "button", "style": "primary", "color": "#e53935", "height": "sm", "flex": 1, "action": {"type": "postback", "label": "削除する", "data": f"action={execute_action}&spot={spot_name}"}}
            ]
        }
    }
    return FlexSendMessage(alt_text=f"{spot_name}の削除確認", contents=bubble)

def build_delete_all_confirm_message():
    bubble = {
        "type": "bubble", "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "15px",
            "contents": [
                {"type": "text", "text": "⚠️ 全て削除の確認", "weight": "bold", "color": "#ff0000", "size": "md"},
                {"type": "text", "text": "表示中のすべてのお気に入りを削除しますか？\n（この操作は元に戻せません）", "wrap": True, "size": "sm", "color": "#333333"}
            ]
        },
        "footer": {
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "secondary", "height": "sm", "flex": 1, "action": {"type": "postback", "label": "キャンセル", "data": "action=fav_del_cancel_and_settings"}},
                {"type": "button", "style": "primary", "color": "#e53935", "height": "sm", "flex": 1, "action": {"type": "postback", "label": "全て削除", "data": "action=fav_del_all_execute"}}
            ]
        }
    }
    return FlexSendMessage(alt_text="全て削除の確認", contents=bubble)

def build_settings_flex_message(fav_list, mode="trout"):
    active_group = COLOR_GROUPS if mode == "trout" else BASS_COLOR_GROUPS
    active_spots = []
    for group in active_group:
        for sg in group["sub_groups"]:
            active_spots.extend(sg["spots"])
            
    filtered_favs = [s for s in fav_list if s in active_spots]

    if mode == "trout":
        switch_btn = {"type": "button", "action": {"type": "postback", "label": "🎣 バスモードへ切替", "data": "action=switch_mode&mode=bass"}, "style": "primary", "color": "#1e88e5", "margin": "md", "height": "sm"}
        title_text = "⚙️ お気に入り設定 (トラウト)"
        header_color = "#d4af37"
    else:
        switch_btn = {"type": "button", "action": {"type": "postback", "label": "🐟 トラウトモードへ戻る", "data": "action=switch_mode&mode=trout"}, "style": "primary", "color": "#e65100", "margin": "md", "height": "sm"}
        title_text = "⚙️ お気に入り設定 (バス)"
        header_color = "#4caf50"

    if not filtered_favs:
        bubble = {
            "type": "bubble", "size": "mega",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": header_color, "paddingAll": "10px",
                "contents": [{"type": "text", "text": title_text, "color": "#ffffff", "weight": "bold", "size": "md"}]
            },
            "body": {
                "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "10px",
                "contents": [
                    switch_btn,
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": "現在お気に入りは登録されていません。\n\n釣り場を検索し、天気カード内の「⭐️ 登録」ボタンを押すだけで追加できます！", "wrap": True, "size": "sm", "color": "#555555", "margin": "md"}
                ]
            }
        }
        return FlexSendMessage(alt_text="お気に入り管理パネル", contents=bubble)

    bubbles = []
    chunk_size = 10
    for i in range(0, len(filtered_favs), chunk_size):
        chunk = filtered_favs[i:i + chunk_size]
        rows = []
        rows.append(switch_btn)
        rows.append({"type": "separator", "margin": "md"})
        rows.append({
            "type": "box", "layout": "horizontal", "spacing": "xs", "paddingTop": "10px", "paddingBottom": "10px",
            "contents": [
                {"type": "button", "action": {"type": "postback", "label": "🥇1番", "data": "action=show_top_selector"}, "style": "secondary", "height": "sm", "flex": 1, "color": "#fff9c4"},
                {"type": "button", "action": {"type": "postback", "label": "🔝先頭", "data": f"action=show_cell_top_selector&chunk={i}"}, "style": "secondary", "height": "sm", "flex": 1, "color": "#e3f2fd"},
                {"type": "button", "action": {"type": "postback", "label": "⏬末尾", "data": f"action=show_cell_bottom_selector&chunk={i}"}, "style": "secondary", "height": "sm", "flex": 1, "color": "#eceff1"}
            ]
        })
        rows.append({"type": "separator", "margin": "sm"})

        for spot in chunk:
            rows.append({
                "type": "box", "layout": "horizontal", "margin": "md", "alignItems": "center",
                "contents": [
                    {"type": "text", "text": f"{spot}", "size": "sm", "weight": "bold", "flex": 4, "color": "#333333", "wrap": True},
                    {"type": "button", "action": {"type": "postback", "label": "⬆️", "data": f"action=fav_up&spot={spot}"}, "style": "secondary", "flex": 2, "margin": "xs"},
                    {"type": "button", "action": {"type": "postback", "label": "⬇️", "data": f"action=fav_down&spot={spot}"}, "style": "secondary", "flex": 2, "margin": "xs"},
                    {"type": "button", "action": {"type": "postback", "label": "🗑️", "data": f"action=fav_del_confirm_and_settings&spot={spot}"}, "style": "secondary", "color": "#ffe6e6", "flex": 2, "margin": "xs"}
                ]
            })

        rows.append({"type": "separator", "margin": "md"})
        rows.append({
            "type": "box", "layout": "horizontal", "margin": "md", "spacing": "sm",
            "contents": [
                {"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#e53935", "borderWidth": "normal", "borderColor": "#e53935", "cornerRadius": "md", "paddingAll": "none", "contents": [{"type": "button", "action": {"type": "postback", "label": "🗑️ 全て削除", "data": "action=fav_del_all_confirm"}, "style": "link", "color": "#ffffff", "height": "sm", "margin": "none"}]},
                {"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "none", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list", "displayText": "📋 一覧"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]}
            ]
        })

        bubbles.append({
            "type": "bubble", "size": "mega",
            "header": {"type": "box", "layout": "vertical", "backgroundColor": header_color, "paddingAll": "10px", "contents": [{"type": "text", "text": f"{title_text} ({i+1}-{min(i+chunk_size, len(filtered_favs))}/{len(filtered_favs)}件)", "color": "#ffffff", "weight": "bold", "size": "md"}]},
            "body": {"type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "10px", "contents": rows}
        })
    
    if len(bubbles) == 1: return FlexSendMessage(alt_text="お気に入り管理パネル", contents=bubbles[0])
    else: return FlexSendMessage(alt_text="お気に入り管理パネル", contents={"type": "carousel", "contents": bubbles})

def build_spot_list_carousel_horizontal(user_id=None, mode="trout"):
    active_group = COLOR_GROUPS if mode == "trout" else BASS_COLOR_GROUPS
    active_spots = []
    for group in active_group:
        for sg in group["sub_groups"]:
            active_spots.extend(sg["spots"])

    bubbles = []
    filtered_favs = []

    if user_id:
        _, favorites, _ = get_user_setting(user_id)
        raw_fav_list = [s for s in favorites.split(',') if s]
        filtered_favs = [s for s in raw_fav_list if s in active_spots]
        
        fav_rows = []
        if not filtered_favs:
            fav_rows.append({"type": "box", "layout": "vertical", "backgroundColor": "#fffde7", "cornerRadius": "md", "paddingAll": "md", "margin": "md", "contents": [{"type": "text", "text": "現在このモードでお気に入りは登録されていません。\n右へスワイプして釣り場を探し、「⭐️ 登録」ボタンを押すか、テキストで「追加 〇〇」と送信してください。", "wrap": True, "size": "sm", "color": "#555555"}]})
        else:
            for i in range(0, len(filtered_favs), 2):
                pair = filtered_favs[i:i+2]
                row_buttons = []
                for j, spot in enumerate(pair):
                    global_idx = i + j
                    if global_idx < 2:
                        row_buttons.append({"type": "box", "layout": "vertical", "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "none", "margin": "xs", "contents": [{"type": "button", "action": {"type": "postback", "label": spot, "data": f"w={spot}"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]})
                    else:
                        row_buttons.append({"type": "button", "style": "secondary", "color": "#fff59d", "margin": "xs", "height": "sm", "action": {"type": "postback", "label": spot, "data": f"w={spot}"}})
                if len(pair) == 1:
                    row_buttons.append({"type": "filler"})
                    
                row_margin = "none" if i == 0 else ("md" if i % 10 == 0 else "xs")
                row_box = {"type": "box", "layout": "horizontal", "contents": row_buttons, "margin": row_margin}
                fav_rows.append(row_box)

        fav_rows.append({"type": "separator", "margin": "md", "color": "#cccccc"})
        fav_rows.append({"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm", "contents": [{"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#f8f9fa", "borderWidth": "normal", "borderColor": "#e0e0e0", "cornerRadius": "md", "paddingAll": "none", "contents": [{"type": "button", "action": {"type": "postback", "label": "⚙️ 設定/切替", "data": "action=show_settings", "displayText": "⚙️ 設定"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]}, {"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "none", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧更新", "data": "action=show_list", "displayText": "📋 一覧"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]}]})

        header_color = "#d4af37" if mode == "trout" else "#4caf50"
        header_text = "⭐ トラウトお気に入り" if mode == "trout" else "⭐ バスお気に入り"

        fav_bubble = {"type": "bubble", "size": "giga", "header": {"type": "box", "layout": "horizontal", "backgroundColor": header_color, "paddingAll": "10px", "alignItems": "center", "contents": [{"type": "text", "text": header_text, "color": "#ffffff", "weight": "bold", "size": "md", "flex": 1}, {"type": "text", "text": f"({len(filtered_favs)}/{MAX_FAVORITES})", "color": "#eeeeee", "size": "xs", "align": "end", "flex": 0}]}, "body": {"type": "box", "layout": "vertical", "paddingAll": "6px", "contents": fav_rows}}
        bubbles.append(fav_bubble)

    for group in active_group:
        rows = []
        is_first_row = True
        for sg in group["sub_groups"]:
            spots = sg["spots"]
            btn_bg = sg["bg"]
            for i in range(0, len(spots), 2):
                pair = spots[i:i+2]
                row_buttons = []
                for spot in pair:
                    label_text = f"★ {spot}" if spot in filtered_favs else spot
                    row_buttons.append({"type": "button", "style": "secondary", "color": btn_bg, "margin": "xs", "height": "sm", "action": {"type": "postback", "label": label_text, "data": f"w={spot}"}})
                if len(pair) == 1:
                    row_buttons.append({"type": "filler"})
                    
                row_margin = "none" if is_first_row else "xs"
                rows.append({"type": "box", "layout": "horizontal", "contents": row_buttons, "margin": row_margin})
                is_first_row = False
            
        bubble = {"type": "bubble", "size": "giga", "header": {"type": "box", "layout": "vertical", "backgroundColor": group["header_bg"], "paddingAll": "10px", "contents": [{"type": "text", "text": group["title"], "color": "#ffffff", "weight": "bold", "size": "md"}]}, "body": {"type": "box", "layout": "vertical", "paddingAll": "6px", "contents": rows}}
        bubbles.append(bubble)

    guide_bubble = {"type": "bubble", "size": "giga", "header": {"type": "box", "layout": "vertical", "backgroundColor": "#888888", "paddingAll": "10px", "contents": [{"type": "text", "text": "📖 使い方ガイド", "color": "#ffffff", "weight": "bold", "size": "md"}]}, "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "15px", "contents": [{"type": "box", "layout": "vertical", "spacing": "sm", "contents": [{"type": "text", "text": "👇 基本の操作", "weight": "bold", "size": "sm", "color": "#333333"}, {"type": "text", "text": "・一覧のボタンをタップで天気予報を表示", "wrap": True, "size": "xs", "color": "#666666"}]}, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [{"type": "text", "text": "💬 テキストコマンド", "weight": "bold", "size": "sm", "color": "#333333"}, {"type": "text", "text": "【まとめて追加】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"}, {"type": "text", "text": "例：「追加 東山湖 すその 足柄 座間 醒井」\n※釣り場と釣り場の名前の間にスペースを入れてください。", "wrap": True, "size": "xs", "color": "#666666"}, {"type": "text", "text": "【まとめて削除】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"}, {"type": "text", "text": "例：「削除 東山湖 すその 足柄」\n※追加と同じく、名前の間にスペースを入れて複数同時に解除できます。", "wrap": True, "size": "xs", "color": "#666666"}, {"type": "text", "text": "【設定】", "weight": "bold", "size": "sm", "color": "#333333", "margin": "sm"}, {"type": "text", "text": "「設定」と送信すると、並び替え・全削除パネルが出ます。", "wrap": True, "size": "xs", "color": "#666666"}, {"type": "text", "text": "【一覧（メニュー）の出し方】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"}, {"type": "text", "text": "「一覧」という言葉や、それ以外の適当な文字（「あ」「1」「a」など）を送信すると、この一覧表が表示されます。", "wrap": True, "size": "xs", "color": "#666666"}]}, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [{"type": "text", "text": "⭐ お気に入り機能とリッチメニュー", "weight": "bold", "size": "sm", "color": "#333333"}, {"type": "text", "text": "【一番お気に入り（メニュー左）】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"}, {"type": "text", "text": "現在のモードにおけるお気に入りリストの「1番目（一番上）」の釣り場の天気を瞬時に表示します。", "wrap": True, "size": "xs", "color": "#666666"}]}, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [{"type": "text", "text": "🛑 配信停止・解除", "weight": "bold", "size": "sm", "color": "#333333"}, {"type": "text", "text": "このBotの利用を停止したい場合は、トーク画面右上のメニュー「≡」から「ブロック」を行ってください。", "wrap": True, "size": "xs", "color": "#666666"}, {"type": "text", "text": "完全に消去する場合", "weight": "bold", "size": "xs", "color": "#333333", "margin": "md"}, {"type": "text", "text": "「トーク一覧」画面に戻り、このBotのトークを長押し（iPhoneは左スワイプ）して「削除」してください。", "wrap": True, "size": "xs", "color": "#666666"}]}]}}
    bubbles.append(guide_bubble)

    return FlexSendMessage(alt_text="釣り場一覧", contents={"type": "carousel", "contents": bubbles})

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
                "アルクス宇宇都宮": "アルクス宇都宮", "片仓ダム": "片倉ダム", "多田良沼": "多々良沼",
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
            norm_aliases = [normalize_name(a) for a in data["aliases"]]
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
            norm_aliases = [normalize_name(a) for a in data["aliases"]]
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

def fetch_weekly_data_from_api(lat, lon, raw_exclude_dates):
    try:
        api_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Asia%2FTokyo&forecast_days=14"
        res = requests.get(api_url, timeout=5.0)
        res.raise_for_status()
        data = res.json()
        
        daily = data.get("daily", {})
        times = daily.get("time", [])
        weathercodes = daily.get("weathercode", [])
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])
        rain_probs = daily.get("precipitation_probability_max", [])
        
        weekly_data = []
        now_jst_date = datetime.now(timezone(timedelta(hours=9))).date()
        last_wn_date = guess_date_from_string(raw_exclude_dates[-1], now_jst_date) if raw_exclude_dates else None

        for i in range(min(len(times), 14)):
            dt = datetime.strptime(times[i], "%Y-%m-%d").date()
            if last_wn_date and dt <= last_wn_date: continue
                
            w_str = ["(月)", "(火)", "(水)", "(木)", "(金)", "(土)", "(日)"][dt.weekday()]
            date_label = f"{dt.day}{w_str}"
            
            code = weathercodes[i] if i < len(weathercodes) and weathercodes[i] is not None else 0
            if code in [0, 1]: img_url = "https://gvs.weathernews.jp/onebox/img/wxicon/100.png"
            elif code in [2, 3, 45, 48]: img_url = "https://gvs.weathernews.jp/onebox/img/wxicon/200.png"
            elif code in [71, 73, 75, 77, 85, 86]: img_url = "https://gvs.weathernews.jp/onebox/img/wxicon/400.png"
            else: img_url = "https://gvs.weathernews.jp/onebox/img/wxicon/300.png"
            
            t_max = str(round(temp_max[i])) if i < len(temp_max) and temp_max[i] is not None else "-"
            t_min = str(round(temp_min[i])) if i < len(temp_min) and temp_min[i] is not None else "-"
            
            r_prob = f"{round(rain_probs[i])}%" if i < len(rain_probs) and rain_probs[i] is not None else "-"
            
            weekly_data.append({"date": date_label, "img_url": img_url, "temp_max": t_max, "temp_min": t_min, "rain_prob": r_prob})
            if len(weekly_data) >= 8: break
        return weekly_data
    except Exception as e:
        print(f"[Open-Meteo API Error] {e}")
        return []

def fetch_weekly_data_from_tenki(tenki_url, raw_exclude_dates):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(tenki_url, headers=headers, timeout=3.0)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        weekly_data = []
        now_jst_date = datetime.now(timezone(timedelta(hours=9))).date()
        last_wn_date = guess_date_from_string(raw_exclude_dates[-1], now_jst_date) if raw_exclude_dates else None
            
        elems = soup.select('.forecast10days-actab, .forecast14days-actab')
        for elem in elems:
            days_elem = elem.find('div', class_='days')
            forecast_elem = elem.find('div', class_='forecast')
            temp_elem = elem.find('div', class_='temp')
            prob_elem = elem.find('div', class_='prob-precip')
            
            if not (days_elem and temp_elem): continue
            raw_days = days_elem.get_text(strip=True) 
            tenki_date = guess_date_from_string(raw_days, now_jst_date)
            if last_wn_date and tenki_date <= last_wn_date: continue

            m = re.search(r'(\d{1,2})[月/](\d{1,2})日?\((.+?)\)', raw_days)
            if m:
                date_label = f"{m.group(2)}({m.group(3)})"
            else:
                date_label = raw_days
                
            high_elem = temp_elem.find('span', class_='high-temp')
            low_elem = temp_elem.find('span', class_='low-temp')
            t_max = high_elem.get_text(strip=True).replace('℃', '').strip() if high_elem else "-"
            t_min = low_elem.get_text(strip=True).replace('℃', '').strip() if low_elem else "-"
            r_prob = prob_elem.get_text(strip=True) if prob_elem else "-"
            
            img_tag = forecast_elem.find('img') if forecast_elem else None
            img_src = img_tag['src'] if img_tag and 'src' in img_tag.attrs else ""
            
            if '01' in img_src or '02' in img_src or '100' in img_src: final_img = "https://gvs.weathernews.jp/onebox/img/wxicon/100.png"
            elif '08' in img_src or '09' in img_src or '12' in img_src or '200' in img_src: final_img = "https://gvs.weathernews.jp/onebox/img/wxicon/200.png"
            elif '雨' in img_src or 'rain' in img_src or '300' in img_src or '20' in img_src or '46' in img_src: final_img = "https://gvs.weathernews.jp/onebox/img/wxicon/300.png"
            elif 'snow' in img_src or '400' in img_src: final_img = "https://gvs.weathernews.jp/onebox/img/wxicon/400.png"
            else: final_img = "https://gvs.weathernews.jp/onebox/img/wxicon/200.png"
                
            weekly_data.append({"date": date_label, "img_url": final_img, "temp_max": t_max, "temp_min": t_min, "rain_prob": r_prob})
            if len(weekly_data) >= 8: break
        return weekly_data
    except Exception as e:
        print(f"[tenki.jp Extract Error] {e}")
        return []

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
        if tenki_url: weekly_data = fetch_weekly_data_from_tenki(tenki_url, raw_exclude_dates)
        if not weekly_data:
            lat, lon = extract_lat_lon(url)
            if lat and lon: weekly_data = fetch_weekly_data_from_api(lat, lon, raw_exclude_dates)

        if not weekly_data or len(weekly_data) < 4:
            now_dt = datetime.now(timezone(timedelta(hours=9)))
            start_date = now_dt.date()
            if raw_exclude_dates:
                last_wn = guess_date_from_string(raw_exclude_dates[-1], now_dt.date())
                start_date = last_wn + timedelta(days=1)
            weekly_data = []
            for i in range(8):
                day_dt = start_date + timedelta(days=i)
                w_str = ["(月)", "(火)", "(水)", "(木)", "(金)", "(土)", "(日)"][day_dt.weekday()]
                weekly_data.append({"date": f"{day_dt.day}{w_str}", "img_url": "https://gvs.weathernews.jp/onebox/img/wxicon/200.png", "temp_max": "-", "temp_min": "-", "rain_prob": "-"})

        weather_by_date["__weekly__"] = weekly_data
        return weather_by_date
    except requests.exceptions.Timeout: return None
    except Exception as e:
        print(f"[スクレイピング＆API エラー] {e}")
        return None

def get_cached_weather(spot_name):
    now = datetime.now(timezone.utc)
    if spot_name in MEMORY_CACHE:
        data, updated_time = MEMORY_CACHE[spot_name]
        if now - updated_time <= timedelta(hours=2):
            if isinstance(data, dict):
                weekly = data.get("__weekly__", [])
                if data.get("_version") != "settings_shortcut_v98": return None
                if not weekly or len(weekly) < 4 or weekly[0].get("temp_max") == "-": return None
                dates = [d for d in data.keys() if d != "__weekly__" and d != "_version"]
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
                            if weather_data.get("_version") != "settings_shortcut_v98": return None
                            if not weekly or len(weekly) < 4 or weekly[0].get("temp_max") == "-": return None
                            dates = [d for d in weather_data.keys() if d != "__weekly__" and d != "_version"]
                            if not dates: return None
                        MEMORY_CACHE[spot_name] = (weather_data, updated_time)
                        return weather_data
                except: pass
        return None
    except Exception as e:
        print(f"[Cache GET Error] {e}")
        return None

def save_cached_weather(spot_name, weather_data):
    now = datetime.now(timezone.utc)
    weather_data["_version"] = "settings_shortcut_v98"
    MEMORY_CACHE[spot_name] = (weather_data, now)
    if not supabase: return
    try:
        supabase.table('weather_cache').upsert({'spot_name': spot_name, 'weather_data': weather_data, 'updated_at': now.isoformat()}).execute()
    except Exception as e: print(f"[Cache SAVE Error] {e}")

def build_grid_flex_message(spot_name, weather_data, hp_url="", hp2_url="", map_url="", tel="", x_url="", fb_url="", insta_url="", blog_url="", yt_url="", is_favorite=False):
    weekly_data = weather_data.get("__weekly__", []) if isinstance(weather_data, dict) else []
    dates = [d for d in weather_data.keys() if d != "__weekly__" and d != "_version"]
    weather_by_date = weather_data
    jst = timezone(timedelta(hours=9))
    now_jst_date = datetime.now(jst).date()

    active_group = COLOR_GROUPS
    for group in BASS_COLOR_GROUPS:
        for sg in group["sub_groups"]:
            if spot_name in sg["spots"]:
                active_group = BASS_COLOR_GROUPS
                break

    header_color = "#0066cc"
    for group in active_group:
        found = False
        for sg in group["sub_groups"]:
            if spot_name in sg["spots"]:
                header_color = group["header_bg"]
                found = True
                break
        if found: break

    def create_day_column(date_str):
        if not date_str: return {"type": "box", "layout": "vertical", "flex": 1, "contents": [{"type": "text", "text": "-", "color": "#cccccc", "align": "center", "size": "xs"}]}
        daily_data = weather_by_date[date_str]
        target_date = guess_date_from_string(date_str, now_jst_date)
        is_hol = jpholiday.is_holiday(target_date)
        is_holiday_flag = is_hol or "(祝)" in date_str
        display_date_str = date_str
        header_bg_color = "#f5f5f5"
        header_text_color = "#333333"

        if is_holiday_flag or "(日)" in date_str:
            header_bg_color = "#ffe6e6"
            header_text_color = "#cc0000"
            if is_holiday_flag and "🇯🇵" not in display_date_str: display_date_str = f"🇯🇵 {date_str}"
        elif "(土)" in date_str:
            header_bg_color = "#e6f2ff"
            header_text_color = "#0066cc"

        rows = [
            {
                "type": "box", "layout": "horizontal", "margin": "none",
                "contents": [
                    {"type": "text", "text": "時", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "天", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "℃", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "☔", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"},
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
                    {"type": "image", "url": img_url, "size": "xs", "flex": 1},
                    {"type": "text", "text": t_val, "size": "xs", "flex": 1, "align": "center", "color": temp_color},
                    {"type": "text", "text": r_val, "size": "xs", "flex": 1, "align": "center", "color": rain_color},
                    {"type": "text", "text": w_val, "size": "xs", "flex": 1, "align": "center"}
                ]
            })

        return {
            "type": "box", "layout": "vertical", "flex": 1,
            "contents": [
                {"type": "box", "layout": "vertical", "backgroundColor": header_bg_color, "paddingAll": "4px", "margin": "sm",
                 "contents": [{"type": "text", "text": display_date_str, "weight": "bold", "size": "sm", "align": "center", "color": header_text_color}]}
            ] + [{"type": "box", "layout": "vertical", "spacing": "none", "margin": "sm", "contents": rows}]
        }

    def create_weekly_box(slice_data):
        if not slice_data: return None
        cols = []
        for w in slice_data:
            rain_val = str(w.get("rain_prob", "0")).replace("%", "").strip()
            rain_color = "#0000ff" if rain_val.isdigit() and int(rain_val) > 0 else "#555555"
            date_str = str(w.get("date", "-"))
            date_color = "#333333" 
            if date_str != "-":
                target_date = guess_date_from_string(date_str, now_jst_date)
                is_hol = jpholiday.is_holiday(target_date)
                if is_hol or "(日)" in date_str or "(祝)" in date_str: date_color = "#cc0000"
                elif "(土)" in date_str: date_color = "#0066cc"

            cols.append({
                "type": "box", "layout": "vertical", "flex": 1, "alignItems": "center", "spacing": "xs",
                "contents": [
                    {"type": "text", "text": date_str, "size": "xxs", "weight": "bold", "color": date_color, "align": "center"},
                    {"type": "image", "url": str(w.get("img_url", "https://gvs.weathernews.jp/onebox/img/wxicon/200.png")), "size": "xs", "aspectMode": "fit"},
                    {"type": "text", "text": f"{w.get('temp_max', '-')}/{w.get('temp_min', '-')}℃", "size": "xxs", "color": "#333333", "weight": "bold", "align": "center"},
                    {"type": "text", "text": f"{w.get('rain_prob', '-')}", "size": "xxs", "color": rain_color, "weight": "bold", "align": "center"}
                ]
            })
        return {"type": "box", "layout": "horizontal", "margin": "md", "spacing": "xs", "backgroundColor": "#f4f4f4", "paddingAll": "8px", "cornerRadius": "sm", "contents": cols}

    def create_header_block(bubble_index):
        header_contents = [{"type": "text", "text": f"📍 {spot_name}", "color": "#ffffff", "weight": "bold", "size": "lg"}]
        all_rows = []
        
        top_buttons = []
        if is_favorite: top_buttons.append({"type": "button", "action": {"type": "postback", "label": "🗑️ 解除", "data": f"action=fav_del_confirm_and_list&spot={spot_name}"}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs", "color": "#ffcccc"})
        else: top_buttons.append({"type": "button", "action": {"type": "postback", "label": "⭐️ 登録", "data": f"action=fav_add_and_list&spot={spot_name}"}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs", "color": "#fff59d"})

        spot_data = ALL_SPOT_DATA.get(spot_name, {})
        hide_default_map = spot_data.get("hide_default_map", False)

        if map_url and not hide_default_map: top_buttons.append({"type": "button", "action": {"type": "uri", "label": "🗺️ 地図", "uri": map_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        elif len(top_buttons) == 1: top_buttons.append({"type": "box", "layout": "vertical", "flex": 1, "margin": "xs", "contents": []})
            
        all_rows.append(top_buttons)

        header_buttons_bottom = []
        if hp_url:
            label_text = "🌐 大崎HP" if spot_name == "大崎・赤城" else "🌐 HP"
            header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": label_text, "uri": hp_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if hp2_url:
            label_text2 = "🌐 赤城HP" if spot_name == "大崎・赤城" else "🌐 HP2"
            header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": label_text2, "uri": hp2_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if x_url: header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": "𝕏", "uri": x_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if fb_url: header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": "📘 FB", "uri": fb_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if insta_url: header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": "📷 Insta", "uri": insta_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if blog_url: header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": "📝 Blog", "uri": blog_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if yt_url: header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": "▶️ YouTube", "uri": yt_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
            
        if header_buttons_bottom: all_rows.append(header_buttons_bottom)

        custom_button_rows = spot_data.get("custom_button_rows", [])
        for row_links in custom_button_rows:
            row_buttons = []
            for link in row_links:
                if link.get("url"):
                    action_data = {"type": "uri", "label": link["label"], "uri": link["url"]}
                else:
                    action_data = {"type": "postback", "label": link["label"], "data": "action=dummy"}
                row_buttons.append({"type": "button", "action": action_data, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
            if row_buttons: all_rows.append(row_buttons)

        if len(all_rows) > 2:
            mid = (len(all_rows) + 1) // 2
            left_rows = all_rows[:mid]
            right_rows = all_rows[mid:]
        else:
            left_rows = all_rows
            right_rows = []

        max_rows = max(len(left_rows), len(right_rows))
        target_rows = left_rows if bubble_index == 0 else right_rows

        for row_buttons in target_rows: header_contents.append({"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "xs", "contents": row_buttons})
        
        spacer_count = max_rows - len(target_rows)
        for _ in range(spacer_count):
            spacer = {"type": "box", "layout": "vertical", "margin": "sm", "height": "40px", "contents": [{"type": "filler"}]}
            header_contents.append(spacer)

        return {"type": "box", "layout": "vertical", "backgroundColor": header_color, "paddingAll": "10px", "contents": header_contents}

    weekly_box_1 = create_weekly_box(weekly_data[0:4]) if len(weekly_data) > 0 else None
    weekly_box_2 = create_weekly_box(weekly_data[4:8]) if len(weekly_data) > 4 else None
    banner_img_url = "https://raw.githubusercontent.com/harackgm/fishing-weather-bot/main/tenkiharackbana.jpg"

    bottom_buttons_1 = [{"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "0px", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list", "displayText": "📋 一覧"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]}]
    bottom_buttons_2 = []
    if tel:
        clean_tel = tel.replace('-', '').strip()
        bottom_buttons_2.append({"type": "box", "layout": "vertical", "flex": 2, "backgroundColor": "#f8f9fa", "borderWidth": "normal", "borderColor": "#e0e0e0", "cornerRadius": "md", "paddingAll": "0px", "contents": [{"type": "button", "action": {"type": "uri", "label": "📞 電話", "uri": f"tel:{clean_tel}"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]})
    bottom_buttons_2.append({"type": "box", "layout": "vertical", "flex": 3 if tel else 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "0px", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list", "displayText": "📋 一覧"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]})

    bottom_block_contents_1 = []
    if weekly_box_1:
        bottom_block_contents_1.append({"type": "separator", "margin": "md"})
        bottom_block_contents_1.append(weekly_box_1)
    bottom_block_contents_1.extend([{"type": "separator", "margin": "md"}, {"type": "image", "url": banner_img_url, "size": "full", "aspectRatio": "3:1", "aspectMode": "cover", "margin": "md"}, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm", "contents": bottom_buttons_1}])

    bottom_block_contents_2 = []
    if weekly_box_2:
        bottom_block_contents_2.append({"type": "separator", "margin": "md"})
        bottom_block_contents_2.append(weekly_box_2)
    bottom_block_contents_2.extend([{"type": "separator", "margin": "md"}, {"type": "image", "url": banner_img_url, "size": "full", "aspectRatio": "3:1", "aspectMode": "cover", "margin": "md"}, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm", "contents": bottom_buttons_2}])

    bubbles = []
    if len(dates) > 0:
        day1 = dates[0]
        day2 = dates[1] if len(dates) > 1 else None
        body_contents_1 = [{"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [create_day_column(day1), {"type": "separator"}, create_day_column(day2)]}]
        body_contents_1.extend(bottom_block_contents_1) 
        bubbles.append({"type": "bubble", "size": "giga", "header": create_header_block(0), "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "8px", "contents": body_contents_1}})
    if len(dates) > 2:
        day3 = dates[2]
        day4 = dates[3] if len(dates) > 3 else None
        body_contents_2 = [{"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [create_day_column(day3), {"type": "separator"}, create_day_column(day4)]}]
        body_contents_2.extend(bottom_block_contents_2) 
        bubbles.append({"type": "bubble", "size": "giga", "header": create_header_block(1), "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "8px", "contents": body_contents_2}})

    return FlexSendMessage(alt_text=f"{spot_name}の天気予報", contents={"type": "carousel", "contents": bubbles})

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
                msg = "⚠️ お気に入りが登録されていないか、件数が足りません。\n「一覧」から釣り場を探して「⭐️ 登録」してください。"
                flex_msg = build_spot_list_carousel_horizontal(user_id=user_id, mode=fishing_mode)
                line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])
            return

        add_match = re.match(r'^追加[\s:：]+(.+)$', raw_msg, re.DOTALL)
        if add_match:
            spots_str = add_match.group(1).strip()
            spot_names = [s for s in re.split(r'[\s,、\n]+', spots_str) if s and s not in ["追加", "削除"]]
            success, added, errors = add_favorite_spots(user_id, spot_names)
            _, favorites, _ = get_user_setting(user_id)
            total_count = get_mode_fav_count(favorites, fishing_mode)
            
            reply_lines = []
            if added: reply_lines.append(f"✅ {len(added)}件追加しました: {', '.join(added)}")
            if errors: reply_lines.append(f"⚠️ スキップ・失敗: {', '.join(errors)}")
            if added or errors: reply_lines.append(f"📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所")
            else: reply_lines.append("⚠️ 釣り場名が認識できませんでした。")
                
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="\n".join(reply_lines)), flex_msg])
            return

        del_match = re.match(r'^削除[\s:：]+(.+)$', raw_msg, re.DOTALL)
        if del_match:
            spots_str = del_match.group(1).strip()
            spot_names = [s for s in re.split(r'[\s,、\n]+', spots_str) if s and s not in ["追加", "削除"]]
            success, removed, errors = remove_favorite_spots(user_id, spot_names)
            _, favorites, _ = get_user_setting(user_id)
            total_count = get_mode_fav_count(favorites, fishing_mode)
            
            reply_lines = []
            if removed: reply_lines.append(f"✅ {len(removed)}件削除しました: {', '.join(removed)}")
            if errors: reply_lines.append(f"⚠️ スキップ・失敗: {', '.join(errors)}")
            if removed or errors: reply_lines.append(f"📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所")
            else: reply_lines.append("⚠️ 釣り場名が認識できませんでした。")
                
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="\n".join(reply_lines)), flex_msg])
            return

        if raw_msg in ["一覧", "リスト", "釣り場一覧", "エリア", "📋 一覧", "📋一覧"]:
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        if raw_msg in ["設定", "⚙️設定", "⚙️ 設定", "設定（並び替え・削除）", "⚙️ 設定（並び替え・削除）"]:
            fav_list = [s.strip() for s in favorites.split(',') if s.strip()]
            flex_msg = build_settings_flex_message(fav_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        flex_msg = build_spot_list_carousel_horizontal(user_id=user_id, mode=fishing_mode)
        line_bot_api.reply_message(event.reply_token, flex_msg)
    except Exception as e:
        print("\n=== システムエラー詳細 ===")
        traceback.print_exc()

@handler.add(PostbackEvent)
def handle_postback(event):
    try:
        user_id = event.source.user_id
        data_dict = dict(parse_qsl(event.postback.data))
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
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id, mode=target_mode)
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
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id, mode=fishing_mode)
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
            _, favorites, _ = get_user_setting(user_id)
            total_count = get_mode_fav_count(favorites, fishing_mode)
            msg = f"✅ 追加しました: {added[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所" if added else f"⚠️ {errors[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所"
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_confirm_and_list":
            flex_msg = build_delete_confirm_message(spot_name, "list")
            line_bot_api.reply_message(event.reply_token, flex_msg)

        elif action == "fav_del_confirm_and_settings":
            flex_msg = build_delete_confirm_message(spot_name, "settings")
            line_bot_api.reply_message(event.reply_token, flex_msg)

        elif action == "fav_del_execute_and_list":
            success, removed, errors = remove_favorite_spots(user_id, [spot_name])
            _, favorites, _ = get_user_setting(user_id)
            total_count = get_mode_fav_count(favorites, fishing_mode)
            msg = f"✅ 削除しました: {removed[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所" if removed else f"⚠️ {errors[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所"
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_execute_and_settings":
            success, removed, errors = remove_favorite_spots(user_id, [spot_name])
            _, favorites, _ = get_user_setting(user_id)
            fav_list = [s.strip() for s in favorites.split(',') if s.strip()]
            total_count = get_mode_fav_count(favorites, fishing_mode)
            msg = f"✅ 削除しました: {removed[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所" if removed else f"⚠️ {errors[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所"
            flex_msg = build_settings_flex_message(fav_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_cancel_and_list":
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id, mode=fishing_mode)
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
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=f"✅ {msg}"), flex_msg])

        elif action in ["fav_up", "fav_down", "fav_top", "fav_bottom", "fav_cell_top", "fav_cell_bottom"]:
            direction = action.replace("fav_", "")
            move_favorite_spot(user_id, spot_name, direction, mode=fishing_mode)
            _, favorites, _ = get_user_setting(user_id)
            fav_list = [s.strip() for s in favorites.split(',') if s.strip()]
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
