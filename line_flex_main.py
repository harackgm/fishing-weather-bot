import os
import re
import jpholiday
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from linebot.models import FlexSendMessage

# --- 外部ファイル(spots.py)からデータをインポート ---
try:
    from spots import COLOR_GROUPS, BASS_COLOR_GROUPS, ALL_SPOT_DATA, SPOT_WEATHER_DATA
except ImportError:
    COLOR_GROUPS = []
    BASS_COLOR_GROUPS = []
    ALL_SPOT_DATA = {}
    SPOT_WEATHER_DATA = {}

MAX_FAVORITES = 30

def guess_date_from_string(date_str, now_date):
    if not date_str: return now_date
    m = re.search(r'(?:(\d{1,2})[月/-])?\s*(\d{1,2})日?', date_str)
    if not m: return now_date
    month_str, day_str = m.group(1), m.group(2)
    day = int(day_str)
    
    if month_str:
        month = int(month_str)
        try: target = now_date.replace(month=month, day=day)
        except ValueError: return now_date
        
        if (now_date - target).days > 180:
            try: target = target.replace(year=now_date.year + 1)
            except ValueError: pass
        elif (target - now_date).days > 180:
            try: target = target.replace(year=now_date.year - 1)
            except ValueError: pass
        return target
    else:
        candidates = []
        for m_offset in [-1, 0, 1]:
            y = now_date.year
            m_val = now_date.month + m_offset
            if m_val < 1:
                m_val += 12
                y -= 1
            elif m_val > 12:
                m_val -= 12
                y += 1
            try:
                candidates.append(datetime(y, m_val, day).date())
            except ValueError:
                pass
        if not candidates: return now_date
        target = min(candidates, key=lambda d: abs((d - now_date).days))
        return target

def build_spot_list_carousel_horizontal(fav_list=None, mode="trout"):
    active_group = COLOR_GROUPS if mode == "trout" else BASS_COLOR_GROUPS
    active_spots = []
    for group in active_group:
        for sg in group["sub_groups"]:
            active_spots.extend(sg["spots"])

    bubbles = []
    filtered_favs = []

    if fav_list is not None:
        filtered_favs = fav_list
        
        fav_rows = []
        if not filtered_favs:
            fav_rows.append({"type": "box", "layout": "vertical", "backgroundColor": "#fffde7", "cornerRadius": "md", "paddingAll": "md", "margin": "md", "contents": [{"type": "text", "text": "現在お気に入りは登録されていません。" + chr(10) + "右へスワイプして釣り場を探し、「⭐ 登録」ボタンを押すか、テキストで「追加 〇〇」と送信してください。", "wrap": True, "size": "sm", "color": "#555555"}]})
        else:
            for i in range(0, len(filtered_favs), 2):
                pair = filtered_favs[i:i+2]
                row_buttons = []
                for j, spot in enumerate(pair):
                    global_idx = i + j
                    is_other_mode = spot not in active_spots
                    
                    if is_other_mode:
                        icon = "🐟 " if mode == "bass" else "🎣 "
                        display_label = f"{icon}{spot}"
                    else:
                        display_label = spot
                    
                    bg_color = "#fff59d"
                    border_color = "#d4af37"
                    text_color = "#555555"
                    btn_style = "secondary"
                    btn_color = "#fff59d"

                    if global_idx < 2:
                        row_buttons.append({"type": "box", "layout": "vertical", "backgroundColor": bg_color, "borderWidth": "normal", "borderColor": border_color, "cornerRadius": "md", "paddingAll": "none", "margin": "xs", "contents": [{"type": "button", "action": {"type": "postback", "label": display_label, "data": f"w={spot}"}, "style": "link", "color": text_color, "height": "sm", "margin": "none"}]})
                    else:
                        row_buttons.append({"type": "button", "style": btn_style, "color": btn_color, "margin": "xs", "height": "sm", "action": {"type": "postback", "label": display_label, "data": f"w={spot}"}})
                
                if len(pair) == 1:
                    row_buttons.append({"type": "filler"})
                    
                row_margin = "none" if i == 0 else ("md" if i % 10 == 0 else "xs")
                row_box = {"type": "box", "layout": "horizontal", "contents": row_buttons, "margin": row_margin}
                fav_rows.append(row_box)

        fav_rows.append({"type": "separator", "margin": "md", "color": "#cccccc"})
        fav_rows.append({"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm", "contents": [{"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#f8f9fa", "borderWidth": "normal", "borderColor": "#e0e0e0", "cornerRadius": "md", "paddingAll": "none", "contents": [{"type": "button", "action": {"type": "postback", "label": "⚙️ 設定/切替", "data": "action=show_settings", "displayText": "⚙ 設定"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]}, {"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "none", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧更新", "data": "action=show_list", "displayText": "📋 一覧"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]}]})

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

    guide_bubble = {"type": "bubble", "size": "giga", "header": {"type": "box", "layout": "vertical", "backgroundColor": "#888888", "paddingAll": "10px", "contents": [{"type": "text", "text": "📖 使い方ガイド", "color": "#ffffff", "weight": "bold", "size": "md"}]}, "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "15px", "contents": [{"type": "box", "layout": "vertical", "spacing": "sm", "contents": [{"type": "text", "text": "👇 基本の操作", "weight": "bold", "size": "sm", "color": "#333333"}, {"type": "text", "text": "・一覧のボタンをタップで天気予報を表示", "wrap": True, "size": "xs", "color": "#666666"}]}, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [{"type": "text", "text": "💬 テキストコマンド", "weight": "bold", "size": "sm", "color": "#333333"}, {"type": "text", "text": "【まとめて追加】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"}, {"type": "text", "text": "例：「追加 東山湖 すその 足柄 座間 醒井」" + chr(10) + "※釣り場と釣り場の名前の間にスペースを入れてください。", "wrap": True, "size": "xs", "color": "#666666"}, {"type": "text", "text": "【まとめて削除】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"}, {"type": "text", "text": "例：「削除 東山湖 すその 足柄」" + chr(10) + "※追加と同じく、名前の間にスペースを入れて複数同時に解除できます。", "wrap": True, "size": "xs", "color": "#666666"}, {"type": "text", "text": "【設定】", "weight": "bold", "size": "sm", "color": "#333333", "margin": "sm"}, {"type": "text", "text": "「設定」と送信すると、並び替え・全削除パネルが出ます。", "wrap": True, "size": "xs", "color": "#666666"}, {"type": "text", "text": "【一覧（メニュー）の出し方】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"}, {"type": "text", "text": "「一覧」という言葉や、それ以外の適当な文字（「あ」「1」「a」など）を送信すると、この一覧表が表示されます。", "wrap": True, "size": "xs", "color": "#666666"}]}, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [{"type": "text", "text": "⭐ お気に入り機能とリッチメニュー", "weight": "bold", "size": "sm", "color": "#333333"}, {"type": "text", "text": "【一番お気に入り（メニュー左）】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"}, {"type": "text", "text": "現在のモードにおけるお気に入りリストの「1番目（一番上）」の釣り場の天気を瞬時に表示します。", "wrap": True, "size": "xs", "color": "#666666"}]}, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [{"type": "text", "text": "🛑 配信停止・解除", "weight": "bold", "size": "sm", "color": "#333333"}, {"type": "text", "text": "このBotの利用を停止したい場合は、トーク画面右上のメニュー「≡」から「ブロック」を行ってください。", "wrap": True, "size": "xs", "color": "#666666"}, {"type": "text", "text": "完全に消去する場合", "weight": "bold", "size": "xs", "color": "#333333", "margin": "md"}, {"type": "text", "text": "「トーク一覧」画面に戻り、このBotのトークを長押し（iPhoneは左スワイプ）して「削除」してください。", "wrap": True, "size": "xs", "color": "#666666"}]}]}}
    bubbles.append(guide_bubble)

    return FlexSendMessage(alt_text="釣り場一覧", contents={"type": "carousel", "contents": bubbles})

def create_disaster_box(disaster_data):
    contents = []
    contents.append({
        "type": "text", "text": "⚠️ リアルタイム防災情報", "weight": "bold", "size": "xs", "color": "#e53935"
    })
    
    lines_added = 0
    warnings = disaster_data.get("warnings", [])
    if warnings:
        warn_text = "・" + " / ".join(warnings)
        contents.append({
            "type": "text", "text": warn_text, "size": "xxs", "wrap": True, "color": "#ff9800", "weight": "bold", "maxLines": 2
        })
        lines_added += 2
    else:
        contents.append({
            "type": "text", "text": "✅ 警報・注意報の発表なし", "size": "xxs", "color": "#4caf50"
        })
        lines_added += 1
        
    contents.append({"type": "separator", "margin": "xs"})
    
    quake = disaster_data.get("quake")
    if quake and lines_added < 4:
        contents.append({
            "type": "text", "text": f"【地震】{quake}", "size": "xxs", "wrap": True, "color": "#555555", "maxLines": 1
        })
        lines_added += 1
        contents.append({"type": "separator", "margin": "xs"})

    volcano = disaster_data.get("volcano")
    if volcano and lines_added < 5:
        contents.append({
            "type": "text", "text": f"【火山】{volcano}", "size": "xxs", "wrap": True, "color": "#555555", "maxLines": 1
        })

    return {
        "type": "box", "layout": "vertical", "margin": "md", "paddingAll": "8px",
        "backgroundColor": "#fffde7", "cornerRadius": "sm", "borderColor": "#ffd54f", "borderWidth": "normal",
        "spacing": "xs", "contents": contents
    }

def build_grid_flex_message(spot_name, weather_data, hp_url="", hp2_url="", map_url="", tel="", x_url="", fb_url="", insta_url="", blog_url="", yt_url="", is_favorite=False):
    weekly_data = weather_data.get("__weekly__", []) if isinstance(weather_data, dict) else []
    disaster_data = weather_data.get("__disaster__", {}) if isinstance(weather_data, dict) else {}
    dates = [d for d in weather_data.keys() if d != "__weekly__" and d != "_version" and d != "__is_dummy__" and d != "__disaster__"]
    weather_by_date = weather_data
    jst = timezone(timedelta(hours=9))
    now_jst_date = datetime.now(jst).date()
    dates = sorted(dates, key=lambda d: guess_date_from_string(d, now_jst_date))

    active_group = COLOR_GROUPS
    is_bass_mode = False
    for group in BASS_COLOR_GROUPS:
        for sg in group["sub_groups"]:
            if spot_name in sg["spots"]:
                active_group = BASS_COLOR_GROUPS
                is_bass_mode = True
                break
        if is_bass_mode: break

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
        
        spot_data = ALL_SPOT_DATA.get(spot_name, {})
        hide_default_map = spot_data.get("hide_default_map", False)

        is_trout_spot = spot_name in SPOT_WEATHER_DATA

        lat, lon = None, None
        wn_url = spot_data.get("url", "")
        if wn_url:
            m = re.search(r'onebox/([0-9.]+)/([0-9.]+)', wn_url)
            if m:
                lat, lon = m.group(1), m.group(2)

        my_render_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000")

        top_buttons = []
        if not is_trout_spot:
            if is_favorite:
                top_buttons.append({"type": "button", "action": {"type": "postback", "label": "🗑️ 解除", "data": f"action=fav_del_confirm_and_list&spot={spot_name}"}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs", "color": "#ffcccc"})
            else:
                top_buttons.append({"type": "button", "action": {"type": "postback", "label": "⭐️ 登録", "data": f"action=fav_add_and_list&spot={spot_name}"}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs", "color": "#fff59d"})
            
            if map_url and not hide_default_map:
                top_buttons.append({"type": "button", "action": {"type": "uri", "label": "🗺️ 地図", "uri": map_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
            elif len(top_buttons) == 1:
                top_buttons.append({"type": "box", "layout": "vertical", "flex": 1, "margin": "xs", "contents": []})
        else:
            if is_favorite:
                top_buttons.append({"type": "button", "action": {"type": "postback", "label": "解除", "data": f"action=fav_del_confirm_and_list&spot={spot_name}"}, "style": "secondary", "height": "sm", "flex": 2, "margin": "xs", "color": "#ffcccc"})
            else:
                top_buttons.append({"type": "button", "action": {"type": "postback", "label": "登録", "data": f"action=fav_add_and_list&spot={spot_name}"}, "style": "secondary", "height": "sm", "flex": 2, "margin": "xs", "color": "#fff59d"})
            
            if map_url and not hide_default_map: 
                search_q = spot_data.get('search_name', spot_name)
                
                if lat and lon:
                    yahoo_map_url = f"{my_render_url}/yjcarnavi?lat={lat}&lon={lon}&name={quote(search_q)}"
                else:
                    yahoo_map_url = f"{my_render_url}/yjcarnavi?q={quote(search_q)}"
                    
                top_buttons.append({"type": "button", "action": {"type": "uri", "label": "🗺️ G!", "uri": map_url}, "style": "secondary", "height": "sm", "flex": 3, "margin": "xs"})
                top_buttons.append({"type": "button", "action": {"type": "uri", "label": "🚗 Y!", "uri": yahoo_map_url}, "style": "secondary", "height": "sm", "flex": 3, "margin": "xs"})
            elif len(top_buttons) == 1: 
                top_buttons.append({"type": "box", "layout": "vertical", "flex": 6, "margin": "xs", "contents": []})
        
        all_rows.append(top_buttons)

        header_buttons_bottom = []
        if hp_url:
            label_text = "大崎HP" if spot_name == "大崎・赤城" else "HP"
            header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": label_text, "uri": hp_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if hp2_url:
            label_text2 = "赤城HP" if spot_name == "大崎・赤城" else "HP2"
            header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": label_text2, "uri": hp2_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if x_url: header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": "𝕏", "uri": x_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if fb_url: header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": "FB", "uri": fb_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if insta_url: header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": "Insta", "uri": insta_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if blog_url: header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": "Blog", "uri": blog_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if yt_url: header_buttons_bottom.append({"type": "button", "action": {"type": "uri", "label": "YouTube", "uri": yt_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
            
        if header_buttons_bottom: all_rows.append(header_buttons_bottom)

        custom_button_rows = spot_data.get("custom_button_rows", [])
        for row_links in custom_button_rows:
            row_buttons = []
            for link in row_links:
                label = link["label"]
                url = link.get("url")
                
                if not is_trout_spot:
                    if url:
                        action_data = {"type": "uri", "label": label, "uri": url}
                    else:
                        action_data = {"type": "postback", "label": label, "data": "action=dummy"}
                    row_buttons.append({"type": "button", "action": action_data, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
                else:
                    if "地図" in label and url:
                        search_q = spot_data.get('search_name', spot_name)
                        
                        if lat and lon:
                            yahoo_map_url = f"{my_render_url}/yjcarnavi?lat={lat}&lon={lon}&name={quote(search_q)}"
                        else:
                            yahoo_map_url = f"{my_render_url}/yjcarnavi?q={quote(search_q)}"
                            
                        row_buttons.append({"type": "button", "action": {"type": "uri", "label": "🗺️ G!", "uri": url}, "style": "secondary", "height": "sm", "flex": 3, "margin": "xs"})
                        row_buttons.append({"type": "button", "action": {"type": "uri", "label": "🚗 Y!", "uri": yahoo_map_url}, "style": "secondary", "height": "sm", "flex": 3, "margin": "xs"})
                    else:
                        short_label = label.replace("🌐", "").replace("🚷", "").replace("📝", "").replace("📘", "").replace("📷", "").replace("▶️", "").replace("🕮", "").strip()
                        if not short_label: short_label = label
                        
                        if url:
                            action_data = {"type": "uri", "label": short_label, "uri": url}
                        else:
                            action_data = {"type": "postback", "label": short_label, "data": "action=dummy"}
                        row_buttons.append({"type": "button", "action": action_data, "style": "secondary", "height": "sm", "flex": 2, "margin": "xs"})
                        
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
    
    banner_img_url = "https://raw.githubusercontent.com/harackgm/fishing-weather-bot/main/tenkiharackbana.jpg"

    bottom_buttons_1 = [{"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "0px", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list", "displayText": "📋 一覧"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]}]
    bottom_buttons_2 = []
    if tel:
        clean_tel = tel.replace('-', '').strip()
        bottom_buttons_2.append({"type": "box", "layout": "vertical", "flex": 2, "backgroundColor": "#f8f9fa", "borderWidth": "normal", "borderColor": "#e0e0e0", "cornerRadius": "md", "paddingAll": "0px", "contents": [{"type": "button", "action": {"type": "uri", "label": "📞 電話", "uri": f"tel:{clean_tel}"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]})
    bottom_buttons_2.append({"type": "box", "layout": "vertical", "flex": 3 if tel else 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "0px", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list", "displayText": "📋 一覧"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]})

    footer_1 = {
        "type": "box", "layout": "vertical", "paddingAll": "8px", "spacing": "none",
        "contents": [
            {"type": "separator", "margin": "none"},
            {"type": "image", "url": banner_img_url, "size": "full", "aspectRatio": "3:1", "aspectMode": "cover", "margin": "md"},
            {"type": "separator", "margin": "md"},
            {"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm", "contents": bottom_buttons_1}
        ]
    }

    footer_2 = {
        "type": "box", "layout": "vertical", "paddingAll": "8px", "spacing": "none",
        "contents": [
            {"type": "separator", "margin": "none"},
            {"type": "image", "url": banner_img_url, "size": "full", "aspectRatio": "3:1", "aspectMode": "cover", "margin": "md"},
            {"type": "separator", "margin": "md"},
            {"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm", "contents": bottom_buttons_2}
        ]
    }

    body_1_contents = [{"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [create_day_column(dates[0] if len(dates)>0 else None), {"type": "separator"}, create_day_column(dates[1] if len(dates)>1 else None)]}]
    if weekly_box_1:
        body_1_contents.append({"type": "separator", "margin": "md"})
        body_1_contents.append(weekly_box_1)

    body_2_contents = [{"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [create_day_column(dates[2] if len(dates)>2 else None), {"type": "separator"}, create_day_column(dates[3] if len(dates)>3 else None)]}]
    
    body_2_contents.append({"type": "separator", "margin": "md", "color": "#00000000"})
    body_2_contents.append(create_disaster_box(disaster_data))

    bubbles = []
    if len(dates) > 0:
        bubbles.append({
            "type": "bubble", "size": "giga", 
            "header": create_header_block(0), 
            "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "8px", "contents": body_1_contents},
            "footer": footer_1
        })
    if len(dates) > 2:
        bubbles.append({
            "type": "bubble", "size": "giga", 
            "header": create_header_block(1), 
            "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "8px", "contents": body_2_contents},
            "footer": footer_2
        })

    return FlexSendMessage(alt_text=f"{spot_name}の天気予報", contents={"type": "carousel", "contents": bubbles})
