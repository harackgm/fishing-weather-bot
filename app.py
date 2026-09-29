import os, time, random, requests, traceback, difflib, re, threading, unicodedata, jpholiday
from urllib.parse import quote, urlparse, parse_qsl
from bs4 import BeautifulSoup
from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage, PostbackEvent
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone

from spots import SPOT_WEATHER_DATA, BASS_SPOT_WEATHER_DATA, COLOR_GROUPS, BASS_COLOR_GROUPS, ALL_SPOT_DATA

os.environ['TZ'] = 'Asia/Tokyo'
if hasattr(time, 'tzset'): time.tzset()

app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '').strip())
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET', '').strip())
MAX_FAVORITES = 30
SUPABASE_URL = os.getenv('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '').strip()
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

MEMORY_CACHE, USER_LAST_REQUEST, REQUEST_LOCK = {}, {}, threading.Lock()

def is_throttled(user_id, cooldown=2.5):
    now_ts = time.time()
    with REQUEST_LOCK:
        if now_ts - USER_LAST_REQUEST.get(user_id, 0) < cooldown: return True
        USER_LAST_REQUEST[user_id] = now_ts
        return False

PREF_TO_JMA={"1":"016000","2":"014100","3":"012000","4":"011000","5":"020000","6":"030000","7":"040000","8":"050000","9":"060000","10":"070000","11":"080000","12":"090000","13":"100000","14":"110000","15":"120000","16":"130000","17":"140000","18":"150000","19":"160000","20":"170000","21":"180000","22":"190000","23":"200000","24":"210000","25":"220000","26":"230000","27":"240000","28":"250000","29":"260000","30":"270000","31":"280000","32":"290000","33":"300000","34":"310000","35":"320000","36":"330000","37":"340000","38":"350000","39":"360000","40":"370000","41":"380000","42":"390000","43":"400000","44":"410000","45":"420000","46":"430000","47":"440000","48":"450000","49":"460100","50":"471000"}
PREF_NAMES={"011000":"北海道","012000":"北海道","014100":"北海道","016000":"北海道","020000":"青森","030000":"岩手","040000":"宮城","050000":"秋田","060000":"山形","070000":"福島","080000":"茨城","090000":"栃木","100000":"群馬","110000":"埼玉","120000":"千葉","130000":"東京","140000":"神奈川","150000":"新潟","160000":"富山","170000":"石川","180000":"福井","190000":"山梨","200000":"長野","210000":"岐阜","220000":"静岡","230000":"愛知","240000":"三重","250000":"滋賀","260000":"京都","270000":"大阪","280000":"兵庫","290000":"奈良","300000":"和歌山","310000":"鳥取","320000":"島根","330000":"岡山","340000":"広島","350000":"山口","360000":"徳島","370000":"香川","380000":"愛媛","390000":"高知","400000":"福岡","410000":"佐賀","420000":"長崎","430000":"大分","450000":"宮崎","460100":"鹿児島","471000":"沖縄"}

def normalize_name(n): return unicodedata.normalize('NFKC', n).lower() if n else ""
def clean_url(u): return u.strip().replace(" ","").replace("\t","").split("#")[0] if u and (u.startswith("http://") or u.startswith("https://")) else ""
def convert_to_10days_url(u):
    c = clean_url(u)
    return c.replace('1hour.html', '10days.html') if c and '1hour.html' in c else (c + '10days.html' if c and c.endswith('/') else c)

def get_spot_details(k):
    d = ALL_SPOT_DATA.get(k)
    if not d: return k, None, "", "", "", "", "", "", "", "", "", None
    m = d.get("map_url") or f"https://www.google.com/maps/search/?api=1&query={quote(d.get('search_name', k))}"
    return k, d["url"], clean_url(d.get("hp_url")), clean_url(d.get("hp2_url")), m, d.get("tel",""), clean_url(d.get("x_url")), clean_url(d.get("fb_url")), clean_url(d.get("insta_url")), clean_url(d.get("blog_url")), clean_url(d.get("yt_url")), convert_to_10days_url(d.get("tenki_url"))

def guess_date_from_string(ds, nd):
    if not ds: return nd
    m = re.search(r'(?:(\d{1,2})[月/-])?\s*(\d{1,2})日?', ds)
    if not m: return nd
    ms, dy = m.group(1), int(m.group(2))
    if ms:
        try: t = nd.replace(month=int(ms), day=dy)
        except: return nd
        if (nd - t).days > 180:
            try: t = t.replace(year=nd.year + 1)
            except: pass
        elif (t - nd).days > 180:
            try: t = t.replace(year=nd.year - 1)
            except: pass
        return t
    cs = []
    for mo in [-1, 0, 1]:
        y, mv = nd.year, nd.month + mo
        if mv < 1: mv += 12; y -= 1
        elif mv > 12: mv -= 12; y += 1
        try: cs.append(datetime(y, mv, dy).date())
        except: pass
    return min(cs, key=lambda d: abs((d - nd).days)) if cs else nd

def build_delete_confirm_message(s, src):
    return FlexSendMessage(alt_text=f"{s}の削除確認", contents={"type": "bubble", "size": "kilo", "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "15px", "contents": [{"type": "text", "text": "⚠️ 削除の確認", "weight": "bold", "color": "#ff0000", "size": "md"}, {"type": "text", "text": f"「{s}」をお気に入りから削除しますか？", "wrap": True, "size": "sm", "color": "#333333"}]}, "footer": {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [{"type": "button", "style": "secondary", "height": "sm", "flex": 1, "action": {"type": "postback", "label": "キャンセル", "data": f"action=fav_del_cancel_and_{src}"}}, {"type": "button", "style": "primary", "color": "#e53935", "height": "sm", "flex": 1, "action": {"type": "postback", "label": "削除", "data": f"action=fav_del_execute_and_{src}&spot={s}"}}]}})

def build_delete_all_confirm_message():
    return FlexSendMessage(alt_text="全て削除の確認", contents={"type": "bubble", "size": "kilo", "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "15px", "contents": [{"type": "text", "text": "⚠️ 全て削除の確認", "weight": "bold", "color": "#ff0000", "size": "md"}, {"type": "text", "text": "表示中のすべてのお気に入りを削除しますか？", "wrap": True, "size": "sm", "color": "#333333"}]}, "footer": {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [{"type": "button", "style": "secondary", "height": "sm", "flex": 1, "action": {"type": "postback", "label": "キャンセル", "data": "action=fav_del_cancel_and_settings"}}, {"type": "button", "style": "primary", "color": "#e53935", "height": "sm", "flex": 1, "action": {"type": "postback", "label": "全て削除", "data": "action=fav_del_all_execute"}}]}})

def build_settings_flex_message(fav_list, mode="trout"):
    ag = COLOR_GROUPS if mode == "trout" else BASS_COLOR_GROUPS
    acs = [s for g in ag for sg in g["sub_groups"] for s in sg["spots"]]
    ff = [s for s in fav_list if s in acs]
    is_trout = (mode == "trout")
    sb = {"type": "button", "action": {"type": "postback", "label": "🎣 バスモードへ切替" if is_trout else "🐟 トラウトモードへ戻る", "data": f"action=switch_mode&mode={'bass' if is_trout else 'trout'}"}, "style": "primary", "color": "#1e88e5" if is_trout else "#e65100", "margin": "md", "height": "sm"}
    tt = "⚙️ お気に入り設定 (トラウト)" if is_trout else "⚙️ お気に入り設定 (バス)"
    hc = "#d4af37" if is_trout else "#4caf50"
    if not ff: return FlexSendMessage(alt_text="設定", contents={"type": "bubble", "size": "mega", "header": {"type": "box", "layout": "vertical", "backgroundColor": hc, "paddingAll": "10px", "contents": [{"type": "text", "text": tt, "color": "#ffffff", "weight": "bold", "size": "md"}]}, "body": {"type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "10px", "contents": [sb, {"type": "separator", "margin": "md"}, {"type": "text", "text": "登録されていません。", "size": "sm", "color": "#555555", "margin": "md"}]}})
    bs = []
    for i in range(0, len(ff), 10):
        c = ff[i:i+10]
        r = [sb, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "horizontal", "spacing": "xs", "paddingTop": "10px", "paddingBottom": "10px", "contents": [{"type": "button", "action": {"type": "postback", "label": "🥇1番", "data": "action=show_top_selector"}, "style": "secondary", "height": "sm", "flex": 1, "color": "#fff9c4"}, {"type": "button", "action": {"type": "postback", "label": "🔝先頭", "data": f"action=show_cell_top_selector&chunk={i}"}, "style": "secondary", "height": "sm", "flex": 1, "color": "#e3f2fd"}, {"type": "button", "action": {"type": "postback", "label": "⏬末尾", "data": f"action=show_cell_bottom_selector&chunk={i}"}, "style": "secondary", "height": "sm", "flex": 1, "color": "#eceff1"}]}, {"type": "separator", "margin": "sm"}]
        for s in c: r.append({"type": "box", "layout": "horizontal", "margin": "md", "alignItems": "center", "contents": [{"type": "text", "text": s, "size": "sm", "weight": "bold", "flex": 4, "color": "#333333", "wrap": True}, {"type": "button", "action": {"type": "postback", "label": "⬆️", "data": f"action=fav_up&spot={s}"}, "style": "secondary", "flex": 2, "margin": "xs"}, {"type": "button", "action": {"type": "postback", "label": "⬇️", "data": f"action=fav_down&spot={s}"}, "style": "secondary", "flex": 2, "margin": "xs"}, {"type": "button", "action": {"type": "postback", "label": "🗑️", "data": f"action=fav_del_confirm_and_settings&spot={s}"}, "style": "secondary", "color": "#ffe6e6", "flex": 2, "margin": "xs"}]})
        r.extend([{"type": "separator", "margin": "md"}, {"type": "box", "layout": "horizontal", "margin": "md", "spacing": "sm", "contents": [{"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#e53935", "cornerRadius": "md", "contents": [{"type": "button", "action": {"type": "postback", "label": "🗑️ 全て削除", "data": "action=fav_del_all_confirm"}, "style": "link", "color": "#ffffff", "height": "sm", "margin": "none"}]}, {"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#fff59d", "cornerRadius": "md", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]}]}])
        bs.append({"type": "bubble", "size": "mega", "header": {"type": "box", "layout": "vertical", "backgroundColor": hc, "paddingAll": "10px", "contents": [{"type": "text", "text": f"{tt} ({i+1}-{min(i+10, len(ff))}/{len(ff)}件)", "color": "#ffffff", "weight": "bold", "size": "md"}]}, "body": {"type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "10px", "contents": r}})
    return FlexSendMessage(alt_text="設定", contents=bs[0] if len(bs)==1 else {"type": "carousel", "contents": bs})

def build_spot_list_carousel_horizontal(user_id=None, mode="trout"):
    ag = COLOR_GROUPS if mode == "trout" else BASS_COLOR_GROUPS
    acs = [s for g in ag for sg in g["sub_groups"] for s in sg["spots"]]
    bs, ff = [], []
    if user_id:
        _, favs, _ = get_user_setting(user_id)
        ff = [s for s in favs.split(',') if s in acs]
        fr = []
        if not ff: fr.append({"type": "box", "layout": "vertical", "backgroundColor": "#fffde7", "cornerRadius": "md", "paddingAll": "md", "margin": "md", "contents": [{"type": "text", "text": "現在登録されていません。", "wrap": True, "size": "sm", "color": "#555555"}]})
        else:
            for i in range(0, len(ff), 2):
                p = ff[i:i+2]
                rb = []
                for j, s in enumerate(p):
                    if i+j < 2: rb.append({"type": "box", "layout": "vertical", "backgroundColor": "#fff59d", "cornerRadius": "md", "margin": "xs", "contents": [{"type": "button", "action": {"type": "postback", "label": s, "data": f"w={s}"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]})
                    else: rb.append({"type": "button", "style": "secondary", "color": "#fff59d", "margin": "xs", "height": "sm", "action": {"type": "postback", "label": s, "data": f"w={s}"}})
                if len(p) == 1: rb.append({"type": "filler"})
                fr.append({"type": "box", "layout": "horizontal", "contents": rb, "margin": "none" if i==0 else "xs"})
        fr.extend([{"type": "separator", "margin": "md", "color": "#cccccc"}, {"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm", "contents": [{"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#f8f9fa", "cornerRadius": "md", "contents": [{"type": "button", "action": {"type": "postback", "label": "⚙️ 設定/切替", "data": "action=show_settings"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]}, {"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#fff59d", "cornerRadius": "md", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧更新", "data": "action=show_list"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]}]}])
        bs.append({"type": "bubble", "size": "giga", "header": {"type": "box", "layout": "horizontal", "backgroundColor": "#d4af37" if mode=="trout" else "#4caf50", "paddingAll": "10px", "alignItems": "center", "contents": [{"type": "text", "text": "⭐ トラウトお気に入り" if mode=="trout" else "⭐ バスお気に入り", "color": "#ffffff", "weight": "bold", "size": "md", "flex": 1}, {"type": "text", "text": f"({len(ff)}/{MAX_FAVORITES})", "color": "#eeeeee", "size": "xs", "align": "end", "flex": 0}]}, "body": {"type": "box", "layout": "vertical", "paddingAll": "6px", "contents": fr}})
    for g in ag:
        r, isf = [], True
        for sg in g["sub_groups"]:
            ss, bg = sg["spots"], sg["bg"]
            for i in range(0, len(ss), 2):
                p = ss[i:i+2]
                rb = [{"type": "button", "style": "secondary", "color": bg, "margin": "xs", "height": "sm", "action": {"type": "postback", "label": f"★ {s}" if s in ff else s, "data": f"w={s}"}} for s in p]
                if len(p) == 1: rb.append({"type": "filler"})
                r.append({"type": "box", "layout": "horizontal", "contents": rb, "margin": "none" if isf else "xs"})
                isf = False
        bs.append({"type": "bubble", "size": "giga", "header": {"type": "box", "layout": "vertical", "backgroundColor": g["header_bg"], "paddingAll": "10px", "contents": [{"type": "text", "text": g["title"], "color": "#ffffff", "weight": "bold", "size": "md"}]}, "body": {"type": "box", "layout": "vertical", "paddingAll": "6px", "contents": r}})
    return FlexSendMessage(alt_text="釣り場一覧", contents={"type": "carousel", "contents": bs})

def get_user_setting(uid):
    if not supabase: return ('ウェザーニュース', '', 'trout')
    try:
        r = supabase.table('user_settings').select('*').eq('user_id', uid).execute()
        if r.data:
            row = r.data[0]
            rm = {"七色ダム":"池原七色ダム","キング":"キングフィッシャー","ツガネ":"JF in Tsugane","キングダム":"川場キングダム","イワセン":"イワナセンター","鹿島やり":"鹿島槍","アルクス宇宇都宮":"アルクス宇宇都宮","片仓ダム":"片倉ダム","多田良沼":"多々良沼","那須烏山":"那須鳥山","柏崎":"霞ケ浦柏崎","霞ケ浦西浦":"土浦港","ＭＡＶ":"宮城","GP不忘":"不忘"}
            fl = [rm.get(s.strip(), s.strip()) for s in (row.get('favorite_spots') or '').split(',')]
            return (row.get('weather_source', 'ウェザーニュース'), ','.join([s for s in fl if s not in ["多摩湖","いなプー"] and s]), row.get('fishing_mode', 'trout'))
    except: pass
    return ('ウェザーニュース', '', 'trout')

def get_mode_fav_count(favs, fm):
    acs = [s for g in (COLOR_GROUPS if fm=="trout" else BASS_COLOR_GROUPS) for sg in g["sub_groups"] for s in sg["spots"]]
    return sum(1 for s in favs.split(',') if s in acs)

def add_favorite_spots(uid, sns):
    if not supabase: return False, [], ["DB未接続"]
    src, favs, fm = get_user_setting(uid)
    fl = [s for s in favs.split(',') if s]
    a, e = [], []
    for sn in sns:
        tn, ni = None, normalize_name(sn)
        for k, d in ALL_SPOT_DATA.items():
            if ni == normalize_name(k) or ni in [normalize_name(x) for x in d["aliases"]]: tn = k; break
        if not tn: e.append(f"{sn}(不明)"); continue
        acs = [s for g in (COLOR_GROUPS if any(tn in sg["spots"] for g in COLOR_GROUPS for sg in g["sub_groups"]) else BASS_COLOR_GROUPS) for sg in g["sub_groups"] for s in sg["spots"]]
        if tn in fl: e.append(f"{tn}(登録済)"); continue
        if sum(1 for s in fl if s in acs) >= MAX_FAVORITES: e.append(f"{tn}(上限)"); continue
        fl.append(tn); a.append(tn)
    if a:
        try: supabase.table('user_settings').upsert({'user_id': uid, 'weather_source': src, 'favorite_spots': ','.join(fl), 'fishing_mode': fm}).execute()
        except: return False, [], ["DB保存エラー"]
    return True, a, e

def remove_favorite_spots(uid, sns):
    if not supabase: return False, [], ["DB未接続"]
    src, favs, fm = get_user_setting(uid)
    fl = [s for s in favs.split(',') if s]
    rm, e = [], []
    for sn in sns:
        tn, ni = None, normalize_name(sn)
        for k, d in ALL_SPOT_DATA.items():
            if ni == normalize_name(k) or ni in [normalize_name(x) for x in d["aliases"]]: tn = k; break
        if not tn: tn = sn
        if tn not in fl: e.append(f"{tn}(未登録)"); continue
        fl.remove(tn); rm.append(tn)
    if rm:
        try: supabase.table('user_settings').upsert({'user_id': uid, 'weather_source': src, 'favorite_spots': ','.join(fl), 'fishing_mode': fm}).execute()
        except: return False, [], ["DB保存エラー"]
    return True, rm, e

def clear_favorite_spots(uid, mode="trout"):
    if not supabase: return False, "DB未接続"
    src, favs, fm = get_user_setting(uid)
    acs = [s for g in (COLOR_GROUPS if mode=="trout" else BASS_COLOR_GROUPS) for sg in g["sub_groups"] for s in sg["spots"]]
    omf = [s for s in favs.split(',') if s and s not in acs]
    try:
        supabase.table('user_settings').upsert({'user_id': uid, 'weather_source': src, 'favorite_spots': ','.join(omf), 'fishing_mode': fm}).execute()
        return True, "全て削除しました。"
    except: return False, "削除失敗"

def move_favorite_spot(uid, sn, d, mode="trout"):
    if not supabase: return False, "DB未接続"
    src, favs, fm = get_user_setting(uid)
    rl = [s for s in favs.split(',') if s]
    if sn not in rl: return False, "未登録"
    acs = [s for g in (COLOR_GROUPS if mode=="trout" else BASS_COLOR_GROUPS) for sg in g["sub_groups"] for s in sg["spots"]]
    cm = [s for s in rl if s in acs]
    om = [s for s in rl if s not in acs]
    if sn not in cm: return False, "モード違い"
    i = cm.index(sn)
    if d == "up" and i > 0: cm[i-1], cm[i] = cm[i], cm[i-1]
    elif d == "down" and i < len(cm)-1: cm[i+1], cm[i] = cm[i], cm[i+1]
    elif d == "top" and i > 0: cm.insert(0, cm.pop(i))
    elif d == "bottom" and i < len(cm)-1: cm.append(cm.pop(i))
    elif d == "cell_top":
        cs = (i//10)*10
        if i > cs: cm.insert(cs, cm.pop(i))
    elif d == "cell_bottom":
        ce = min(((i//10)+1)*10-1, len(cm)-1)
        if i < ce: cm.insert(ce, cm.pop(i))
    try:
        supabase.table('user_settings').upsert({'user_id': uid, 'weather_source': src, 'favorite_spots': ','.join(cm+om), 'fishing_mode': fm}).execute()
        return True, "移動完了"
    except: return False, "移動失敗"

def fetch_weekly_data_from_jma(t_url, ex_dates):
    if not t_url: return []
    m = re.search(r'forecast/\d+/(\d+)/', t_url)
    if not m: return []
    jc = PREF_TO_JMA.get(m.group(1))
    if not jc: return []
    try:
        r = requests.get(f"https://www.jma.go.jp/bosai/forecast/data/forecast/{jc}.json", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5.0)
        r.raise_for_status()
        fd = {}
        for p in r.json():
            for ts in p.get('timeSeries', []):
                tms, ars = ts.get('timeDefines', []), ts.get('areas', [])
                if not tms or not ars: continue
                ta = ars[0]
                for a in ars:
                    if a.get("area", {}).get("name", "") in ["北部", "大田原", "西部", "秩父", "北部の山沿い", "飛騨地方", "長野", "塩尻", "松本"]: ta = a; break
                for i, dt_s in enumerate(tms):
                    try: dt = datetime.strptime(dt_s[:10], "%Y-%m-%d").date()
                    except: continue
                    if dt not in fd: fd[dt] = {"c": 100, "p": "-", "mn": "-", "mx": "-"}
                    if "weatherCodes" in ta and i < len(ta["weatherCodes"]) and ta["weatherCodes"][i]: fd[dt]["c"] = ta["weatherCodes"][i]
                    if "pops" in ta and i < len(ta["pops"]) and ta["pops"][i] not in ["", None]:
                        vs = str(ta["pops"][i]).replace('%','')
                        if vs.isdigit(): fd[dt]["p"] = f"{vs}%"
                    if "tempsMin" in ta and i < len(ta["tempsMin"]) and ta["tempsMin"][i] not in ["", None]: fd[dt]["mn"] = str(ta["tempsMin"][i])
                    if "tempsMax" in ta and i < len(ta["tempsMax"]) and ta["tempsMax"][i] not in ["", None]: fd[dt]["mx"] = str(ta["tempsMax"][i])
                    if "temps" in ta and i < len(ta["temps"]) and ta["temps"][i] not in ["", None]:
                        try:
                            tv = int(ta["temps"][i])
                            if fd[dt]["mn"] == "-" or tv < int(fd[dt]["mn"]): fd[dt]["mn"] = str(tv)
                            if fd[dt]["mx"] == "-" or tv > int(fd[dt]["mx"]): fd[dt]["mx"] = str(tv)
                        except: pass
        njd = datetime.now(timezone(timedelta(hours=9))).date()
        lwd = guess_date_from_string(ex_dates[-1], njd) if ex_dates else None
        wd = []
        for dt in sorted(fd.keys()):
            if lwd and dt <= lwd: continue
            dd = fd[dt]
            ws = ["(月)","(火)","(水)","(木)","(金)","(土)","(日)"][dt.weekday()]
            try: c = int(dd["c"])
            except: c = 100
            img = "100" if c<200 else ("200" if c<300 else ("300" if c<400 else "400"))
            wd.append({"date": f"{dt.day}{ws}", "img_url": f"https://gvs.weathernews.jp/onebox/img/wxicon/{img}.png", "temp_max": dd["mx"], "temp_min": dd["mn"], "rain_prob": dd["p"]})
            if len(wd) >= 8: break
        return wd
    except: return []

def fetch_disaster_info(t_url):
    if not t_url: return {}
    m = re.search(r'forecast/\d+/(\d+)/', t_url)
    if not m: return {}
    jc = PREF_TO_JMA.get(m.group(1))
    if not jc: return {}
    pn = PREF_NAMES.get(jc, "")
    wl, qs, vs = [], None, None
    hd = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(f"https://www.jma.go.jp/bosai/warning/data/warning/{jc}.json", headers=hd, timeout=2.0)
        if r.status_code == 200:
            cm = {"02":"暴風雪警報","03":"大雨警報","04":"洪水警報","05":"暴風警報","06":"大雪警報","07":"波浪警報","08":"高潮警報","10":"大雨注意報","12":"大雪注意報","13":"風雪注意報","14":"雷注意報","15":"強風注意報","16":"波浪注意報","17":"融雪注意報","18":"洪水注意報","19":"高潮注意報","20":"濃霧注意報","21":"乾燥注意報","22":"なだれ注意報","23":"低温注意報","24":"霜注意報","25":"着氷注意報","26":"着雪注意報","32":"暴風雪特別警報","33":"大雨特別警報","35":"暴風特別警報","36":"大雪特別警報","37":"波浪特別警報","38":"高潮特別警報"}
            d = r.json()
            if "areaTypes" in d and d["areaTypes"]:
                for w in d["areaTypes"][0].get("areas", [])[0].get("warnings", []):
                    if w.get("status") != "解除" and w.get("code") in cm: wl.append(cm[w["code"]])
            wl = list(dict.fromkeys(wl))
    except: pass
    try:
        r = requests.get("https://www.jma.go.jp/bosai/quake/data/list.json", headers=hd, timeout=2.0)
        if r.status_code == 200:
            for eq in r.json():
                anm = eq.get("anm", "")
                if pn and (pn in anm or pn in str(eq)):
                    dts = eq.get("at", eq.get("rdt", ""))
                    if dts:
                        dt = datetime.fromisoformat(dts)
                        qs = f"{dt.month}/{dt.day} {dt.hour}:{dt.minute:02d} {anm} (震度{eq.get('maxi','')}/M{eq.get('mag','')})"
                        break
    except: pass
    try:
        r = requests.get("https://www.jma.go.jp/bosai/volcano/data/list.json", headers=hd, timeout=2.0)
        if r.status_code == 200:
            for v in r.json():
                tit = v.get("tit", "")
                if pn and (pn in tit or pn in str(v)):
                    vs = (tit[:14] + "…") if len(tit) > 15 else tit
                    break
    except: pass
    return {"warnings": wl, "quake": qs, "volcano": vs}

def fetch_spot_1hour_data(url, tenki_url=None):
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3.8)
        r.raise_for_status()
        s = BeautifulSoup(r.text, 'html.parser')
        wbd = {}
        fl = s.find('div', id='flick_list_1hour') or s.find('div', id='flick_list_3hour')
        if fl:
            for g in fl.find_all('div', class_='group'):
                dtg = g.find('div', class_='date')
                if not dtg: continue
                ds = dtg.text.strip()
                dl = []
                for i in g.find_all('ul', class_='list'):
                    if 'past' in i.get('class', []): continue
                    ttg = i.find('li', class_='time')
                    hs = ttg.text.strip() if ttg else ""
                    if not hs.isdigit(): continue
                    hi = int(hs)
                    if not (3 <= hi <= 20): continue
                    hr = f"{hi:02d}時"
                    img = "https://gvs.weathernews.jp/onebox/img/wxicon/200.png"
                    wtg = i.find('li', class_='weather')
                    itg = wtg.find('img') if wtg else None
                    if itg and 'src' in itg.attrs:
                        src = itg['src']
                        img = ("https:" + src if src.startswith('//') else ("https://weathernews.jp" + src if src.startswith('/') else src)).replace("http://", "https://")
                    rn = i.find('li', class_='rain').text.strip().replace("ミリ", "mm") if i.find('li', class_='rain') else "-"
                    tp = i.find('li', class_='temp').text.strip() if i.find('li', class_='temp') else "-"
                    wp = i.find('li', class_='wind').find('p') if i.find('li', class_='wind') else None
                    wd = wp.text.strip() if wp else "-"
                    dl.append({"time": hr, "img_url": img, "temp": tp, "rain": rn, "wind": wd})
                if dl: wbd[ds] = dl
                if len(wbd) >= 4: break
        if not wbd: return None
        red = list(wbd.keys())
        wd = fetch_weekly_data_from_jma(tenki_url, red) if tenki_url else []
        if not wd:
            ndt = datetime.now(timezone(timedelta(hours=9)))
            sd = guess_date_from_string(red[-1], ndt.date()) + timedelta(days=1) if red else ndt.date()
            for i in range(8):
                dd = sd + timedelta(days=i)
                ws = ["(月)","(火)","(水)","(木)","(金)","(土)","(日)"][dd.weekday()]
                wd.append({"date": f"{dd.day}{ws}", "img_url": "https://gvs.weathernews.jp/onebox/img/wxicon/200.png", "temp_max": "-", "temp_min": "-", "rain_prob": "-"})
            wbd["__is_dummy__"] = True
        else:
            ldt = guess_date_from_string(wd[-1]["date"], datetime.now(timezone(timedelta(hours=9))).date())
            while len(wd) < 8:
                ldt += timedelta(days=1)
                ws = ["(月)","(火)","(水)","(木)","(金)","(土)","(日)"][ldt.weekday()]
                wd.append({"date": f"{ldt.day}{ws}", "img_url": "https://gvs.weathernews.jp/onebox/img/wxicon/200.png", "temp_max": "-", "temp_min": "-", "rain_prob": "-"})
        wbd["__weekly__"] = wd
        wbd["__disaster__"] = fetch_disaster_info(tenki_url)
        return wbd
    except: return None

def get_cached_weather(sn):
    n = datetime.now(timezone.utc)
    if sn in MEMORY_CACHE:
        d, ut = MEMORY_CACHE[sn]
        if n - ut <= timedelta(hours=2) and isinstance(d, dict) and d.get("_version") == "v131" and d.get("__weekly__"): return d
    if not supabase: return None
    try:
        r = supabase.table('weather_cache').select('*').eq('spot_name', sn).execute()
        if r.data:
            ut_s = r.data[0].get('updated_at')
            if ut_s:
                ut = datetime.fromisoformat(ut_s.replace('Z', '+00:00'))
                if n - ut <= timedelta(hours=2):
                    wd = r.data[0].get('weather_data')
                    if isinstance(wd, dict) and wd.get("_version") == "v131" and wd.get("__weekly__"):
                        MEMORY_CACHE[sn] = (wd, ut)
                        return wd
    except: pass
    return None

def save_cached_weather(sn, wd):
    if wd.get("__is_dummy__"): return
    n = datetime.now(timezone.utc)
    wd["_version"] = "v131"
    MEMORY_CACHE[sn] = (wd, n)
    if supabase:
        try: supabase.table('weather_cache').upsert({'spot_name': sn, 'weather_data': wd, 'updated_at': n.isoformat()}).execute()
        except: pass

def create_disaster_box(d):
    c = [{"type": "text", "text": "⚠️ リアルタイム防災情報", "weight": "bold", "size": "xs", "color": "#e53935"}]
    l = 0
    w = d.get("warnings", [])
    if w:
        c.append({"type": "text", "text": "・" + " / ".join(w), "size": "xxs", "wrap": True, "color": "#ff9800", "weight": "bold", "maxLines": 2})
        l += 2
    else:
        c.append({"type": "text", "text": "✅ 警報・注意報の発表なし", "size": "xxs", "color": "#4caf50"})
        l += 1
    c.append({"type": "separator", "margin": "xs"})
    q = d.get("quake")
    if q and l < 4:
        c.append({"type": "text", "text": f"【地震】{q}", "size": "xxs", "wrap": True, "color": "#555555", "maxLines": 1})
        l += 1
        c.append({"type": "separator", "margin": "xs"})
    v = d.get("volcano")
    if v and l < 5:
        c.append({"type": "text", "text": f"【火山】{v}", "size": "xxs", "wrap": True, "color": "#555555", "maxLines": 1})
    return {"type": "box", "layout": "vertical", "margin": "md", "paddingAll": "8px", "backgroundColor": "#fffde7", "cornerRadius": "sm", "borderColor": "#ffd54f", "borderWidth": "normal", "spacing": "xs", "contents": c}

def build_grid_flex_message(spot_name, weather_data, hp_url="", hp2_url="", map_url="", tel="", x_url="", fb_url="", insta_url="", blog_url="", yt_url="", is_favorite=False):
    weekly_data = weather_data.get("__weekly__", []) if isinstance(weather_data, dict) else []
    disaster_data = weather_data.get("__disaster__", {}) if isinstance(weather_data, dict) else {}
    dates = [d for d in weather_data.keys() if d not in ["__weekly__", "_version", "__is_dummy__", "__disaster__"]]
    weather_by_date = weather_data
    njd = datetime.now(timezone(timedelta(hours=9))).date()
    dates = sorted(dates, key=lambda d: guess_date_from_string(d, njd))

    ag = BASS_COLOR_GROUPS if any(spot_name in sg["spots"] for g in BASS_COLOR_GROUPS for sg in g["sub_groups"]) else COLOR_GROUPS
    hc = "#0066cc"
    for g in ag:
        if any(spot_name in sg["spots"] for sg in g["sub_groups"]):
            hc = g["header_bg"]
            break

    def create_day_column(ds):
        if not ds: return {"type": "box", "layout": "vertical", "flex": 1, "contents": [{"type": "text", "text": "-", "color": "#cccccc", "align": "center", "size": "xs"}]}
        dd = weather_by_date[ds]
        td = guess_date_from_string(ds, njd)
        ihf = jpholiday.is_holiday(td) or "(祝)" in ds
        dds, hbc, htc = ds, "#f5f5f5", "#333333"
        if ihf or "(日)" in ds:
            hbc, htc = "#ffe6e6", "#cc0000"
            if ihf and "🇯🇵" not in dds: dds = f"🇯🇵 {ds}"
        elif "(土)" in ds: hbc, htc = "#e6f2ff", "#0066cc"
        r = [{"type": "box", "layout": "horizontal", "margin": "none", "contents": [{"type": "text", "text": "時", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"}, {"type": "text", "text": "天", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"}, {"type": "text", "text": "℃", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"}, {"type": "text", "text": "☔", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"}, {"type": "text", "text": "m", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"}]}, {"type": "separator", "margin": "xs"}]
        for d in dd:
            tv = d.get('temp', '').replace("℃", "").strip() or "-"
            rv = d.get('rain', '').replace("mm", "").strip() or "-"
            wv = d.get('wind', '').replace("m/s", "").replace("m", "").strip() or "-"
            ts = d.get('time', '').replace("時", "").strip() or "-"
            iu = d.get('img_url', '') or "https://gvs.weathernews.jp/onebox/img/wxicon/200.png"
            tc = "#ff0000" if tv.isdigit() and int(tv)>=25 else "#333333"
            rc = "#0000ff" if rv.isdigit() and int(rv)>0 else "#333333"
            r.append({"type": "box", "layout": "horizontal", "margin": "xs", "alignItems": "center", "contents": [{"type": "text", "text": ts, "size": "xs", "flex": 1, "align": "center", "weight": "bold"}, {"type": "image", "url": iu, "size": "xs", "flex": 1}, {"type": "text", "text": tv, "size": "xs", "flex": 1, "align": "center", "color": tc}, {"type": "text", "text": rv, "size": "xs", "flex": 1, "align": "center", "color": rc}, {"type": "text", "text": wv, "size": "xs", "flex": 1, "align": "center"}]})
        return {"type": "box", "layout": "vertical", "flex": 1, "contents": [{"type": "box", "layout": "vertical", "backgroundColor": hbc, "paddingAll": "4px", "margin": "sm", "contents": [{"type": "text", "text": dds, "weight": "bold", "size": "sm", "align": "center", "color": htc}]}] + [{"type": "box", "layout": "vertical", "spacing": "none", "margin": "sm", "contents": r}]}

    def create_weekly_box(sd):
        if not sd: return None
        cols = []
        for w in sd:
            rv = str(w.get("rain_prob", "0")).replace("%", "").strip()
            rc = "#0000ff" if rv.isdigit() and int(rv)>0 else "#555555"
            ds = str(w.get("date", "-"))
            dc = "#333333"
            if ds != "-":
                td = guess_date_from_string(ds, njd)
                if jpholiday.is_holiday(td) or "(日)" in ds or "(祝)" in ds: dc = "#cc0000"
                elif "(土)" in ds: dc = "#0066cc"
            cols.append({"type": "box", "layout": "vertical", "flex": 1, "alignItems": "center", "spacing": "xs", "contents": [{"type": "text", "text": ds, "size": "xxs", "weight": "bold", "color": dc, "align": "center"}, {"type": "image", "url": str(w.get("img_url", "https://gvs.weathernews.jp/onebox/img/wxicon/200.png")), "size": "xs", "aspectMode": "fit"}, {"type": "text", "text": f"{w.get('temp_max', '-')}/{w.get('temp_min', '-')}℃", "size": "xxs", "color": "#333333", "weight": "bold", "align": "center"}, {"type": "text", "text": f"{w.get('rain_prob', '-')}", "size": "xxs", "color": rc, "weight": "bold", "align": "center"}]})
        return {"type": "box", "layout": "horizontal", "margin": "md", "spacing": "xs", "backgroundColor": "#f4f4f4", "paddingAll": "8px", "cornerRadius": "sm", "contents": cols}

    def create_header_block(bi):
        hc_list = [{"type": "text", "text": f"📍 {spot_name}", "color": "#ffffff", "weight": "bold", "size": "lg"}]
        ar, tb = [], []
        tb.append({"type": "button", "action": {"type": "postback", "label": "🗑️ 解除" if is_favorite else "⭐️ 登録", "data": f"action=fav_del_confirm_and_list&spot={spot_name}" if is_favorite else f"action=fav_add_and_list&spot={spot_name}"}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs", "color": "#ffcccc" if is_favorite else "#fff59d"})
        sd = ALL_SPOT_DATA.get(spot_name, {})
        if map_url and not sd.get("hide_default_map", False): tb.append({"type": "button", "action": {"type": "uri", "label": "🗺️ 地図", "uri": map_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        elif len(tb)==1: tb.append({"type": "box", "layout": "vertical", "flex": 1, "margin": "xs", "contents": []})
        ar.append(tb)
        bb = []
        if hp_url: bb.append({"type": "button", "action": {"type": "uri", "label": "🌐 大崎HP" if spot_name=="大崎・赤城" else "🌐 HP", "uri": hp_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if hp2_url: bb.append({"type": "button", "action": {"type": "uri", "label": "🌐 赤城HP" if spot_name=="大崎・赤城" else "🌐 HP2", "uri": hp2_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if x_url: bb.append({"type": "button", "action": {"type": "uri", "label": "𝕏", "uri": x_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if fb_url: bb.append({"type": "button", "action": {"type": "uri", "label": "📘 FB", "uri": fb_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if insta_url: bb.append({"type": "button", "action": {"type": "uri", "label": "📷 Insta", "uri": insta_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if blog_url: bb.append({"type": "button", "action": {"type": "uri", "label": "📝 Blog", "uri": blog_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if yt_url: bb.append({"type": "button", "action": {"type": "uri", "label": "▶️ YouTube", "uri": yt_url}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
        if bb: ar.append(bb)
        for rl in sd.get("custom_button_rows", []):
            rb = [{"type": "button", "action": {"type": "uri", "label": l["label"], "uri": l["url"]} if l.get("url") else {"type": "postback", "label": l["label"], "data": "action=dummy"}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"} for l in rl]
            if rb: ar.append(rb)
        lr = ar[:(len(ar)+1)//2] if len(ar)>2 else ar
        rr = ar[(len(ar)+1)//2:] if len(ar)>2 else []
        mr = max(len(lr), len(rr))
        tr = lr if bi == 0 else rr
        for rb in tr: hc_list.append({"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "xs", "contents": rb})
        for _ in range(mr - len(tr)): hc_list.append({"type": "box", "layout": "vertical", "margin": "sm", "height": "40px", "contents": [{"type": "filler"}]})
        return {"type": "box", "layout": "vertical", "backgroundColor": hc, "paddingAll": "10px", "contents": hc_list}

    wb1 = create_weekly_box(weekly_data[0:4]) if len(weekly_data)>0 else None
    wb2 = create_weekly_box(weekly_data[4:8]) if len(weekly_data)>4 else None
    bi_url = "https://raw.githubusercontent.com/harackgm/fishing-weather-bot/main/tenkiharackbana.jpg"
    bb1 = [{"type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "0px", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]}]
    bb2 = []
    if tel: bb2.append({"type": "box", "layout": "vertical", "flex": 2, "backgroundColor": "#f8f9fa", "borderWidth": "normal", "borderColor": "#e0e0e0", "cornerRadius": "md", "paddingAll": "0px", "contents": [{"type": "button", "action": {"type": "uri", "label": "📞 電話", "uri": f"tel:{tel.replace('-','').strip()}"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]})
    bb2.append({"type": "box", "layout": "vertical", "flex": 3 if tel else 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "0px", "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]})
    bc1, bc2 = [], []
    if wb1: bc1.extend([{"type": "separator", "margin": "md"}, wb1])
    bc1.extend([{"type": "separator", "margin": "md"}, {"type": "image", "url": bi_url, "size": "full", "aspectRatio": "3:1", "aspectMode": "cover", "margin": "md"}, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm", "contents": bb1}])
    if wb2: bc2.extend([{"type": "separator", "margin": "md"}, wb2])
    bc2.extend([{"type": "separator", "margin": "md"}, {"type": "image", "url": bi_url, "size": "full", "aspectRatio": "3:1", "aspectMode": "cover", "margin": "md"}, {"type": "separator", "margin": "md"}, {"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm", "contents": bb2}])
    
    bs = []
    if len(dates) > 0:
        b1c = [{"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [create_day_column(dates[0]), {"type": "separator"}, create_day_column(dates[1] if len(dates)>1 else None)]}]
        b1c.extend(bc1)
        bs.append({"type": "bubble", "size": "giga", "header": create_header_block(0), "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "8px", "contents": b1c}})
    if len(dates) > 2:
        b2c = [{"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [create_day_column(dates[2]), {"type": "separator"}, create_day_column(dates[3] if len(dates)>3 else None)]}]
        b2c.extend(bc2)
        b2c.append({"type": "separator", "margin": "md", "color": "#00000000"})
        if disaster_data: b2c.append(create_disaster_box(disaster_data))
        bs.append({"type": "bubble", "size": "giga", "header": create_header_block(1), "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "8px", "contents": b2c}})
    return FlexSendMessage(alt_text=f"{spot_name}の天気", contents={"type": "carousel", "contents": bs})

@app.route("/", methods=['GET'])
def top_page(): return "LINE Reply Bot Server is running!", 200

@app.route("/debug/cache", methods=['GET'])
def debug_cache():
    return jsonify({"total_cached": len(MEMORY_CACHE), "active_caches": sum(1 for d, u in MEMORY_CACHE.values() if datetime.now(timezone.utc)-u<=timedelta(hours=2)), "details": {k: {"version": d.get("_version", "unknown")} for k, (d, u) in MEMORY_CACHE.items()}}), 200

@app.route("/callback", methods=['POST'])
def callback():
    try: handler.handle(request.get_data(as_text=True), request.headers.get('X-Line-Signature', ''))
    except InvalidSignatureError: abort(400)
    return 'OK', 200

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        msg = event.message.text.strip()
        uid = event.source.user_id
        if is_throttled(uid): return
        src, favs, fm = get_user_setting(uid)
        
        if msg in ["お気に入り1", "お気に入り2"]:
            acs = [s for g in (COLOR_GROUPS if fm=="trout" else BASS_COLOR_GROUPS) for sg in g["sub_groups"] for s in sg["spots"]]
            fl = [s for s in favs.split(',') if s in acs]
            ts = fl[0] if msg=="お気に入り1" and len(fl)>0 else (fl[1] if msg=="お気に入り2" and len(fl)>1 else None)
            if ts:
                tsn, tu, h1, h2, mu, tel, xu, fb, ins, bl, yt, t_url = get_spot_details(ts)
                if not tu: return
                wd = get_cached_weather(tsn)
                if not wd:
                    wd = fetch_spot_1hour_data(tu, t_url)
                    if wd: save_cached_weather(tsn, wd)
                if wd: line_bot_api.reply_message(event.reply_token, build_grid_flex_message(tsn, wd, h1, h2, mu, tel, xu, fb, ins, bl, yt, True))
            else: line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="⚠️ お気に入りが未登録です。"), build_spot_list_carousel_horizontal(uid, fm)])
            return
            
        m = re.match(r'^(追加|削除)[\s:：]+(.+)$', msg, re.DOTALL)
        if m:
            cmd, sn = m.groups()
            sns = [s for s in re.split(r'[\s,、\n]+', sn.strip()) if s and s not in ["追加", "削除"]]
            success, pl, el = add_favorite_spots(uid, sns) if cmd=="追加" else remove_favorite_spots(uid, sns)
            tc = get_mode_fav_count(get_user_setting(uid)[1], fm)
            r = []
            if pl: r.append(f"✅ {cmd}しました: {','.join(pl)}")
            if el: r.append(f"⚠️ 失敗: {','.join(el)}")
            if pl or el: r.append(f"📊 登録数: {tc}/{MAX_FAVORITES}")
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="\n".join(r)), build_spot_list_carousel_horizontal(uid, fm)])
            return
            
        if msg in ["設定", "⚙️設定", "⚙️ 設定", "設定（並び替え・削除）"]: line_bot_api.reply_message(event.reply_token, build_settings_flex_message([s for s in favs.split(',') if s], fm))
        else: line_bot_api.reply_message(event.reply_token, build_spot_list_carousel_horizontal(uid, fm))
    except: traceback.print_exc()

@handler.add(PostbackEvent)
def handle_postback(event):
    try:
        uid = event.source.user_id
        if is_throttled(uid): return
        d = dict(parse_qsl(event.postback.data))
        act, sp = d.get("action"), d.get("spot")
        src, favs, fm = get_user_setting(uid)
        if act == "dummy": return
        if "w" in d: act, sp = "show_weather", d["w"]
        
        if act == "switch_mode":
            tm = d.get("mode", "trout")
            if supabase: supabase.table('user_settings').upsert({'user_id': uid, 'weather_source': src, 'favorite_spots': favs, 'fishing_mode': tm}).execute()
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=f"🐟 {'ブラックバス' if tm=='bass' else 'エリアトラウト'}モードへ切替！"), build_spot_list_carousel_horizontal(uid, tm)])
        elif act in ["show_top_selector", "show_cell_top_selector", "show_cell_bottom_selector"]:
            fl = [s for s in favs.split(',') if s in [x for g in (COLOR_GROUPS if fm=="trout" else BASS_COLOR_GROUPS) for sg in g["sub_groups"] for x in sg["spots"]]]
            if not fl: return
            ci = int(d.get("chunk", 0))
            ta = "fav_top" if act=="show_top_selector" else ("fav_cell_top" if act=="show_cell_top_selector" else "fav_cell_bottom")
            lc = [(i, fl[i:i+10]) for i in range(0, len(fl), 10)] if act=="show_top_selector" else [(ci, fl[ci:ci+10])]
            bs = [{"type": "bubble", "size": "kilo", "header": {"type": "box", "layout": "vertical", "backgroundColor": "#d4af37" if act=="show_top_selector" else "#64b5f6", "paddingAll": "10px", "contents": [{"type": "text", "text": "移動先を選択", "color": "#ffffff", "weight": "bold", "size": "sm"}]}, "body": {"type": "box", "layout": "vertical", "paddingAll": "10px", "contents": [{"type": "button", "action": {"type": "postback", "label": s, "data": f"action={ta}&spot={s}"}, "style": "secondary", "margin": "xs", "height": "sm"} for s in c] + [{"type": "button", "action": {"type": "postback", "label": "🔙 戻る", "data": "action=show_settings"}, "style": "secondary", "margin": "md", "height": "sm"}]}} for _, c in lc if c]
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="選択", contents={"type": "carousel", "contents": bs}))
        elif act == "show_list": line_bot_api.reply_message(event.reply_token, build_spot_list_carousel_horizontal(uid, fm))
        elif act == "show_settings": line_bot_api.reply_message(event.reply_token, build_settings_flex_message([s for s in favs.split(',') if s], fm))
        elif act == "show_weather":
            tsn, tu, h1, h2, mu, tel, xu, fb, ins, bl, yt, t_url = get_spot_details(sp)
            if not tu: return
            wd = get_cached_weather(tsn)
            if not wd:
                wd = fetch_spot_1hour_data(tu, t_url)
                if wd: save_cached_weather(tsn, wd)
            if wd: line_bot_api.reply_message(event.reply_token, build_grid_flex_message(tsn, wd, h1, h2, mu, tel, xu, fb, ins, bl, yt, tsn in [s for s in favs.split(',') if s]))
        elif act in ["fav_add_and_list", "fav_del_execute_and_list", "fav_del_execute_and_settings"]:
            success, res, err = add_favorite_spots(uid, [sp]) if "add" in act else remove_favorite_spots(uid, [sp])
            tc = get_mode_fav_count(get_user_setting(uid)[1], fm)
            msg = f"✅ 完了: {res[0]}\n📊 登録数: {tc}/{MAX_FAVORITES}" if res else f"⚠️ {err[0]}\n📊 登録数: {tc}/{MAX_FAVORITES}"
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), build_settings_flex_message([s for s in get_user_setting(uid)[1].split(',') if s], fm) if "settings" in act else build_spot_list_carousel_horizontal(uid, fm)])
        elif act in ["fav_del_confirm_and_list", "fav_del_confirm_and_settings"]: line_bot_api.reply_message(event.reply_token, build_delete_confirm_message(sp, act.split("_and_")[1]))
        elif act in ["fav_del_cancel_and_list", "fav_del_cancel_and_settings"]: line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="キャンセルしました。"), build_settings_flex_message([s for s in favs.split(',') if s], fm) if "settings" in act else build_spot_list_carousel_horizontal(uid, fm)])
        elif act == "fav_del_all_confirm": line_bot_api.reply_message(event.reply_token, build_delete_all_confirm_message())
        elif act == "fav_del_all_execute":
            clear_favorite_spots(uid, fm)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="✅ 全て削除しました"), build_spot_list_carousel_horizontal(uid, fm)])
        elif act in ["fav_up", "fav_down", "fav_top", "fav_bottom", "fav_cell_top", "fav_cell_bottom"]:
            move_favorite_spot(uid, sp, act.replace("fav_", ""), fm)
            line_bot_api.reply_message(event.reply_token, build_settings_flex_message([s for s in get_user_setting(uid)[1].split(',') if s], fm))
    except: traceback.print_exc()

def get_top_favorite_spots(t_limit=24, b_limit=12):
    if not supabase: return [], []
    try:
        r = supabase.table('user_settings').select('favorite_spots').execute()
        tc, bc = {}, {}
        tsl = [s for g in COLOR_GROUPS for sg in g["sub_groups"] for s in sg["spots"]]
        bsl = [s for g in BASS_COLOR_GROUPS for sg in g["sub_groups"] for s in sg["spots"]]
        for row in (r.data or []):
            for s in [x.strip() for x in (row.get('favorite_spots') or '').split(',') if x.strip()]:
                if s in tsl: tc[s] = tc.get(s, 0) + 1
                elif s in bsl: bc[s] = bc.get(s, 0) + 1
        return [s for s, _ in sorted(tc.items(), key=lambda x: x[1], reverse=True)[:t_limit]], [s for s, _ in sorted(bc.items(), key=lambda x: x[1], reverse=True)[:b_limit]]
    except: return [], []

def run_background_update():
    if not supabase: return
    try:
        tt, tb = get_top_favorite_spots(24, 12)
        tt_targets, tb_targets = [], []
        if tt:
            tct = {}
            for s in tt:
                r = supabase.table('weather_cache').select('updated_at').eq('spot_name', s).execute()
                tct[s] = datetime.fromisoformat(r.data[0].get('updated_at').replace('Z', '+00:00')) if r.data else datetime.min.replace(tzinfo=timezone.utc)
            tt_targets = [s for s, _ in sorted(tct.items(), key=lambda x: x[1])[:5]]
        if tb:
            bct = {}
            for s in tb:
                r = supabase.table('weather_cache').select('updated_at').eq('spot_name', s).execute()
                bct[s] = datetime.fromisoformat(r.data[0].get('updated_at').replace('Z', '+00:00')) if r.data else datetime.min.replace(tzinfo=timezone.utc)
            tb_targets = [s for s, _ in sorted(bct.items(), key=lambda x: x[1])[:3]]
        
        for s in tt_targets:
            d = ALL_SPOT_DATA.get(s)
            if d:
                wd = fetch_spot_1hour_data(d["url"], convert_to_10days_url(d.get("tenki_url")))
                if wd: save_cached_weather(s, wd)
            time.sleep(random.uniform(2.5, 4.0))
            
        if tb_targets:
            time.sleep(random.uniform(5.0, 10.0))
            for s in tb_targets:
                d = ALL_SPOT_DATA.get(s)
                if d:
                    wd = fetch_spot_1hour_data(d["url"], convert_to_10days_url(d.get("tenki_url")))
                    if wd: save_cached_weather(s, wd)
                time.sleep(random.uniform(2.5, 4.0))
    except: traceback.print_exc()

@app.route("/cron_trigger", methods=['GET', 'POST'])
def cron_trigger():
    if not supabase: return jsonify({"status": "error"}), 500
    threading.Thread(target=run_background_update).start()
    return jsonify({"status": "success"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
