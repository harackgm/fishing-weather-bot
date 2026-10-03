from linebot.models import FlexSendMessage

# --- 外部ファイル(spots.py)からデータをインポート ---
try:
    from spots import COLOR_GROUPS, BASS_COLOR_GROUPS
except ImportError:
    COLOR_GROUPS = []
    BASS_COLOR_GROUPS = []

MAX_FAVORITES = 30

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
                {"type": "text", "text": "すべてのお気に入りを削除しますか？" + chr(10) + "（この操作は元に戻せません）", "wrap": True, "size": "sm", "color": "#333333"}
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
            
    filtered_favs = fav_list

    if mode == "trout":
        add_other_btn = {"type": "button", "action": {"type": "postback", "label": "➕ バス釣り場を追加", "data": "action=show_other_mode_areas"}, "style": "secondary", "color": "#e1f5fe", "margin": "xs", "height": "sm"}
        switch_btn = {"type": "button", "action": {"type": "postback", "label": "🎣 バスモードへ切替", "data": "action=switch_mode&mode=bass"}, "style": "primary", "color": "#0288d1", "margin": "xs", "height": "sm"}
        title_text = "⚙️ お気に入り設定 (トラウト)"
        header_color = "#d4af37"
    else:
        add_other_btn = {"type": "button", "action": {"type": "postback", "label": "➕ トラウト釣り場を追加", "data": "action=show_other_mode_areas"}, "style": "secondary", "color": "#fff3e0", "margin": "xs", "height": "sm"}
        switch_btn = {"type": "button", "action": {"type": "postback", "label": "🐟 トラウトモードへ戻る", "data": "action=switch_mode&mode=trout"}, "style": "primary", "color": "#e65100", "margin": "xs", "height": "sm"}
        title_text = "⚙ お気に入り設定 (バス)"
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
                    add_other_btn,
                    switch_btn,
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": "現在お気に入りは登録されていません。" + chr(10) + chr(10) + "「➕ 他モード追加」ボタンや、釣り場一覧の「⭐ 登録」から追加できます！", "wrap": True, "size": "sm", "color": "#555555", "margin": "md"}
                ]
            }
        }
        return FlexSendMessage(alt_text="お気に入り管理パネル", contents=bubble)

    bubbles = []
    chunk_size = 10
    for i in range(0, len(filtered_favs), chunk_size):
        chunk = filtered_favs[i:i + chunk_size]
        rows = []
        rows.append(add_other_btn)
        rows.append(switch_btn)
        rows.append({"type": "separator", "margin": "md"})
        rows.append({
            "type": "box", "layout": "horizontal", "spacing": "xs", "paddingTop": "10px", "paddingBottom": "10px",
            "contents": [
                {"type": "button", "action": {"type": "postback", "label": "🥇1番", "data": f"action=show_top_selector&chunk={i}"}, "style": "secondary", "height": "sm", "flex": 1, "color": "#fff9c4"},
                {"type": "button", "action": {"type": "postback", "label": "🔝先頭", "data": f"action=show_cell_top_selector&chunk={i}"}, "style": "secondary", "height": "sm", "flex": 1, "color": "#e3f2fd"},
                {"type": "button", "action": {"type": "postback", "label": "⏬末尾", "data": f"action=show_cell_bottom_selector&chunk={i}"}, "style": "secondary", "height": "sm", "flex": 1, "color": "#eceff1"}
            ]
        })
        rows.append({"type": "separator", "margin": "sm"})

        for spot in chunk:
            is_other_mode = spot not in active_spots
            if is_other_mode:
                icon = "🐟 " if mode == "bass" else "🎣 "
                spot_label = f"{icon}{spot}"
            else:
                spot_label = spot

            rows.append({
                "type": "box", "layout": "horizontal", "margin": "md", "alignItems": "center",
                "contents": [
                    {"type": "text", "text": spot_label, "size": "sm", "weight": "bold", "flex": 4, "color": "#333333", "wrap": True},
                    {"type": "button", "action": {"type": "postback", "label": "⬆️", "data": f"action=fav_up&spot={spot}"}, "style": "secondary", "flex": 2, "margin": "xs"},
                    {"type": "button", "action": {"type": "postback", "label": "⬇", "data": f"action=fav_down&spot={spot}"}, "style": "secondary", "flex": 2, "margin": "xs"},
                    {"type": "button", "action": {"type": "postback", "label": "🗑️", "data": f"action=fav_del_confirm_and_settings&spot={spot}"}, "style": "secondary", "color": "#ffe6e6", "flex": 2, "margin": "xs"}
                ]
            })

        rows.append({"type": "separator", "margin": "md"})
        rows.append({
            "type": "box", "layout": "horizontal", "margin": "md", "spacing": "sm",
            "contents": [
                {"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#e53935", "borderWidth": "normal", "borderColor": "#e53935", "cornerRadius": "md", "paddingAll": "none", "contents": [{"type": "button", "action": {"type": "postback", "label": "🗑 全て削除", "data": "action=fav_del_all_confirm"}, "style": "link", "color": "#ffffff", "height": "sm", "margin": "none"}]},
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

def build_move_selector_flex_message(fav_list, chunk_idx=0, action_type="top"):
    if not fav_list:
        return FlexSendMessage(alt_text="お気に入りがありません", contents={
            "type": "bubble", "size": "kilo",
            "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "⚠️ お気に入りが登録されていません。"}]}
        })

    chunk = fav_list[chunk_idx:chunk_idx + 10]
    if not chunk:
        chunk = fav_list[:10]

    if action_type == "top":
        target_action = "fav_top"
        header_text = "🥇 1番目に設定する釣り場を選択"
        bg_color = "#d4af37"
    elif action_type == "cell_top":
        target_action = "fav_cell_top"
        header_text = "🔝 枠の先頭へ移動する釣り場を選択"
        bg_color = "#0288d1"
    else:
        target_action = "fav_cell_bottom"
        header_text = "⏬ 枠の最後尾へ移動する釣り場を選択"
        bg_color = "#78909c"

    btns = []
    for spot in chunk:
        btns.append({
            "type": "button",
            "action": {"type": "postback", "label": spot, "data": f"action={target_action}&spot={spot}"},
            "style": "secondary", "margin": "xs", "height": "sm", "color": "#fff59d" if action_type == "top" else "#f8f9fa"
        })

    btns.append({"type": "separator", "margin": "md"})
    btns.append({
        "type": "button",
        "action": {"type": "postback", "label": "🔙 戻る（キャンセル）", "data": "action=show_settings"},
        "style": "secondary", "margin": "md", "height": "sm", "color": "#e0e0e0"
    })

    bubble = {
        "type": "bubble", "size": "kilo",
        "header": {"type": "box", "layout": "vertical", "backgroundColor": bg_color, "paddingAll": "10px", "contents": [{"type": "text", "text": header_text, "color": "#ffffff", "weight": "bold", "size": "sm"}]},
        "body": {"type": "box", "layout": "vertical", "paddingAll": "10px", "contents": btns}
    }
    return FlexSendMessage(alt_text=header_text, contents=bubble)

def build_other_mode_area_selector(current_mode="trout"):
    target_groups = BASS_COLOR_GROUPS if current_mode == "trout" else COLOR_GROUPS
    target_name = "バス" if current_mode == "trout" else "トラウト"
    header_color = "#1565c0" if current_mode == "trout" else "#6a1b9a"
    
    btns = []
    for idx, group in enumerate(target_groups):
        btns.append({
            "type": "button",
            "action": {"type": "postback", "label": group["title"].replace("📍 ", ""), "data": f"action=show_other_mode_spots&g_idx={idx}"},
            "style": "secondary", "margin": "xs", "height": "sm", "color": "#f8f9fa"
        })
    btns.append({"type": "separator", "margin": "md"})
    btns.append({"type": "button", "action": {"type": "postback", "label": "🔙 設定に戻る", "data": "action=show_settings"}, "style": "secondary", "margin": "md", "height": "sm", "color": "#e0e0e0"})

    bubble = {
        "type": "bubble", "size": "kilo",
        "header": {"type": "box", "layout": "vertical", "backgroundColor": header_color, "paddingAll": "10px", "contents": [{"type": "text", "text": f"📍 追加する{target_name}の地域を選択", "color": "#ffffff", "weight": "bold", "size": "sm"}]},
        "body": {"type": "box", "layout": "vertical", "paddingAll": "10px", "contents": btns}
    }
    return FlexSendMessage(alt_text=f"{target_name}エリア選択", contents=bubble)

def build_other_mode_spots_selector(group_idx, current_mode="trout"):
    target_groups = BASS_COLOR_GROUPS if current_mode == "trout" else COLOR_GROUPS
    target_name = "バス" if current_mode == "trout" else "トラウト"
    header_color = "#1565c0" if current_mode == "trout" else "#6a1b9a"
    
    if group_idx >= len(target_groups):
        group_idx = 0
    
    group = target_groups[group_idx]
    all_spots = []
    for sg in group["sub_groups"]:
        all_spots.extend(sg["spots"])

    bubbles = []
    chunk_size = 10
    for i in range(0, len(all_spots), chunk_size):
        chunk = all_spots[i:i + chunk_size]
        btns = []
        for spot in chunk:
            btns.append({
                "type": "button",
                "action": {"type": "postback", "label": f"＋ {spot}", "data": f"action=fav_add_and_settings&spot={spot}"},
                "style": "secondary", "margin": "xs", "height": "sm", "color": "#fff59d"
            })
        btns.append({"type": "separator", "margin": "md"})
        btns.append({"type": "button", "action": {"type": "postback", "label": "🔙 地域選択に戻る", "data": "action=show_other_mode_areas"}, "style": "secondary", "margin": "md", "height": "sm", "color": "#e0e0e0"})

        bubbles.append({
            "type": "bubble", "size": "kilo",
            "header": {"type": "box", "layout": "vertical", "backgroundColor": header_color, "paddingAll": "10px", "contents": [{"type": "text", "text": f"タップして追加: {group['title'].replace('📍 ', '')}", "color": "#ffffff", "weight": "bold", "size": "xs"}]},
            "body": {"type": "box", "layout": "vertical", "paddingAll": "10px", "contents": btns}
        })

    if len(bubbles) == 1:
        return FlexSendMessage(alt_text=f"{target_name}スポット選択", contents=bubbles[0])
    else:
        return FlexSendMessage(alt_text=f"{target_name}スポット選択", contents={"type": "carousel", "contents": bubbles})
