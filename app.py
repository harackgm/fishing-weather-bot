import os, time, random, requests, traceback, re, threading, unicodedata
from urllib.parse import quote, parse_qsl
from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, PostbackEvent
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
    build_delete_confirm_message,
    build_delete_all_confirm_message,
    build_settings_flex_message,
    build_move_selector_flex_message,
    build_spot_list_carousel_horizontal,
    build_grid_flex_message,
    build_other_mode_area_selector,
    build_other_mode_spots_selector
)

# --- 天気・災害情報APIモジュール（weather_api.py）の読み込み ---
from weather_api import (
    fetch_spot_1hour_data,
    get_cached_weather,
    save_cached_weather
)

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

USER_LAST_REQUEST = {}
REQUEST_LOCK = threading.Lock()

# 元通りの 2.5秒 に正確に復元
def is_throttled(user_id, cooldown=2.5):
    now_ts = time.time()
    with REQUEST_LOCK:
        last_ts = USER_LAST_REQUEST.get(user_id, 0)
        if now_ts - last_ts < cooldown:
            return True
        USER_LAST_REQUEST[user_id] = now_ts
        return False

def get_spot_details(spot_key):
    data = ALL_SPOT_DATA.get(spot_key)
    if not data: return spot_key, None, "", "", "", "", "", "", "", "", "", None
    map_url = data.get("map_url")
    if not map_url:
        search_q = data.get('search_name', spot_key)
        map_url = f"https://www.google.com/maps/search/?api=1&query={quote(search_q)}"
    return (
        spot_key, data["url"], data.get("hp_url", ""), data.get("hp2_url", ""), 
        map_url, data.get("tel", ""), data.get("x_url", ""), data.get("fb_url", ""),
        data.get("insta_url", ""), data.get("blog_url", ""), data.get("yt_url", ""),
        data.get("tenki_url")
    )

def resolve_spot_name(query):
    query_clean = query.strip()
    if not query_clean: return None
    if query_clean in ALL_SPOT_DATA: return query_clean
    for formal_name, data in ALL_SPOT_DATA.items():
        aliases = data.get('aliases', [])
        if query_clean.lower() in [a.lower() for a in aliases]: return formal_name
    return None

def get_user_setting(user_id):
    if not supabase: return ('ウェザーニュース', [], [], 'trout')
    try:
        res = supabase.table('user_settings').select('*').eq('user_id', user_id).execute()
        if res.data and len(res.data) > 0:
            row = res.data[0]
            favs = row.get('favorite_spots') or ''
            try: fishing_mode = row.get('fishing_mode') or 'trout'
            except KeyError: fishing_mode = 'trout'
            
            rename_map = {
                "七色ダム": "池原七色ダム", "キング": "キングフィッシャー",
                "キングダム": "川場キングダム", "イワセン": "イワナセンター",
                "アルクス宇宇都宮": "アルクス宇宇都宮", "片仓ダム": "片倉ダム", "多田良沼": "多々良沼",
                "那須烏山": "那須鳥山", "柏崎": "霞ケ浦柏崎", "霞ケ浦西浦": "土浦港", "ＭＡＶ": "宮城", "GP不忘": "不忘",
                "グングン": "GunGun"
            }
            
            trout_list = []
            bass_list = []
            
            if '|' in favs:
                t_str, b_str = favs.split('|', 1)
                t_raw = [s.strip() for s in t_str.split(',') if s.strip()]
                b_raw = [s.strip() for s in b_str.split(',') if s.strip()]
            else:
                all_raw = [s.strip() for s in favs.split(',') if s.strip()]
                t_all = []
                for g in COLOR_GROUPS:
                    for sg in g["sub_groups"]: t_all.extend(sg["spots"])
                b_all = []
                for g in BASS_COLOR_GROUPS:
                    for sg in g["sub_groups"]: b_all.extend(sg["spots"])
                
                t_raw = []
                b_raw = []
                for s in all_raw:
                    s_clean = rename_map.get(s, s)
                    if s_clean in b_all and s_clean not in t_all:
                        b_raw.append(s_clean)
                    else:
                        t_raw.append(s_clean)

            for s in t_raw:
                s_clean = rename_map.get(s, s)
                if s_clean not in ["多摩湖", "いなプー"] and s_clean: trout_list.append(s_clean)
            for s in b_raw:
                s_clean = rename_map.get(s, s)
                if s_clean not in ["多摩湖", "いなプー"] and s_clean: bass_list.append(s_clean)
                    
            return (row.get('weather_source', 'ウェザーニュース'), trout_list, bass_list, fishing_mode)
        return ('ウェザーニュース', [], [], 'trout')
    except Exception as e:
        print(f"[Supabase取得エラー] {e}")
        return ('ウェザーニュース', [], [], 'trout')

def add_favorite_spots(user_id, spot_names):
    if not supabase: return False, [], ["DB接続未完了です。"]
    source, trout_list, bass_list, fishing_mode = get_user_setting(user_id)
    
    current_list = trout_list if fishing_mode == 'trout' else bass_list
    
    added = []
    errors = []
    for spot_name in spot_names:
        target_name = resolve_spot_name(spot_name)
        if not target_name:
            errors.append(f"{spot_name}(不明)")
            continue
            
        if target_name in current_list:
            errors.append(f"{target_name}(登録済)")
            continue
            
        if len(current_list) + len(added) >= MAX_FAVORITES:
            errors.append(f"{target_name}(上限{MAX_FAVORITES}件超過)")
            continue
            
        added.append(target_name)
        
    if added:
        current_list.extend(added)
        new_favs = f"{','.join(trout_list)}|{','.join(bass_list)}"
        try:
            supabase.table('user_settings').upsert({
                'user_id': user_id, 'weather_source': source, 'favorite_spots': new_favs, 'fishing_mode': fishing_mode
            }).execute()
        except Exception:
            return False, [], [f"DB保存エラー"]
    return True, added, errors

def remove_favorite_spots(user_id, spot_names):
    if not supabase: return False, [], ["DB接続未完了です。"]
    source, trout_list, bass_list, fishing_mode = get_user_setting(user_id)
    
    current_list = trout_list if fishing_mode == 'trout' else bass_list
    
    removed = []
    errors = []
    for spot_name in spot_names:
        target_name = resolve_spot_name(spot_name)
        if not target_name: target_name = spot_name 
        if target_name not in current_list:
            errors.append(f"{target_name}(未登録)")
            continue
            
        current_list.remove(target_name)
        removed.append(target_name)
        
    if removed:
        new_favs = f"{','.join(trout_list)}|{','.join(bass_list)}"
        try:
            supabase.table('user_settings').upsert({
                'user_id': user_id, 'weather_source': source, 'favorite_spots': new_favs, 'fishing_mode': fishing_mode
            }).execute()
        except Exception:
            return False, [], [f"DB保存エラー"]
    return True, removed, errors

def clear_favorite_spots(user_id):
    if not supabase: return False, "DB接続未完了です。"
    source, trout_list, bass_list, fishing_mode = get_user_setting(user_id)

    if fishing_mode == 'trout':
        trout_list = []
    else:
        bass_list = []

    new_favs = f"{','.join(trout_list)}|{','.join(bass_list)}"
    try:
        supabase.table('user_settings').upsert({
            'user_id': user_id, 'weather_source': source, 'favorite_spots': new_favs, 'fishing_mode': fishing_mode
        }).execute()
        return True, "現在開いているモードのすべてのお気に入りを削除しました。"
    except Exception as e:
        return False, f"削除に失敗しました。詳細:{e}"

def move_favorite_spot(user_id, spot_name, direction):
    if not supabase: return False, "DB接続未完了です。"
    source, trout_list, bass_list, fishing_mode = get_user_setting(user_id)
    
    current_list = trout_list if fishing_mode == 'trout' else bass_list
    
    if spot_name not in current_list:
        return False, "登録されていません。"

    idx = current_list.index(spot_name)
    
    if direction == "up" and idx > 0:
        current_list[idx - 1], current_list[idx] = current_list[idx], current_list[idx - 1]
    elif direction == "down" and idx < len(current_list) - 1:
        current_list[idx + 1], current_list[idx] = current_list[idx], current_list[idx + 1]
    elif direction == "top":
        current_list.insert(0, current_list.pop(idx))
    elif direction == "bottom":
        current_list.append(current_list.pop(idx))
    elif direction == "cell_top":
        chunk_start = (idx // 10) * 10
        if idx > chunk_start:
            current_list.insert(chunk_start, current_list.pop(idx))
    elif direction == "cell_bottom":
        chunk_end = min(((idx // 10) + 1) * 10 - 1, len(current_list) - 1)
        if idx < chunk_end:
            current_list.insert(chunk_end, current_list.pop(idx))
    else:
        return True, "移動不要"
        
    new_favs = f"{','.join(trout_list)}|{','.join(bass_list)}"
    try:
        supabase.table('user_settings').upsert({
            'user_id': user_id, 'weather_source': source, 'favorite_spots': new_favs, 'fishing_mode': fishing_mode
        }).execute()
        return True, "移動しました"
    except Exception as e:
        return False, f"移動失敗。詳細:{e}"

@app.route("/", methods=['GET'])
def top_page():
    return "LINE Reply Bot Server is running!", 200

# ── Yahoo!カーナビ用クッションページ（公式ルート案内コマンド＆Googleマップフォールバック版） ──
@app.route("/yjcarnavi", methods=['GET'])
def yjcarnavi_redirect():
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    name = request.args.get('name')
    q = request.args.get('q')

    search_keyword = name if name else q

    if lat and lon and search_keyword:
        # Yahoo!カーナビ公式の「ルート選択画面」を直接開くコマンド
        app_url = f"yjcarnavi://navi/select?lat={lat}&lon={lon}&name={quote(search_keyword)}"
    else:
        # 緯度・経度が何らかの理由で欠損している場合は、直接Googleマップへ逃がす
        fallback_url = f"https://www.google.com/maps/search/?api=1&query={quote(search_keyword)}" if search_keyword else "https://www.google.com/maps"
        return f'<script>window.location.href="{fallback_url}";</script>'

    # アプリが入っていない人向けのGoogleマップURL（ピンポイント座標）
    web_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"

    html = f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>カーナビ起動</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; text-align: center; padding-top: 50px; background-color: #f8f9fa; color: #333; }}
            .loader {{ border: 4px solid #f3f3f3; border-top: 4px solid #1565c0; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            .btn {{ display: inline-block; margin-top: 20px; padding: 12px 24px; background-color: #1565c0; color: white; text-decoration: none; border-radius: 8px; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .fallback {{ margin-top: 40px; font-size: 0.9em; color: #666; line-height: 1.6; }}
            .fallback a {{ color: #1a73e8; font-weight: bold; text-decoration: none; }}
        </style>
    </head>
    <body>
        <h2>Yahoo!カーナビを起動しています...</h2>
        <div class="loader"></div>
        <p style="font-size: 0.9em; color: #555;">自動的に起動しない場合は、以下のボタンを押してください。</p>
        <p><a href="{app_url}" class="btn">🚗 カーナビアプリを開く</a></p>
        
        <div class="fallback">
            <p>※カーナビアプリをお持ちでない方は<br>
            <a href="{web_url}">🗺️ Googleマップで開く</a></p>
        </div>

        <script>
            // ページ表示と同時にカーナビのルート案内コマンドを実行
            window.location.href = "{app_url}";
            
            // 2.5秒後にGoogleマップへ自動フォールバック（アプリがない人向け安全装置）
            setTimeout(function() {{
                window.location.href = "{web_url}";
            }}, 2500);
        </script>
    </body>
    </html>
    """
    return html, 200

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

        source, trout_list, bass_list, fishing_mode = get_user_setting(user_id)
        current_list = trout_list if fishing_mode == 'trout' else bass_list

        if raw_msg in ["お気に入り1", "お気に入り2"]:
            target_spot = None
            if raw_msg == "お気に入り1" and len(current_list) > 0: target_spot = current_list[0]
            elif raw_msg == "お気に入り2" and len(current_list) > 1: target_spot = current_list[1]
                
            if target_spot:
                target_spot_name, target_url, hp_url, hp2_url, map_url, tel, x_url, fb_url, insta_url, blog_url, yt_url, tenki_url = get_spot_details(target_spot)
                if not target_url:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ 【{target_spot}】のデータが見つかりません。"))
                    return

                is_fav = True
                weather_data = get_cached_weather(target_spot_name, supabase, MEMORY_CACHE)
                if not weather_data:
                    weather_data = fetch_spot_1hour_data(target_url, tenki_url)
                    if weather_data: save_cached_weather(target_spot_name, weather_data, supabase, MEMORY_CACHE)

                if weather_data:
                    flex_msg = build_grid_flex_message(target_spot_name, weather_data, hp_url, hp2_url, map_url, tel, x_url, fb_url, insta_url, blog_url, yt_url, is_favorite=is_fav)
                    line_bot_api.reply_message(event.reply_token, flex_msg)
                else:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ 【{target_spot_name}】の天気データの取得に失敗しました。少し時間をおいてから再度お試しください。"))
            else:
                msg = "⚠️ お気に入りが登録されていないか、件数が足りません。" + chr(10) + "「一覧」から釣り場を探して「⭐️ 登録」してください。"
                flex_msg = build_spot_list_carousel_horizontal(current_list, mode=fishing_mode)
                line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])
            return

        # ── 追加コマンド ──
        add_match = re.match(r'^追加[\s:：]+(.+)$', raw_msg, re.DOTALL)
        if add_match:
            spots_str = add_match.group(1).strip()
            spot_names = [s for s in re.split(r'[\s,、\n]+', spots_str) if s and s not in ["追加", "削除"]]
            
            active_group = COLOR_GROUPS if fishing_mode == "trout" else BASS_COLOR_GROUPS
            active_spots = []
            for group in active_group:
                for sg in group["sub_groups"]: active_spots.extend(sg["spots"])

            resolved_spots = []
            failed_queries = []

            for p in spot_names:
                if p in AREA_MAPPING:
                    area_spots = AREA_MAPPING[p]
                    for s_item in area_spots:
                        formal_name = resolve_spot_name(s_item)
                        if formal_name and formal_name in active_spots:
                            if formal_name not in resolved_spots:
                                resolved_spots.append(formal_name)
                else:
                    formal_name = resolve_spot_name(p)
                    if formal_name:
                        if formal_name not in resolved_spots:
                            resolved_spots.append(formal_name)
                    else:
                        failed_queries.append(p)
            
            to_add = [s for s in resolved_spots if s not in current_list]
            total_after_add = len(current_list) + len(to_add)

            if total_after_add > MAX_FAVORITES:
                msg_lines = [
                    f"⚠️ 登録上限（{MAX_FAVORITES}箇所）を超えるため、追加処理を中断しました。",
                    "━━━━━━━━━━━━━━━",
                    f"現在の登録数: {len(current_list)}/{MAX_FAVORITES}箇所",
                    f"追加対象数: {len(to_add)}箇所",
                    f"追加後の合計: {total_after_add}箇所（上限超え）",
                    "━━━━━━━━━━━━━━━",
                    "お気に入りを削除してから再度実行してください。"
                ]
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=chr(10).join(msg_lines)))
                return
            
            success, added, errors = add_favorite_spots(user_id, to_add) if to_add else (True, [], [])
            _, trout_after, bass_after, _ = get_user_setting(user_id)
            current_list_after = trout_after if fishing_mode == 'trout' else bass_after
            
            reply_lines = []
            if added: reply_lines.append(f"✅ {len(added)}件追加しました: {', '.join(added)}")
            if errors or failed_queries: 
                all_err = errors + [f"{f}(不明)" for f in failed_queries]
                reply_lines.append(f"⚠ スキップ・対象外: {', '.join(all_err)}")
            if added or errors or failed_queries: 
                reply_lines.append(f"📊 現在の登録数: {len(current_list_after)}/{MAX_FAVORITES}箇所")
            else: 
                reply_lines.append("⚠️ 対象の釣り場がありませんでした（既に登録済みです）。")
                
            flex_msg = build_spot_list_carousel_horizontal(current_list_after, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=chr(10).join(reply_lines)), flex_msg])
            return

        # ── 削除コマンド ──
        del_match = re.match(r'^削除[\s:：]+(.+)$', raw_msg, re.DOTALL)
        if del_match:
            spots_str = del_match.group(1).strip()
            spot_names = [s for s in re.split(r'[\s,、\n]+', spots_str) if s and s not in ["追加", "削除"]]
            
            expanded_queries = []
            for p in spot_names:
                if p in AREA_MAPPING:
                    expanded_queries.extend(AREA_MAPPING[p])
                else:
                    expanded_queries.append(p)

            target_to_remove = []
            for q in expanded_queries:
                formal_name = resolve_spot_name(q)
                if not formal_name: formal_name = q
                if formal_name not in target_to_remove:
                     target_to_remove.append(formal_name)

            success, removed, errors = remove_favorite_spots(user_id, target_to_remove) if target_to_remove else (True, [], [])
            _, trout_after, bass_after, _ = get_user_setting(user_id)
            current_list_after = trout_after if fishing_mode == 'trout' else bass_after
            
            reply_lines = []
            if removed: reply_lines.append(f"✅ {len(removed)}件削除しました: {', '.join(removed)}")
            if errors: reply_lines.append(f"⚠️ スキップ・失敗: {', '.join(errors)}")
            if removed or errors: 
                reply_lines.append(f"📊 現在の登録数: {len(current_list_after)}/{MAX_FAVORITES}箇所")
            else: 
                reply_lines.append("⚠️ 対象の釣り場がありませんでした（未登録です）。")
                
            flex_msg = build_spot_list_carousel_horizontal(current_list_after, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=chr(10).join(reply_lines)), flex_msg])
            return

        if raw_msg in ["一覧", "リスト", "釣り場一覧", "エリア", "📋 一覧", "📋一覧"]:
            flex_msg = build_spot_list_carousel_horizontal(current_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        if raw_msg in ["設定", "⚙️設定", "⚙️ 設定", "設定（並び替え・削除）", "⚙ 設定（並び替え・削除）"]:
            flex_msg = build_settings_flex_message(current_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        flex_msg = build_spot_list_carousel_horizontal(current_list, mode=fishing_mode)
        line_bot_api.reply_message(event.reply_token, flex_msg)
    except Exception as e:
        print("\n=== システムエラー詳細 ===")
        traceback.print_exc()

@handler.add(PostbackEvent)
def handle_postback(event):
    try:
        user_id = event.source.user_id
        data_dict = dict(parse_qsl(event.postback.data))

        # 2.5秒のストッパー（元の仕様通りの安全クールダウン）
        if is_throttled(user_id, cooldown=2.5):
            return

        action = data_dict.get("action")
        spot_name = data_dict.get("spot")
        source, trout_list, bass_list, fishing_mode = get_user_setting(user_id)
        current_list = trout_list if fishing_mode == 'trout' else bass_list
        
        if action == "dummy": return

        if "w" in data_dict:
            action = "show_weather"
            spot_name = data_dict["w"]

        if action == "switch_mode":
            target_mode = data_dict.get("mode", "trout")
            if supabase:
                new_favs = f"{','.join(trout_list)}|{','.join(bass_list)}"
                try: supabase.table('user_settings').upsert({'user_id': user_id, 'weather_source': source, 'favorite_spots': new_favs, 'fishing_mode': target_mode}).execute()
                except: pass
            mode_name = "🐟 ブラックバス" if target_mode == "bass" else "🐟 エリアトラウト"
            current_list_after = trout_list if target_mode == 'trout' else bass_list
            flex_msg = build_spot_list_carousel_horizontal(current_list_after, mode=target_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=f"{mode_name} モードに切り替えました！"), flex_msg])
            return

        elif action == "show_other_mode_areas":
            flex_msg = build_other_mode_area_selector(current_mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        elif action == "show_other_mode_spots":
            g_idx = int(data_dict.get("g_idx", 0))
            flex_msg = build_other_mode_spots_selector(g_idx, current_mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        # ── 1番・先頭・末尾 ボタンの移動対象選択ダイアログ表示 ──
        elif action in ["show_top_selector", "show_cell_top_selector", "show_cell_bottom_selector"]:
            chunk_idx_str = data_dict.get("chunk", "0")
            c_idx = int(chunk_idx_str) if chunk_idx_str.isdigit() else 0
            
            action_type = "top" if action == "show_top_selector" else ("cell_top" if action == "show_cell_top_selector" else "cell_bottom")
            flex_msg = build_move_selector_flex_message(current_list, chunk_idx=c_idx, action_type=action_type)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        elif action == "show_list":
            flex_msg = build_spot_list_carousel_horizontal(current_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return
            
        elif action == "show_settings":
            flex_msg = build_settings_flex_message(current_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        elif action == "show_weather":
            target_spot_name, target_url, hp_url, hp2_url, map_url, tel, x_url, fb_url, insta_url, blog_url, yt_url, tenki_url = get_spot_details(spot_name)
            if not target_url: return
            is_fav = target_spot_name in current_list

            weather_data = get_cached_weather(target_spot_name, supabase, MEMORY_CACHE)
            if not weather_data:
                weather_data = fetch_spot_1hour_data(target_url, tenki_url)
                if weather_data: save_cached_weather(target_spot_name, weather_data, supabase, MEMORY_CACHE)

            if weather_data:
                flex_msg = build_grid_flex_message(target_spot_name, weather_data, hp_url, hp2_url, map_url, tel, x_url, fb_url, insta_url, blog_url, yt_url, is_favorite=is_fav)
                line_bot_api.reply_message(event.reply_token, flex_msg)
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ 【{target_spot_name}】の天気データの取得に失敗しました。少し時間を置いてから再度お試しください。"))
            return

        elif action == "fav_add_and_list":
            success, added, errors = add_favorite_spots(user_id, [spot_name])
            _, trout_after, bass_after, _ = get_user_setting(user_id)
            current_list_after = trout_after if fishing_mode == 'trout' else bass_after
            msg = f"✅ 追加しました: {added[0]}\n📊 現在の登録数: {len(current_list_after)}/{MAX_FAVORITES}箇所" if added else f"⚠️ {errors[0]}\n📊 現在の登録数: {len(current_list_after)}/{MAX_FAVORITES}箇所"
            flex_msg = build_spot_list_carousel_horizontal(current_list_after, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_add_and_settings":
            success, added, errors = add_favorite_spots(user_id, [spot_name])
            _, trout_after, bass_after, _ = get_user_setting(user_id)
            current_list_after = trout_after if fishing_mode == 'trout' else bass_after
            msg = f"✅ 追加しました: {added[0]}\n📊 現在の登録数: {len(current_list_after)}/{MAX_FAVORITES}箇所" if added else f"⚠️ {errors[0]}\n📊 現在の登録数: {len(current_list_after)}/{MAX_FAVORITES}箇所"
            flex_msg = build_settings_flex_message(current_list_after, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_confirm_and_list":
            flex_msg = build_delete_confirm_message(spot_name, "list")
            line_bot_api.reply_message(event.reply_token, flex_msg)

        elif action == "fav_del_confirm_and_settings":
            flex_msg = build_delete_confirm_message(spot_name, "settings")
            line_bot_api.reply_message(event.reply_token, flex_msg)

        elif action == "fav_del_execute_and_list":
            success, removed, errors = remove_favorite_spots(user_id, [spot_name])
            _, trout_after, bass_after, _ = get_user_setting(user_id)
            current_list_after = trout_after if fishing_mode == 'trout' else bass_after
            msg = f"✅ 削除しました: {removed[0]}\n📊 現在の登録数: {len(current_list_after)}/{MAX_FAVORITES}箇所" if removed else f"⚠️ {errors[0]}\n📊 現在の登録数: {len(current_list_after)}/{MAX_FAVORITES}箇所"
            flex_msg = build_spot_list_carousel_horizontal(current_list_after, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_execute_and_settings":
            success, removed, errors = remove_favorite_spots(user_id, [spot_name])
            _, trout_after, bass_after, _ = get_user_setting(user_id)
            current_list_after = trout_after if fishing_mode == 'trout' else bass_after
            msg = f"✅ 削除しました: {removed[0]}\n📊 現在の登録数: {len(current_list_after)}/{MAX_FAVORITES}箇所" if removed else f"⚠️ {errors[0]}\n📊 現在の登録数: {len(current_list_after)}/{MAX_FAVORITES}箇所"
            flex_msg = build_settings_flex_message(current_list_after, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_cancel_and_list":
            flex_msg = build_spot_list_carousel_horizontal(current_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="キャンセルしました。"), flex_msg])

        elif action == "fav_del_cancel_and_settings":
            flex_msg = build_settings_flex_message(current_list, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="キャンセルしました。"), flex_msg])

        elif action == "fav_del_all_confirm":
            flex_msg = build_delete_all_confirm_message()
            line_bot_api.reply_message(event.reply_token, flex_msg)

        elif action == "fav_del_all_execute":
            success, msg = clear_favorite_spots(user_id)
            _, trout_after, bass_after, _ = get_user_setting(user_id)
            current_list_after = trout_after if fishing_mode == 'trout' else bass_after
            flex_msg = build_spot_list_carousel_horizontal(current_list_after, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=f"✅ {msg}"), flex_msg])

        # ── 釣り場の移動処理を実行 ──
        elif action in ["fav_up", "fav_down", "fav_top", "fav_bottom", "fav_cell_top", "fav_cell_bottom"]:
            direction = action.replace("fav_", "")
            move_favorite_spot(user_id, spot_name, direction)
            _, trout_after, bass_after, _ = get_user_setting(user_id)
            current_list_after = trout_after if fishing_mode == 'trout' else bass_after
            flex_msg = build_settings_flex_message(current_list_after, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            
    except Exception as e:
        print(f"Postback Error: {e}")
        traceback.print_exc()

def get_top_favorite_spots(trout_limit=30, bass_limit=30):
    """ユーザーのお気に入り登録数集計により上位30件を取得"""
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
                spots = [s.strip() for s in favs.replace('|', ',').split(',') if s.strip()]
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
    """
    Cronjobs用（10分ごとに実行）:
    トラウト上位30件・バス上位30件の中で、DB更新日時（updated_at）が『最も古い順』に
    トラウト5件・バス5件を選出し、順繰り（ローテーション）にキャッシュ更新を行う。
    1時間（6回実行）で上位30件×2（計60件）の全キャッシュが確実に一周して最新化される。
    """
    if not supabase: return
    try:
        top_trout, top_bass = get_top_favorite_spots(trout_limit=30, bass_limit=30)
        
        trout_targets = []
        if top_trout:
            trout_cache_times = {}
            for spot in top_trout:
                res = supabase.table('weather_cache').select('updated_at').eq('spot_name', spot).execute()
                if res.data and len(res.data) > 0:
                    try: trout_cache_times[spot] = datetime.fromisoformat(res.data[0].get('updated_at').replace('Z', '+00:00'))
                    except: trout_cache_times[spot] = datetime.min.replace(tzinfo=timezone.utc)
                else: trout_cache_times[spot] = datetime.min.replace(tzinfo=timezone.utc)
            # 最も更新日時が古い順にソートして上位5件を選出（順繰り更新）
            sorted_trout = sorted(trout_cache_times.items(), key=lambda x: x[1])
            trout_targets = [spot for spot, time_val in sorted_trout[:5]]

        bass_targets = []
        if top_bass:
            bass_cache_times = {}
            for spot in top_bass:
                res = supabase.table('weather_cache').select('updated_at').eq('spot_name', spot).execute()
                if res.data and len(res.data) > 0:
                    try: bass_cache_times[spot] = datetime.fromisoformat(res.data[0].get('updated_at').replace('Z', '+00:00'))
                    except: bass_cache_times[spot] = datetime.min.replace(tzinfo=timezone.utc)
                else: bass_cache_times[spot] = datetime.min.replace(tzinfo=timezone.utc)
            # 最も更新日時が古い順にソートして上位5件を選出（順繰り更新）
            sorted_bass = sorted(bass_cache_times.items(), key=lambda x: x[1])
            bass_targets = [spot for spot, time_val in sorted_bass[:5]]

        # トラウト5件のキャッシュ更新
        for spot_name in trout_targets:
            data = ALL_SPOT_DATA.get(spot_name)
            if not data: continue
            url = data["url"]
            tenki_url = data.get("tenki_url")
            weather_data = fetch_spot_1hour_data(url, tenki_url)
            if weather_data: save_cached_weather(spot_name, weather_data, supabase, MEMORY_CACHE)
            time.sleep(random.uniform(2.5, 4.0))

        # バス5件のキャッシュ更新（サーバー負荷分散のため少し間隔を置く）
        if bass_targets:
            time.sleep(random.uniform(5.0, 8.0))
            for spot_name in bass_targets:
                data = ALL_SPOT_DATA.get(spot_name)
                if not data: continue
                url = data["url"]
                tenki_url = data.get("tenki_url")
                weather_data = fetch_spot_1hour_data(url, tenki_url)
                if weather_data: save_cached_weather(spot_name, weather_data, supabase, MEMORY_CACHE)
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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
