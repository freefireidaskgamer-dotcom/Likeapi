# Zexxy Free Fire Like API
# Multi-server like sender
# Author: Zexxy

from flask import Flask, request, jsonify
import asyncio
import os
import json
import tempfile
import threading
import binascii
import requests
import aiohttp
from datetime import datetime

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
from google.protobuf.message import DecodeError

import like_pb2
import uid_generator_pb2
import visit_count_pb2


app = Flask(__name__)
app.json.sort_keys = False

# bump this when a new OB drops
RELEASE_VERSION = "OB55"

HOST = "0.0.0.0"
PORT = 5000

BOT_TOKEN = os.getenv("JWT_BOT_TOKEN", os.getenv("BOT_TOKEN", "8765709173:AAGE1-IBr23wEUbot2OBLc0uE-zN2MhOLB8")).strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "7161571409"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE_LOCK = threading.RLock()
_bot_started = False
_bot_start_lock = threading.Lock()


def get_client_url(region):
    # all regions use one of these three base hosts
    if region == "IND":
        return "https://clientbp.freefireind.in"
    if region in ("BR", "US", "SAC", "NA"):
        return "https://client.us.freefiremobile.com"
    return "https://clientbp.ppmainecoonghj.com"


def get_token_file_path(region):
    reg = (region or "IND").upper()
    if reg == "IND":
        filename = "token_ind.json"
    elif reg in ("BR", "US", "SAC", "NA"):
        filename = "token_br.json"
    else:
        filename = "token_bd.json"
    return os.path.join(BASE_DIR, filename)


def load_tokens(region):
    # hot-reload tokens safely on every request
    with TOKEN_FILE_LOCK:
        try:
            path = get_token_file_path(region)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "token" in data:
                return [data]
            return data
        except Exception as e:
            app.logger.error(f"token load failed for {region}: {e}")
            return None


def save_tokens(region, payload):
    # atomic write using temp file + os.replace so concurrent reads never see partial JSON
    with TOKEN_FILE_LOCK:
        path = get_token_file_path(region)
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)

        if isinstance(payload, dict) and "token" in payload:
            normalized = [payload]
        elif isinstance(payload, list):
            normalized = payload
        else:
            raise ValueError("Token data must be a list of token objects")

        if not normalized:
            raise ValueError("Token list cannot be empty")

        fd, tmp_path = tempfile.mkstemp(prefix=".tok_", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tf:
                json.dump(normalized, tf, indent=2, ensure_ascii=False)
                tf.flush()
                os.fsync(tf.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            raise
        return path, normalized


def aes_encrypt(data):
    # fixed key/iv, same as the game client uses
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = pad(data, AES.block_size)
    return binascii.hexlify(cipher.encrypt(padded)).decode()


def build_like_payload(uid, region):
    msg = like_pb2.like()
    msg.uid = int(uid)
    msg.region = region
    return msg.SerializeToString()


def build_uid_payload(uid):
    msg = uid_generator_pb2.uid_generator()
    msg.saturn_ = int(uid)
    msg.garena = 1
    return msg.SerializeToString()


def enc_uid(uid):
    try:
        return aes_encrypt(build_uid_payload(uid))
    except Exception as e:
        app.logger.error(f"uid encrypt failed: {e}")
        return None


def decode_protobuf(data):
    try:
        info = visit_count_pb2.Info()
        info.ParseFromString(data)
        return info
    except DecodeError as e:
        app.logger.error(f"protobuf decode error: {e}")
        return None
    except Exception as e:
        app.logger.error(f"unexpected decode error: {e}")
        return None


def fetch_player(encrypted_uid, region, token):
    # GetPlayerPersonalShow - used for before/after snapshot
    url = get_client_url(region) + "/GetPlayerPersonalShow"
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': RELEASE_VERSION,
    }
    try:
        r = requests.post(url, data=bytes.fromhex(encrypted_uid), headers=headers, verify=False)
        return decode_protobuf(r.content)
    except Exception as e:
        app.logger.error(f"fetch_player error: {e}")
        return None


async def send_like(encrypted_uid, token, url):
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'Expect': "100-continue",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': RELEASE_VERSION,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=bytes.fromhex(encrypted_uid), headers=headers) as resp:
                if resp.status != 200:
                    app.logger.warning(f"like request returned {resp.status}")
                return resp.status
    except Exception as e:
        app.logger.error(f"send_like error: {e}")
        return None


async def blast_likes(uid, region, url):
    # fire 220 like requests spread across the token pool
    payload = build_like_payload(uid, region)
    encrypted_uid = aes_encrypt(payload)

    tokens = load_tokens(region)
    if not tokens:
        return None

    tasks = []
    for i in range(220):
        tok = tokens[i % len(tokens)]["token"]
        tasks.append(send_like(encrypted_uid, tok, url))

    return await asyncio.gather(*tasks, return_exceptions=True)


@app.route('/like', methods=['GET'])
def handle_like():
    uid = request.args.get("uid")
    region = request.args.get("region", "").upper()

    if not uid or not region:
        return jsonify({"error": "uid and region are required"}), 400

    try:
        tokens = load_tokens(region)
        if not tokens:
            raise Exception("could not load tokens for this region")

        primary_token = tokens[0]['token']
        encrypted_uid = enc_uid(uid)
        if not encrypted_uid:
            raise Exception("failed to encrypt uid")

        base_url = get_client_url(region)
        like_url = base_url + "/LikeProfile"

        # snapshot before
        before = fetch_player(encrypted_uid, region, primary_token)
        if before is None:
            raise Exception("could not fetch player info (check uid / region)")

        before_json = json.loads(MessageToJson(before))
        before_likes = int(before_json.get('AccountInfo', {}).get('Likes', 0) or 0)

        # send the likes
        asyncio.run(blast_likes(uid, region, like_url))

        # snapshot after
        after = fetch_player(encrypted_uid, region, primary_token)
        if after is None:
            raise Exception("could not fetch player info after likes")

        after_json = json.loads(MessageToJson(after))
        acct = after_json.get('AccountInfo', {})
        after_likes = int(acct.get('Likes', 0) or 0)
        player_uid = int(acct.get('UID', 0) or 0)
        player_name = str(acct.get('PlayerNickname', ''))
        player_region = str(acct.get('PlayerRegion', region))
        try:
            player_level = int(acct.get('Levels', 0) or 0)
        except Exception:
            player_level = 0

        gained = after_likes - before_likes
        status = 1 if gained != 0 else 2

        return app.response_class(
            response=json.dumps({
                "LikesGivenByAPI": gained,
                "LikesafterCommand": after_likes,
                "LikesbeforeCommand": before_likes,
                "PlayerNickname": player_name,
                "Level": player_level,
                "Region": player_region,
                "UID": player_uid,
                "status": status,
                "version": RELEASE_VERSION,
                "ClientURL": base_url,
                "credit": "Zexxy",
            }),
            status=200,
            mimetype='application/json',
        )

    except Exception as e:
        app.logger.error(f"like handler failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/', methods=['GET'])
def home():
    # serve dashboard if index.html is present, else fall back to json
    here = os.path.dirname(os.path.abspath(__file__))
    html_file = os.path.join(here, "index.html")

    if os.path.exists(html_file):
        try:
            with open(html_file, "r", encoding="utf-8") as f:
                page = f.read()
            page = page.replace("{{VERSION}}", RELEASE_VERSION)
            page = page.replace("{{TIME}}", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            return page, 200, {'Content-Type': 'text/html; charset=utf-8'}
        except Exception as e:
            app.logger.error(f"index.html read error: {e}")

    return jsonify({
        "status": "online",
        "message": "Zexxy FF Like API is running",
        "note": "index.html not found, serving JSON instead",
        "version": RELEASE_VERSION,
        "endpoints": {
            "like": "/like?uid=<uid>&region=<REGION>",
            "status": "/status",
        },
        "servers": ["IND", "BR", "US", "SAC", "NA", "BD"],
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }), 200


@app.route('/status', methods=['GET'])
def status():
    return jsonify({
        "status": "online",
        "version": RELEASE_VERSION,
        "api": "Zexxy FF Like API",
        "endpoints": ["/", "/like", "/status"],
        "servers": ["IND", "BR", "US", "SAC", "NA", "BD"],
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }), 200


def start_token_bot_in_background():
    global _bot_started
    # Avoid spawning duplicate threads under Werkzeug reloader
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return
    if not BOT_TOKEN:
        return
    with _bot_start_lock:
        if _bot_started:
            return
        _bot_started = True
    try:
        import token_bot
        threading.Thread(target=token_bot.run_bot_loop, args=(BOT_TOKEN,), daemon=True).start()
        app.logger.info("Telegram Token Updater Bot started in background.")
    except Exception as e:
        app.logger.error(f"Failed to start Telegram Token Updater Bot: {e}")


start_token_bot_in_background()


if __name__ == '__main__':
    print(f"Zexxy FF Like API  |  version {RELEASE_VERSION}")
    print(f"listening on http://{HOST}:{PORT}")
    print("endpoints:")
    print("  GET  /                          dashboard (or json fallback)")
    print("  GET  /like?uid=X&region=Y       send likes")
    print("  GET  /status                    health check")
    print("servers: IND  BR  US  SAC  NA  BD")

    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
