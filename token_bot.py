# -*- coding: utf-8 -*-
import os
import json
import time
import telebot
from telebot import types

from app import save_tokens, load_tokens, get_token_file_path, BOT_TOKEN, ADMIN_ID

pending_update = {}


def is_admin(user_id):
    return int(user_id) == int(ADMIN_ID)


def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🔄 Update JWT (IND)")
    markup.row("📄 View token_ind.json")
    markup.row("🌐 Other Regions (BR / BD)")
    return markup


def parse_payload_to_list(raw_text):
    """
    Supports:
    1. JSON array like [{"token": "..."}] or JSON object {"token": "..."}
    2. Single or multiple JWT tokens (separated by newlines or commas)
    """
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("Empty input")

    # Strip optional markdown code fences
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()

    # Try parsing JSON first
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
        raise ValueError("JSON must contain non-empty token(s)")
    except json.JSONDecodeError:
        pass

    # Fallback: raw JWT token(s) separated by newlines or commas
    tokens = []
    for line in text.splitlines():
        for part in line.split(","):
            tok = part.strip().strip('"').strip("'")
            if tok:
                if "." not in tok:
                    raise ValueError("Invalid JWT token format")
                tokens.append({"token": tok})

    if not tokens:
        raise ValueError("No valid token found")
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
            "• Default file: `token_ind.json`\n"
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
        tokens = load_tokens("IND") or []
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
        fname = os.path.basename(get_token_file_path(reg))
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
            saved_path, saved_items = save_tokens(region, token_list)
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


def run_bot_loop(bot_token):
    bot = telebot.TeleBot(bot_token)
    register_handlers(bot)
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=25)
        except Exception:
            time.sleep(5)


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing.")
    run_bot_loop(BOT_TOKEN)
