# -*- coding: utf-8 -*-
import os
import json
import time
import tempfile
import threading
import telebot
from telebot import types

BOT_TOKEN = os.getenv("JWT_BOT_TOKEN", os.getenv("BOT_TOKEN", "8765709173:AAGE1-IBr23wEUbot2OBLc0uE-zN2MhOLB8")).strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "7161571409"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_LOCK = threading.RLock()
pending_update = {}


def is_admin(user_id):
    return int(user_id) == int(ADMIN_ID)


def get_token_file(region="IND"):
    reg = (region or "IND").upper()
    if reg == "IND":
        fname = "token_ind.json"
    elif reg in ("BR", "US", "SAC", "NA"):
        fname = "token_br.json"
    else:
        fname = "token_bd.json"
    return os.path.join(BASE_DIR, fname)


def read_tokens(region="IND"):
    with FILE_LOCK:
        path = get_token_file(region)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "token" in data:
            return [data]
        return data if isinstance(data, list) else []


def write_tokens(region, payload):
    with FILE_LOCK:
        path = get_token_file(region)
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)

        if isinstance(payload, dict) and "token" in payload:
            normalized = [payload]
        elif isinstance(payload, list):
            normalized = payload
        else:
            raise ValueError("Invalid token format")

        if not normalized:
            raise ValueError("Token list empty")

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


def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🔄 Update JWT (IND)")
    markup.row("📄 View token_ind.json")
    markup.row("🌐 Other Regions (BR / BD)")
    return markup


def parse_payload_to_list(raw_text):
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("Empty input")

    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "token" in parsed and str(parsed["token"]).strip():
            return [{"token": str(parsed["token"]).strip()}]
        if isinstance(parsed, list) and len(parsed) > 0:
            valid = []
            for item in parsed:
                if isinstance(item, dict) and "token" in item and str(item["token"]).strip():
                    valid.append({"token": str(item["token"]).strip()})
                elif isinstance(item, str) and item.strip():
                    valid.append({"token": item.strip()})
            if valid:
                return valid
        raise ValueError("JSON must contain token")
    except json.JSONDecodeError:
        pass

    tokens = []
    for line in text.splitlines():
        for part in line.split(","):
            tok = part.strip().strip('"').strip("'")
            if tok:
                if "." not in tok:
                    raise ValueError("Invalid JWT token")
                tokens.append({"token": tok})

    if not tokens:
        raise ValueError("No token found")
    return tokens


def register_handlers(bot):
    @bot.message_handler(commands=["start", "help"])
    def on_start(message):
        uid = message.from_user.id
        if not is_admin(uid):
            bot.send_message(uid, "❌ Sirf Admin hi is bot ka use kar sakta hai.")
            return
        bot.send_message(
            uid,
            "⚡ *JWT Token Updater Ready*\n\n"
            "• Target File: `token_ind.json`\n"
            "• **🔄 Update JWT (IND)** dabakar naya JWT token ya JSON bhejein.",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

    @bot.message_handler(func=lambda m: m.text == "🔄 Update JWT (IND)")
    def on_update_ind(message):
        uid = message.from_user.id
        if not is_admin(uid):
            bot.send_message(uid, "❌ Access denied.")
            return
        pending_update[uid] = "IND"
        bot.send_message(
            uid,
            "✍️ *Naya JWT Token ya JSON (`token_ind.json` ke liye) paste karke bhejein:*",
            parse_mode="Markdown"
        )

    @bot.message_handler(func=lambda m: m.text == "📄 View token_ind.json")
    def on_view_ind(message):
        uid = message.from_user.id
        if not is_admin(uid):
            bot.send_message(uid, "❌ Access denied.")
            return
        tokens = read_tokens("IND")
        preview = json.dumps(tokens, indent=2, ensure_ascii=False)
        if len(preview) > 3800:
            preview = preview[:3800] + "\n... (truncated)"
        bot.send_message(
            uid,
            f"📄 *Current `token_ind.json` ({len(tokens)} token(s)):*\n\n```json\n{preview}\n```",
            parse_mode="Markdown"
        )

    @bot.message_handler(func=lambda m: m.text == "🌐 Other Regions (BR / BD)")
    def on_other_regions(message):
        uid = message.from_user.id
        if not is_admin(uid):
            bot.send_message(uid, "❌ Access denied.")
            return
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("Update token_br.json", callback_data="jwt_reg_BR"),
            types.InlineKeyboardButton("Update token_bd.json", callback_data="jwt_reg_BD")
        )
        bot.send_message(uid, "🌐 Kis region ki token file update karni hai?", reply_markup=markup)

    @bot.callback_query_handler(func=lambda call: call.data in ("jwt_reg_BR", "jwt_reg_BD"))
    def on_region_cb(call):
        uid = call.from_user.id
        if not is_admin(uid):
            bot.answer_callback_query(call.id, "❌ Access denied.", show_alert=True)
            return
        reg = call.data.split("_")[-1]
        pending_update[uid] = reg
        fname = os.path.basename(get_token_file(reg))
        bot.send_message(uid, f"✍️ *Naya JWT Token ya JSON (`{fname}` ke liye) bhejein:*", parse_mode="Markdown")
        bot.answer_callback_query(call.id)

    @bot.message_handler(func=lambda m: True, content_types=["text"])
    def on_text_input(message):
        uid = message.from_user.id
        if not is_admin(uid):
            return
        region = pending_update.pop(uid, None)
        if not region:
            bot.send_message(uid, "👇 Pehle **🔄 Update JWT (IND)** button dabayein.", reply_markup=main_keyboard())
            return

        try:
            token_list = parse_payload_to_list(message.text)
            saved_path, saved_items = write_tokens(region, token_list)
            fname = os.path.basename(saved_path)
            bot.send_message(
                uid,
                f"✅ *`{fname}` Safely Update Ho Gayi!*\n\n"
                f"• Region: `{region}`\n"
                f"• Total Tokens: `{len(saved_items)}`\n"
                f"• Time: `{time.strftime('%Y-%m-%d %H:%M:%S')}`",
                parse_mode="Markdown",
                reply_markup=main_keyboard()
            )
        except Exception as e:
            bot.send_message(
                uid,
                f"❌ *Update Failed:* `{e}`\nDobara **🔄 Update JWT (IND)** dabayein.",
                parse_mode="Markdown",
                reply_markup=main_keyboard()
            )


def run_bot_loop(bot_token=BOT_TOKEN):
    tok = (bot_token or "").strip()
    if not tok:
        print("JWT Bot token missing.")
        return
    bot = telebot.TeleBot(tok)
    register_handlers(bot)
    try:
        bot.remove_webhook()
    except Exception:
        pass
    while True:
        try:
            print("JWT Updater Bot polling started...")
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=25)
        except Exception as e:
            print(f"JWT Updater Bot polling error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    run_bot_loop(BOT_TOKEN)
