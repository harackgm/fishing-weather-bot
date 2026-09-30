import json
import os

# 同じディレクトリにある spots.json を読み込む
json_path = os.path.join(os.path.dirname(__file__), 'spots.json')
try:
    with open(json_path, 'r', encoding='utf-8') as f:
        _data = json.load(f)
except Exception as e:
    print(f"[Error] Failed to load spots.json: {e}")
    _data = {}

# JSONからデータを取得し、app.pyがこれまで通り使えるように変数を定義
SPOT_WEATHER_DATA = _data.get("SPOT_WEATHER_DATA", {})
BASS_SPOT_WEATHER_DATA = _data.get("BASS_SPOT_WEATHER_DATA", {})
COLOR_GROUPS = _data.get("COLOR_GROUPS", [])
BASS_COLOR_GROUPS = _data.get("BASS_COLOR_GROUPS", [])

# 全スポットデータを統合
ALL_SPOT_DATA = {**SPOT_WEATHER_DATA, **BASS_SPOT_WEATHER_DATA}
