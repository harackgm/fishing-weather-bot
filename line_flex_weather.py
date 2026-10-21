import os
import re
import jpholiday
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from linebot.models import FlexSendMessage

# --- 外部ファイルからデータをインポート ---
try:
    from spots import COLOR_GROUPS, BASS_COLOR_GROUPS, ALL_SPOT_DATA, SPOT_WEATHER_DATA
except ImportError:
    COLOR_GROUPS = []
    BASS_COLOR_GROUPS = []
    ALL_SPOT_DATA = {}
    SPOT_WEATHER_DATA = {}

# 分割した line_flex_list.py から日付判定関数を拝借
from line_flex_list import guess_date_from_string

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

def create_source_links_box(wn_url, tenki_url):
    """WeatherNewsとtenki.jpの文字リンクを最小限の高さで生成"""
    link_items = []
    if wn_url:
        link_items.append({
            "type": "text",
            "text": "WeatherNews",
            "size": "xxs",
            "color": "#1565c0",
            "decoration": "underline",
            "action": {"type": "uri", "label": "WeatherNews", "uri": wn_url}
        })
    if wn_url and tenki_url:
        link_items.append({
            "type": "text",
            "text": "｜",
            "size": "xxs",
            "color": "#cccccc",
            "flex": 0
        })
    if tenki_url:
        link_items.append({
            "type": "text",
            "text": "tenki.jp",
            "size": "xxs",
            "color": "#1565c0",
            "decoration": "underline",
            "action": {"type": "uri", "label": "tenki.jp", "uri": tenki_url}
        })
    if not link_items:
        return None

    return {
        "type": "box",
        "layout": "horizontal",
        "justifyContent": "center",
        "alignItems": "center",
        "spacing": "xs",
        "margin": "xs",
        "contents": [
            {"type": "text", "text": "予報元:", "size": "xxs", "color": "#888888", "flex": 0}
        ] + link_items
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

    # スポットごとの予報元URL取得
    spot_data = ALL_SPOT_DATA.get(spot_name, {})
    spot_wn_url = spot_data.get("url", "")
    spot_tenki_url = spot_data.get("tenki_url", "")
    source_box = create_source_links_box(spot_wn_url, spot_tenki_url)

    bottom_buttons_1 = [{"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "0px", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list", "displayText": "📋 一覧"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]}]
    bottom_buttons_2 = []
    if tel:
        clean_tel = tel.replace('-', '').strip()
        bottom_buttons_2.append({"type": "box", "layout": "vertical", "flex": 2, "backgroundColor": "#f8f9fa", "borderWidth": "normal", "borderColor": "#e0e0e0", "cornerRadius": "md", "paddingAll": "0px", "contents": [{"type": "button", "action": {"type": "uri", "label": "📞 電話", "uri": f"tel:{clean_tel}"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]})
    bottom_buttons_2.append({"type": "box", "layout": "vertical", "flex": 3 if tel else 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "0px", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list", "displayText": "📋 一覧"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]})

    footer_1_contents = [{"type": "separator", "margin": "none"}]
    if source_box:
        footer_1_contents.append(source_box)
        footer_1_contents.append({"type": "separator", "margin": "xs"})
    footer_1_contents.append({"type": "image", "url": banner_img_url, "size": "full", "aspectRatio": "3:1", "aspectMode": "cover", "margin": "xs" if source_box else "md"})
    footer_1_contents.append({"type": "separator", "margin": "md"})
    footer_1_contents.append({"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm", "contents": bottom_buttons_1})

    footer_1 = {
        "type": "box", "layout": "vertical", "paddingAll": "8px", "spacing": "none",
        "contents": footer_1_contents
    }

    footer_2_contents = [{"type": "separator", "margin": "none"}]
    if source_box:
        footer_2_contents.append(source_box)
        footer_2_contents.append({"type": "separator", "margin": "xs"})
    footer_2_contents.append({"type": "image", "url": banner_img_url, "size": "full", "aspectRatio": "3:1", "aspectMode": "cover", "margin": "xs" if source_box else "md"})
    footer_2_contents.append({"type": "separator", "margin": "md"})
    footer_2_contents.append({"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm", "contents": bottom_buttons_2})

    footer_2 = {
        "type": "box", "layout": "vertical", "paddingAll": "8px", "spacing": "none",
        "contents": footer_2_contents
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
