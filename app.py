import os
import time
import random
import requests
import traceback
import difflib
import re
import threading
import unicodedata
import jpholiday
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

MAX_FAVORITES = 30

# Supabase接続初期化
SUPABASE_URL = os.getenv('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '').strip()

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"[Supabase初期化エラー] {e}")

# 超高速メモリキャッシュ
MEMORY_CACHE = {}

# ==========================================
# 3. 釣り場データ定義（トラウト用 ＆ バス用）
# ==========================================
SPOT_WEATHER_DATA = {
    # --- 静岡県 ---
    "東山湖": {
        "url": "https://weathernews.jp/onebox/35.296739/138.955925/",
        "tenki_url": "https://tenki.jp/forecast/5/25/5030/22215/1hour.html",
        "hp_url": "http://www.higashiyamako.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "東山湖フィッシングエリア", "tel": "0550-82-2161",
        "aliases": ["東山湖", "東山湖フィッシングエリア", "東山湖FA", "ひがしやまこ", "ひがしやま", "東山", "がし山", "がしやま"]
    },
    "すその": {
        "url": "https://weathernews.jp/onebox/35.166667/138.899162/",
        "tenki_url": "https://tenki.jp/forecast/5/25/5030/22220/1hour.html",
        "hp_url": "http://www.susono-f-park.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "すそのフィッシングパーク", "tel": "055-993-5514",
        "aliases": ["すその", "すそのフィッシングパーク", "すそのFP", "裾野", "すそぱ", "すそパ"]
    },
    "須川": {
        "url": "https://weathernews.jp/onebox/35.359818/138.977710/",
        "tenki_url": "https://tenki.jp/forecast/5/25/5030/22344/1hour.html",
        "hp_url": "http://www.sukawa.ne.jp/",
        "x_url": "https://x.com/sukawafp", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "須川フィッシングパーク", "tel": "0550-75-3077",
        "aliases": ["須川", "須川フィッシングパーク", "須川FP", "すがわ"]
    },
    "アルクス焼津": {
        "url": "https://weathernews.jp/onebox/34.789110/138.294771/",
        "tenki_url": "https://tenki.jp/forecast/5/25/5010/22212/1hour.html",
        "hp_url": "http://www.arcus-pond.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "アルクスポンド焼津", "tel": "054-622-7102",
        "aliases": ["アルクス焼津", "アルクスポンド焼津", "あるくすやいづ", "あるくす", "焼津", "アルクスポンド", "やいづ"]
    },
    "浜名湖": {
        "url": "https://weathernews.jp/onebox/34.712749/137.629457/",
        "tenki_url": "https://tenki.jp/forecast/5/25/5040/22133/1hour.html",
        "hp_url": "http://www.hamanako-fr.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "浜名湖フィッシングリゾート", "tel": "053-592-2221",
        "aliases": ["浜名湖", "浜名湖フィッシングリゾート", "浜名湖FR", "はまなこ"]
    },

    # --- 栃木県 ---
    "キング": {
        "url": "https://weathernews.jp/onebox/36.907054/140.078650/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4120/9210/1hour.html",
        "hp_url": "https://kingfisher-tochigi.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "キングフィッシャー 大田原", "tel": "0287-23-1253",
        "aliases": ["キング", "きんぐ", "キングフィッシャー", "きんぐふぃっしゃー"]
    },
    "みどり": {
        "url": "https://weathernews.jp/onebox/36.834975/140.002410/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4120/9210/1hour.html",
        "hp_url": "http://www.nasu-net.or.jp/~midorifi/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "みどりフィッシングエリア", "tel": "0287-28-3334",
        "aliases": ["みどり", "みどりフィッシングエリア", "みどりFA"]
    },
    "那須高原": {
        "url": "https://weathernews.jp/onebox/37.001929/140.104991/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4120/9407/1hour.html",
        "hp_url": "http://lure-f.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "那須高原ルアーフィールド", "tel": "0287-78-1005",
        "aliases": ["那須高原", "那須高原ルアーフィールド", "那須高原LF", "なすこうげん"]
    },
    "尚仁沢": {
        "url": "https://weathernews.jp/onebox/37.001929/140.104991/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4120/9384/1hour.html",
        "hp_url": "https://shojinzawa.com/",
        "x_url": "", "fb_url": "", "insta_url": "https://www.instagram.com/sofield1996/", "blog_url": "http://sofield.jugem.jp/", "yt_url": "",
        "search_name": "尚仁沢アウトドアフィールド", "tel": "0287-41-0051",
        "aliases": ["尚仁沢", "尚仁沢アウトドアフィールド", "尚仁沢AF", "しょうじんざわ"]
    },
    "つり天国": {
        "url": "https://weathernews.jp/onebox/37.073444/140.044452/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4120/9407/1hour.html",
        "hp_url": "http://www.tsuritengoku.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "つり天国 那須", "tel": "0287-64-4286",
        "aliases": ["つり天国", "ツリテンゴク", "つりてんごく"]
    },
    "関根養魚場": {
        "url": "https://weathernews.jp/onebox/36.851308/139.979065/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4120/9213/1hour.html",
        "hp_url": "http://sekine-fish.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "関根養魚場", "tel": "0287-35-2630",
        "aliases": ["関根養魚場", "関根", "せきね", "せきねようぎょじょう"]
    },
    "408": {
        "url": "https://weathernews.jp/onebox/36.763055/139.858269/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4120/9384/1hour.html",
        "hp_url": "https://408club.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "408Club", "tel": "0287-43-0408",
        "aliases": ["408", "408クラブ", "408club", "よんまるはち"]
    },
    "308": {
        "url": "https://weathernews.jp/onebox/36.824828/139.896229/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4120/9211/1hour.html",
        "hp_url": "http://408club.com/308/index.html",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "308Club", "tel": "0287-43-0308",
        "aliases": ["308", "308クラブ", "308club", "さんまるはち"]
    },
    "蛇尾（さび）川": {
        "url": "https://weathernews.jp/onebox/36.981351/139.901534/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4120/9213/1hour.html",
        "hp_url": "https://sabigawafishingpark.com/",
        "x_url": "https://x.com/matagi_nasu",
        "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "蛇尾川フィッシングパーク", "tel": "0287-32-2212",
        "aliases": ["蛇尾川", "蛇尾（さび）川", "さびがわ", "サビガワ", "へびがわ", "いびがわ", "えびがわ", "蛇尾川フィッシングパーク"]
    },
    "レイクウッド": {
        "url": "https://weathernews.jp/onebox/36.611334/139.666579/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4110/9205/1hour.html",
        "hp_url": "http://lakewoodresort.info/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "レイクウッドリゾート 鹿沼", "tel": "0289-75-1008",
        "aliases": ["レイクウッド", "レイクウッドリゾート", "れいくうっど"]
    },
    "なら山沼": {
        "url": "https://weathernews.jp/onebox/36.373741/139.802713/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4110/9208/1hour.html",
        "hp_url": "http://www.shimotsuga-fc.org/index.html",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "なら山沼漁場", "tel": "0285-25-4350",
        "aliases": ["なら山沼", "なら山沼漁場", "ならやま", "なら山", "ならやまぬま", "ならやま沼"]
    },
    "大芦川": {
        "url": "https://weathernews.jp/onebox/36.590732/139.693652/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4110/9205/1hour.html",
        "hp_url": "http://park10.wakwak.com/~field-village/",
        "x_url": "", "fb_url": "https://ja-jp.facebook.com/ooashigawa.fcfv/", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "大芦川 F&C フィールドビレッジ", "tel": "0289-74-7222",
        "aliases": ["大芦川", "大芦川F&C", "おおあしがわ"]
    },
    "加賀": {
        "url": "https://weathernews.jp/onebox/36.388609/139.537247/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4110/9204/1hour.html",
        "hp_url": "http://www.kaga-fa.co.jp/",
        "x_url": "", "fb_url": "", "insta_url": "https://www.instagram.com/kaga_fishing_area/", "blog_url": "https://ameblo.jp/kaga-fa/", "yt_url": "",
        "search_name": "加賀フィッシングエリア", "tel": "0283-24-1513",
        "aliases": ["加賀", "加賀フィッシングエリア", "加賀FA", "かが"]
    },
    "発光路": {
        "url": "https://weathernews.jp/onebox/36.580281/139.532829/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4110/9205/1hour.html",
        "hp_url": "https://ov-hokkojinomori-fa.jimdosite.com/",
        "x_url": "", "fb_url": "", "insta_url": "https://www.instagram.com/ov.hokkojinomori.fa/", "blog_url": "https://hokkojinomori.livedoor.blog/", "yt_url": "",
        "search_name": "発光路の森ファアルクス", "tel": "0289-85-3503",
        "aliases": ["発光路", "発光路の森", "ほっこうじ", "はっこうじ", "発光時", "発酵時"]
    },
    "上永野": {
        "url": "https://weathernews.jp/onebox/36.511884/139.573442/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4110/9205/1hour.html",
        "hp_url": "https://kaminagano-fishing.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "フィッシングリゾート上永野", "tel": "0289-84-0335",
        "aliases": ["上永野", "上永野FR", "かみながの"]
    },
    "柏倉": {
        "url": "https://weathernews.jp/onebox/36.398276/139.660428/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4110/9203/1hour.html",
        "hp_url": "http://kashiwagurafishingpk.g3.xrea.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "柏倉フィッシングパーク", "tel": "0282-23-6622",
        "aliases": ["柏倉", "柏倉FP", "かしわぐら"]
    },
    "遊水園": {
        "url": "https://weathernews.jp/onebox/36.342013/139.863541/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4110/9208/1hour.html",
        "hp_url": "http://meiseikousan.jp/oyamawaterpark/",
        "x_url": "https://x.com/ParkOyama", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "Oyama Water Park 遊水園", "tel": "0285-38-8255",
        "aliases": ["遊水園", "OyamaWaterPark遊水園", "ゆうすいえん"]
    },
    "アルクス宇都宮": {
        "url": "https://weathernews.jp/onebox/36.566488/139.960060/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4110/9201/1hour.html",
        "hp_url": "http://www.arcus-pond.com/",
        "x_url": "", "fb_url": "https://www.facebook.com/p/Arcus-Pond%E3%82%A2%E3%83%AB%E3%82%AF%E3%82%B9%E3%83%9D%E3%83%B3%E3%83%89-100041638634155/", "insta_url": "", "blog_url": "https://www.arcus-pond.com/wp/category/blog/", "yt_url": "",
        "search_name": "アルクスポンド宇都宮", "tel": "028-652-3210",
        "aliases": ["アルクス宇都宮", "アルクスポンド宇都宮", "あるくすうつのみや", "あるくす", "アルクスポンド", "うつのみや"]
    },
    "エリア21": {
        "url": "https://weathernews.jp/onebox/36.496150/139.899522/",
        "tenki_url": "https://tenki.jp/forecast/3/16/4410/13201/1hour.html",
        "hp_url": "http://www.area21.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "エリア21 宇都宮", "tel": "028-656-1188",
        "aliases": ["エリア21", "えりあ21"]
    },
    "ベアーズパーク": {
        "url": "https://weathernews.jp/onebox/36.513221/139.956989/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4110/9201/1hour.html",
        "hp_url": "https://bearspark.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "ベアーズパーク宇都宮", "tel": "028-656-2580",
        "aliases": ["ベアーズパーク", "増井養魚場", "べあーずぱーく"]
    },
    "鬼怒川": {
        "url": "https://weathernews.jp/onebox/36.617621/139.937106/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4110/9201/1hour.html",
        "hp_url": "http://kinugawa-fa.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "鬼怒川フィッシングエリア", "tel": "028-672-1815",
        "aliases": ["鬼怒川", "鬼怒川フィッシングエリア", "鬼怒川FA", "きぬがわ"]
    },
    "名草": {
        "url": "https://weathernews.jp/onebox/36.418930/139.466355/",
        "tenki_url": "https://tenki.jp/forecast/3/12/4110/9202/1hour.html",
        "hp_url": "https://ja-jp.facebook.com/nagusaturibori",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "名草釣堀", "tel": "0284-36-2480",
        "aliases": ["名草", "名草釣堀", "なぐさ"]
    },

    # --- 千葉県 ---
    "座間": {
        "url": "https://weathernews.jp/onebox/35.843581/140.010676/",
        "tenki_url": "https://tenki.jp/forecast/3/15/4510/12217/1hour.html",
        "hp_url": "http://zamayougyo.com/",
        "x_url": "", "fb_url": "https://www.facebook.com/people/%E5%BA%A7%E9%96%93%E9%A4%8A%E9%AD%9A%E5%A0%B4-762125983928950/", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "座間養魚場", "tel": "04-7192-1080",
        "aliases": ["ざま", "ザマ", "座間養魚場", "あめいず", "アメイズ", "amazトラウトエリア", "座間・amaz"]
    },
    "ジョイバレー": {
        "url": "https://weathernews.jp/onebox/35.744779/140.417401/",
        "tenki_url": "https://tenki.jp/forecast/3/15/4520/12409/1hour.html",
        "hp_url": "http://www.joyvalley.co.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "ジョイバレー 成田", "tel": "0479-78-1840",
        "aliases": ["ジョイバレー", "じょいばれー", "ジョイバ"]
    },
    "ウォルトン": {
        "url": "https://weathernews.jp/onebox/35.863326/140.290525/",
        "tenki_url": "https://tenki.jp/forecast/3/15/4510/12211/1hour.html",
        "hp_url": "https://www.waltongarden.net/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "ウォルトンガーデン", "tel": "0476-37-3315",
        "aliases": ["ウォルトン", "ウォルトンガーデン", "うぉるとん"]
    },
    "NOIKE": {
        "url": "https://weathernews.jp/onebox/35.576969/140.234786/",
        "tenki_url": "https://tenki.jp/forecast/3/15/4510/12104/1hour.html",
        "hp_url": "https://troutpond1089.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "trout pond NOIKE", "tel": "043-228-8283",
        "aliases": ["NOIKE", "ノイケ", "のいけ"]
    },
    "釣パラダイス": {
        "url": "https://weathernews.jp/onebox/35.653330/140.338663/",
        "tenki_url": "https://tenki.jp/forecast/3/15/4520/12237/1hour.html",
        "hp_url": "https://www.tsuripara.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "釣りパラダイス 山武", "tel": "043-445-1216",
        "aliases": ["釣パラダイス", "パラダイス", "釣りパラダイス", "つりぱら"]
    },

    # --- 埼玉県 ---
    "長瀞": {
        "url": "https://weathernews.jp/onebox/36.084376/139.104604/",
        "tenki_url": "https://tenki.jp/forecast/3/14/4330/11362/1hour.html",
        "hp_url": "https://waterpark.jp/fishing/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "ウォーターパーク長瀞", "tel": "0494-66-0312",
        "aliases": ["長瀞", "WP長瀞", "ウォーターパーク長瀞", "ながとろ"]
    },
    "彩の国": {
        "url": "https://weathernews.jp/onebox/35.992469/139.473372/",
        "tenki_url": "https://tenki.jp/forecast/3/14/4310/11346/1hour.html",
        "hp_url": "https://fs-sainokuni.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "フィッシングフィールド彩の国", "tel": "049-297-7815",
        "aliases": ["彩の国", "FF彩の国", "さいのくに"]
    },
    "朝霞Ｇ": {
        "url": "https://weathernews.jp/onebox/35.813481/139.604736/",
        "tenki_url": "https://tenki.jp/forecast/3/14/4310/11227/1hour.html",
        "hp_url": "http://www.asaka-garden.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "朝霞ガーデン", "tel": "048-456-0260",
        "aliases": ["朝霞Ｇ", "朝霞", "朝霞ガーデン", "アサカガーデン", "ガーデン", "あさか", "アサカ", "あさかガーデン"]
    },
    "しらこばと": {
        "url": "https://weathernews.jp/onebox/35.917970/139.752203/",
        "tenki_url": "https://tenki.jp/forecast/3/14/4310/11222/1hour.html",
        "hp_url": "https://www.parks.or.jp/shirakobatosuijo/guide/003/003811.html",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "しらこばと水上公園", "tel": "048-977-5111",
        "aliases": ["しらこばと", "しらこばと水上公園"]
    },
    "川越パーク": {
        "url": "https://weathernews.jp/onebox/35.907152/139.444046/",
        "tenki_url": "https://tenki.jp/forecast/3/14/4310/11201/1hour.html",
        "hp_url": "https://www.parks.or.jp/kawagoesuijo/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "川越水上公園", "tel": "049-241-2241",
        "aliases": ["川越パーク", "川越", "川越水上公園", "かわごえ"]
    },
    "加須はなさき": {
        "url": "https://weathernews.jp/onebox/36.096192/139.636601/",
        "tenki_url": "https://tenki.jp/forecast/3/14/4320/11210/1hour.html",
        "hp_url": "https://www.parks.or.jp/kazohanasaki/guide/000/000031.html",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "加須はなさき水上公園", "tel": "0480-65-7155",
        "aliases": ["加須はなさき", "はなさき", "はなさき公園"]
    },
    "中里": {
        "url": "https://weathernews.jp/onebox/36.163896/139.176567/",
        "tenki_url": "https://tenki.jp/forecast/3/14/4320/11381/1hour.html",
        "hp_url": "http://fish104.in.coocan.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "中里フィッシングクラブ", "tel": "0495-76-1120",
        "aliases": ["中里", "中里FC", "なかざと"]
    },
    "伊古の里": {
        "url": "https://weathernews.jp/onebox/36.071547/139.339037/",
        "tenki_url": "https://tenki.jp/forecast/3/14/4320/11341/1hour.html",
        "hp_url": "http://www.ikonosato.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "伊古の里フィッシングパーク", "tel": "0493-57-0505",
        "aliases": ["伊古", "伊古の里", "いこのさと", "伊古の里フィッシングパーク"]
    },

    # --- 神奈川県・東京都 ---
    "足柄": {
        "url": "https://weathernews.jp/onebox/35.319275/139.042723/",
        "tenki_url": "https://tenki.jp/forecast/3/17/4620/14217/1hour.html",
        "hp_url": "http://www.ashigara-ca.com/aca/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "足柄キャスティングエリア", "tel": "0465-73-2030",
        "aliases": ["足柄", "足柄CA", "あしがら"]
    },
    "中津川": {
        "url": "https://weathernews.jp/onebox/35.521698/139.285609/",
        "tenki_url": "https://tenki.jp/forecast/3/17/4620/14401/1hour.html",
        "hp_url": "http://www.nakatugawa-gyokyou.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "フィッシングフィールド中津川", "tel": "046-281-5421",
        "aliases": ["中津川", "FF中津川", "なかつがわ", "なかつ", "中津"]
    },
    "早戸川": {
        "url": "https://weathernews.jp/onebox/35.543063/139.216090/",
        "tenki_url": "https://tenki.jp/forecast/3/17/4620/14151/1hour.html",
        "hp_url": "http://www.hayatogawa.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "リヴァスポット早戸", "tel": "042-785-0774",
        "aliases": ["早戸川", "リヴァスポット早戸", "はやとがわ"]
    },
    "王禅寺": {
        "url": "https://weathernews.jp/onebox/35.587020/139.524309/",
        "tenki_url": "https://tenki.jp/forecast/3/17/4610/14137/1hour.html",
        "hp_url": "https://www.fishon-oz.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "BerryPark in 王禅寺", "tel": "044-959-0037",
        "aliases": ["王禅寺", "ベリーパーク in 王禅寺", "おうぜんじ", "王禅寺ベリーパーク", "寺", "てら"]
    },
    "開成": {
        "url": "https://weathernews.jp/onebox/35.334342/139.130344/",
        "tenki_url": "https://tenki.jp/forecast/3/17/4620/14366/1hour.html",
        "hp_url": "https://kaisei.forest-springs.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "開成水辺フォレストスプリングス", "tel": "0465-85-2020",
        "aliases": ["開成", "開成水辺フォレストスプリングス", "開成FS", "かいせい", "フォレストスプリングス"]
    },
    "浅川国際": {
        "url": "https://weathernews.jp/onebox/35.641903/139.231262/",
        "tenki_url": "https://tenki.jp/forecast/3/16/4410/13201/1hour.html",
        "hp_url": "http://www5c.biglobe.ne.jp/~fly-lure/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "浅川国際マス釣り場", "tel": "042-661-2228",
        "aliases": ["浅川国際", "浅川", "浅川国際マス釣り場", "あさかわ", "あさかわこくさい", "あさこく", "アサコク"]
    },

    # --- 山梨県・長野県 ---
    "鹿留": {
        "url": "https://weathernews.jp/onebox/35.512350/138.887160/",
        "tenki_url": "https://tenki.jp/forecast/3/22/4920/19204/1hour.html",
        "hp_url": "http://www.sisidome.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "ベリーパーク in 鹿留", "tel": "0554-43-0082",
        "aliases": ["鹿留", "シシドメ", "ししどめ", "ベリーパーク"]
    },
    "小菅": {
        "url": "https://weathernews.jp/onebox/35.760330/138.940529/",
        "tenki_url": "https://tenki.jp/forecast/3/22/4920/19442/1hour.html",
        "hp_url": "http://kosuge-tg.com/",
        "x_url": "", "fb_url": "", "insta_url": "https://kosugetg.jugem.jp/", "yt_url": "",
        "search_name": "小菅トラウトガーデン", "tel": "0428-87-0373",
        "aliases": ["小菅", "小菅TG", "こすげ"]
    },
    "奈良子": {
        "url": "https://weathernews.jp/onebox/35.672184/138.917831/",
        "tenki_url": "https://tenki.jp/forecast/3/22/4920/19206/1hour.html",
        "hp_url": "https://www.narago.jp/index.html",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "奈良子釣りセンター", "tel": "0554-24-7636",
        "aliases": ["奈良子", "奈良子釣りセンター", "ならこ", "ならご", "ナラコ", "ナラゴ", "ならごつりせんたー", "ナラゴツリセンター"]
    },
    "シルフ": {
        "url": "https://weathernews.jp/onebox/35.778458/138.316489/",
        "tenki_url": "https://tenki.jp/forecast/3/22/4910/19209/1hour.html",
        "hp_url": "https://shylph.boy.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "白州トラウトフィッシングエリア", "tel": "0551-35-4308",
        "aliases": ["シルフ", "Shylph", "しるふ"]
    },
    "ツガネ": {
        "url": "https://weathernews.jp/onebox/35.866755/138.451406/",
        "tenki_url": "https://tenki.jp/forecast/3/22/4910/19209/1hour.html",
        "hp_url": "http://www6.nns.ne.jp/~joy-field/index.html",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "ジョイフィールド in Tsugane", "tel": "0551-20-7888",
        "aliases": ["つがね", "ツガネ", "津金", "ジョイフィールド", "じょいふぃーるど", "JF in Tsugane"]
    },
    "竜華池": {
        "url": "https://weathernews.jp/onebox/35.681978/138.576164/",
        "tenki_url": "https://tenki.jp/forecast/3/22/4910/19201/1hour.html",
        "hp_url": "https://fishingmarketbear.wixsite.com/ryugaike",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "フィッシングパーク竜華池", "tel": "055-252-0938",
        "aliases": ["竜華池", "りゅうがいけ", "竜华池"]
    },
    "平谷湖": {
        "url": "https://weathernews.jp/onebox/35.332243/137.632213/",
        "tenki_url": "https://tenki.jp/forecast/3/23/4830/20409/1hour.html",
        "hp_url": "https://hirayako.com/",
        "x_url": "", "fb_url": "", "insta_url": "https://ameblo.jp/hirayakobakucho/", "yt_url": "",
        "search_name": "平谷湖フィッシングスポット", "tel": "0265-48-1127",
        "aliases": ["平谷湖", "平谷湖フィッシングスポット", "ひらやこ"]
    },
    "ハーブ": {
        "url": "https://weathernews.jp/onebox/36.403436/137.890526/",
        "tenki_url": "https://tenki.jp/forecast/3/23/4810/20485/1hour.html",
        "hp_url": "https://herbfa1995.kikirara.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "ハーブの里フィッシングエリア", "tel": "0261-62-6322",
        "aliases": ["ハーブ", "はーぶ", "ハーブの里", "はーぶの里", "里", "さと"]
    },
    "ニレ池": {
        "url": "https://weathernews.jp/onebox/36.712669/137.845826/",
        "tenki_url": "https://tenki.jp/forecast/3/23/4810/20485/1hour.html",
        "hp_url": "http://www.nireike.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "白馬八方ニレ池フィッシングセンター", "tel": "0261-72-5086",
        "aliases": ["ニレ池", "にれいけ"]
    },
    "鹿島やり": {
        "url": "https://weathernews.jp/onebox/36.548940/137.809757/",
        "tenki_url": "https://tenki.jp/forecast/3/23/4810/20212/1hour.html",
        "hp_url": "https://www.kashimayari-garden.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "鹿島槍ガーデン", "tel": "0261-22-2253",
        "aliases": ["鹿島", "かしまやり", "カシマヤリ", "鹿島槍", "鹿島槍ガーデン"]
    },
    "つきの池": {
        "url": "https://weathernews.jp/onebox/36.011582/138.197271/",
        "tenki_url": "https://tenki.jp/forecast/3/23/4820/20214/1hour.html",
        "hp_url": "http://www.tsukinoike.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "槻の池フィッシングエリア", "tel": "0266-76-2280",
        "aliases": ["つきの池", "槻の池", "槻の池フィッシングエリア", "つきのいけ"]
    },
    "あずみ野": {
        "url": "https://weathernews.jp/onebox/36.337699/137.885455/",
        "tenki_url": "https://tenki.jp/forecast/3/23/4820/20220/1hour.html",
        "hp_url": "http://www7b.biglobe.ne.jp/~azuminoturibori/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "あずみ野フィッシングセンター", "tel": "0263-82-8280",
        "aliases": ["あずみ野", "あずみ野FC", "あずみの"]
    },

    # --- 群馬県 ---
    "川場": {
        "url": "https://weathernews.jp/onebox/36.690767/139.121662/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4220/10444/1hour.html",
        "hp_url": "http://www.kawaba-fp.jp/",
        "x_url": "", "fb_url": "", "insta_url": "https://www.instagram.com/kawaba.numata.fishingplaza/?utm_source=ig_embed", "blog_url": "", "yt_url": "",
        "search_name": "川場フィッシングプラザ", "tel": "0278-52-3200",
        "aliases": ["川場", "川場FP", "かわば", "カワバ"]
    },
    "キングダム": {
        "url": "https://weathernews.jp/onebox/36.754213/139.142256/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4220/10444/1hour.html",
        "hp_url": "http://kawaba-kingdomfishing.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "川場キングダムフィッシング", "tel": "0278-52-2002",
        "aliases": ["きんぐだむ", "キングダム", "かわばきんぐだむ", "川場キングダム"]
    },
    "おくとね": {
        "url": "https://weathernews.jp/onebox/36.663005/139.163750/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4220/10206/1hour.html",
        "hp_url": "http://www7.wind.ne.jp/okutone/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "おくとねフィッシングパーク", "tel": "0278-53-3802",
        "aliases": ["おくとね", "おくとねFP"]
    },
    "イワセン": {
        "url": "https://weathernews.jp/onebox/36.610095/139.243740/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4220/10206/1hour.html",
        "hp_url": "http://www7.wind.ne.jp/okutone/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "日本イワナセンター", "tel": "0278-54-8433",
        "aliases": ["いわなせんたー", "イワナセンター", "いわせん", "イワセン", "イワナ", "いわな"]
    },
    "黒保根": {
        "url": "https://weathernews.jp/onebox/36.515041/139.252324/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4210/10203/1hour.html",
        "hp_url": "https://www.kurohone-fishing.com/",
        "x_url": "https://twitter.com/kurohoneKF", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "黒保根渓流フィッシング", "tel": "0277-96-2091",
        "aliases": ["黒保根", "くろほね"]
    },
    "迦葉山": {
        "url": "https://weathernews.jp/onebox/36.685419/139.071387/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4220/10206/1hour.html",
        "hp_url": "http://www.fp-berrys.net/",
        "x_url": "", "fb_url": "", "insta_url": "https://ameblo.jp/fp-berrys2006/", "yt_url": "",
        "search_name": "ベリーズ迦葉山", "tel": "0278-23-9333",
        "aliases": ["迦葉山", "ベリーズ迦葉山", "かしょうざん", "ベリーズ"]
    },
    "片品": {
        "url": "https://weathernews.jp/onebox/36.624564/139.046703/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4220/10206/1hour.html",
        "hp_url": "https://www.turinavi.info/gunma/katashinagawakokusai/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "片品川国際マス釣り場", "tel": "0278-24-1188",
        "aliases": ["片品", "片品川国際", "かたしな"]
    },
    "中之沢": {
        "url": "https://weathernews.jp/onebox/36.492057/139.195293/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4210/10201/1hour.html",
        "hp_url": "http://gfc.sakura.ne.jp/index.htm",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "GFC中之沢", "tel": "027-283-3532",
        "aliases": ["中之沢", "GFC中之沢", "なかのさわ"]
    },
    "宮城": {
        "url": "https://weathernews.jp/onebox/36.483735/139.188251/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4210/10201/1hour.html",
        "hp_url": "http://www.anglers-village.com/index2.html",
        "x_url": "", "fb_url": "https://www.facebook.com/people/%E5%AE%AE%E5%9F%8E%E3%82%A2%E3%83%B3%E3%82%B0%E3%83%A9%E3%83%BC%E3%82%BA%E3%83%B4%E3%82%A3%E3%83%AC%E3%83%83%E3%82%B8/100049219011936/#", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "宮城アングラーズヴィレッジ", "tel": "027-283-0035",
        "aliases": ["マブ", "まぶ", "みやぎ", "ミヤギ", "宮城", "アンビレ", "ＭＡＶ", "宮城AV", "みやぎあんぐらーず", "MAV", "mav"]
    },
    "大崎・赤城": {
        "url": "https://weathernews.jp/onebox/36.463209/139.164867/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4210/10201/1hour.html",
        "hp_url": "https://nijimasu.com/", "hp2_url": "https://anglers-base.com/",  
        "search_name": "大崎つりぼり", "tel": "027-283-2945",
        "aliases": ["大崎・赤城", "大崎", "赤城", "大崎つりぼり", "アングラーズベース", "アングラーズベース赤城山", "おおさき", "あかぎ", "オオサキ", "アカギ", "ABA", "大崎釣り堀"]
    },
    "けん太": {
        "url": "https://weathernews.jp/onebox/36.386648/138.960021/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4210/10202/1hour.html",
        "hp_url": "http://www.tsurikichikenta.com/index.htm",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "釣りキチけん太", "tel": "027-371-3312",
        "aliases": ["けん太", "釣りキチけん太", "けんた"]
    },
    "フック": {
        "url": "https://weathernews.jp/onebox/36.457699/139.173191/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4210/10201/1hour.html",
        "hp_url": "https://aa-hook.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "アングラーズエリアHOOK", "tel": "027-283-0535",
        "aliases": ["フック", "HOOK", "ふっく"]
    },
    "赤久縄": {
        "url": "https://weathernews.jp/onebox/36.160894/138.895355/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4210/10209/1hour.html",
        "hp_url": "https://www.akaguna.net/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "赤久縄", "tel": "0274-56-0230",
        "aliases": ["赤久縄", "あかぐな"]
    },
    "太田": {
        "url": "https://weathernews.jp/onebox/36.357774/139.330830/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4210/10205/1hour.html",
        "hp_url": "https://www.facebook.com/otafishingclub/",
        "x_url": "", "fb_url": "https://www.facebook.com/otafishingclub/", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "太田フィッシングクラブ", "tel": "0276-32-1230",
        "aliases": ["太田", "太田FC", "おおた"]
    },
    "東山道": {
        "url": "https://weathernews.jp/onebox/36.323047/139.280989/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4210/10205/1hour.html",
        "hp_url": "https://emrp-fishing.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "東山道公園フィッシングエリア", "tel": "0276-56-1180",
        "aliases": ["東山道", "東山道FA", "とうさんどう"]
    },
    "榛名": {
        "url": "https://weathernews.jp/onebox/36.443570/138.898498/",
        "tenki_url": "https://tenki.jp/forecast/3/13/4210/10202/1hour.html",
        "hp_url": "https://haruna-turibori.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "榛名高原つり堀センター", "tel": "027-374-2228",
        "aliases": ["榛名", "榛名高原", "はるな"]
    },

    # --- 茨城県 ---
    "水戸南": {
        "url": "https://weathernews.jp/onebox/36.326377/140.501362/",
        "tenki_url": "https://tenki.jp/forecast/3/11/4020/8230/1hour.html",
        "hp_url": "http://www.mitominami-fa.jp/index.html",
        "x_url": "https://x.com/TSURIBORIMITO?lang=ja", "fb_url": "", "insta_url": "https://www.instagram.com/tsuriborimitominami/", "blog_url": "", "yt_url": "",
        "search_name": "水戸南フィッシングエリア", "tel": "029-246-1233",
        "aliases": ["水戸南", "水戸南FA", "みとみなみ"]
    },
    "高萩": {
        "url": "https://weathernews.jp/onebox/36.788035/140.577243/",
        "tenki_url": "https://tenki.jp/forecast/3/11/4010/8214/1hour.html",
        "hp_url": "https://takahagifureainosato.web.fc2.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "高萩ふれあいの里フィッシングエリア", "tel": "0293-24-1888",
        "aliases": ["高萩", "高萩ふれあいの里", "たかはぎ"]
    },
    "つくば園": {
        "url": "https://weathernews.jp/onebox/36.224122/140.144261/",
        "tenki_url": "https://tenki.jp/forecast/3/11/4020/8205/1hour.html",
        "hp_url": "http://tsukuba-en.jp/",
        "x_url": "", "fb_url": "https://www.facebook.com/tsukubaen5355/?ref=page_internal", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "フィッシングパークつくば園", "tel": "0299-43-6111",
        "aliases": ["つくば園", "つくばえん"]
    },
    "Ｊ": {
        "url": "https://weathernews.jp/onebox/36.081494/140.164360/",
        "tenki_url": "https://tenki.jp/forecast/3/11/4020/8203/1hour.html",
        "hp_url": "https://sites.google.com/view/fishing-area-j/",
        "x_url": "https://x.com/madara_area_j", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "フィッシングエリアJ", "tel": "029-842-1698",
        "aliases": ["Ｊ", "J", "FAJ", "フィッシングエリアJ", "ふぃっしんぐえりあじぇい", "じぇー", "じぇい", "ジェー"]
    },
    "ユザキ": {
        "url": "https://weathernews.jp/onebox/36.314550/140.335285/",
        "tenki_url": "https://tenki.jp/forecast/3/11/4010/8216/1hour.html",
        "hp_url": "https://yuzakiko.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "レイクユザキ", "tel": "0296-77-8500",
        "aliases": ["ユザキ", "レイクユザキ", "ゆざき"]
    },
    "笠間": {
        "url": "https://weathernews.jp/onebox/36.412866/140.208145/",
        "tenki_url": "https://tenki.jp/forecast/3/11/4010/8216/1hour.html",
        "hp_url": "http://www.leisure-park-kasama.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "レジャーパーク笠間", "tel": "0296-72-8888",
        "aliases": ["笠間", "LP笠間", "かさま"]
    },
    "DoDoo": {
        "url": "https://weathernews.jp/onebox/36.187994/140.216734/",
        "tenki_url": "https://tenki.jp/forecast/3/11/4020/8230/1hour.html",
        "hp_url": "http://www.fishing-dodoo.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "フィッシングDoDoo", "tel": "0299-59-7052",
        "aliases": ["DoDoo", "ドゥドゥー", "どぅどぅー"]
    },
    "若栗": {
        "url": "https://weathernews.jp/onebox/36.779644/140.633185/",
        "tenki_url": "https://tenki.jp/forecast/3/11/4010/8214/1hour.html",
        "hp_url": "http://wakagurinomori.ina-ka.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "若栗フィッシングの森", "tel": "0293-23-3882",
        "aliases": ["若栗", "若栗フィッシングの森", "わかぐり"]
    },
    "ミッドクリーク": {
        "url": "https://weathernews.jp/onebox/36.192975/140.164058/",
        "tenki_url": "https://tenki.jp/forecast/3/11/4020/8205/1hour.html",
        "hp_url": "http://midcreek.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "ミッドクリークフィッシングエリア", "tel": "0299-42-4578",
        "aliases": ["ミッドクリーク", "みっどくりーく"]
    },

    # --- 東北・東海・関西 ---
    "Lost Lures": {
        "url": "https://weathernews.jp/onebox/37.081688/139.680305/",
        "tenki_url": "https://tenki.jp/forecast/2/10/3630/7368/1hour.html",
        "hp_url": "https://www.lost-lures.com/",
        "x_url": "https://x.com/lostlures", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "https://www.youtube.com/@lostlures/videos",
        "search_name": "ロストルアーズ", "tel": "0241-66-3266",
        "aliases": ["Lost Lures", "lost lures", "ロストルアーズ", "ろすとるあーず", "ろすとるあー", "ロストルアー", "ろすと", "ロスト"]
    },
    "不忘": {
        "url": "https://weathernews.jp/onebox/38.042491/140.554478/",
        "tenki_url": "https://tenki.jp/forecast/2/7/3420/4206/1hour.html",
        "hp_url": "http://www.fubou.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "グリーンパーク不忘", "tel": "0224-24-8131",
        "aliases": ["ぐりーんぱーくふぼう", "グリーンパークフボウ", "不忘", "ふぼう", "フボウ", "ぐりーんぱーく", "グリーンパーク"]
    },
    "白河": {
        "url": "https://weathernews.jp/onebox/37.127955/140.081827/",
        "tenki_url": "https://tenki.jp/forecast/2/10/3610/7461/1hour.html",
        "hp_url": "https://shirakawa.forest-springs.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "白河フォレストスプリングス", "tel": "0248-25-3535",
        "aliases": ["白河", "白河フォレストスプリングス", "白河FS", "しらかわ"]
    },
    "ほのぼの": {
        "url": "https://weathernews.jp/onebox/36.837687/140.472433/",
        "tenki_url": "https://tenki.jp/forecast/2/10/3610/7482/1hour.html",
        "hp_url": "http://honobono.travel.coocan.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "ほのぼのフィッシングエリア", "tel": "0247-46-3200",
        "aliases": ["ほのぼの", "ほのぼのプール"]
    },
    "WaDoNa": {
        "url": "https://weathernews.jp/onebox/36.877372/140.540954/",
        "tenki_url": "https://tenki.jp/forecast/2/10/3610/7483/1hour.html",
        "hp_url": "https://wadona.work/",
        "x_url": "https://x.com/wadonanikko", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "WaDoNa 釣り場", "tel": "090-3121-6677",
        "aliases": ["WaDoNa", "ワドナ", "わどな"]
    },
    "鶴沼川": {
        "url": "https://weathernews.jp/onebox/37.255460/139.872256/",
        "tenki_url": "https://tenki.jp/forecast/2/10/3630/7362/1hour.html",
        "hp_url": "https://aizuiwanacenter.com/",
        "x_url": "https://x.com/4knL7KqJ86Iu9Ya", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "鶴沼川フィッシングパーク", "tel": "0241-67-2708",
        "aliases": ["鶴沼川", "つるぬまがわ", "鶴沼"]
    },
    "オーパ": {
        "url": "https://weathernews.jp/onebox/37.314342/140.449245/",
        "tenki_url": "https://tenki.jp/forecast/2/10/3610/7203/1hour.html",
        "hp_url": "https://welcomeohpa.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "ウエルカムオーパ", "tel": "024-954-2007",
        "aliases": ["オーパ", "ウエルカムオーパ", "おーぱ"]
    },
    "あいづ": {
        "url": "https://weathernews.jp/onebox/37.204977/139.729681/",
        "tenki_url": "https://tenki.jp/forecast/2/10/3630/7368/1hour.html",
        "hp_url": "https://aizufishing.jp/",
        "x_url": "https://x.com/aizufishing", "fb_url": "", "insta_url": "https://ameblo.jp/aizu2024/", "yt_url": "",
        "search_name": "あいづフィッシングエリア", "tel": "0241-64-2101",
        "aliases": ["あいづ", "あいづFA"]
    },
    "上浜": {
        "url": "https://weathernews.jp/onebox/39.142616/139.945938/",
        "tenki_url": "https://tenki.jp/forecast/2/8/3210/5214/1hour.html",
        "hp_url": "http://kamihama.web.fc2.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "上浜釣り場", "tel": "0184-38-3488",
        "aliases": ["上浜", "上浜釣り場", "かみはま"]
    },
    "GOZU": {
        "url": "https://weathernews.jp/onebox/37.819471/139.238518/",
        "tenki_url": "https://tenki.jp/forecast/4/18/5410/15223/1hour.html",
        "hp_url": "http://www.gozu-fp.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "五頭フィッシングパーク", "tel": "0250-63-0051",
        "aliases": ["GOZU", "ごず", "五頭", "ごづ", "五頭FP", "五頭フィッシングパーク", "gozu"]
    },
    "FCE瑞浪": {
        "url": "https://weathernews.jp/onebox/35.433516/137.295266/",
        "tenki_url": "https://tenki.jp/forecast/5/24/5210/21208/1hour.html",
        "hp_url": "https://www.fishing-autocamp-mizunami.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "フィッシングキャンプエリア瑞浪", "tel": "0572-68-1212",
        "aliases": ["FCE瑞浪", "瑞浪", "FC瑞浪", "みずなみ", "フィッシングキャンプエリアミズナミ", "フィッシングキャンプエリア瑞浪"]
    },
    "３９": {
        "url": "https://weathernews.jp/onebox/35.187504/136.457803/",
        "tenki_url": "https://tenki.jp/forecast/5/27/5310/24214/1hour.html",
        "hp_url": "https://go-sanctuary.com/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "フィッシングサンクチュアリ", "tel": "0594-46-8820",
        "aliases": ["３９", "サンクチュアリ", "サンク", "さんくちゅあり", "39"]
    },
    "醒井": {
        "url": "https://weathernews.jp/onebox/35.303671/136.349914/",
        "tenki_url": "https://tenki.jp/forecast/6/28/6020/25214/1hour.html",
        "hp_url": "http://samegai.siga.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "醒井養鱒場", "tel": "0749-54-0301",
        "aliases": ["醒井", "醒井養鱒場", "さめがい"]
    },
    "高島の泉": {
        "url": "https://weathernews.jp/onebox/35.348308/136.052288/",
        "tenki_url": "https://tenki.jp/forecast/6/28/6020/25212/1hour.html",
        "hp_url": "https://www.takashimanoizumi.com/",
        "x_url": "https://x.com/takashima_izumi", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "高島の泉", "tel": "0740-25-3790",
        "aliases": ["高島の泉", "高島", "たかしまのいずみ", "たかしま"]
    },
    "千早川": {
        "url": "https://weathernews.jp/onebox/34.417118/135.647482/",
        "tenki_url": "https://tenki.jp/forecast/6/30/6200/27383/1hour.html",
        "hp_url": "http://chihayagawa.jp/",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "千早川マス釣り場", "tel": "0721-74-0116",
        "aliases": ["千早川", "千早川マス釣り場", "ちはやがわ"]
    }
}

# --- バス釣り用データ定義 ---
BASS_SPOT_WEATHER_DATA = {
    "亀山湖": {
        "url": "https://weathernews.jp/onebox/35.23/140.09/",
        "tenki_url": "https://tenki.jp/forecast/3/15/4530/12225/1hour.html",
        "hp_url": "", "hp2_url": "",
        "hide_default_map": True,
        "custom_button_rows": [
            [
                {"label": "🌐つばき", "url": "https://tubakimoto.com/sp/"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/search/?api=1&query=" + quote("亀山湖 つばきもとボート")}
            ],
            [
                {"label": "🌐のむら", "url": "https://nomuraboat.com/"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/search/?api=1&query=" + quote("亀山湖 のむらボートハウス")}
            ],
            [
                {"label": "🌐トキタ", "url": "http://www.tokitaboat.com/"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/search/?api=1&query=" + quote("亀山湖 トキタボート")}
            ]
        ],
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "亀山湖", "tel": "",
        "aliases": ["亀山湖", "亀山ダム", "かめやまこ", "亀山"]
    },
    "高滝湖": {
        "url": "https://weathernews.jp/onebox/35.34/140.15/",
        "tenki_url": "https://tenki.jp/forecast/3/15/4510/12219/1hour.html",
        "hp_url": "", "hp2_url": "",
        "hide_default_map": True,
        "custom_button_rows": [
            [
                {"label": "🌐ボート", "url": "http://www.takatakiko.jp/"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/place/%E9%AB%98%E6%BB%9D%E6%B9%96%E8%A6%B3%E5%85%89%E4%BC%81%E6%A5%AD%E7%B5%84%E5%90%88/data=!4m2!3m1!1s0x0:0xeaa9dddefc1dab6?sa=X&ved=1t:2428&ictx=111"}
            ]
        ],
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "高滝湖", "tel": "",
        "aliases": ["高滝湖", "高滝ダム", "たかたきこ", "高滝", "たかたき"]
    },
    "GGD": {
        "url": "https://weathernews.jp/onebox/36.103735/139.726303/",
        "tenki_url": "https://tenki.jp/forecast/3/14/4320/11232/1hour.html",
        "hp_url": "", "hp2_url": "",
        "map_url": "https://www.google.com/maps/place/36%C2%B006'13.5%22N+139%C2%B043'34.7%22E/@36.103735,139.7237281,17z/data=!3m1!4b1!4m4!3m3!8m2!3d36.103735!4d139.726303",
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "権現堂川", "tel": "",
        "aliases": ["GGD", "権現堂川", "権現堂", "ごんげんどう", "ggd", "権現堂公園"]
    },
    "片倉ダム": {
        "url": "https://weathernews.jp/onebox/35.198/140.070/",
        "tenki_url": "https://tenki.jp/forecast/3/15/4530/12225/1hour.html",
        "hp_url": "", "hp2_url": "",
        "hide_default_map": True,
        "custom_button_rows": [
            [
                {"label": "🌐笹川", "url": "http://sasagawab.xsrv.jp/index555555.htm"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/place/%E3%83%AC%E3%83%B3%E3%82%BF%E3%83%AB%E3%83%9C%E3%83%BC%E3%83%88%E7%AC%B9%E5%B7%9D+%E7%AC%B9%E5%B7%9D%E3%83%9C%E3%83%BC%E3%83%88/@35.199604,140.071301,17z/data=!4m6!3m5!1s0x6022abc7ec99af2b:0xf3ec8e21fec19bac!8m2!3d35.199604!4d140.071301!16s%2Fg%2F1tfn2w38"}
            ],
            [
                {"label": "🌐すずき", "url": "https://shop-hp.com/suzuki/"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/place/%E3%83%AC%E3%83%B3%E3%82%BF%E3%83%AB%E3%83%9C%E3%83%BC%E3%83%88%E3%81%99%E3%81%9A%E3%81%8D/@35.1965734,140.0701992,17z/data=!4m6!3m5!1s0x6022abb789c73453:0x7cbbb99574db9fa!8m2!3d35.1965734!4d140.0701992!16s%2Fg%2F1t_wpgq2"}
            ],
            [
                {"label": "🌐もとよし", "url": "https://www.kimitsu-rentalboatmotoyoshi.com/"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/place/%E3%83%AC%E3%83%B3%E3%82%BF%E3%83%AB%E3%83%9C%E3%83%BC%E3%83%88%E3%82%82%E3%81%A8%E3%82%88%E3%81%97/@35.193371,140.062838,17z/data=!4m6!3m5!1s0x6022abb5ac3b3e55:0xd4e187031199a582!8m2!3d35.193371!4d140.062838!16s%2Fg%2F12hmg6w0f"}
            ]
        ],
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "片倉ダム", "tel": "",
        "aliases": ["片倉ダム", "笹川湖", "かたくらだむ", "かたくら", "片倉"]
    },
    "三島湖": {
        "url": "https://weathernews.jp/onebox/35.211/140.033/",
        "tenki_url": "https://tenki.jp/forecast/3/15/4530/12225/1hour.html",
        "hp_url": "", "hp2_url": "",
        "hide_default_map": True,
        "custom_button_rows": [
            [
                {"label": "🌐ともえ", "url": "https://tomoeboat.jp/"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/place/%E3%81%A8%E3%82%82%E3%82%91%E9%87%A3%E8%88%9F%E5%BA%97/@35.2125738,140.032063,17z/data=!4m6!3m5!1s0x6022a9ee4ef4324f:0xfcc38c1093948001!8m2!3d35.2125738!4d140.032063!16s%2Fg%2F1tg15vsm"}
            ],
            [
                {"label": "🌐石井", "url": "https://mishimako-ishii-bass.net/"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/place/%E7%9F%B3%E4%BA%95%E9%87%A3%E8%88%9F%E5%BA%97/@35.209197,140.03331,17z/data=!4m6!3m5!1s0x6022a9f1763b3519:0x994b241807e038bf!8m2!3d35.209197!4d140.03331!16s%2Fg%2F1tfn2w37"}
            ],
            [
                {"label": "🌐ロッヂ", "url": "https://bousou60.net/"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/place/%E6%88%BF%E7%B7%8F%E3%83%AD%E3%83%83%E3%83%82%E9%87%A3%E3%82%8A%E3%82%BB%E3%83%B3%E3%82%BF%E3%83%BC/@35.2114932,140.0332243,17z/data=!4m6!3m5!1s0x6022a9ee1f03983d:0x517ca52856b81f5a!8m2!3d35.2114932!4d140.0332243!16s%2Fg%2F1ts2_d6_"}
            ]
        ],
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "三島湖", "tel": "",
        "aliases": ["三島湖", "三島ダム", "みしまこ", "みしま", "三島"]
    },
    "豊英ダム": {
        "url": "https://weathernews.jp/onebox/35.190041/140.015195/",
        "tenki_url": "https://tenki.jp/forecast/3/15/4530/12225/1hour.html",
        "hp_url": "", "hp2_url": "",
        "hide_default_map": True,
        "custom_button_rows": [
            [
                {"label": "🌐豊英湖", "url": "https://www.bassinheaven.com/toyofusa/toyofusaindex.html"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/place/%E8%B1%8A%E8%8B%B1%E6%B9%96%E3%81%A4%E3%82%8A%E8%88%9F%E3%82%BB%E3%83%B3%E3%82%BF%E3%83%BC/@35.190041,140.015195,17z/data=!4m6!3m5!1s0x601800a9666e2423:0xb9b78a967c956e!8m2!3d35.190041!4d140.015195!16s%2Fg%2F1tjg_9xs"}
            ]
        ],
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "豊英ダム", "tel": "",
        "aliases": ["豊英ダム", "豊英湖", "とよふさ", "豊英", "豊栄ダム", "豊栄"]
    },
    "相模湖": {
        "url": "https://weathernews.jp/onebox/35.6122/139.1567/",
        "tenki_url": "https://tenki.jp/forecast/3/17/4620/14151/1hour.html",
        "hp_url": "", "hp2_url": "",
        "hide_default_map": True,
        "custom_button_rows": [
            [
                {"label": "🌐日相園", "url": "https://nissoen.com/fishing.html"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/place/%E6%97%A5%E7%9B%B8%E5%9C%92/@35.6122284,139.1567688,17z/data=!4m9!3m8!1s0x601916e4bc54fcd1:0xaae699bbf6f6a491!5m2!4m1!1i2!8m2!3d35.6122284!4d139.1567688!16s%2Fg%2F1tdy935d"}
            ],
            [
                {"label": "🌐小川亭", "url": "https://www.ogawatei.info/"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/place/%E5%B0%8F%E5%B7%9D%E4%BA%AD%E3%83%9C%E3%83%BC%E3%83%88%E4%B9%97%E3%82%8A%E5%A0%B4/@35.6125584,139.1929263,17z/data=!4m6!3m5!1s0x601917dc454d5fdd:0x96e49dec990ec06d!8m2!3d35.6125584!4d139.1929263!16s%2Fg%2F11ghq01q9k"}
            ],
            [
                {"label": "🌐柴田", "url": "https://www.shibata-boat.com/"},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/place/%E6%9F%B4%E7%94%B0%E3%83%9C%E3%83%BC%E3%83%88/@35.6147906,139.1714628,17z/data=!4m6!3m5!1s0x60191719f57c043f:0xe8099ba9d0727d8b!8m2!3d35.6147906!4d139.1714628!16s%2Fg%2F1tvrzs4p"}
            ]
        ],
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "相模湖", "tel": "",
        "aliases": ["相模湖", "さがみこ", "さがみ"]
    },
    "東山ダム": {
        "url": "https://weathernews.jp/onebox/37.460705/139.965895/",
        "tenki_url": "https://tenki.jp/forecast/2/10/3630/7202/1hour.html",
        "hp_url": "", "hp2_url": "",
        "hide_default_map": True,
        "custom_button_rows": [
            [
                {"label": "🚷陸っぱり", "url": ""},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/search/%E6%9D%B1%E5%B1%B1%E3%83%80%E3%83%A0/@37.4607054,139.9658954,17z"}
            ]
        ],
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "東山ダム", "tel": "",
        "aliases": ["東山ダム", "ひがしやまだむ", "ひがしやま"]
    },
    # ★ 羽鳥湖を追加 ★
    "羽鳥湖": {
        "url": "https://weathernews.jp/onebox/37.261/140.079/",
        "tenki_url": "https://tenki.jp/forecast/2/10/3610/7461/1hour.html",
        "hp_url": "", "hp2_url": "",
        "hide_default_map": True,
        "custom_button_rows": [
            [
                {"label": "🚷陸っぱり", "url": ""},
                {"label": "🗺️地図", "url": "https://www.google.com/maps/place/%E7%BE%BD%E9%B3%A5%E3%83%80%E3%83%A0/@37.2715954,140.0769915,17.25z/data=!4m14!1m7!3m6!1s0x60201e92da9ad8eb:0xad0e8032ff7d73cc!2z57696bOl5rmW!8m2!3d37.2613577!4d140.0791107!16s%2Fg%2F1yl491l68!3m5!1s0x60201c21470050c1:0x591eec4fb9db922e!8m2!3d37.2715547!4d140.0760678!16s%2Fm%2F04n1yk0"}
            ]
        ],
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "羽鳥湖", "tel": "",
        "aliases": ["羽鳥湖", "羽鳥ダム", "はとりこ", "はとり"]
    },
    # ★ 桧原湖を追加 ★
    "桧原湖": {
        "url": "https://weathernews.jp/onebox/37.652/140.062/",
        "tenki_url": "https://tenki.jp/forecast/2/10/3630/7428/1hour.html",
        "hp_url": "", "hp2_url": "",
        "hide_default_map": True,
        "custom_button_rows": [
            [
                {"label": "🌐ゴールドH", "url": "https://gmeguro.com/"},
                {"label": "🗺️地図", "url": "https://www.google.co.jp/maps/place/%E3%80%92969-2701+%E7%A6%8F%E5%B3%B6%E7%9C%8C%E8%80%B6%E9%BA%BB%E9%83%A1%E5%8C%97%E5%A1%A9%E5%8E%9F%E6%9D%91%E6%AA%9C%E5%8E%9F%E5%A4%A7%E5%BA%9C%E5%B9%B3%E5%8E%9F%EF%BC%91%EF%BC%91%EF%BC%97%EF%BC%92%E2%88%92%EF%BC%94/@37.6529382,140.0621476,17z/data=!3m1!4b1!4m6!3m5!1s0x5f8abb0db874825d:0x68d33e5c0fb7e72d!8m2!3d37.6529382!4d140.0647225!16s%2Fg%2F11ggzdspy0"}
            ]
        ],
        "x_url": "", "fb_url": "", "insta_url": "", "blog_url": "", "yt_url": "",
        "search_name": "桧原湖", "tel": "",
        "aliases": ["桧原湖", "ひばらこ", "ひばら", "桧原", "裏磐梯"]
    }
}

COLOR_GROUPS = [
    {
        "title": "📍 静岡・神奈川・東京・千葉",
        "header_bg": "#0066cc",
        "sub_groups": [
            {"bg": "#e6f0fa", "spots": ["東山湖", "すその", "須川", "アルクス焼津", "浜名湖"]},
            {"bg": "#d4e6f1", "spots": ["足柄", "中津川", "早戸川", "王禅寺", "開成", "浅川国際"]},
            {"bg": "#cce5ff", "spots": ["座間", "ジョイバレー", "ウォルトン", "NOIKE", "釣パラダイス"]}
        ]
    },
    {
        "title": "📍 埼玉・群馬",
        "header_bg": "#2e7d32",
        "sub_groups": [
            {"bg": "#e8f5e9", "spots": ["長瀞", "彩の国", "朝霞Ｇ", "しらこばと", "川越パーク", "加須はなさき", "中里", "伊古の里"]},
            {"bg": "#c8e6c9", "spots": ["川場", "キングダム", "おくとね", "イワセン", "黒保根", "迦葉山", "片品", "中之沢", "宮城", "大崎・赤城", "けん太", "フック", "赤久縄", "太田", "東山道", "榛名"]}
        ]
    },
    {
        "title": "📍 栃木・茨城",
        "header_bg": "#e65100",
        "sub_groups": [
            {"bg": "#fff3e0", "spots": ["キング", "みどり", "那須高原", "尚仁沢", "つり天国", "関根養魚場", "408", "308", "蛇尾（さび）川", "レイクウッド", "なら山沼", "大芦川", "加賀", "発光路", "上永野", "柏倉", "遊水園", "アルクス宇都宮", "エリア21", "ベアーズパーク", "鬼怒川", "名草"]},
            {"bg": "#ffe0b2", "spots": ["水戸南", "高萩", "つくば園", "Ｊ", "ユザキ", "笠間", "DoDoo", "若栗", "ミッドクリーク"]}
        ]
    },
    {
        "title": "📍 甲信・東北・東海・関西",
        "header_bg": "#6a1b9a",
        "sub_groups": [
            {"bg": "#f3e5f5", "spots": ["鹿留", "小菅", "奈良子", "シルフ", "ツガネ", "竜华池", "平谷湖", "ハーブ", "ニレ池", "鹿島やり", "つきの池", "あずみ野"]},
            {"bg": "#e1bee7", "spots": ["Lost Lures", "不忘", "白河", "ほのぼの", "WaDoNa", "鶴沼川", "オーパ", "あいづ", "上浜", "GOZU"]},
            {"bg": "#d1c4e9", "spots": ["FCE瑞浪", "３９", "醒井", "高島の泉", "千早川"]}
        ]
    }
]

BASS_COLOR_GROUPS = [
    {
        "title": "📍 関東（千葉・埼玉・神奈川）",
        "header_bg": "#2e7d32",
        "sub_groups": [
            {"bg": "#e8f5e9", "spots": ["亀山湖", "高滝湖", "片倉ダム", "三島湖", "豊英ダム"]},
            {"bg": "#e3f2fd", "spots": ["GGD"]},
            {"bg": "#f3e5f5", "spots": ["相模湖"]}
        ]
    },
    {
        "title": "📍 東北（福島）",
        "header_bg": "#6a1b9a",
        "sub_groups": [
            {"bg": "#e1bee7", "spots": ["東山ダム", "羽鳥湖", "桧原湖"]}
        ]
    }
]

ALL_SPOT_DATA = {**SPOT_WEATHER_DATA, **BASS_SPOT_WEATHER_DATA}

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
                {
                    "type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#e53935", "borderWidth": "normal", "borderColor": "#e53935", "cornerRadius": "md", "paddingAll": "none",
                    "contents": [{"type": "button", "action": {"type": "postback", "label": "🗑️ 全て削除", "data": "action=fav_del_all_confirm"}, "style": "link", "color": "#ffffff", "height": "sm", "margin": "none"}]
                },
                {
                    "type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "none",
                    "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧", "data": "action=show_list", "displayText": "📋 一覧"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]
                }
            ]
        })

        bubbles.append({
            "type": "bubble", "size": "mega",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": header_color, "paddingAll": "10px",
                "contents": [{"type": "text", "text": f"{title_text} ({i+1}-{min(i+chunk_size, len(filtered_favs))}/{len(filtered_favs)}件)", "color": "#ffffff", "weight": "bold", "size": "md"}]
            },
            "body": {
                "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "10px", "contents": rows
            }
        })
    
    if len(bubbles) == 1:
        return FlexSendMessage(alt_text="お気に入り管理パネル", contents=bubbles[0])
    else:
        return FlexSendMessage(alt_text="お気に入り管理パネル", contents={"type": "carousel", "contents": bubbles})

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
            fav_rows.append({
                "type": "box", "layout": "vertical", "backgroundColor": "#fffde7", "cornerRadius": "md", "paddingAll": "md", "margin": "md",
                "contents": [{"type": "text", "text": "現在このモードでお気に入りは登録されていません。\n右へスワイプして釣り場を探し、「⭐️ 登録」ボタンを押すか、テキストで「追加 〇〇」と送信してください。", "wrap": True, "size": "sm", "color": "#555555"}]
            })
        else:
            for i in range(0, len(filtered_favs), 2):
                pair = filtered_favs[i:i+2]
                row_buttons = []
                for j, spot in enumerate(pair):
                    global_idx = i + j
                    if global_idx < 2:
                        row_buttons.append({
                            "type": "box", "layout": "vertical", "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "none", "margin": "xs",
                            "contents": [
                                {
                                    "type": "button",
                                    "action": {"type": "postback", "label": spot, "data": f"w={spot}"},
                                    "style": "link",
                                    "color": "#555555",
                                    "height": "sm",
                                    "margin": "none"
                                }
                            ]
                        })
                    else:
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
                    
                row_margin = "none" if i == 0 else ("md" if i % 10 == 0 else "xs")
                row_box = {"type": "box", "layout": "horizontal", "contents": row_buttons, "margin": row_margin}
                fav_rows.append(row_box)

        fav_rows.append({"type": "separator", "margin": "md", "color": "#cccccc"})
        
        fav_rows.append({
            "type": "box", "layout": "horizontal", "margin": "sm", "spacing": "sm",
            "contents": [
                {
                    "type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#f8f9fa", "borderWidth": "normal", "borderColor": "#e0e0e0", "cornerRadius": "md", "paddingAll": "none",
                    "contents": [{"type": "button", "action": {"type": "postback", "label": "⚙️ 設定/切替", "data": "action=show_settings", "displayText": "⚙️ 設定"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]
                },
                {
                    "type": "box", "layout": "vertical", "flex": 1, "backgroundColor": "#fff59d", "borderWidth": "normal", "borderColor": "#d4af37", "cornerRadius": "md", "paddingAll": "none",
                    "contents": [{"type": "button", "action": {"type": "postback", "label": "📋 一覧更新", "data": "action=show_list", "displayText": "📋 一覧"}, "style": "link", "color": "#555555", "height": "sm", "margin": "none"}]
                }
            ]
        })

        header_color = "#d4af37" if mode == "trout" else "#4caf50"
        header_text = "⭐ トラウトお気に入り" if mode == "trout" else "⭐ バスお気に入り"

        fav_bubble = {
            "type": "bubble", "size": "giga",
            "header": {
                "type": "box", "layout": "horizontal", "backgroundColor": header_color, "paddingAll": "10px", "alignItems": "center",
                "contents": [
                    {"type": "text", "text": header_text, "color": "#ffffff", "weight": "bold", "size": "md", "flex": 1},
                    {"type": "text", "text": f"({len(filtered_favs)}/{MAX_FAVORITES})", "color": "#eeeeee", "size": "xs", "align": "end", "flex": 0}
                ]
            },
            "body": {"type": "box", "layout": "vertical", "paddingAll": "6px", "contents": fav_rows}
        }
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
            
        bubble = {
            "type": "bubble", "size": "giga",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": group["header_bg"], "paddingAll": "10px",
                "contents": [{"type": "text", "text": group["title"], "color": "#ffffff", "weight": "bold", "size": "md"}]
            },
            "body": {"type": "box", "layout": "vertical", "paddingAll": "6px", "contents": rows}
        }
        bubbles.append(bubble)

    guide_bubble = {
        "type": "bubble", "size": "giga",
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
                },
                {"type": "separator", "margin": "md"},
                {
                    "type": "box", "layout": "vertical", "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": "⭐ お気に入り機能とリッチメニュー", "weight": "bold", "size": "sm", "color": "#333333"},
                        {"type": "text", "text": "【一番お気に入り（メニュー左）】", "weight": "bold", "size": "xs", "color": "#333333", "margin": "sm"},
                        {"type": "text", "text": "現在のモードにおけるお気に入りリストの「1番目（一番上）」の釣り場の天気を瞬時に表示します。", "wrap": True, "size": "xs", "color": "#666666"}
                    ]
                },
                {"type": "separator", "margin": "md"},
                {
                    "type": "box", "layout": "vertical", "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": "🛑 配信停止・解除", "weight": "bold", "size": "sm", "color": "#333333"},
                        {"type": "text", "text": "このBotの利用を停止したい場合は、トーク画面右上のメニュー「≡」から「ブロック」を行ってください。", "wrap": True, "size": "xs", "color": "#666666"},
                        {"type": "text", "text": "完全に消去する場合", "weight": "bold", "size": "xs", "color": "#333333", "margin": "md"},
                        {"type": "text", "text": "「トーク一覧」画面に戻り、このBotのトークを長押し（iPhoneは左スワイプ）して「削除」してください。", "wrap": True, "size": "xs", "color": "#666666"}
                    ]
                }
            ]
        }
    }
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
                "五頭": "GOZU", "竜华池": "竜華池", "ハーブの里": "ハーブ", "サンクチュアリ": "３９",
                "高島": "高島の泉", "瑞浪": "FCE瑞浪", "槻の池": "つきの池", "川越": "川越パーク",
                "ＭＡＶ": "宮城", "浅川": "浅川国際", "関根": "関根養魚場", "FAJ": "Ｊ", "朝霞": "朝霞Ｇ",
                "GP不忘": "不忘", "座間・amaz": "座間", "パラダイス": "釣パラダイス", "蛇尾川": "蛇尾（さび）川",
                "大崎": "大崎・赤城", "ロストルアーズ": "Lost Lures", "キングフィッシャー": "キング",
                "JF in Tsugane": "ツガネ", "川場キングダム": "キングダム", "イワナセンター": "イワセン", "鹿島槍": "鹿島やり",
                "アルクス宇宇都宮": "アルクス宇都宮"
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
        api_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=weathercode,temperature_2m_max,temperature_2m_min&timezone=Asia%2FTokyo&forecast_days=14"
        res = requests.get(api_url, timeout=5.0)
        res.raise_for_status()
        data = res.json()
        
        daily = data.get("daily", {})
        times = daily.get("time", [])
        weathercodes = daily.get("weathercode", [])
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])
        rain_prob = ["-"] * len(times) 
        
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
            r_prob = f"{rain_prob[i]}%" if i < len(rain_prob) and rain_prob[i] != "-" else "-"
            
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
        if now - updated_time <= timedelta(hours=1):
            if isinstance(data, dict):
                weekly = data.get("__weekly__", [])
                if data.get("_version") != "settings_shortcut_v44": return None
                if not weekly or len(weekly) < 4 or weekly[0].get("temp_max") == "-": return None
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
                    if now - updated_time <= timedelta(hours=1):
                        weather_data = row.get('weather_data')
                        if isinstance(weather_data, dict):
                            weekly = weather_data.get("__weekly__", [])
                            if weather_data.get("_version") != "settings_shortcut_v44": return None
                            if not weekly or len(weekly) < 4 or weekly[0].get("temp_max") == "-": return None
                        MEMORY_CACHE[spot_name] = (weather_data, updated_time)
                        return weather_data
                except: pass
        return None
    except Exception as e:
        print(f"[Cache GET Error] {e}")
        return None

def save_cached_weather(spot_name, weather_data):
    now = datetime.now(timezone.utc)
    weather_data["_version"] = "settings_shortcut_v44"
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

        header_buttons_bottom = []
        if not custom_button_rows:
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
            total_count = len([s for s in favorites.split(',') if s])
            
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
            total_count = len([s for s in favorites.split(',') if s])
            
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
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ 【{target_spot_name}】の天気データの取得に失敗しました。"))
            return

        elif action == "fav_add_and_list":
            success, added, errors = add_favorite_spots(user_id, [spot_name])
            _, favorites, _ = get_user_setting(user_id)
            total_count = len([s for s in favorites.split(',') if s])
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
            total_count = len([s for s in favorites.split(',') if s])
            msg = f"✅ 削除しました: {removed[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所" if removed else f"⚠️ {errors[0]}\n📊 現在の登録数: {total_count}/{MAX_FAVORITES}箇所"
            flex_msg = build_spot_list_carousel_horizontal(user_id=user_id, mode=fishing_mode)
            line_bot_api.reply_message(event.reply_token, [TextSendMessage(text=msg), flex_msg])

        elif action == "fav_del_execute_and_settings":
            success, removed, errors = remove_favorite_spots(user_id, [spot_name])
            _, favorites, _ = get_user_setting(user_id)
            fav_list = [s.strip() for s in favorites.split(',') if s.strip()]
            total_count = len(fav_list)
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

def get_top_favorite_spots(limit=30):
    if not supabase: return []
    try:
        res = supabase.table('user_settings').select('favorite_spots').execute()
        spot_counts = {}
        if res.data:
            for row in res.data:
                favs = row.get('favorite_spots', '')
                if not favs: continue
                spots = [s.strip() for s in favs.split(',') if s.strip()]
                for s in spots: spot_counts[s] = spot_counts.get(s, 0) + 1
        sorted_spots = sorted(spot_counts.items(), key=lambda x: x[1], reverse=True)
        top_spots = [spot for spot, count in sorted_spots[:limit]]
        for bass_spot in BASS_SPOT_WEATHER_DATA.keys():
            if bass_spot not in top_spots: top_spots.append(bass_spot)
        return top_spots
    except Exception as e:
        print(f"[Top Favs Error] {e}")
        return list(BASS_SPOT_WEATHER_DATA.keys())

def run_background_update():
    if not supabase: return
    try:
        top_spots = get_top_favorite_spots(limit=30)
        if not top_spots: return
        cache_times = {}
        for spot in top_spots:
            res = supabase.table('weather_cache').select('updated_at').eq('spot_name', spot).execute()
            if res.data and len(res.data) > 0:
                updated_at_str = res.data[0].get('updated_at')
                try: cache_times[spot] = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                except: cache_times[spot] = datetime.min.replace(tzinfo=timezone.utc)
            else: cache_times[spot] = datetime.min.replace(tzinfo=timezone.utc)
                
        sorted_by_oldest = sorted(cache_times.items(), key=lambda x: x[1])
        target_spots = [spot for spot, time in sorted_by_oldest[:4]]
        
        for spot_name in target_spots:
            data = ALL_SPOT_DATA.get(spot_name)
            if not data: continue
            url = data["url"]
            tenki_url = convert_to_10days_url(data.get("tenki_url"))
            weather_data = fetch_spot_1hour_data(url, tenki_url)
            if weather_data: save_cached_weather(spot_name, weather_data)
            time.sleep(random.uniform(2.0, 3.5))
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
