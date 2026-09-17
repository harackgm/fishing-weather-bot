import os
import time
import random
import requests
import traceback
import difflib
from urllib.parse import quote
from bs4 import BeautifulSoup
from flask import Flask, request, abort, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
from supabase import create_client, Client

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

ADMIN_USER_ID = os.getenv('ADMIN_USER_ID', '').strip()
IS_TEST_MODE = True  # テストモード（Trueの場合、ADMIN_USER_IDのみに通知送信）
MAX_LIMIT = 5        # 大量通知ストッパー（1回の処理上限数）

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
# 3. 釣り場URL・HP・Googleマップ・電話番号・表記揺れ辞書（全57箇所）
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
        "aliases": ["アルクス焼津", "アルクスポンド焼津", "あるくすやいづ"]
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
    "関根": {
        "url": "https://weathernews.jp/onebox/36.851308/139.979065/",
        "hp_url": "http://sekine-fish.com/",
        "search_name": "関根養魚場",
        "tel": "0287-35-2630",
        "aliases": ["関根", "関根養魚場", "せきね"]
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
        "aliases": ["発光路", "発光路の森", "発光路の森ファアルクス", "ほっこうじ"]
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
        "aliases": ["アルクス宇都宮", "アルクスポンド宇都宮", "あるくすうつのみや"]
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
        "aliases": ["ジョイバレー", "じょいばれー"]
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
    "いなプー": {
        "url": "https://weathernews.jp/onebox/35.619254/140.074365/",
        "hp_url": "https://sunsetbeachpark.jp/",
        "search_name": "稲毛海浜公園プール",
        "tel": "043-247-2700",
        "aliases": ["いなプー", "稲毛プール", "いなぷー"]
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
    "朝霞": {
        "url": "https://weathernews.jp/onebox/35.813481/139.604736/",
        "hp_url": "http://www.asaka-garden.com/",
        "search_name": "朝霞ガーデン",
        "tel": "048-456-0260",
        "aliases": ["朝霞", "朝霞ガーデン", "あさか", "あさかガーデン"]
    },
    "しらこばと": {
        "url": "https://weathernews.jp/onebox/35.917970/139.752203/",
        "hp_url": "https://www.parks.or.jp/shirakobatosuijo/guide/003/003811.html",
        "search_name": "しらこばと水上公園",
        "tel": "048-977-5111",
        "aliases": ["しらこばと", "しらこばと水上公園"]
    },
    "川越": {
        "url": "https://weathernews.jp/onebox/35.907152/139.444046/",
        "hp_url": "https://www.parks.or.jp/kawagoesuijo/",
        "search_name": "川越水上公園",
        "tel": "049-241-2241",
        "aliases": ["川越", "川越水上公園", "かわごえ"]
    },
    "加須はなさき": {
        "url": "https://weathernews.jp/onebox/36.096192/139.636601/",
        "hp_url": "https://www.parks.or.jp/kazohanasaki/guide/000/000031.html",
        "search_name": "加須はなさき水上公園",
        "tel": "0480-65-7155",
        "aliases": ["加須はなさき", "はなさき", "はなさき公園"]
    },
    "多摩湖": {
        "url": "https://weathernews.jp/onebox/35.780248/139.440732/",
        "hp_url": "https://www.s-fishingarea.com/",
        "search_name": "多摩湖フィッシングエリア",
        "tel": "042-922-1371",
        "aliases": ["多摩湖", "西武園", "たまこ"]
    },
    "中里": {
        "url": "https://weathernews.jp/onebox/36.163896/139.176567/",
        "hp_url": "http://fish104.in.coocan.jp/",
        "search_name": "中里フィッシングクラブ",
        "tel": "0495-76-1120",
        "aliases": ["中里", "中里FC", "なかざと"]
    },
    "伊古": {
        "url": "https://weathernews.jp/onebox/36.071547/139.339037/",
        "hp_url": "http://www.ikonosato.jp/",
        "search_name": "伊古の里フィッシングパーク",
        "tel": "0493-57-0505",
        "aliases": ["伊古", "伊古の里", "いこのさと"]
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
        "aliases": ["中津川", "FF中津川", "なかつがわ"]
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
        "aliases": ["開成", "開成水辺フォレストスプリングス", "開成FS", "かいせい"]
    },
    "浅川": {
        "url": "https://weathernews.jp/onebox/35.641903/139.231262/",
        "hp_url": "http://www5c.biglobe.ne.jp/~fly-lure/",
        "search_name": "浅川国際マス釣り場",
        "tel": "042-661-2228",
        "aliases": ["浅川", "浅川国際マス釣り場", "あさかわ"]
    },

    # --- 山梨県・長野県 ---
    "鹿留": {
        "url": "https://weathernews.jp/onebox/35.512350/138.887160/",
        "hp_url": "http://www.sisidome.jp/",
        "search_name": "ベリーパーク in 鹿留",
        "tel": "0554-43-0082",
        "aliases": ["鹿留", "シシドメ", "ししどめ"]
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
        "aliases": ["JF in Tsugane", "Tsugane", "ジョイフィールド", "つがね"]
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
    "ハーブ": {
        "url": "https://weathernews.jp/onebox/36.403436/137.890526/",
        "hp_url": "https://herbfa1995.kikirara.jp/",
        "search_name": "ハーブの里フィッシングエリア",
        "tel": "0261-62-6322",
        "aliases": ["ハーブ", "ハーブの里", "はーぶ"]
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
    "槻の池": {
        "url": "https://weathernews.jp/onebox/36.011582/138.197271/",
        "hp_url": "http://www.tsukinoike.jp/",
        "search_name": "槻の池フィッシングエリア",
        "tel": "0266-76-2280",
        "aliases": ["槻の池", "つきのいけ"]
    },
    "あずみ野": {
        "url": "https://weathernews.jp/onebox/36.337699/137.885455/",
        "hp_url": "http://www7b.biglobe.ne.jp/~azuminoturibori/",
        "search_name": "あずみ野フィッシングセンター",
        "tel": "0263-82-8280",
        "aliases": ["あずみ野", "あずみ野FC", "あずみの"]
    },

    # --- 東北・東海・関西 ---
    "不忘": {
        "url": "https://weathernews.jp/onebox/38.042491/140.554478/",
        "hp_url": "http://www.fubou.jp/",
        "search_name": "グリーンコンプラザ不忘",
        "tel": "0224-24-8131",
        "aliases": ["不忘", "グリーンコンプラザ不忘", "ふぼう"]
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
        "aliases": ["鶴沼川", "つるぬまがわ"]
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
    "五頭": {
        "url": "https://weathernews.jp/onebox/37.819471/139.238518/",
        "hp_url": "http://www.gozu-fp.jp/",
        "search_name": "五頭フィッシングパーク",
        "tel": "0250-63-0051",
        "aliases": ["五頭", "五頭FP", "ごず"]
    },
    "瑞浪": {
        "url": "https://weathernews.jp/onebox/35.433516/137.295266/",
        "hp_url": "https://www.fishing-autocamp-mizunami.com/",
        "search_name": "フィッシングキャンプエリア瑞浪",
        "tel": "0572-68-1212",
        "aliases": ["瑞浪", "FC瑞浪", "みずなみ"]
    },
    "サンクチュアリ": {
        "url": "https://weathernews.jp/onebox/35.187504/136.457803/",
        "hp_url": "https://go-sanctuary.com/",
        "search_name": "フィッシングサンクチュアリ",
        "tel": "0594-46-8820",
        "aliases": ["サンクチュアリ", "サンク", "さんくちゅあり"]
    },
    "醒井": {
        "url": "https://weathernews.jp/onebox/35.303671/136.349914/",
        "hp_url": "http://samegai.siga.jp/",
        "search_name": "醒井養鱒場",
        "tel": "0749-54-0301",
        "aliases": ["醒井", "醒井養鱒場", "さめがい"]
    },
    "高島": {
        "url": "https://weathernews.jp/onebox/35.348308/136.052288/",
        "hp_url": "https://www.takashimanoizumi.com/",
        "search_name": "高島の泉",
        "tel": "0740-25-3790",
        "aliases": ["高島", "高島の泉", "たかしまのいずみ"]
    },
    "千早川": {
        "url": "https://weathernews.jp/onebox/34.417118/135.647482/",
        "hp_url": "http://chihayagawa.jp/",
        "search_name": "千早川マス釣り場",
        "tel": "0721-74-0116",
        "aliases": ["千早川", "千早川マス釣り場", "ちはやがわ"]
    }
}

# 8グループの地域・県別カルーセル用分類データ
SPOT_CAROUSEL_GROUPS = [
    {"title": "📍 静岡・神奈川・東京", "spots": ["東山湖", "すその", "須川", "アルクス焼津", "浜名湖", "足柄", "中津川", "早戸川", "王禅寺", "開成", "浅川"]},
    {"title": "📍 栃木（大田原・那須）", "spots": ["キングフィッシャー", "みどり", "那須高原", "尚仁沢", "つり天国", "関根", "408", "308", "蛇尾川"]},
    {"title": "📍 栃木（小山・佐野・宇都宮）", "spots": ["レイクウッド", "なら山沼", "大芦川", "加賀", "発光路", "上永野", "柏倉", "遊水園", "アルクス宇都宮", "エリア21", "ベアーズパーク", "鬼怒川", "名草"]},
    {"title": "📍 千葉・埼玉", "spots": ["座間", "ジョイバレー", "ウォルトン", "NOIKE", "パラダイス", "いなプー", "長瀞", "彩の国", "朝霞", "しらこばと", "川越", "加須はなさき", "多摩湖", "中里", "伊古"]},
    {"title": "📍 群馬", "spots": ["川場", "川場キングダム", "おくとね", "イワナセンター", "黒保根", "迦葉山", "片品", "中之沢", "宮城", "大崎", "けん太", "フック", "赤久縄", "太田", "東山道", "榛名"]},
    {"title": "📍 茨城", "spots": ["水戸南", "高萩", "つくば園", "FAJ", "ユザキ", "笠間", "DoDoo", "若栗", "ミッドクリーク"]},
    {"title": "📍 山梨・長野", "spots": ["鹿留", "小菅", "シルフ", "JF in Tsugane", "竜華池", "平谷湖", "ハーブ", "ニレ池", "鹿島槍", "槻の池", "あずみ野"]},
    {"title": "📍 東北・他エリア", "spots": ["不忘", "白河", "ほのぼの", "WaDoNa", "鶴沼川", "オーパ", "あいづ", "上浜", "五頭", "瑞浪", "サンクチュアリ", "醒井", "高島", "千早川"]}
]

def find_best_match_spot(user_text):
    """ユーザー入力から最適な釣り場情報（正式名、天気URL、HP URL、GoogleマップURL、電話番号）を特定"""
    text = user_text.strip().lower()

    # 1. エイリアス完全一致および部分一致検索（最優先）
    for spot_key, data in SPOT_WEATHER_DATA.items():
        for alias in data["aliases"]:
            alias_lower = alias.lower()
            if text == alias_lower or alias_lower in text or text in alias_lower:
                map_url = f"https://www.google.com/maps/search/?api=1&query={quote(data.get('search_name', spot_key))}"
                return spot_key, data["url"], data.get("hp_url", ""), map_url, data.get("tel", "")

    # 2. あいまい類似度検索 (difflib)
    all_aliases = []
    alias_to_spot = {}
    for spot_key, data in SPOT_WEATHER_DATA.items():
        for alias in data["aliases"]:
            all_aliases.append(alias.lower())
            alias_to_spot[alias.lower()] = spot_key

    matches = difflib.get_close_matches(text, all_aliases, n=1, cutoff=0.6)
    if matches:
        matched_spot_key = alias_to_spot[matches[0]]
        data = SPOT_WEATHER_DATA[matched_spot_key]
        map_url = f"https://www.google.com/maps/search/?api=1&query={quote(data.get('search_name', matched_spot_key))}"
        return matched_spot_key, data["url"], data.get("hp_url", ""), map_url, data.get("tel", "")

    return None, None, None, None, None

def build_spot_list_carousel():
    """地域別・2列格子（セル分割）カルーセルメッセージの構築"""
    bubbles = []
    
    for group in SPOT_CAROUSEL_GROUPS:
        title = group["title"]
        spots = group["spots"]
        
        # ボタンを2列ずつの行に分割
        rows = []
        for i in range(0, len(spots), 2):
            pair = spots[i:i+2]
            row_buttons = []
            for spot in pair:
                row_buttons.append({
                    "type": "button",
                    "action": {"type": "message", "label": spot, "text": spot},
                    "style": "secondary",
                    "height": "sm",
                    "flex": 1,
                    "margin": "xs"
                })
            # 奇数個の場合は右側に空スペースを追加して揃える
            if len(pair) == 1:
                row_buttons.append({"type": "spacer", "size": "xs", "flex": 1})
                
            rows.append({
                "type": "box",
                "layout": "horizontal",
                "margin": "xs",
                "contents": row_buttons
            })
            
        bubble = {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": "#0066cc", "paddingAll": "10px",
                "contents": [
                    {"type": "text", "text": title, "color": "#ffffff", "weight": "bold", "size": "md"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical", "spacing": "xs", "paddingAll": "8px",
                "contents": rows
            }
        }
        bubbles.append(bubble)

    carousel = {
        "type": "carousel",
        "contents": bubbles
    }
    return FlexSendMessage(alt_text="全国管理釣り場一覧", contents=carousel)

# ==========================================
# 4. Supabase データベース管理関数
# ==========================================
def get_user_setting(user_id):
    if not supabase:
        return ('ウェザーニュース', '')
    try:
        res = supabase.table('user_settings').select('*').eq('user_id', user_id).execute()
        if not res.data:
            supabase.table('user_settings').insert({
                'user_id': user_id,
                'weather_source': 'ウェザーニュース',
                'favorite_spots': ''
            }).execute()
            return ('ウェザーニュース', '')
        row = res.data[0]
        return (row.get('weather_source', 'ウェザーニュース'), row.get('favorite_spots', ''))
    except Exception as e:
        print(f"[Supabase取得エラー] {e}")
        return ('ウェザーニュース', '')

def add_favorite_spot(user_id, spot_name):
    if not supabase: return False, "DB接続未完了です。"
    
    matched_spot, _, _, _, _ = find_best_match_spot(spot_name)
    target_name = matched_spot if matched_spot else spot_name

    _, favorites = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    if target_name in fav_list:
        return False, f"「{target_name}」はすでに登録されています。"
    if len(fav_list) >= 5:
        return False, "お気に入り釣り場は最大5箇所まで登録可能です。"
    
    fav_list.append(target_name)
    try:
        supabase.table('user_settings').update({'favorite_spots': ','.join(fav_list)}).eq('user_id', user_id).execute()
        return True, f"「{target_name}」をお気に入りに追加しました。"
    except Exception as e:
        return False, f"保存に失敗しました: {e}"

def remove_favorite_spot(user_id, spot_name):
    if not supabase: return False, "DB接続未完了です。"
    
    matched_spot, _, _, _, _ = find_best_match_spot(spot_name)
    target_name = matched_spot if matched_spot else spot_name

    _, favorites = get_user_setting(user_id)
    fav_list = [s for s in favorites.split(',') if s]
    if target_name not in fav_list:
        return False, f"「{target_name}」は登録されていません。"
    
    fav_list.remove(target_name)
    try:
        supabase.table('user_settings').update({'favorite_spots': ','.join(fav_list)}).eq('user_id', user_id).execute()
        return True, f"「{target_name}」をお気に入りから削除しました。"
    except Exception as e:
        return False, f"削除に失敗しました: {e}"

# ==========================================
# 5. ウェザーニュース 実データスクレイピング関数
# ==========================================
def fetch_spot_1hour_data(url):
    """指定されたURLから現在時刻以降の予報を取得（6〜21時抽出版）"""
    time.sleep(random.uniform(1.0, 2.5))  # サーバー負荷軽減のゆらぎ待機
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    
    try:
        response = requests.get(url, headers=headers, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        flick_list = soup.find('div', id='flick_list_1hour')
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
                if 'past' in item.get('class', []):
                    continue
                
                time_tag = item.find('li', class_='time')
                hour_str = time_tag.text.strip() if time_tag else ""
                if not hour_str.isdigit(): continue
                
                hour_int = int(hour_str)
                if not (6 <= hour_int <= 21): 
                    continue
                    
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

                rain = item.find('li', class_='rain').text.strip().replace("ミリ", "mm") if item.find('li', class_='rain') else "-"
                temp = item.find('li', class_='temp').text.strip() if item.find('li', class_='temp') else "-"
                wind_p = item.find('li', class_='wind').find('p') if item.find('li', class_='wind') else None
                wind = wind_p.text.strip() if wind_p else "-"

                daily_list.append({
                    "time": hour,
                    "img_url": img_url,
                    "temp": temp,
                    "rain": rain,
                    "wind": wind
                })
            
            if daily_list:
                weather_by_date[date_str] = daily_list
            
            if len(weather_by_date) >= 4:
                break
            
        return weather_by_date
    except Exception as e:
        print(f"[スクレイピングエラー] {e}")
        return None

def build_grid_flex_message(spot_name, weather_by_date, hp_url="", map_url="", tel=""):
    """田の字型（2行×2列）グリッドレイアウト"""
    dates = list(weather_by_date.keys())
    
    def create_day_column(date_str):
        if not date_str:
            return {
                "type": "box", "layout": "vertical", "flex": 1, 
                "contents": [{"type": "text", "text": "-", "color": "#cccccc", "align": "center", "size": "xs"}]
            }
            
        daily_data = weather_by_date[date_str]
        rows = [
            {
                "type": "box", "layout": "horizontal", "margin": "none",
                "contents": [
                    {"type": "text", "text": "時", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "天", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "℃", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"},
                    {"type": "text", "text": "mm", "weight": "bold", "size": "xxs", "flex": 1, "align": "center", "color": "#888888"},
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
                    {"type": "image", "url": img_url, "size": "xs", "flex": 1, "align": "center"},
                    {"type": "text", "text": t_val, "size": "xs", "flex": 1, "align": "center", "color": temp_color},
                    {"type": "text", "text": r_val, "size": "xs", "flex": 1, "align": "center", "color": rain_color},
                    {"type": "text", "text": w_val, "size": "xs", "flex": 1, "align": "center"}
                ]
            })
            
        return {
            "type": "box", "layout": "vertical", "flex": 1,
            "contents": [
                {
                    "type": "box", "layout": "vertical", "backgroundColor": "#e6f2ff", "paddingAll": "4px", "margin": "sm",
                    "contents": [
                        {"type": "text", "text": date_str, "weight": "bold", "size": "sm", "align": "center", "color": "#0066cc"}
                    ]
                }
            ] + [{"type": "box", "layout": "vertical", "spacing": "none", "margin": "sm", "contents": rows}]
        }

    body_contents = []

    # 1行目（上段）
    row1 = {
        "type": "box", "layout": "horizontal", "spacing": "sm",
        "contents": [
            create_day_column(dates[0] if len(dates) > 0 else None),
            {"type": "separator"},
            create_day_column(dates[1] if len(dates) > 1 else None)
        ]
    }
    body_contents.append(row1)

    # 2行目（下段）
    if len(dates) > 2:
        body_contents.append({"type": "separator", "margin": "md"})
        row2 = {
            "type": "box", "layout": "horizontal", "spacing": "sm",
            "contents": [
                create_day_column(dates[2] if len(dates) > 2 else None),
                {"type": "separator"},
                create_day_column(dates[3] if len(dates) > 3 else None)
            ]
        }
        body_contents.append(row2)

    # 最下段に控えめな電話ボタン（誤タップ防止用リンクスタイル）を配置
    if tel:
        clean_tel = tel.replace('-', '').strip()
        body_contents.append({"type": "separator", "margin": "md"})
        body_contents.append({
            "type": "box", "layout": "horizontal", "margin": "sm", "justifyContent": "center",
            "contents": [
                {
                    "type": "button",
                    "action": {"type": "uri", "label": f"📞 電話問合せ ({tel})", "uri": f"tel:{clean_tel}"},
                    "style": "link",
                    "height": "sm",
                    "color": "#888888"
                }
            ]
        })

    # ヘッダー内のリンクボタン組み立て（HP / Google Map のみ）
    header_buttons = []
    if hp_url:
        header_buttons.append({
            "type": "button",
            "action": {"type": "uri", "label": "🌐 HP", "uri": hp_url},
            "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"
        })
    if map_url:
        header_buttons.append({
            "type": "button",
            "action": {"type": "uri", "label": "🗺️ 地図", "uri": map_url},
            "style": "secondary", "height": "sm", "flex": 1, "margin": "xs"
        })

    header_contents = [
        {"type": "text", "text": f"📍 {spot_name}", "color": "#ffffff", "weight": "bold", "size": "md"}
    ]
    if header_buttons:
        header_contents.append({
            "type": "box", "layout": "horizontal", "margin": "sm", "spacing": "xs",
            "contents": header_buttons
        })

    bubble = {
        "type": "bubble",
        "size": "giga",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#0066cc", "paddingAll": "10px",
            "contents": header_contents
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "8px",
            "contents": body_contents
        }
    }
    return FlexSendMessage(alt_text=f"{spot_name}の天気予報(4日間)", contents=bubble)

# ==========================================
# 6. Webサーバーのエンドポイント
# ==========================================
@app.route("/", methods=['GET'])
def top_page():
    return "LINE Reply Bot Server (Supabase DB) is running!", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK', 200

# ==========================================
# 7. LINEメッセージ受信処理
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        user_message = event.message.text.strip()
        user_id = event.source.user_id

        print(f"[受信] ユーザー({user_id}): {user_message}")

        # 1. 一覧カルーセル表示コマンド
        if user_message in ["一覧", "リスト", "釣り場一覧", "エリア"]:
            flex_msg = build_spot_list_carousel()
            line_bot_api.reply_message(event.reply_token, flex_msg)
            return

        elif user_message == "設定":
            user_setting = get_user_setting(user_id)
            source, favorites = user_setting
            fav_list = [s for s in favorites.split(',') if s]
            fav_display = "\n".join([f"・{spot}" for spot in fav_list]) if fav_list else "・未登録"
            reply_text = (
                "⚙️ 【現在の設定状況】\n\n"
                "■ 天気詳細度: 常に最詳細モード\n"
                f"■ 参照ソース: {source}\n"
                f"■ お気に入り釣り場:\n{fav_display}\n\n"
                "【設定変更コマンド】\n"
                "・「追加:釣り場名」\n"
                "・「削除:釣り場名」\n"
                "・「一覧」（釣り場リストを表示）"
            )
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        elif user_message.startswith("追加:"):
            spot_name = user_message.replace("追加:", "").strip()
            success, msg = add_favorite_spot(user_id, spot_name) if spot_name else (False, "⚠️ 釣り場名を入力してください。")
            reply_text = f"✅ {msg}" if success else f"⚠️ {msg}"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        elif user_message.startswith("削除:"):
            spot_name = user_message.replace("削除:", "").strip()
            success, msg = remove_favorite_spot(user_id, spot_name) if spot_name else (False, "⚠️ 削除する釣り場名を入力してください。")
            reply_text = f"✅ {msg}" if success else f"⚠️ {msg}"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        # ゆらぎ検索で釣り場情報（HP/MAP/TEL）を特定
        target_spot_name, target_url, hp_url, map_url, tel = find_best_match_spot(user_message)

        if target_url:
            weather_by_date = fetch_spot_1hour_data(target_url)
            if weather_by_date:
                flex_msg = build_grid_flex_message(target_spot_name, weather_by_date, hp_url, map_url, tel)
                line_bot_api.reply_message(event.reply_token, flex_msg)
                print(f"[送信] {target_spot_name}の Grid FlexMessage応答を完了しました。")
            else:
                error_msg = f"⚠️ 【{target_spot_name}】の天気データの取得に失敗しました。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=error_msg))
            return
            
        reply_text = (
            "🔍 その釣り場は現在対応していません、もしくは名前が間違っています。\n\n"
            "「一覧」と送信すると全国60箇所以上の釣り場リストを表示できます！\n\n"
            "※「ざま」「すそぱ」「寺」「てら」「ならやま」「がし山」などの略称でも検索可能です。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

    except Exception as e:
        print("\n=== システムエラー詳細 ===")
        traceback.print_exc()
        print("==========================\n")
        try:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 処理中にエラーが発生しました。時間を置いて再度お試しください。"))
        except Exception:
            pass

# ==========================================
# 8. 定期トリガーエンドポイント（Cron自動通知用）
# ==========================================
@app.route("/cron_trigger", methods=['GET', 'POST'])
def cron_trigger():
    print("\n--- 定期トリガーを受信しました ---")
    if not supabase:
        return jsonify({"status": "error", "reason": "DB_NOT_CONNECTED"}), 500

    try:
        res = supabase.table('user_settings').select('*').execute()
        users = res.data or []

        # テストモード安全ガード: IS_TEST_MODE が True の場合は ADMIN_USER_ID のみに絞り込み
        if IS_TEST_MODE:
            print(f"[テストモード有効] 送信対象を管理者({ADMIN_USER_ID})のみに絞り込みます。")
            users = [u for u in users if u.get('user_id') == ADMIN_USER_ID]
            if not users and ADMIN_USER_ID:
                users = [{'user_id': ADMIN_USER_ID, 'favorite_spots': ''}]

        # 大量通知ストッパー（安全装置）
        if len(users) > MAX_LIMIT:
            print(f"[安全装置作動] 対象件数({len(users)}件)が上限({MAX_LIMIT}件)を超えたためスキップします。")
            return jsonify({"status": "skipped", "reason": "MAX_LIMIT_EXCEEDED"}), 200

        print(f"配信対象件数: {len(users)}件")

        for user in users:
            uid = user.get('user_id')
            _, favorites = get_user_setting(uid)
            fav_list = [s for s in favorites.split(',') if s]

            if not fav_list:
                print(f"ユーザー({uid}): お気に入り未登録のためスキップ")
                continue

            for spot_name in fav_list:
                matched_spot, url, hp_url, map_url, tel = find_best_match_spot(spot_name)
                if not url:
                    continue

                print(f"ユーザー({uid}) へ 「{matched_spot}」 の定期通知を処理中...")
                weather_data = fetch_spot_1hour_data(url)
                if weather_data:
                    flex_msg = build_grid_flex_message(matched_spot, weather_data, hp_url, map_url, tel)
                    line_bot_api.push_message(uid, flex_msg)
                    print(f"-> 「{matched_spot}」 のPush送信成功")
                
                time.sleep(random.uniform(1.5, 3.0))  # サーバー負荷軽減のゆらぎ待機

        return jsonify({"status": "success", "processed_users": len(users)}), 200

    except Exception as e:
        print("\n=== Cron処理エラー ===")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
