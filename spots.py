import json
import os

base_dir = os.path.dirname(__file__)

def _load_json(filename):
    path = os.path.join(base_dir, filename)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[Error] Failed to load {filename}: {e}")
        return {}

# 役割別JSONファイルの読み込み
SPOT_WEATHER_DATA = _load_json('spots_trout.json')
BASS_SPOT_WEATHER_DATA = _load_json('spots_bass.json')
_groups_data = _load_json('spots_groups.json')

COLOR_GROUPS = _groups_data.get('COLOR_GROUPS', [])
BASS_COLOR_GROUPS = _groups_data.get('BASS_COLOR_GROUPS', [])

# 全スポットデータの統合
ALL_SPOT_DATA = {**SPOT_WEATHER_DATA, **BASS_SPOT_WEATHER_DATA}
