import os
import time
import random
import requests
import traceback
import difflib
import re
import threading
from urllib.parse import quote, urlparse, parse_qsl
from bs4 import BeautifulSoup
from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage, PostbackEvent
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. 日本時間（JST）設定と初期化
# ==========================================
os.environ['TZ'] = 'Asia/Tokyo'
if hasattr(time, 'tzset'):
    time.tzset()

app = Flask(__name__)

# ==========================================
# 2. 設定値および安全装置（ガードレール）
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '').strip()

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

MAX_FAVORITES = 30   # ★お気に入り登録の最大数（30箇所）

# Supabase接続初期化
SUPABASE_URL = os.getenv('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '').strip()

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"[Supabase初期化エラー] {e}")

# ==========================================
# 3. 釣り場URL・HP・Googleマップ・電話番号・表記揺れ辞書
# ==========================================
SPOT_WEATHER_DATA = {
    # --- 静岡県 ---
    "東山湖": {
        "url": "https://weathernews.jp/onebox/35.296739/138.955925/",
        "hp_url": "http://www.higashiyamako.com/",
        "search_name": "東山湖フィッシングエリア",
        "tel": "0550-82-2161",
        "aliases": ["東山湖", "東山湖フィッシングエリア", "東山湖FA", "ひがしやまこ", "ひがしやま", "東山", "がし山", "がしやま"]
    },
    "すその": {
        "url": "https://weathernews.jp/onebox/35.166667/138.899162/",
        "hp_url": "http://www.susono-f-p.jp/",
        "search_name": "すそのフィッシングパーク",
        "tel": "055-997-0041",
        "aliases": ["すその", "すそのフィッシングパーク", "すそのFP", "裾野", "すそぱ", "すそパ"]
    },
    "須川": {
        "url": "https://weathernews.jp/onebox/35.359818/138.977710/",
        "hp_url": "http://www.sukawa.ne.jp/",
        "search_name": "須川フィッシングパーク",
        "tel": "0550-75-3077",
        "aliases": ["須川", "須川フィッシングパーク", "須川FP", "すがわ"]
    },
    "アルクス焼津": {
        "url": "https://weathernews.jp/onebox/34.789110/138.294771/",
        "hp_url": "http://www.arcus-pond.com/",
        "search_name": "アルクスポンド焼津",
        "tel": "054-622-7102",
        "aliases": ["アルクス焼津", "アルクスポンド焼津", "あるくすやいづ", "あるくす", "焼津", "アルクスポンド", "やいづ"]
    },
    "浜名湖": {
        "url": "https://weathernews.jp/onebox/34.712749/137.629457/",
        "hp_url": "http://www.hamanako-fr.com/",
        "search_name": "浜名湖フィッシングリゾート",
        "tel": "053-592-2221",
        "aliases": ["浜名湖", "浜名湖フィッシングリゾート", "浜名湖FR", "はまなこ"]
    },

    # --- 栃木県 ---
    "キングフィッシャー": {
        "url": "https://weathernews.jp/onebox/36.907054/140.078650/",
        "hp_url": "https://kingfisher-jp.com/",
        "search_name": "キングフィッシャー 大田原",
        "tel": "0287-23-1253",
        "aliases": ["キングフィッシャー", "キング", "キングフィッシャ", "きんぐふぃっしゃー"]
    },
    "みどり": {
        "url": "https://weathernews.jp/onebox/36.834975/140.002410/",
        "hp_url": "http://www.nasu-net.or.jp/~midorifi/",
        "search_name": "みどりフィッシングエリア",
        "tel": "0287-28-3334",
        "aliases": ["みどり", "みどりフィッシングエリア", "みどりFA"]
    },
    "那須高原": {
        "url": "https://weathernews.jp/onebox/37.001929/140.104991/",
        "hp_url": "http://lure-f.jp/",
        "search_name": "那須高原ルアーフィールド",
        "tel": "0287-78-1005",
        "aliases": ["那須高原", "那須高原ルアーフィールド", "那須高原LF", "なすこうげん"]
    },
    "尚仁沢": {
        "url": "https://weathernews.jp/onebox/37.001929/140.104991/",
        "hp_url": "http://www.shojinzawa.com/",
        "search_name": "尚仁沢アウトドアフィールド",
        "tel": "0287-41-0051",
        "aliases": ["尚仁沢", "尚仁沢アウトドアフィールド", "尚仁沢AF", "しょうじんざわ"]
    },
    "つり天国": {
        "url": "https://weathernews.jp/onebox/37.073444/140.044452/",
        "hp_url": "http://www.tsuritengoku.com/",
        "search_name": "つり天国 那須",
        "tel": "0287-64-4286",
        "aliases": ["つり天国", "ツリテンゴク", "つりてんごく"]
    },
    "関根養魚場": {
        "url": "https://weathernews.jp/onebox/36.851308/139.979065/",
        "hp_url": "http://sekine-fish.com/",
        "search_name": "関根養魚場",
        "tel": "0287-35-2630",
        "aliases": ["関根養魚場", "関根", "せきね", "せきねようぎょじょう"]
    },
    "408": {
        "url": "https://weathernews.jp/onebox/36.763055/139.858269/",
        "hp_url": "https://408club.com/index.html",
        "search_name": "408Club",
        "tel": "0287-43-0408",
        "aliases": ["408", "408クラブ", "408club", "よんまるはち"]
    },
    "308": {
        "url": "https://weathernews.jp/onebox/36.824828/139.896229/",
        "hp_url": "http://408club.com/308/index.html",
        "search_name": "308Club",
        "tel": "0287-43-0308",
        "aliases": ["308", "308クラブ", "308club", "さんまるはち"]
    },
    "蛇尾川": {
        "url": "https://weathernews.jp/onebox/36.981351/139.901534/",
        "hp_url": "https://www.facebook.com/472959680156166/",
        "search_name": "蛇尾川フィッシングパーク",
        "tel": "0287-32-2212",
        "aliases": ["蛇尾川", "蛇尾川フィッシングパーク", "さびがわ"]
    },
    "レイクウッド": {
        "url": "https://weathernews.jp/onebox/36.611334/139.666579/",
        "hp_url": "http://lakewoodresort.info/",
        "search_name": "レイクウッドリゾート 鹿沼",
        "tel": "0289-75-1008",
        "aliases": ["レイクウッド", "レイクウッドリゾート", "れいくうっど"]
    },
    "なら山沼": {
        "url": "https://weathernews.jp/onebox/36.373741/139.802713/",
        "hp_url": "http://www.shimotsuga-fc.org/index.html",
        "search_name": "なら山沼漁場",
        "tel": "0285-25-4350",
        "aliases": ["なら山沼", "なら山沼漁場", "ならやま", "なら山", "ならやまぬま", "ならやま沼"]
    },
    "大芦川": {
        "url": "https://weathernews.jp/onebox/36.590732/139.693652/",
        "hp_url": "http://park10.wakwak.com/~field-village/",
        "search_name": "大芦川 F&C フィールドビレッジ",
        "tel": "0289-74-7222",
        "aliases": ["大芦川", "大芦川F&C", "おおあしがわ"]
    },
    "加賀": {
        "url": "https://weathernews.jp/onebox/36.388609/139.537247/",
        "hp_url": "http://www.kaga-fa.co.jp/",
        "search_name": "加賀フィッシングエリア",
        "tel": "0283-24-1513",
        "aliases": ["加賀", "加賀フィッシングエリア", "加賀FA", "かが"]
    },
    "発光路": {
        "url": "https://weathernews.jp/onebox/36.580281/139.532829/",
        "hp_url": "https://www.hokkoji.com/",
        "search_name": "発光路の森ファアルクス",
        "tel": "0289-85-3503",
        "aliases": ["発光路", "発光路の森", "ほっこうじ", "はっこうじ", "発光時", "発酵時"]
    },
    "上永野": {
        "url": "https://weathernews.jp/onebox/36.511884/139.573442/",
        "hp_url": "https://kaminagano-fishing.com/",
        "search_name": "フィッシングリゾート上永野",
        "tel": "0289-84-0335",
        "aliases": ["上永野", "上永野FR", "かみながの"]
    },
    "柏倉": {
        "url": "https://weathernews.jp/onebox/36.398276/139.660428/",
        "hp_url": "http://kashiwagurafishingpk.g3.xrea.com/",
        "search_name": "柏倉フィッシングパーク",
        "tel": "0282-23-6622",
        "aliases": ["柏倉", "柏倉FP", "かしわぐら"]
    },
    "遊水園": {
        "url": "https://weathernews.jp/onebox/36.342013/139.863541/",
        "hp_url": "http://meiseikousan.jp/oyamawaterpark/",
        "search_name": "Oyama Water Park 遊水園",
        "tel": "0285-38-8255",
        "aliases": ["遊水園", "OyamaWaterPark遊水園", "ゆうすいえん"]
    },
    "アルクス宇都宮": {
        "url": "https://weathernews.jp/onebox/36.566488/139.960060/",
        "hp_url": "http://www.arcus-pond.com/",
        "search_name": "アルクスポンド宇都宮",
        "tel": "028-652-3210",
        "aliases": ["アルクス宇都宮", "アルクスポンド宇都宮", "あるくすうつのみや", "あるくす", "アルクスポンド", "うつのみや"]
    },
    "エリア21": {
        "url": "https://weathernews.jp/onebox/36.496150/139.899522/",
        "hp_url": "http://www.area21.jp/",
        "search_name": "エリア21 宇都宮",
        "tel": "028-656-1188",
        "aliases": ["エリア21", "えりあ21"]
    },
    "ベアーズパーク": {
        "url": "https://weathernews.jp/onebox/36.513221/139.956989/",
        "hp_url": "https://bearspark.jp/",
        "search_name": "ベアーズパーク宇都宮",
        "tel": "028-656-2580",
        "aliases": ["ベアーズパーク", "増井養魚場", "べあーずぱーく"]
    },
    "鬼怒川": {
        "url": "https://weathernews.jp/onebox/36.617621/139.937106/",
        "hp_url": "http://kinugawa-fa.com/",
        "search_name": "鬼怒川フィッシングエリア",
        "tel": "028-672-1815",
        "aliases": ["鬼怒川", "鬼怒川フィッシングエリア", "鬼怒川FA", "きぬがわ"]
    },
    "名草": {
        "url": "https://weathernews.jp/onebox/36.418930/139.466355/",
        "hp_url": "https://ja-jp.facebook.com/nagusaturibori",
        "search_name": "名草釣堀",
        "tel": "0284-36-2480",
        "aliases": ["名草", "名草釣堀", "なぐさ"]
    },

    # --- 千葉県 ---
    "座間": {
        "url": "https://weathernews.jp/onebox/35.843581/140.010676/",
        "hp_url": "http://zamayougyo.com/",
        "search_name": "座間養魚場",
        "tel": "04-7192-1080",
        "aliases": ["座間", "座間養魚場", "ざま", "ざまようぎょじょう"]
    },
    "ジョイバレー": {
        "url": "https://weathernews.jp/onebox/35.744779/140.417401/",
        "hp_url": "http://www.joyvalley.co.jp/",
        "search_name": "ジョイバレー 成田",
        "tel": "0479-78-1840",
        "aliases": ["ジョイバレー", "じょいばれー", "ジョイバ"]
    },
    "ウォルトン": {
        "url": "https://weathernews.jp/onebox/35.863326/140.290525/",
        "hp_url": "https://www.waltongarden.net/",
        "search_name": "ウォルトンガーデン",
        "tel": "0476-37-3315",
        "aliases": ["ウォルトン", "ウォルトンガーデン", "うぉるとん"]
    },
    "NOIKE": {
        "url": "https://weathernews.jp/onebox/35.576969/140.234786/",
        "hp_url": "https://troutpond1089.com/",
        "search_name": "trout pond NOIKE",
        "tel": "043-228-8283",
        "aliases": ["NOIKE", "ノイケ", "のいけ"]
    },
    "パラダイス": {
        "url": "https://weathernews.jp/onebox/35.653330/140.338663/",
        "hp_url": "http://tsuripara.planet.bindcloud.jp/",
        "search_name": "釣りパラダイス 山武",
        "tel": "043-445-1216",
        "aliases": ["パラダイス", "釣りパラダイス", "つりぱら"]
    },

    # --- 埼玉県 ---
    "長瀞": {
        "url": "https://weathernews.jp/onebox/36.084376/139.104604/",
        "hp_url": "https://waterpark.jp/fishing/",
        "search_name": "ウォーターパーク長瀞",
        "tel": "0494-66-0312",
        "aliases": ["長瀞", "WP長瀞", "ウォーターパーク長瀞", "ながとろ"]
    },
    "彩の国": {
        "url": "https://weathernews.jp/onebox/35.992469/139.473372/",
        "hp_url": "https://fs-sainokuni.jp/",
        "search_name": "フィッシングフィールド彩の国",
        "tel": "049-297-7815",
        "aliases": ["彩の国", "FF彩の国", "さいのくに"]
    },
    "朝霞Ｇ": {
        "url": "https://weathernews.jp/onebox/35.813481/139.604736/",
        "hp_url": "http://www.asaka-garden.com/",
        "search_name": "朝霞ガーデン",
        "tel": "048-456-0260",
        "aliases": ["朝霞Ｇ", "朝霞", "朝霞ガーデン", "アサカガーデン", "ガーデン", "あさか", "アサカ", "あさかガーデン"]
    },
    "しらこばと": {
        "url": "https://weathernews.jp/onebox/35.917970/139.752203/",
        "hp_url": "https://www.parks.or.jp/shirakobatosuijo/guide/003/003811.html",
        "search_name": "しらこばと水上公園",
        "tel": "048-977-5111",
        "aliases": ["しらこばと", "しらこばと水上公園"]
    },
    "川越パーク": {
        "url": "https://weathernews.jp/onebox/35.907152/139.444046/",
        "hp_url": "https://www.parks.or.jp/kawagoesuijo/",
        "search_name": "川越水上公園",
        "tel": "049-241-2241",
        "aliases": ["川越パーク", "川越", "川越水上公園", "かわごえ"]
    },
    "加須はなさき": {
        "url": "https://weathernews.jp/onebox/36.096192/139.636601/",
        "hp_url": "https://www.parks.or.jp/kazohanasaki/guide/000/000031.html",
        "search_name": "加須はなさき水上公園",
        "tel": "0480-65-7155",
        "aliases": ["加須はなさき", "はなさき", "はなさき公園"]
    },
    "中里": {
        "url": "https://weathernews.jp/onebox/36.163896/139.176567/",
        "hp_url": "http://fish104.in.coocan.jp/",
        "search_name": "中里フィッシングクラブ",
        "tel": "0495-76-1120",
        "aliases": ["中里", "中里FC", "なかざと"]
    },
    "伊古の里": {
        "url": "https://weathernews.jp/onebox/36.071547/139.339037/",
        "hp_url": "http://www.ikonosato.jp/",
        "search_name": "伊古の里フィッシングパーク",
        "tel": "0493-57-0505",
        "aliases": ["伊古", "伊古の里", "いこのさと", "伊古の里フィッシングパーク"]
    },

    # --- 神奈川県・東京都 ---
    "足柄": {
        "url": "https://weathernews.jp/onebox/35.319275/139.042723/",
        "hp_url": "http://www.ashigara-ca.com/aca/",
        "search_name": "足柄キャスティングエリア",
        "tel": "0465-73-2030",
        "aliases": ["足柄", "足柄CA", "あしがら"]
    },
    "中津川": {
        "url": "https://weathernews.jp/onebox/35.521698/139.285609/",
        "hp_url": "http://www.nakatugawa-gyokyou.jp/",
        "search_name": "フィッシングフィールド中津川",
        "tel": "046-281-5421",
        "aliases": ["中津川", "FF中津川", "なかつがわ", "なかつ", "中津"]
    },
    "早戸川": {
        "url": "https://weathernews.jp/onebox/35.543063/139.216090/",
        "hp_url": "http://www.hayatogawa.com/",
        "search_name": "リヴァスポット早戸",
        "tel": "042-785-0774",
        "aliases": ["早戸川", "リヴァスポット早戸", "はやとがわ"]
    },
    "王禅寺": {
        "url": "https://weathernews.jp/onebox/35.587020/139.524309/",
        "hp_url": "https://www.berrypark.jp/ozenji/",
        "search_name": "BerryPark in 王禅寺",
        "tel": "044-959-0037",
        "aliases": ["王禅寺", "ベリーパーク in 王禅寺", "おうぜんじ", "王禅寺ベリーパーク", "寺", "てら"]
    },
    "開成": {
        "url": "https://weathernews.jp/onebox/35.334342/139.130344/",
        "hp_url": "https://kaisei.forest-springs.com/",
        "search_name": "開成水辺フォレストスプリングス",
        "tel": "0465-85-2020",
        "aliases": ["開成", "開成水辺フォレストスプリングス", "開成FS", "かいせい", "フォレストスプリングス"]
    },
    "浅川国際": {
        "url": "https://weathernews.jp/onebox/35.641903/139.231262/",
        "hp_url": "http://www5c.biglobe.ne.jp/~fly-lure/",
        "search_name": "浅川国際マス釣り場",
        "tel": "042-661-2228",
        "aliases": ["浅川国際", "浅川", "浅川国際マス釣り場", "あさかわ", "あさかわこくさい", "あさこく", "アサコク"]
    },

    # --- 山梨県・長野県 ---
    "鹿留": {
        "url": "https://weathernews.jp/onebox/35.512350/138.887160/",
        "hp_url": "http://www.sisidome.jp/",
        "search_name": "ベリーパーク in 鹿留",
        "tel": "0554-43-0082",
        "aliases": ["鹿留", "シシドメ", "ししどめ", "ベリーパーク"]
    },
    "小菅": {
        "url": "https://weathernews.jp/onebox/35.760330/138.940529/",
        "hp_url": "http://kosuge-tg.com/",
        "search_name": "小菅トラウトガーデン",
        "tel": "0428-87-0373",
        "aliases": ["小菅", "小菅TG", "こすげ"]
    },
    "シルフ": {
        "url": "https://weathernews.jp/onebox/35.778458/138.316489/",
        "hp_url": "https://shylph.boy.jp/",
        "search_name": "白州トラウトフィッシングエリア",
        "tel": "0551-35-4308",
        "aliases": ["シルフ", "Shylph", "しるふ"]
    },
    "JF in Tsugane": {
        "url": "https://weathernews.jp/onebox/35.866755/138.451406/",
        "hp_url": "http://www6.nns.ne.jp/~joy-field/index.html",
        "search_name": "ジョイフィールド in Tsugane",
        "tel": "0551-20-7888",
        "aliases": ["JF in Tsugane", "Tsugane", "ジョイフィールド", "つがね", "ツガネ", "じょいふぃーるど"]
    },
    "竜華池": {
        "url": "https://weathernews.jp/onebox/35.681978/138.576164/",
        "hp_url": "https://fishingmarketbear.wixsite.com/ryugaike",
        "search_name": "フィッシングパーク竜華池",
        "tel": "055-252-0938",
        "aliases": ["竜華池", "りゅうがいけ"]
    },
    "平谷湖": {
        "url": "https://weathernews.jp/onebox/35.332243/137.632213/",
        "hp_url": "https://hirayako.com/",
        "search_name": "平谷湖フィッシングスポット",
        "tel": "0265-48-1127",
        "aliases": ["平谷湖", "平谷湖フィッシングスポット", "ひらやこ"]
    },
    "ハーブの里": {
        "url": "https://weathernews.jp/onebox/36.403436/137.890526/",
        "hp_url": "https://herbfa1995.kikirara.jp/",
        "search_name": "ハーブの里フィッシングエリア",
        "tel": "0261-62-6322",
        "aliases": ["ハーブの里", "ハーブ", "はーぶ"]
    },
    "ニレ池": {
        "url": "https://weathernews.jp/onebox/36.712669/137.845826/",
        "hp_url": "http://www.nireike.com/",
        "search_name": "白馬八方ニレ池フィッシングセンター",
        "tel": "0261-72-5086",
        "aliases": ["ニレ池", "にれいけ"]
    },
    "鹿島槍": {
        "url": "https://weathernews.jp/onebox/36.548940/137.809757/",
        "hp_url": "https://www.kashimayari-garden.com/",
        "search_name": "鹿島槍ガーデン",
        "tel": "0261-22-2253",
        "aliases": ["鹿島槍", "鹿島槍ガーデン", "かしまやり"]
    },
    "つきの池": {
        "url": "https://weathernews.jp/onebox/36.011582/138.197271/",
        "hp_url": "http://www.tsukinoike.jp/",
        "search_name": "槻の池フィッシングエリア",
        "tel": "0266-76-2280",
        "aliases": ["つきの池", "槻の池", "槻の池フィッシングエリア"]
    },
    "あずみ野": {
        "url": "https://weathernews.jp/onebox/36.337699/137.885455/",
        "hp_url": "http://www7b.biglobe.ne.jp/~azuminoturibori/",
        "search_name": "あずみ野フィッシングセンター",
        "tel": "0263-82-8280",
        "aliases": ["あずみ野", "あずみ野FC", "あずみの"]
    },

    # --- 群馬県 ---
    "川場": {
        "url": "https://weathernews.jp/onebox/36.690767/139.121662/",
        "hp_url": "http://www.kawaba-fp.jp/",
        "search_name": "川場フィッシングプラザ",
        "tel": "0278-52-3200",
        "aliases": ["川場", "川場FP", "かわば"]
    },
    "川場キングダム": {
        "url": "https://weathernews.jp/onebox/36.754213/139.142256/",
        "hp_url": "http://kawaba-kingdomfishing.com/",
        "search_name": "川場キングダムフィッシング",
        "tel": "0278-52-2002",
        "aliases": ["川場キングダム", "キングダム", "かわばきんぐだむ"]
    },
    "おくとね": {
        "url": "https://weathernews.jp/onebox/36.663005/139.163750/",
        "hp_url": "http://www7.wind.ne.jp/okutone/",
        "search_name": "おくとねフィッシングパーク",
        "tel": "0278-53-3802",
        "aliases": ["おくとね", "おくとねFP"]
    },
    "イワナセンター": {
        "url": "https://weathernews.jp/onebox/36.610095/139.243740/",
        "hp_url": "http://www7.wind.ne.jp/okutone/",
        "search_name": "日本イワナセンター",
        "tel": "0278-54-8433",
        "aliases": ["イワナセンター", "日本イワナセンター", "いわなせんたー"]
    },
    "黒保根": {
        "url": "https://weathernews.jp/onebox/36.515041/139.252324/",
        "hp_url": "https://www.kurohone-fishing.com/",
        "search_name": "黒保根渓流フィッシング",
        "tel": "0277-96-2091",
        "aliases": ["黒保根", "くろほね"]
    },
    "迦葉山": {
        "url": "https://weathernews.jp/onebox/36.685419/139.071387/",
        "hp_url": "http://www.fp-berrys.net/",
        "search_name": "ベリーズ迦葉山",
        "tel": "0278-23-9333",
        "aliases": ["迦葉山", "ベリーズ迦葉山", "かしょうざん", "ベリーズ"]
    },
    "片品": {
        "url": "https://weathernews.jp/onebox/36.624564/139.046703/",
        "hp_url": "https://www.turinavi.info/gunma/katashinagawakokusai/",
        "search_name": "片品川国際マス釣り場",
        "tel": "0278-24-1188",
        "aliases": ["片品", "片品川国際", "かたしな"]
    },
    "中之沢": {
        "url": "https://weathernews.jp/onebox/36.492057/139.195293/",
        "hp_url": "http://gfc.sakura.ne.jp/index.htm",
        "search_name": "GFC中之沢",
        "tel": "027-283-3532",
        "aliases": ["中之沢", "GFC中之沢", "なかのさわ"]
    },
    "ＭＡＶ": {
        "url": "https://weathernews.jp/onebox/36.483735/139.188251/",
        "hp_url": "http://www.anglers-village.com/index2.html",
        "search_name": "宮城アングラーズヴィレッジ",
        "tel": "027-283-0035",
        "aliases": ["ＭＡＶ", "宮城", "宮城AV", "みやぎあんぐらーず", "まぶ", "マブ", "あんびれ", "アンビレ", "MAV", "mav"]
    },
    "大崎": {
        "url": "https://weathernews.jp/onebox/36.463209/139.164867/",
        "hp_url": "https://nijimasu.com/",
        "search_name": "大崎つりぼり",
        "tel": "027-283-2945",
        "aliases": ["大崎", "大崎つりぼり", "おおさき"]
    },
    "けん太": {
        "url": "https://weathernews.jp/onebox/36.386648/138.960021/",
        "hp_url": "http://www.tsurikichikenta.com/index.htm",
        "search_name": "釣りキチけん太",
        "tel": "027-371-3312",
        "aliases": ["けん太", "釣りキチけん太", "けんた"]
    },
    "フック": {
        "url": "https://weathernews.jp/onebox/36.457699/139.173191/",
        "hp_url": "https://aa-hook.jp/",
        "search_name": "アングラーズエリアHOOK",
        "tel": "027-283-0535",
        "aliases": ["フック", "HOOK", "ふっく"]
    },
    "赤久縄": {
        "url": "https://weathernews.jp/onebox/36.160894/138.895355/",
        "hp_url": "https://www.akaguna.net/",
        "search_name": "赤久縄",
        "tel": "0274-56-0230",
        "aliases": ["赤久縄", "あかぐな"]
    },
    "太田": {
        "url": "https://weathernews.jp/onebox/36.357774/139.330830/",
        "hp_url": "https://www.facebook.com/otafishingclub/",
        "search_name": "太田フィッシングクラブ",
        "tel": "0276-32-1230",
        "aliases": ["太田", "太田FC", "おおた"]
    },
    "東山道": {
        "url": "https://weathernews.jp/onebox/36.323047/139.280989/",
        "hp_url": "https://emrp-fishing.com/",
        "search_name": "東山道公園フィッシングエリア",
        "tel": "0276-56-1180",
        "aliases": ["東山道", "東山道FA", "とうさんどう"]
    },
    "榛名": {
        "url": "https://weathernews.jp/onebox/36.443570/138.898498/",
        "hp_url": "https://haruna-turibori.com/",
        "search_name": "榛名高原つり堀センター",
        "tel": "027-374-2228",
        "aliases": ["榛名", "榛名高原", "はるな"]
    },

    # --- 茨城県 ---
    "水戸南": {
        "url": "https://weathernews.jp/onebox/36.326377/140.501362/",
        "hp_url": "http://www.mitominami-fa.jp/index.html",
        "search_name": "水戸南フィッシングエリア",
        "tel": "029-246-1233",
        "aliases": ["水戸南", "水戸南FA", "みとみなみ"]
    },
    "高萩": {
        "url": "https://weathernews.jp/onebox/36.788035/140.577243/",
        "hp_url": "https://takahagifureainosato.web.fc2.com/",
        "search_name": "高萩ふれあいの里フィッシングエリア",
        "tel": "0293-24-1888",
        "aliases": ["高萩", "高萩ふれあいの里", "たかはぎ"]
    },
    "つくば園": {
        "url": "https://weathernews.jp/onebox/36.224122/140.144261/",
        "hp_url": "http://tsukuba-en.jp/",
        "search_name": "フィッシングパークつくば園",
        "tel": "0299-43-6111",
        "aliases": ["つくば園", "つくばえん"]
    },
    "Ｊ": {
        "url": "https://weathernews.jp/onebox/36.081494/140.164360/",
        "hp_url": "https://sites.google.com/view/fishing-area-j/",
        "search_name": "フィッシングエリアJ",
        "tel": "029-842-1698",
        "aliases": ["Ｊ", "J", "FAJ", "フィッシングエリアJ", "ふぃっしんぐえりあじぇい", "じぇー", "じぇい", "ジェー"]
    },
    "ユザキ": {
        "url": "https://weathernews.jp/onebox/36.314550/140.335285/",
        "hp_url": "https://yuzakiko.com/",
        "search_name": "レイクユザキ",
        "tel": "0296-77-8500",
        "aliases": ["ユザキ", "レイクユザキ", "ゆざき"]
    },
    "笠間": {
        "url": "https://weathernews.jp/onebox/36.412866/140.208145/",
        "hp_url": "http://www.leisure-park-kasama.jp/",
        "search_name": "レジャーパーク笠間",
        "tel": "0296-72-8888",
        "aliases": ["笠間", "LP笠間", "かさま"]
    },
    "DoDoo": {
        "url": "https://weathernews.jp/onebox/36.187994/140.216734/",
        "hp_url": "http://www.fishing-dodoo.com/",
        "search_name": "フィッシングDoDoo",
        "tel": "0299-59-7052",
        "aliases": ["DoDoo", "ドゥドゥー", "どぅどぅー"]
    },
    "若栗": {
        "url": "https://weathernews.jp/onebox/36.779644/140.633185/",
        "hp_url": "http://wakagurinomori.ina-ka.com/",
        "search_name": "若栗フィッシングの森",
        "tel": "0293-23-3882",
        "aliases": ["若栗", "若栗フィッシングの森", "わかぐり"]
    },
    "ミッドクリーク": {
        "url": "https://weathernews.jp/onebox/36.192975/140.164058/",
        "hp_url": "http://midcreek.jp/",
        "search_name": "ミッドクリークフィッシングエリア",
        "tel": "0299-42-4578",
        "aliases": ["ミッドクリーク", "みっどくりーく"]
    },

    # --- 東北・東海・関西 ---
    "GP不忘": {
        "url": "https://weathernews.jp/onebox/38.042491/140.554478/",
        "hp_url": "http://www.fubou.jp/",
        "search_name": "グリーンパーク不忘",
        "tel": "0224-24-8131",
        "aliases": ["GP不忘", "不忘", "グリーンパーク不忘", "グリーンパーク", "ぐりーんぱーく", "ふぼう", "フボウ"]
    },
    "白河": {
        "url": "https://weathernews.jp/onebox/37.127955/140.081827/",
        "hp_url": "https://shirakawa.forest-springs.com/",
        "search_name": "白河フォレストスプリングス",
        "tel": "0248-25-3535",
        "aliases": ["白河", "白河フォレストスプリングス", "白河FS", "しらかわ"]
    },
    "ほのぼの": {
        "url": "https://weathernews.jp/onebox/36.837687/140.472433/",
        "hp_url": "http://honobono.travel.coocan.jp/",
        "search_name": "ほのぼのフィッシングエリア",
        "tel": "0247-46-3200",
        "aliases": ["ほのぼの", "ほのぼのプール"]
    },
    "WaDoNa": {
        "url": "https://weathernews.jp/onebox/36.877372/140.540954/",
        "hp_url": "https://wadona.work/",
        "search_name": "WaDoNa 釣り場",
        "tel": "090-3121-6677",
        "aliases": ["WaDoNa", "ワドナ", "わどな"]
    },
    "鶴沼川": {
        "url": "https://weathernews.jp/onebox/37.255460/139.872256/",
        "hp_url": "https://aizuiwanacenter.com/",
        "search_name": "鶴沼川フィッシングパーク",
        "tel": "0241-67-2708",
        "aliases": ["鶴沼川", "つるぬまがわ", "鶴沼"]
    },
    "オーパ": {
        "url": "https://weathernews.jp/onebox/37.314342/140.449245/",
        "hp_url": "https://welcomeohpa.com/",
        "search_name": "ウエルカムオーパ",
        "tel": "024-954-2007",
        "aliases": ["オーパ", "ウエルカムオーパ", "おーぱ"]
    },
    "あいづ": {
        "url": "https://weathernews.jp/onebox/37.204977/139.729681/",
        "hp_url": "https://aizufishing.jp/",
        "search_name": "あいづフィッシングエリア",
        "tel": "0241-64-2101",
        "aliases": ["あいづ", "あいづFA"]
    },
    "上浜": {
        "url": "https://weathernews.jp/onebox/39.142616/139.945938/",
        "hp_url": "http://kamihama.web.fc2.com/",
        "search_name": "上浜釣り場",
        "tel": "0184-38-3488",
        "aliases": ["上浜", "上浜釣り場", "かみはま"]
    },
    "GOZU": {
        "url": "https://weathernews.jp/onebox/37.819471/139.238518/",
        "hp_url": "http://www.gozu-fp.jp/",
        "search_name": "五頭フィッシングパーク",
        "tel": "0250-63-0051",
        "aliases": ["GOZU", "ごず", "五頭", "ごづ", "五頭FP", "五頭フィッシングパーク", "gozu"]
    },
    "FCE瑞浪": {
        "url": "https://weathernews.jp/onebox/35.433516/137.295266/",
        "hp_url": "https://www.fishing-autocamp-mizunami.com/",
        "search_name": "フィッシングキャンプエリア瑞浪",
        "tel": "0572-68-1212",
        "aliases": ["FCE瑞浪", "瑞浪", "FC瑞浪", "みずなみ", "フィッシングキャンプエリアミズナミ", "フィッシングキャンプエリア瑞浪"]
    },
    "３９": {
        "url": "https://weathernews.jp/onebox/35.187504/136.457803/",
        "hp_url": "https://go-sanctuary.com/",
        "search_name": "フィッシングサンクチュアリ",
        "tel": "0594-46-8820",
        "aliases": ["３９", "サンクチュアリ", "サンク", "さんくちゅあり", "39"]
    },
    "醒井": {
        "url": "https://weathernews.jp/onebox/35.303671/136.349914/",
        "hp_url": "http://samegai.siga.jp/",
        "search_name": "醒井養鱒場",
        "tel": "0749-54-0301",
        "aliases": ["醒井", "醒井養鱒場", "さめがい"]
    },
    "高島の泉": {
        "url": "https://weathernews.jp/onebox/35.348308/136.052288/",
        "hp_url": "https://www.takashimanoizumi.com/",
        "search_name": "高島の泉",
        "tel": "0740-25-3790",
        "aliases": ["高島の泉", "高島", "たかしまのいずみ", "たかしま"]
    },
    "千早川": {
        "url": "https://weathernews.jp/onebox/34.417118/135.647482/",
        "hp_url": "http://chihayagawa.jp/",
        "search_name": "千早川マス釣り場",
        "tel": "0721-74-0116",
        "aliases": ["千早川", "千早川マス釣り場", "ちはやがわ"]
    }
}

# 各地域カード内での県別ブロック＆色分けデータ
COLOR_GROUPS = [
    {
        "title": "📍 静岡・神奈川・東京・千葉",
        "header_bg": "#0066cc",
        "sub_groups": [
            {"bg": "#e6f0fa", "spots": ["東山湖", "すその", "須川", "アルクス焼津", "浜名湖"]},
            {"bg": "#d4e6f1", "spots": ["足柄", "中津川", "早戸川", "王禅寺", "開成", "浅川国際"]},
            {"bg": "#cce5ff", "spots": ["座間", "ジョイバレー", "ウォルトン", "NOIKE", "パラダイス"]}
        ]
    },
    {
        "title": "📍 埼玉・群馬",
        "header_bg": "#2e7d32",
        "sub_groups": [
            {"bg": "#e8f5e9", "spots": ["長瀞", "彩の国", "朝霞Ｇ", "しらこばと", "川越パーク", "加須はなさき", "中里", "伊古の里"]},
            {"bg": "#c8e6c9", "spots": ["川場", "川場キングダム", "おくとね", "イワナセンター", "黒保根", "迦葉山", "片品", "中之沢", "ＭＡＶ", "大崎", "けん太", "フック", "赤久縄", "太田", "東山道", "榛名"]}
        ]
    },
    {
        "title": "📍 栃木・茨城",
        "header_bg": "#e65100",
        "sub_groups": [
            {"bg": "#fff3e0", "spots": ["キングフィッシャー", "みどり", "那須高原", "尚仁沢", "つり天国", "関根養魚場", "408", "308", "蛇尾川", "レイクウッド", "なら山沼", "大芦川", "加賀", "発光路", "上永野", "柏倉", "遊水園", "アルクス宇都宮", "エリア21", "ベアーズパーク", "鬼怒川", "名草"]},
            {"bg": "#ffe0b2", "spots": ["水戸南", "高萩", "つくば園", "Ｊ", "ユザキ", "笠間", "DoDoo", "若栗", "ミッドクリーク"]}
        ]
    },
    {
        "title": "📍 甲信・東北・東海・関西",
        "header_bg": "#6a1b9a",
        "sub_groups": [
            {"bg": "#f3e5f5", "spots": ["鹿留", "小菅", "シルフ", "JF in Tsugane", "竜華池", "平谷湖", "ハーブの里", "ニレ池", "鹿島槍", "つきの池", "あずみ野"]},
            {"bg": "#e1bee7", "spots": ["GP不忘", "白河", "ほのぼの", "WaDoNa", "鶴沼川", "オーパ", "あいづ", "上浜", "GOZU"]},
            {"bg": "#d1c4e9", "spots": ["FCE瑞浪", "３９", "醒井", "高島の泉", "千早川"]}
        ]
    }
]

def clean_url(url_str):
    if not url_str:
        return ""
    cleaned = url_str.strip().replace(" ", "").replace("\t", "")
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        return ""
    return cleaned

def get_spot_details(spot_key):
    data = SPOT_WEATHER_DATA.get(spot_key)
    if not data:
        return spot_key, None, "", "", ""
    map_url = f"https://www.google.com/maps/search/?api=1&query={quote(data.get('search_name', spot_key))}"
    hp_url = clean_url(data.get("hp_url", ""))
    return spot_key, data["url"], hp_url, map_url, data.get("tel", "")

def build_delete_confirm_message(spot_name, source):
    execute_action = f"fav_del_execute_and_{source}"
    cancel_action = f"fav_del_cancel_and_{source}"
    
    bubble = {
        "type": "bubble",
        "size": "kilo",
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
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "15px",
            "contents": [
                {"type": "text", "text": "⚠️ 全て削除の確認", "weight": "bold", "color": "#ff0000", "size": "md"},
                {"type": "text", "text": "登録されているすべてのお気に入りを削除しますか？\n（この操作は元に戻せません）", "wrap": True, "size": "sm", "color": "#333333"}
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

def build_settings_flex_message(fav_list):
    rows = []
    if not fav_list:
        rows.append({
            "type": "text",
            "text": "現在お気に入りは登録されていません。\n\n釣り場を検索し、天気カード内の「⭐️ 登録」ボタンを押すだけで追加できます！",
            "wrap": True, "size": "sm", "color": "#555555"
        })
    else:
        for spot in fav_list:
            rows.append({
                "type": "box", "layout": "horizontal", "margin": "md", "alignItems": "center",
                "contents": [
                    {"type": "text", "text": f"{spot}", "size": "sm", "weight": "bold", "flex": 4, "color": "#333333", "wrap": True},
                    {
                        "type": "button",
                        "action": {"type": "postback", "label": "⬆️", "data": f"action=fav_up&spot={spot}"},
                        "style": "secondary", "flex": 2, "margin": "xs"
                    },
                    {
                        "type": "button",
                        "action": {"type": "postback", "label": "⬇️", "data": f"action=fav_down&spot={spot}"},
                        "style": "secondary", "flex": 2, "margin": "xs"
                    },
                    {
                        "type": "button",
                        "action": {"type": "postback", "label": "🗑️", "data": f"action=fav_del_confirm_and_settings&spot={spot}"},
                        "style": "secondary", "color": "#ffe6e6", "flex": 2, "margin": "xs"
                    }
                ]
            })

        rows.append({"type": "separator", "margin": "md"})
        
        rows.append({
            "type": "box",
            "layout": "horizontal",
            "margin": "md",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list", "displayText": "📋 一覧"},
                    "style": "secondary",
                    "color": "#fff59d",
                    "flex": 1
                },
                {
                    "type": "button",
                    "action": {"type": "postback", "label": "🗑️ 全て削除", "data": "action=fav_del_all_confirm"},
                    "style": "primary",
                    "color": "#e53935",
                    "flex": 1
                }
            ]
        })

    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#d4af37", "paddingAll": "10px",
            "contents": [
                {"type": "text", "text": f"⚙️ お気に入り並び替え ({len(fav_list)}/{MAX_FAVORITES}件)", "color": "#ffffff", "weight": "bold", "size": "md"}
            ]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "10px",
            "contents": rows
        }
    }
    return FlexSendMessage(alt_text="お気に入り管理パネル", contents=bubble)

def build_spot_list_carousel_horizontal(user_id=None):
    bubbles = []
    fav_list = []

    if user_id:
        _, favorites = get_user_setting(user_id)
        fav_list = [s for s in favorites.split(',') if s]
        
        fav_rows = []
        if not fav_list:
            fav_rows.append({
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#fffde7",
                "cornerRadius": "md",
                "paddingAll": "md",
                "margin": "md",
                "contents": [
                    {
                        "type": "text",
                        "text": "現在お気に入りは登録されていません。\n右へスワイプして釣り場を探し、「⭐️ 登録」ボタンを押すか、テキストで「追加 東山湖」と送信して登録してください。",
                        "wrap": True,
                        "size": "sm",
                        "color": "#555555"
                    }
                ]
            })
        else:
            for i in range(0, len(fav_list), 2):
                pair = fav_list[i:i+2]
                row_buttons = []
                for spot in pair:
                    row_buttons.append({
                        "type": "button",
                        "style": "secondary",
                        "color": "#fff59d",  
                        "margin": "xs",
                        "height": "sm",
                        "action": {"type": "postback", "label": spot, "data": f"w={spot}"}
                    })
                if len(pair) == 1:
                    row_buttons.append({"type": "filler"})
                    
                row_box = {"type": "box", "layout": "horizontal", "contents": row_buttons}
                if i > 0 and i % 10 == 0:
                    row_box["margin"] = "lg"
                    
                fav_rows.append(row_box)

        fav_rows.append({"type": "separator", "margin": "lg" if fav_list else "md", "color": "#cccccc"})
        fav_rows.append({
            "type": "button",
            "action": {"type": "postback", "label": "⚙️ 設定（並び替え・削除）", "data": "action=show_settings", "displayText": "⚙️ 設定"},
            "style": "secondary",
            "color": "#f8f9fa",
            "height": "sm",
            "margin": "md"
        })

        fav_bubble = {
            "type": "bubble",
            "size": "giga",
            "header": {
                "type": "box", "layout": "horizontal", "backgroundColor": "#d4af37", "paddingAll": "10px", "alignItems": "center",
                "contents": [
                    {"type": "text", "text": "⭐ お気に入り釣り場", "color": "#ffffff", "weight": "bold", "size": "md", "flex": 1},
                    {"type": "text", "text": "(最大30箇所)", "color": "#eeeeee", "size": "xs", "align": "end", "flex": 0}
                ]
            },
            "body": {"type": "box", "layout": "vertical", "paddingAll": "6px", "contents": fav_rows}
        }
        bubbles.append(fav_bubble)

    for group in COLOR_GROUPS:
        rows = []
        for sg in group["sub_groups"]:
            spots = sg["spots"]
            btn_bg = sg["bg"]
            for i in range(0, len(spots), 2):
                pair = spots[i:i+2]
                row_buttons = []
                for spot in pair:
                    label_text = f"★ {spot}" if spot in fav_list else spot
                    row_buttons.append({
                        "type": "button",
                        "style": "secondary",
                        "color": btn_bg,
                        "margin": "xs",
                        "height": "sm",
                        "action": {"type": "postback", "label": label_text, "data": f"w={spot}"}
                    })
                if len(pair) == 1:
                    row_buttons.append({"type": "filler"})
                    
                rows.append({"type": "box", "layout": "horizontal", "contents": row_buttons})
            
        bubble = {
            "type": "bubble",
            "size": "giga",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": group["header_bg"], "paddingAll": "10px",
                "contents": [{"type": "text", "text": group["title"], "color": "#ffffff", "weight": "bold", "size": "md"}]
            },
            "body": {"type": "box", "layout": "vertical", "paddingAll": "6px", "contents": rows}
        }
        bubbles.append(bubble)

    # ガイドの復元
    guide_bubble = {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#888888", "paddingAll": "10px",
            "contents": [{"type": "text", "text": "📖 使い方ガイド", "color": "#ffffff", "weight": "bold", "size": "md"}]
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "15px",
            "contents": [
                {
                    "type": "box", "layout": "vertical", "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": "👇 基本の操作", "weight": "bold", "size": "sm", "color": "#333333"},
                        {"type": "text", "text": "・一覧のボタンをタップで天気予報を表示", "wrap": True, "size": "xs", "color": "#666666"}
                    ]
                },
                {"type": "separator", "margin": "md"},
                {
                    "type": "box", "layout": "vertical", "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": "💬 テキストコマンド", "weight": "bold", "size": "sm", "color": "#333333"},
                        {"type": "text", "text": "【まとめて追加】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"},
                        {"type": "text", "text": "例：「追加 東山湖 すその 足柄 座間 醒井」\n※釣り場と釣り場の名前の間にスペースを入れてください。", "wrap": True, "size": "xs", "color": "#666666"},
                        {"type": "text", "text": "【まとめて削除】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"},
                        {"type": "text", "text": "例：「削除 東山湖 すその 足柄」\n※追加と同じく、名前の間にスペースを入れて複数同時に解除できます。", "wrap": True, "size": "xs", "color": "#666666"},
                        {"type": "text", "text": "【設定】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"},
                        {"type": "text", "text": "「設定」と送信すると、並び替え・全削除パネルが出ます。", "wrap": True, "size": "xs", "color": "#666666"},
                        {"type": "text", "text": "【一覧（メニュー）の出し方】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"},
                        {"type": "text", "text": "「一覧」という言葉や、それ以外の適当な文字（「あ」「1」「a」など）を送信すると、この一覧表が表示されます。", "wrap": True, "size": "xs", "color": "#666666"}
                    ]
                }
            ]
        }
    }
    bubbles.append(guide_bubble)

    return FlexSendMessage(alt_text="釣り場一覧", contents={"type": "carousel", "contents": bubbles})


def get_cached_weather(spot_name):
    if not supabase: return None
    try:
        res = supabase.table('weather_cache').select('*').eq('spot_name', spot_name).execute()
        if res.data and len(res.data) > 0:
            row = res.data[0]
            updated_at_str = row.get('updated_at')
            if updated_at_str:
                try:
                    updated_time = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    if now - updated_time > timedelta(hours=1):
                        return None 
                except:
                    pass
            return row.get('weather_data')
        return None
    except Exception as e:
        print(f"[Cache GET Error] {e}")
        return None

def save_cached_weather(spot_name, weather_data):
    if not supabase: return
    try:
        supabase.table('weather_cache').upsert({
            'spot_name': spot_name,
            'weather_data': weather_data,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).execute()
    except Exception as e:
        print(f"[Cache SAVE Error] {e}")

def get_user_setting(user_id):
    if not supabase: return ('ウェザーニュース', '')
    try:
        res = supabase.table('user_settings').select('*').eq('user_id', user_id).execute()
        if res.data and len(res.data) > 0:
            row = res.data[0]
            favs = row.get('favorite_spots') or ''
            
            # 名称変更対応マップ（過去登録された古い名前を自動で新しい名前に変換）
            rename_map = {
                "五頭": "GOZU",
                "竜华池": "竜華池",
                "ハーブ": "ハーブの里",
                "サンクチュアリ": "３９",
                "高島": "高島の泉",
                "瑞浪": "FCE瑞浪",
                "槻の池": "つきの池",
                "川越": "川越パーク",
                "宮城": "ＭＡＶ",
                "浅川": "浅川国際",
                "関根": "関根養魚場",
                "FAJ": "Ｊ",
                "朝霞": "朝霞Ｇ",
                "不忘": "GP不忘"
            }
            
            raw_favs = [s.strip() for s in favs.split(',')]
            favs_list = []
            for s in raw_favs:
                if s in rename_map:
                    s = rename_map[s]
                # 削除された釣り場は除外する
                if s not in ["多摩湖", "いなプー"] and s:
                    favs_list.append(s)
                    
            return (row.get('weather_source', 'ウェザーニュース'), ','.join(favs_list))
        return ('ウェザーニュース', '')
    except Exception as e:
        print(f"[Supabase取得エラー] {e}")
        return ('ウェザーニュース', '')

def add_favorite_spots(user_id, spot_names):
    if not supabase: return False, [], ["DB接続未完了です。"]
    source, favorites = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    
    added = []
    errors = []
    for spot_name in spot_names:
        target_name = None
        for spot_key, data in SPOT_WEATHER_DATA.items():
            if spot_name.lower() == spot_key.lower() or spot_name.lower() in [a.lower() for a in data["aliases"]]:
                target_name = spot_key
                break
        
        if not target_name:
            errors.append(f"{spot_name}(不明)")
            continue
            
        if target_name in fav_list:
            errors.append(f"{target_name}(登録済)")
            continue
        if len(fav_list) >= MAX_FAVORITES:
            errors.append(f"{target_name}(上限{MAX_FAVORITES}件超過)")
            continue
            
        fav_list.append(target_name)
        added.append(target_name)
        
    if added:
        try:
            supabase.table('user_settings').upsert({
                'user_id': user_id, 'weather_source': source, 'favorite_spots': ','.join(fav_list)
            }).execute()
        except Exception as e:
            return False, [], [f"DB保存エラー"]
    return True, added, errors

def remove_favorite_spots(user_id, spot_names):
    if not supabase: return False, [], ["DB接続未完了です。"]
    source, favorites = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    
    removed = []
    errors = []
    for spot_name in spot_names:
        target_name = None
        for spot_key, data in SPOT_WEATHER_DATA.items():
            if spot_name.lower() == spot_key.lower() or spot_name.lower() in [a.lower() for a in data["aliases"]]:
                target_name = spot_key
                break
        
        if not target_name:
            target_name = spot_name 
            
        if target_name not in fav_list:
            errors.append(f"{target_name}(未登録)")
            continue
            
        fav_list.remove(target_name)
        removed.append(target_name)
        
    if removed:
        try:
            supabase.table('user_settings').upsert({
                'user_id': user_id, 'weather_source': source, 'favorite_spots': ','.join(fav_list)
            }).execute()
        except Exception as e:
            return False, [], [f"DB保存エラー"]
    return True, removed, errors

def clear_favorite_spots(user_id):
    if not supabase: return False, "DB接続未完了です。"
    source, _ = get_user_setting(user_id)
    try:
        supabase.table('user_settings').upsert({
            'user_id': user_id, 'weather_source': source, 'favorite_spots': ''
        }).execute()
        return True, "すべてのお気に入りを削除しました。"
    except Exception as e:
        return False, f"削除に失敗しました: {e}"

def move_favorite_spot(user_id, spot_name, direction):
    if not supabase: return False, "DB接続未完了です。"
    source, favorites = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    
    if spot_name not in fav_list:
        return False, "登録されていません。"
    
    idx = fav_list.index(spot_name)
    
    if direction == "up" and idx > 0:
        fav_list[idx - 1], fav_list[idx] = fav_list[idx], fav_list[idx - 1]
    elif direction == "down" and idx < len(fav_list) - 1:
        fav_list[idx + 1], fav_list[idx] = fav_list[idx], fav_list[idx + 1]
    else:
        return True, "移動不要"
        
    try:
        supabase.table('user_settings').upsert({
            'user_id': user_id, 'weather_source': source, 'favorite_spots': ','.join(fav_list)
        }).execute()
        return True, "移動しました"
    except Exception as e:
        return False, f"移動失敗: {e}"

def fetch_spot_1hour_data(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        flick_list = soup.find('div', id='flick_list_1hour')
        if not flick_list:
            flick_list = soup.find('div', id='flick_list_3hour')
            
        if not flick_list: return None

        weather_by_date = {}
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
                if not (6 <= hour_int <= 21): continue
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
        return weather_by_date
    except Exception as e:
        print(f"[スクレイピングエラー] {e}")
        return None

def build_grid_flex_message(spot_name, weather_by_date, hp_url="", map_url="", tel="", is_favorite=False):
    dates = list(weather_by_date.keys())
    
    header_color = "#0066cc"
    for group in COLOR_GROUPS:
        found = False
        for sg in group["sub_groups"]:
            if spot_name in sg["spots"]:
                header_color = group["header_bg"]
                found = True
                break
        if found:
            break

    def create_day_column(date_str):
        if not date_str:
            return {"type": "box", "layout": "vertical", "flex": 1, "contents": [{"type": "text", "text": "-", "color": "#cccccc", "align": "center", "size": "xs"}]}
        daily_data = weather_by_date[date_str]
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
                {"type": "box", "layout": "vertical", "backgroundColor": "#e6f2ff", "paddingAll": "4px", "margin": "sm",
                 "contents": [{"type": "text", "text": date_str, "weight": "bold", "size": "sm", "align": "center", "color": "#0066cc"}]}
            ] + [{"type": "box", "layout": "vertical", "spacing": "none", "margin": "sm", "contents": rows}]
        }

    body_contents = []
    row1 = {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [create_day_column(dates[0] if len(dates) > 0 else None), {"type": "separator"}, create_day_column(dates[1] if len(dates) > 1 else None)]}
    body_contents.append(row1)
    if len(dates) > 2:
        body_contents.append({"type": "separator", "margin": "md"})
        row2 = {"type": "box", "layout": "horizontal", "spacing": "sm", "contents": [create_day_column(dates[2] if len(dates) > 2 else None), {"type": "separator"}, create_day_column(dates[3] if len(dates) > 3 else None)]}
        body_contents.append(row2)

    bottom_buttons = []
    if tel:
        clean_tel = tel.replace('-', '').strip()
        bottom_buttons.append({"type": "button", "action": {"type": "uri", "label": "📞 電話", "uri": f"tel:{clean_tel}"}, "style": "secondary", "height": "sm", "flex": 1})
    
    bottom_buttons.append({"type": "button", "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list", "displayText": "📋 一覧"}, "style": "secondary", "color": "#fff59d", "height": "sm", "flex": 1})

    body_contents.append({"type": "separator", "margin": "md"})
    body_contents.append({
        "type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm",
        "contents": bottom_buttons
    })

    header_buttons = []
    if is_favorite:
        header_buttons.append({"type": "button", "action": {"type": "postback", "label": "🗑️ 解除", "data": f"action=fav_del_confirm_and_list&spot={spot_name}"}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs", "color": "#ffcccc"})
    else:
        header_buttons.append({"type": "button", "action": {"type": "postback", "label": "⭐️ 登録", "data": f"action=fav_add_and_list&spot={spot_name}"}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs", "color": "#fff59d"})

    clean_hp = clean_url(hp_url)
    clean_map = clean_url(map_url)
    if clean_hp: header_buttons.append({"type": "button", "action": {"type": "uri", "label": "🌐 HP", "uri": clean_hp}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})
    if clean_map: header_buttons.append({"type": "button", "action": {"type": "uri", "label": "🗺️ 地図", "uri": clean_map}, "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"})

    header_contents = [{"type": "text", "text": f"📍 {spot_name}", "color": "#ffffff", "weight": "bold", "size": "lg"}]
    if header_buttons: header_contents.append({"type": "box", "layout": "horizontal", "margin": "sm", "spacing": "xs", "contents": header_buttons})

    bubble = {
        "type": "bubble", "size": "giga",
        "header": {"type": "box", "layout": "vertical", "backgroundColor": header_color, "paddingAll": "10px", "contents": header_contents},
        "body": {"type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "8px", "contents": body_contents}
    }
    return FlexSendMessage(alt_text=f"{spot_name}の天気予報", contents=bubble)

@app.route("/", methods=['GET'])
def top_page():
    return "LINE Reply Bot Server is running!", 200

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

        add_match = re.match(r'^追加[\s:：]+(.+)$', raw_msg, re.DOTALL)
        if add_match:
            spots_str = add_match.group(1).strip()
            spot_names = [s for s in re.split(r'[\s,、\n]+', spots_str) if s]
            
            success, added, errors = add_favorite_spots(user_id, spot_names)
            reply_lines = []
            if added:
                reply_lines.append(f"✅ 追加しました: {', '.join(added)}")
            if errors:
                reply_lines.append(f"⚠️ スキップ・失敗: {', '.join(errors)}")
            if not reply_lines:
                reply_lines.append("⚠️ 釣り場名が認識できませんでした。")
                
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="\n".join(reply_lines)), flex_msg])
            return

        del_match = re.match(r'^削除[\s:：]+(.+)$', raw_msg, re.DOTALL)
        if del_match:
            spots_str = del_match.group(1).strip()
            spot_names = [s for s in re.split(r'[\s,、\n]+', spots_str) if s]
            
            success, removed, errors = remove_favorite_spots(user_id, spot_names)
            reply_lines = []
            if removed:
                reply_lines.append(f"✅ 削除しました: {', '.join(removed)}")
            if errors:
                reply_lines.append(f"⚠️ スキップ・失敗: {', '.join(errors)}")
            if not reply_lines:
                reply_lines.append("⚠️ 釣り場名が認識できませんでした。")
                
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="\n".join(reply_lines)), flex_msg])
            return

        if raw_msg in ["一覧", "リスト", "釣り場一覧", "エリア", "📋 一覧", "📋一覧"]:
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        if raw_msg in ["設定", "⚙️設定", "⚙️ 設定", "設定（並び替え・削除）", "⚙️ 設定（並び替え・削除）"]:
            _, favorites = get_user_setting(user_id)
            fav_list = [s.strip() for s in favorites.split(',')]
            fav_list = [s for s in fav_list if s]
            flex_msg = build_settings_flex_message(fav_list)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        flex_msg = build_spot_list_carousel_horizontal(user_id=user_id)
        line_bot_api.reply_message(event.reply_token, flex_msg)

    except LineBotApiError as e:
        print(f"\n=== LINE API エラー: {e.status_code} ===")
        print(e.error.message)
        for d in e.error.details:
            print(f" - {d.property}: {d.message}")
        try: line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ LINE通信エラーが発生しました。（データ容量制限エラー等の可能性があります）"))
        except Exception: pass
    except Exception as e:
        print("\n=== システムエラー詳細 ===")
        traceback.print_exc()
        try: line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 処理中にエラーが発生しました。"))
        except Exception: pass

@handler.add(PostbackEvent)
def handle_postback(event):
    try:
        user_id = event.source.user_id
        data_dict = dict(parse_qsl(event.postback.data))
        
        action = data_dict.get("action")
        spot_name = data_dict.get("spot")

        if "w" in data_dict:
            action = "show_weather"
            spot_name = data_dict["w"]

        if action == "show_list":
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return
            
        elif action == "show_settings":
            _, favorites = get_user_setting(user_id)
            fav_list = [s.strip() for s in favorites.split(',')]
            fav_list = [s for s in fav_list if s]
            flex_msg = build_settings_flex_message(fav_list)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        elif action == "show_weather":
            target_spot_name, target_url, hp_url, map_url, tel = get_spot_details(spot_name)
            _, favorites = get_user_setting(user_id)
            fav_list = [s.strip() for s in favorites.split(',')]
            fav_list = [s for s in fav_list if s]
            is_fav = target_spot_name in fav_list

            weather_by_date = get_cached_weather(target_spot_name)
            
            if not weather_by_date:
                weather_by_date = fetch_spot_1hour_data(target_url)
                if weather_by_date:
                    save_cached_weather(target_spot_name, weather_by_date)

            if weather_by_date:
                flex_msg = build_grid_flex_message(target_spot_name, weather_by_date, hp_url, map_url, tel, is_favorite=is_fav)
                line_bot_api.reply_message(event.reply_token, flex_msg)
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ 【{target_spot_name}】の天気データの取得に失敗しました。"))
            return

        elif action == "fav_add_and_list":
            success, added, errors = add_favorite_spots(user_id, [spot_name])
            msg = f"✅ 追加しました: {added[0]}" if added else f"⚠️ {errors[0]}"
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_confirm_and_list":
            flex_msg = build_delete_confirm_message(spot_name, "list")
            line_bot_api.reply_message(event.reply_token, flex_msg)

        elif action == "fav_del_confirm_and_settings":
            flex_msg = build_delete_confirm_message(spot_name, "settings")
            line_bot_api.reply_message(event.reply_token, flex_msg)

        elif action == "fav_del_execute_and_list":
            success, removed, errors = remove_favorite_spots(user_id, [spot_name])
            msg = f"✅ 削除しました: {removed[0]}" if removed else f"⚠️ {errors[0]}"
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_execute_and_settings":
            success, removed, errors = remove_favorite_spots(user_id, [spot_name])
            msg = f"✅ 削除しました: {removed[0]}" if removed else f"⚠️ {errors[0]}"
            _, favorites = get_user_setting(user_id)
            fav_list = [s.strip() for s in favorites.split(',')]
            fav_list = [s for s in fav_list if s]
            flex_msg = build_settings_flex_message(fav_list)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_cancel_and_list":
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="キャンセルしました。"), flex_msg])

        elif action == "fav_del_cancel_and_settings":
            _, favorites = get_user_setting(user_id)
            fav_list = [s.strip() for s in favorites.split(',')]
            fav_list = [s for s in fav_list if s]
            flex_msg = build_settings_flex_message(fav_list)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text="キャンセルしました。"), flex_msg])

        elif action == "fav_del_all_confirm":
            flex_msg = build_delete_all_confirm_message()
            line_bot_api.reply_message(event.reply_token, flex_msg)

        elif action == "fav_del_all_execute":
            success, msg = clear_favorite_spots(user_id)
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=f"✅ {msg}"), flex_msg])

        elif action in ["fav_up", "fav_down"]:
            direction = "up" if action == "fav_up" else "down"
            move_favorite_spot(user_id, spot_name, direction)
            _, favorites = get_user_setting(user_id)
            fav_list = [s.strip() for s in favorites.split(',')]
            fav_list = [s for s in fav_list if s]
            flex_msg = build_settings_flex_message(fav_list)
            line_bot_api.reply_message(event.reply_token, flex_msg)
            
    except LineBotApiError as e:
        print(f"\n=== LINE API エラー: {e.status_code} ===")
        print(e.error.message)
        for d in e.error.details:
            print(f" - {d.property}: {d.message}")
        try: line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ LINE通信エラーが発生しました。（データ容量オーバー等の可能性があります）"))
        except Exception: pass
    except Exception as e:
        print(f"Postback Error: {e}")
        traceback.print_exc()
        try:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 処理中にシステムエラーが発生しました。"))
        except Exception:
            pass

def run_background_update():
    if not supabase: return
    try:
        for spot_name, data in SPOT_WEATHER_DATA.items():
            url = data["url"]
            weather_data = fetch_spot_1hour_data(url)
            if weather_data:
                save_cached_weather(spot_name, weather_data)
            time.sleep(random.uniform(1.0, 2.0))
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
