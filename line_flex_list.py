import os
import re
import jpholiday
from datetime import datetime, timedelta, timezone
from linebot.models import FlexSendMessage

# --- 外部ファイル(spots.py)からグループデータをインポート ---
try:
    from spots import COLOR_GROUPS, BASS_COLOR_GROUPS
except ImportError:
    COLOR_GROUPS = []
    BASS_COLOR_GROUPS = []

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
