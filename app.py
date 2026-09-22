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

# 超高速メモリキャッシュ
MEMORY_CACHE = {}

# プッシュ通知安全装置設定 (将来用)
MAX_PUSH_LIMIT = 10  # 一度に通知する最大人数
TEST_MODE_USER_ID = "" 

# ==========================================
# 3. 釣り場URL・HP・Googleマップ・電話番号・SNS・表記揺れ辞書
# ==========================================
SPOT_WEATHER_DATA = {
    # --- 静岡県 ---
    "東山湖": {
        "url": "https://weathernews.jp/onebox/35.296739/138.955925/",
        "hp_url": "http://www.higashiyamako.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "東山湖フィッシングエリア",
        "tel": "0550-82-2161",
        "aliases": ["東山湖", "東山湖フィッシングエリア", "東山湖FA", "ひがしやまこ", "ひがしやま", "東山", "がし山", "がしやま"]
    },
    "すその": {
        "url": "https://weathernews.jp/onebox/35.166667/138.899162/",
        "hp_url": "http://www.susono-f-park.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "すそのフィッシングパーク",
        "tel": "055-993-5514",
        "aliases": ["すその", "すそのフィッシングパーク", "すそのFP", "裾野", "すそぱ", "すそパ"]
    },
    "須川": {
        "url": "https://weathernews.jp/onebox/35.359818/138.977710/",
        "hp_url": "http://www.sukawa.ne.jp/",
        "x_url": "https://x.com/sukawafp",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "須川フィッシングパーク",
        "tel": "0550-75-3077",
        "aliases": ["須川", "須川フィッシングパーク", "須川FP", "すがわ"]
    },
    "アルクス焼津": {
        "url": "https://weathernews.jp/onebox/34.789110/138.294771/",
        "hp_url": "http://www.arcus-pond.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "アルクスポンド焼津",
        "tel": "054-622-7102",
        "aliases": ["アルクス焼津", "アルクスポンド焼津", "あるくすやいづ", "あるくす", "焼津", "アルクスポンド", "やいづ"]
    },
    "浜名湖": {
        "url": "https://weathernews.jp/onebox/34.712749/137.629457/",
        "hp_url": "http://www.hamanako-fr.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "浜名湖フィッシングリゾート",
        "tel": "053-592-2221",
        "aliases": ["浜名湖", "浜名湖フィッシングリゾート", "浜名湖FR", "はまなこ"]
    },

    # --- 栃木県 ---
    "キングフィッシャー": {
        "url": "https://weathernews.jp/onebox/36.907054/140.078650/",
        "hp_url": "https://kingfisher-tochigi.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "キングフィッシャー 大田原",
        "tel": "0287-23-1253",
        "aliases": ["キングフィッシャー", "キング", "キングフィッシャ", "きんぐふぃっしゃー"]
    },
    "みどり": {
        "url": "https://weathernews.jp/onebox/36.834975/140.002410/",
        "hp_url": "http://www.nasu-net.or.jp/~midorifi/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "みどりフィッシングエリア",
        "tel": "0287-28-3334",
        "aliases": ["みどり", "みどりフィッシングエリア", "みどりFA"]
    },
    "那須高原": {
        "url": "https://weathernews.jp/onebox/37.001929/140.104991/",
        "hp_url": "http://lure-f.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "那須高原ルアーフィールド",
        "tel": "0287-78-1005",
        "aliases": ["那須高原", "那須高原ルアーフィールド", "那須高原LF", "なすこうげん"]
    },
    "尚仁沢": {
        "url": "https://weathernews.jp/onebox/37.001929/140.104991/",
        "hp_url": "https://shojinzawa.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "http://sofield.jugem.jp/",
        "yt_url": "",
        "search_name": "尚仁沢アウトドアフィールド",
        "tel": "0287-41-0051",
        "aliases": ["尚仁沢", "尚仁沢アウトドアフィールド", "尚仁沢AF", "しょうじんざわ"]
    },
    "つり天国": {
        "url": "https://weathernews.jp/onebox/37.073444/140.044452/",
        "hp_url": "http://www.tsuritengoku.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "つり天国 那須",
        "tel": "0287-64-4286",
        "aliases": ["つり天国", "ツリテンゴク", "つりてんごく"]
    },
    "関根養魚場": {
        "url": "https://weathernews.jp/onebox/36.851308/139.979065/",
        "hp_url": "http://sekine-fish.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "関根養魚場",
        "tel": "0287-35-2630",
        "aliases": ["関根養魚場", "関根", "せきね", "せきねようぎょじょう"]
    },
    "408": {
        "url": "https://weathernews.jp/onebox/36.763055/139.858269/",
        "hp_url": "https://408club.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "408Club",
        "tel": "0287-43-0408",
        "aliases": ["408", "408クラブ", "408club", "よんまるはち"]
    },
    "308": {
        "url": "https://weathernews.jp/onebox/36.824828/139.896229/",
        "hp_url": "http://408club.com/308/index.html",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "308Club",
        "tel": "0287-43-0308",
        "aliases": ["308", "308クラブ", "308club", "さんまるはち"]
    },
    "蛇尾（さび）川": {
        "url": "https://weathernews.jp/onebox/36.981351/139.901534/",
        "hp_url": "https://sabigawafishingpark.com/",
        "x_url": "https://x.com/matagi_nasu?ref_src=twsrc%5Egoogle%7Ctwcamp%5Eserp%7Ctwgr%5Eauthor",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "蛇尾川フィッシングパーク",
        "tel": "0287-32-2212",
        "aliases": ["蛇尾川", "蛇尾（さび）川", "さびがわ", "サビガワ", "へびがわ", "いびがわ", "えびがわ", "蛇尾川フィッシングパーク"]
    },
    "レイクウッド": {
        "url": "https://weathernews.jp/onebox/36.611334/139.666579/",
        "hp_url": "http://lakewoodresort.info/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "レイクウッドリゾート 鹿沼",
        "tel": "0289-75-1008",
        "aliases": ["レイクウッド", "レイクウッドリゾート", "れいくうっど"]
    },
    "なら山沼": {
        "url": "https://weathernews.jp/onebox/36.373741/139.802713/",
        "hp_url": "http://www.shimotsuga-fc.org/index.html",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "なら山沼漁場",
        "tel": "0285-25-4350",
        "aliases": ["なら山沼", "なら山沼漁場", "ならやま", "なら山", "ならやまぬま", "ならやま沼"]
    },
    "大芦川": {
        "url": "https://weathernews.jp/onebox/36.590732/139.693652/",
        "hp_url": "http://park10.wakwak.com/~field-village/",
        "x_url": "",
        "fb_url": "https://ja-jp.facebook.com/ooashigawa.fcfv/",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "大芦川 F&C フィールドビレッジ",
        "tel": "0289-74-7222",
        "aliases": ["大芦川", "大芦川F&C", "おおあしがわ"]
    },
    "加賀": {
        "url": "https://weathernews.jp/onebox/36.388609/139.537247/",
        "hp_url": "http://www.kaga-fa.co.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "https://ameblo.jp/kaga-fa/",
        "yt_url": "",
        "search_name": "加賀フィッシングエリア",
        "tel": "0283-24-1513",
        "aliases": ["加賀", "加賀フィッシングエリア", "加賀FA", "かが"]
    },
    "発光路": {
        "url": "https://weathernews.jp/onebox/36.580281/139.532829/",
        "hp_url": "https://ov-hokkojinomori-fa.jimdosite.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "https://www.instagram.com/ov.hokkojinomori.fa/",
        "blog_url": "https://hokkojinomori.livedoor.blog/",
        "yt_url": "",
        "search_name": "発光路の森ファアルクス",
        "tel": "0289-85-3503",
        "aliases": ["発光路", "発光路の森", "ほっこうじ", "はっこうじ", "発光時", "発酵時"]
    },
    "上永野": {
        "url": "https://weathernews.jp/onebox/36.511884/139.573442/",
        "hp_url": "https://kaminagano-fishing.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "フィッシングリゾート上永野",
        "tel": "0289-84-0335",
        "aliases": ["上永野", "上永野FR", "かみながの"]
    },
    "柏倉": {
        "url": "https://weathernews.jp/onebox/36.398276/139.660428/",
        "hp_url": "http://kashiwagurafishingpk.g3.xrea.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "柏倉フィッシングパーク",
        "tel": "0282-23-6622",
        "aliases": ["柏倉", "柏倉FP", "かしわぐら"]
    },
    "遊水園": {
        "url": "https://weathernews.jp/onebox/36.342013/139.863541/",
        "hp_url": "http://meiseikousan.jp/oyamawaterpark/",
        "x_url": "https://x.com/ParkOyama",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "Oyama Water Park 遊水園",
        "tel": "0285-38-8255",
        "aliases": ["遊水園", "OyamaWaterPark遊水園", "ゆうすいえん"]
    },
    "アルクス宇都宮": {
        "url": "https://weathernews.jp/onebox/36.566488/139.960060/",
        "hp_url": "http://www.arcus-pond.com/",
        "x_url": "",
        "fb_url": "https://www.facebook.com/p/Arcus-Pond%E3%82%A2%E3%83%AB%E3%82%AF%E3%82%B9%E3%83%9D%E3%83%B3%E3%83%89-100041638634155/",
        "insta_url": "",
        "blog_url": "https://www.arcus-pond.com/wp/category/blog/",
        "yt_url": "",
        "search_name": "アルクスポンド宇都宮",
        "tel": "028-652-3210",
        "aliases": ["アルクス宇都宮", "アルクスポンド宇都宮", "あるくすうつのみや", "あるくす", "アルクスポンド", "うつのみや"]
    },
    "エリア21": {
        "url": "https://weathernews.jp/onebox/36.496150/139.899522/",
        "hp_url": "http://www.area21.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "エリア21 宇都宮",
        "tel": "028-656-1188",
        "aliases": ["エリア21", "えりあ21"]
    },
    "ベアーズパーク": {
        "url": "https://weathernews.jp/onebox/36.513221/139.956989/",
        "hp_url": "https://bearspark.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "ベアーズパーク宇都宮",
        "tel": "028-656-2580",
        "aliases": ["ベアーズパーク", "増井養魚場", "べあーずぱーく"]
    },
    "鬼怒川": {
        "url": "https://weathernews.jp/onebox/36.617621/139.937106/",
        "hp_url": "http://kinugawa-fa.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "鬼怒川フィッシングエリア",
        "tel": "028-672-1815",
        "aliases": ["鬼怒川", "鬼怒川フィッシングエリア", "鬼怒川FA", "きぬがわ"]
    },
    "名草": {
        "url": "https://weathernews.jp/onebox/36.418930/139.466355/",
        "hp_url": "https://ja-jp.facebook.com/nagusaturibori",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "名草釣堀",
        "tel": "0284-36-2480",
        "aliases": ["名草", "名草釣堀", "なぐさ"]
    },

    # --- 千葉県 ---
    "座間・amaz": {
        "url": "https://weathernews.jp/onebox/35.843581/140.010676/",
        "hp_url": "http://zamayougyo.com/",
        "x_url": "",
        "fb_url": "https://www.facebook.com/people/%E5%BA%A7%E9%96%93%E9%A4%8A%E9%AD%9A%E5%A0%B4/100065552678584/#",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "座間養魚場",
        "tel": "04-7192-1080",
        "aliases": ["座間・amaz", "座間", "座間養魚場", "ざま", "ザマ", "ざまようぎょじょう", "アメイズ", "あめいず"]
    },
    "ジョイバレー": {
        "url": "https://weathernews.jp/onebox/35.744779/140.417401/",
        "hp_url": "http://www.joyvalley.co.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "ジョイバレー 成田",
        "tel": "0479-78-1840",
        "aliases": ["ジョイバレー", "じょいばれー", "ジョイバ"]
    },
    "ウォルトン": {
        "url": "https://weathernews.jp/onebox/35.863326/140.290525/",
        "hp_url": "https://www.waltongarden.net/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "ウォルトンガーデン",
        "tel": "0476-37-3315",
        "aliases": ["ウォルトン", "ウォルトンガーデン", "うぉるとん"]
    },
    "NOIKE": {
        "url": "https://weathernews.jp/onebox/35.576969/140.234786/",
        "hp_url": "https://troutpond1089.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "trout pond NOIKE",
        "tel": "043-228-8283",
        "aliases": ["NOIKE", "ノイケ", "のいけ"]
    },
    "釣パラダイス": {
        "url": "https://weathernews.jp/onebox/35.653330/140.338663/",
        "hp_url": "https://www.tsuripara.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "釣りパラダイス 山武",
        "tel": "043-445-1216",
        "aliases": ["釣パラダイス", "パラダイス", "釣りパラダイス", "つりぱら"]
    },

    # --- 埼玉県 ---
    "長瀞": {
        "url": "https://weathernews.jp/onebox/36.084376/139.104604/",
        "hp_url": "https://waterpark.jp/fishing/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "ウォーターパーク長瀞",
        "tel": "0494-66-0312",
        "aliases": ["長瀞", "WP長瀞", "ウォーターパーク長瀞", "ながとろ"]
    },
    "彩の国": {
        "url": "https://weathernews.jp/onebox/35.992469/139.473372/",
        "hp_url": "https://fs-sainokuni.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "フィッシングフィールド彩の国",
        "tel": "049-297-7815",
        "aliases": ["彩の国", "FF彩の国", "さいのくに"]
    },
    "朝霞Ｇ": {
        "url": "https://weathernews.jp/onebox/35.813481/139.604736/",
        "hp_url": "http://www.asaka-garden.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "朝霞ガーデン",
        "tel": "048-456-0260",
        "aliases": ["朝霞Ｇ", "朝霞", "朝霞ガーデン", "アサカガーデン", "ガーデン", "あさか", "アサカ", "あさかガーデン"]
    },
    "しらこばと": {
        "url": "https://weathernews.jp/onebox/35.917970/139.752203/",
        "hp_url": "https://www.parks.or.jp/shirakobatosuijo/guide/003/003811.html",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "しらこばと水上公園",
        "tel": "048-977-5111",
        "aliases": ["しらこばと", "しらこばと水上公園"]
    },
    "川越パーク": {
        "url": "https://weathernews.jp/onebox/35.907152/139.444046/",
        "hp_url": "https://www.parks.or.jp/kawagoesuijo/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "川越水上公園",
        "tel": "049-241-2241",
        "aliases": ["川越パーク", "川越", "川越水上公園", "かわごえ"]
    },
    "加須はなさき": {
        "url": "https://weathernews.jp/onebox/36.096192/139.636601/",
        "hp_url": "https://www.parks.or.jp/kazohanasaki/guide/000/000031.html",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "加須はなさき水上公園",
        "tel": "0480-65-7155",
        "aliases": ["加須はなさき", "はなさき", "はなさき公園"]
    },
    "中里": {
        "url": "https://weathernews.jp/onebox/36.163896/139.176567/",
        "hp_url": "http://fish104.in.coocan.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "中里フィッシングクラブ",
        "tel": "0495-76-1120",
        "aliases": ["中里", "中里FC", "なかざと"]
    },
    "伊古の里": {
        "url": "https://weathernews.jp/onebox/36.071547/139.339037/",
        "hp_url": "http://www.ikonosato.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "伊古の里フィッシングパーク",
        "tel": "0493-57-0505",
        "aliases": ["伊古", "伊古の里", "いこのさと", "伊古の里フィッシングパーク"]
    },

    # --- 神奈川県・東京都 ---
    "足柄": {
        "url": "https://weathernews.jp/onebox/35.319275/139.042723/",
        "hp_url": "http://www.ashigara-ca.com/aca/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "足柄キャスティングエリア",
        "tel": "0465-73-2030",
        "aliases": ["足柄", "足柄CA", "あしがら"]
    },
    "中津川": {
        "url": "https://weathernews.jp/onebox/35.521698/139.285609/",
        "hp_url": "http://www.nakatugawa-gyokyou.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "フィッシングフィールド中津川",
        "tel": "046-281-5421",
        "aliases": ["中津川", "FF中津川", "なかつがわ", "なかつ", "中津"]
    },
    "早戸川": {
        "url": "https://weathernews.jp/onebox/35.543063/139.216090/",
        "hp_url": "http://www.hayatogawa.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "リヴァスポット早戸",
        "tel": "042-785-0774",
        "aliases": ["早戸川", "リヴァスポット早戸", "はやとがわ"]
    },
    "王禅寺": {
        "url": "https://weathernews.jp/onebox/35.587020/139.524309/",
        "hp_url": "https://www.fishon-oz.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "BerryPark in 王禅寺",
        "tel": "044-959-0037",
        "aliases": ["王禅寺", "ベリーパーク in 王禅寺", "おうぜんじ", "王禅寺ベリーパーク", "寺", "てら"]
    },
    "開成": {
        "url": "https://weathernews.jp/onebox/35.334342/139.130344/",
        "hp_url": "https://kaisei.forest-springs.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "開成水辺フォレストスプリングス",
        "tel": "0465-85-2020",
        "aliases": ["開成", "開成水辺フォレストスプリングス", "開成FS", "かいせい", "フォレストスプリングス"]
    },
    "浅川国際": {
        "url": "https://weathernews.jp/onebox/35.641903/139.231262/",
        "hp_url": "http://www5c.biglobe.ne.jp/~fly-lure/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "浅川国際マス釣り場",
        "tel": "042-661-2228",
        "aliases": ["浅川国際", "浅川", "浅川国際マス釣り場", "あさかわ", "あさかわこくさい", "あさこく", "アサコク"]
    },

    # --- 山梨県・長野県 ---
    "鹿留": {
        "url": "https://weathernews.jp/onebox/35.512350/138.887160/",
        "hp_url": "http://www.sisidome.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "ベリーパーク in 鹿留",
        "tel": "0554-43-0082",
        "aliases": ["鹿留", "シシドメ", "ししどめ", "ベリーパーク"]
    },
    "小菅": {
        "url": "https://weathernews.jp/onebox/35.760330/138.940529/",
        "hp_url": "http://kosuge-tg.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "https://kosugetg.jugem.jp/",
        "yt_url": "",
        "search_name": "小菅トラウトガーデン",
        "tel": "0428-87-0373",
        "aliases": ["小菅", "小菅TG", "こすげ"]
    },
    "奈良子": {
        "url": "https://weathernews.jp/onebox/35.672184/138.917831/",
        "hp_url": "https://www.narago.jp/index.html",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "奈良子釣りセンター",
        "tel": "0554-24-7636",
        "aliases": ["奈良子", "奈良子釣りセンター", "ならこ", "ならご", "ナラコ", "ナラゴ", "ならごつりせんたー", "ナラゴツリセンター"]
    },
    "シルフ": {
        "url": "https://weathernews.jp/onebox/35.778458/138.316489/",
        "hp_url": "https://shylph.boy.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "白州トラウトフィッシングエリア",
        "tel": "0551-35-4308",
        "aliases": ["シルフ", "Shylph", "しるふ"]
    },
    "JF in Tsugane": {
        "url": "https://weathernews.jp/onebox/35.866755/138.451406/",
        "hp_url": "http://www6.nns.ne.jp/~joy-field/index.html",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "ジョイフィールド in Tsugane",
        "tel": "0551-20-7888",
        "aliases": ["JF in Tsugane", "Tsugane", "ジョイフィールド", "つがね", "ツガネ", "じょいふぃーるど"]
    },
    "竜華池": {
        "url": "https://weathernews.jp/onebox/35.681978/138.576164/",
        "hp_url": "https://fishingmarketbear.wixsite.com/ryugaike",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "フィッシングパーク竜華池",
        "tel": "055-252-0938",
        "aliases": ["竜華池", "りゅうがいけ"]
    },
    "平谷湖": {
        "url": "https://weathernews.jp/onebox/35.332243/137.632213/",
        "hp_url": "https://hirayako.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "https://ameblo.jp/hirayakobakucho/",
        "yt_url": "",
        "search_name": "平谷湖フィッシングスポット",
        "tel": "0265-48-1127",
        "aliases": ["平谷湖", "平谷湖フィッシングスポット", "ひらやこ"]
    },
    "ハーブの里": {
        "url": "https://weathernews.jp/onebox/36.403436/137.890526/",
        "hp_url": "https://herbfa1995.kikirara.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "ハーブの里フィッシングエリア",
        "tel": "0261-62-6322",
        "aliases": ["ハーブの里", "ハーブ", "はーぶ"]
    },
    "ニレ池": {
        "url": "https://weathernews.jp/onebox/36.712669/137.845826/",
        "hp_url": "http://www.nireike.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "白馬八方ニレ池フィッシングセンター",
        "tel": "0261-72-5086",
        "aliases": ["ニレ池", "にれいけ"]
    },
    "鹿島槍": {
        "url": "https://weathernews.jp/onebox/36.548940/137.809757/",
        "hp_url": "https://www.kashimayari-garden.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "鹿島槍ガーデン",
        "tel": "0261-22-2253",
        "aliases": ["鹿島槍", "鹿島槍ガーデン", "かしまやり"]
    },
    "つきの池": {
        "url": "https://weathernews.jp/onebox/36.011582/138.197271/",
        "hp_url": "http://www.tsukinoike.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "槻の池フィッシングエリア",
        "tel": "0266-76-2280",
        "aliases": ["つきの池", "槻の池", "槻の池フィッシングエリア", "つきのいけ"]
    },
    "あずみ野": {
        "url": "https://weathernews.jp/onebox/36.337699/137.885455/",
        "hp_url": "http://www7b.biglobe.ne.jp/~azuminoturibori/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "あずみ野フィッシングセンター",
        "tel": "0263-82-8280",
        "aliases": ["あずみ野", "あずみ野FC", "あずみの"]
    },

    # --- 群馬県 ---
    "川場": {
        "url": "https://weathernews.jp/onebox/36.690767/139.121662/",
        "hp_url": "http://www.kawaba-fp.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "https://www.instagram.com/kawaba.numata.fishingplaza/?utm_source=ig_embed",
        "blog_url": "",
        "yt_url": "",
        "search_name": "川場フィッシングプラザ",
        "tel": "0278-52-3200",
        "aliases": ["川場", "川場FP", "かわば"]
    },
    "川場キングダム": {
        "url": "https://weathernews.jp/onebox/36.754213/139.142256/",
        "hp_url": "http://kawaba-kingdomfishing.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "川場キングダムフィッシング",
        "tel": "0278-52-2002",
        "aliases": ["川場キングダム", "キングダム", "かわばきんぐだむ"]
    },
    "おくとね": {
        "url": "https://weathernews.jp/onebox/36.663005/139.163750/",
        "hp_url": "http://www7.wind.ne.jp/okutone/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "おくとねフィッシングパーク",
        "tel": "0278-53-3802",
        "aliases": ["おくとね", "おくとねFP"]
    },
    "イワナセンター": {
        "url": "https://weathernews.jp/onebox/36.610095/139.243740/",
        "hp_url": "http://www7.wind.ne.jp/okutone/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "日本イワナセンター",
        "tel": "0278-54-8433",
        "aliases": ["イワナセンター", "日本イワナセンター", "いわなせんたー"]
    },
    "黒保根": {
        "url": "https://weathernews.jp/onebox/36.515041/139.252324/",
        "hp_url": "https://www.kurohone-fishing.com/",
        "x_url": "https://twitter.com/kurohoneKF",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "黒保根渓流フィッシング",
        "tel": "0277-96-2091",
        "aliases": ["黒保根", "くろほね"]
    },
    "迦葉山": {
        "url": "https://weathernews.jp/onebox/36.685419/139.071387/",
        "hp_url": "http://www.fp-berrys.net/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "https://ameblo.jp/fp-berrys2006/",
        "yt_url": "",
        "search_name": "ベリーズ迦葉山",
        "tel": "0278-23-9333",
        "aliases": ["迦葉山", "ベリーズ迦葉山", "かしょうざん", "ベリーズ"]
    },
    "片品": {
        "url": "https://weathernews.jp/onebox/36.624564/139.046703/",
        "hp_url": "https://www.turinavi.info/gunma/katashinagawakokusai/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "片品川国際マス釣り場",
        "tel": "0278-24-1188",
        "aliases": ["片品", "片品川国際", "かたしな"]
    },
    "中之沢": {
        "url": "https://weathernews.jp/onebox/36.492057/139.195293/",
        "hp_url": "http://gfc.sakura.ne.jp/index.htm",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "GFC中之沢",
        "tel": "027-283-3532",
        "aliases": ["中之沢", "GFC中之沢", "なかのさわ"]
    },
    "ＭＡＶ": {
        "url": "https://weathernews.jp/onebox/36.483735/139.188251/",
        "hp_url": "http://www.anglers-village.com/index2.html",
        "x_url": "",
        "fb_url": "https://www.facebook.com/people/%E5%AE%AE%E5%9F%8E%E3%82%A2%E3%83%B3%E3%82%B0%E3%83%A9%E3%83%BC%E3%82%BA%E3%83%B4%E3%82%A3%E3%83%AC%E3%83%83%E3%82%B8/100049219011936/#",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "宮城アングラーズヴィレッジ",
        "tel": "027-283-0035",
        "aliases": ["ＭＡＶ", "宮城", "宮城AV", "みやぎあんぐらーず", "まぶ", "マブ", "あんびれ", "アンビレ", "MAV", "mav"]
    },
    "大崎・赤城": {
        "url": "https://weathernews.jp/onebox/36.463209/139.164867/",
        "hp_url": "https://nijimasu.com/",
        "hp2_url": "https://anglers-base.com/",  
        "search_name": "大崎つりぼり",
        "tel": "027-283-2945",
        "aliases": ["大崎・赤城", "大崎", "赤城", "大崎つりぼり", "アングラーズベース", "アングラーズベース赤城山", "おおさき", "あかぎ"]
    },
    "けん太": {
        "url": "https://weathernews.jp/onebox/36.386648/138.960021/",
        "hp_url": "http://www.tsurikichikenta.com/index.htm",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "釣りキチけん太",
        "tel": "027-371-3312",
        "aliases": ["けん太", "釣りキチけん太", "けんた"]
    },
    "フック": {
        "url": "https://weathernews.jp/onebox/36.457699/139.173191/",
        "hp_url": "https://aa-hook.jp/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "アングラーズエリアHOOK",
        "tel": "027-283-0535",
        "aliases": ["フック", "HOOK", "ふっく"]
    },
    "赤久縄": {
        "url": "https://weathernews.jp/onebox/36.160894/138.895355/",
        "hp_url": "https://www.akaguna.net/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "赤久縄",
        "tel": "0274-56-0230",
        "aliases": ["赤久縄", "あかぐな"]
    },
    "太田": {
        "url": "https://weathernews.jp/onebox/36.357774/139.330830/",
        "hp_url": "https://www.facebook.com/otafishingclub/",
        "x_url": "",
        "fb_url": "https://www.facebook.com/otafishingclub/",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "太田フィッシングクラブ",
        "tel": "0276-32-1230",
        "aliases": ["太田", "太田FC", "おおた"]
    },
    "東山道": {
        "url": "https://weathernews.jp/onebox/36.323047/139.280989/",
        "hp_url": "https://emrp-fishing.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "東山道公園フィッシングエリア",
        "tel": "0276-56-1180",
        "aliases": ["東山道", "東山道FA", "とうさんどう"]
    },
    "榛名": {
        "url": "https://weathernews.jp/onebox/36.443570/138.898498/",
        "hp_url": "https://haruna-turibori.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "榛名高原つり堀センター",
        "tel": "027-374-2228",
        "aliases": ["榛名", "榛名高原", "はるな"]
    },

    # --- 茨城県 ---
    "水戸南": {
        "url": "https://weathernews.jp/onebox/36.326377/140.501362/",
        "hp_url": "http://www.mitominami-fa.jp/index.html",
        "x_url": "https://x.com/TSURIBORIMITO?lang=ja",
        "fb_url": "",
        "insta_url": "https://www.instagram.com/tsuriborimitominami/",
        "blog_url": "",
        "yt_url": "",
        "search_name": "水戸南フィッシングエリア",
        "tel": "029-246-1233",
        "aliases": ["水戸南", "水戸南FA", "みとみなみ"]
    },
    "高萩": {
        "url": "https://weathernews.jp/onebox/36.788035/140.577243/",
        "hp_url": "https://takahagifureainosato.web.fc2.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "高萩ふれあいの里フィッシングエリア",
        "tel": "0293-24-1888",
        "aliases": ["高萩", "高萩ふれあいの里", "たかはぎ"]
    },
    "つくば園": {
        "url": "https://weathernews.jp/onebox/36.224122/140.144261/",
        "hp_url": "http://tsukuba-en.jp/",
        "x_url": "",
        "fb_url": "https://www.facebook.com/tsukubaen5355/?ref=page_internal",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "フィッシングパークつくば園",
        "tel": "0299-43-6111",
        "aliases": ["つくば園", "つくばえん"]
    },
    "Ｊ": {
        "url": "https://weathernews.jp/onebox/36.081494/140.164360/",
        "hp_url": "https://sites.google.com/view/fishing-area-j/",
        "x_url": "https://x.com/madara_area_j",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "フィッシングエリアJ",
        "tel": "029-842-1698",
        "aliases": ["Ｊ", "J", "FAJ", "フィッシングエリアJ", "ふぃっしんぐえりあじぇい", "じぇー", "じぇい", "ジェー"]
    },
    "ユザキ": {
        "url": "https://weathernews.jp/onebox/36.314550/140.335285/",
        "hp_url": "https://yuzakiko.com/",
        "x_url": "",
        "fb_url": "",
        "insta_url": "",
        "blog_url": "",
        "yt_url": "",
        "search_name": "レイクユザキ",
        "tel": "0296-77-8500",
        "aliases": ["ユザキ", "レイクユザキ", "ゆざき"]
    },
    "笠間":自信度：90%

ご指摘の通り、25日の「1時間ごとのピンポイント予報（晴れ）」と「下部の週間予報（雨・降水確率24%）」で完全に予報結果が矛盾しています。

日本気象協会（JWA）などの特定事業者にカスタマイズされているか、および予報内容が大きく異なる理由について、システム構造の観点から解説します。

---

### 1時間予報と週間予報で内容が食い違う主な原因

| 要因 | 解説・背景 |
| :--- | :--- |
| **参照データソース（API）の別構成** | 上部の「1時間予報」と下部の「週間予報」で**異なる気象API（データ提供元）を参照している**可能性が極めて高いです。例えば、上部はJWAのピンポイントAPI、下部は気象庁の週間概況データなど、別々のソースを結合して表示しているケースです。 |
| **数値予報モデルの更新タイミング差** | ピンポイント予報は局地モデル（MSM等）をベースに高頻度更新されますが、週間予報は全球モデル（GSM等）をベースに1日2〜3回程度しか更新されません。データ取得・反映バッチのタイミングがズレている可能性があります。 |
| **アイコン表示ロジック（判定閾値）の問題** | 下部の25日は「降水確率24%」にもかかわらず「雨アイコン」が表示されています。システム側で「降水確率が一定以上なら雨アイコンを出す」といった判定ロジックの閾値設定やマッピングミスが起きている可能性があります。 |

---

### ウェザーニュース（WN）等と予報が大きく異なる理由

1. **独自計算モデルの違い**
   * **ウェザーニュース（WN）**: 独自観測網と独自AIモデル（1kmメッシュ等）を中心に予報を生成。
   * **日本気象協会（JWA）など**: 気象庁の計算モデルをベースに独自補正を加えたデータを配信。
   * 3日以上先の予報（25日以降）になると、各社が採用する計算モデル（ECMWF、GFS、気象庁モデル等）の初期値の違いによって予報のブレが大幅に広がります。

2. **ピンポイント（地点）補正の有無**
   * 対象地点（キングフィッシャー）周辺の山間部や地形起伏に対する補正アルゴリズムが事業者ごとに異なるため、特定の場所で予報が真逆になる現象が発生します。

---

### スクレイピング・システム実装時の注意事項

スクレイピングやLINE BOT等でこのデータを扱う場合、表示上の矛盾をそのままユーザーに通知してしまうリスクがあります。

* **データの優先度設定**: 上部の1時間予報と下部の週間予報で日付が重複している場合（例：25日）、精度が高い**1時間予報のデータを優先して採用する**コードロジックを組むことを推奨します。
* **異常値フィルタ**: 降水確率24%で雨アイコンになるような判定のゆらぎに対応するため、アイコン画像だけでなく数値（降水確率・降水量）をベースに天気を再定義する処理を入れると安全です。
