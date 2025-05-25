import os
import asyncio
import aiosqlite
import random
import string
import requests
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS").split(",")]
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))
DB_CHANNEL_ID = int(os.getenv("DB_CHANNEL_ID"))
DOMAIN = os.getenv("DOMAIN")
TINYURL_API = os.getenv("TINYURL_API", "")

# Initialize Pyrogram client
app = Client("file_sharing_bot", bot_token=BOT_TOKEN)

# Initialize SQLite database
async def init_db():
    async with aiosqlite.connect("database.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS content (
                shortlink TEXT PRIMARY KEY,
                message_id INTEGER,
                uploader_id INTEGER,
                upload_time TEXT,
                is_batch INTEGER DEFAULT 0,
                batch_first_id INTEGER,
                batch_last_id INTEGER
            )
        """)
        await db.commit()

# Generate random shortlink (e.g., abc123)
def generate_shortlink():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))

# Generate TinyURL shortlink
def create_tinyurl(long_url):
    try:
        response = requests.get(f"https://tinyurl.com/api-create.php?url={long_url}")
        return response.text if response.status_code == 200 else long_url
    except Exception:
        return long_url

# Check if user is admin
def is_admin(user_id):
    return user_id in ADMIN_IDS

# Log to channel
async def log_event(message):
    await app.send_message(LOG_CHANNEL_ID, message)

# Start command
@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("Hello! I'm a file-sharing bot. Use /link to share content or /batch for multiple files (admins only).")

# /link command: Store any content (file, text, sticker, link, etc.)
@app.on_message(filters.command("link") & filters.private)
async def link_command(client, message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.reply_text("Sorry, only admins can use /link!")
        await log_event(f"Non-admin {user_id} tried to use /link.")
        return

    # Forward content to database channel
    try:
        db_message = await message.forward(DB_CHANNEL_ID)
        shortlink = generate_shortlink()
        bot_link = f"{DOMAIN}/{shortlink}"
        tinyurl_link = create_tinyurl(bot_link)
        
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "INSERT INTO content (shortlink, message_id, uploader_id, upload_time) VALUES (?, ?, ?, ?)",
                (shortlink, db_message.id, user_id, datetime.now().isoformat())
            )
            await db.commit()
        
        await message.reply_text(
            f"Content saved! Shareable link: {tinyurl_link}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open Link", url=tinyurl_link)]])
        )
        await log_event(f"Content uploaded by {user_id}: {shortlink}")
    except Exception as e:
        await message.reply_text("Error saving content!")
        await log_event(f"Error in /link for {user_id}: {e}")

# /batch command: Store multiple files
@app.on_message(filters.command("batch") & filters.private)
async def batch_command(client, message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.reply_text("Sorry, only admins can use /batch!")
        await log_event(f"Non-admin {user_id} tried to use /batch.")
        return

    try:
        args = message.text.split()
        if len(args) != 3:
            await message.reply_text("Usage: /batch <first_message_id> <last_message_id>")
            return
        
        first_id, last_id = int(args[1]), int(args[2])
        if first_id >= last_id:
            await message.reply_text("First ID must be less than last ID!")
            return

        # Forward messages in range to database channel
        shortlink = generate_shortlink()
        bot_link = f"{DOMAIN}/{shortlink}"
        tinyurl_link = create_tinyurl(bot_link)
        
        for msg_id in range(first_id, last_id + 1):
            try:
                await app.forward_messages(DB_CHANNEL_ID, message.chat.id, msg_id)
            except Exception:
                continue
        
        async with aiosqlite.connect("database.db") as db:
            await db.execute(
                "INSERT INTO content (shortlink, batch_first_id, batch_last_id, uploader_id, upload_time, is_batch) VALUES (?, ?, ?, ?, ?, ?)",
                (shortlink, first_id, last_id, user_id, datetime.now().isoformat(), 1)
            )
            await db.commit()
        
        await message.reply_text(
            f"Batch saved! Shareable link: {tinyurl_link}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open Link", url=tinyurl_link)]])
        )
        await log_event(f"Batch uploaded by {user_id}: {shortlink} (Messages {first_id}-{last_id})")
    except Exception as e:
        await message.reply_text("Error saving batch!")
        await log_event(f"Error in /batch for {user_id}: {e}")

# Admin panel commands
@app.on_message(filters.command("admin") & filters.private)
async def admin_panel(client, message):
    if not is_admin(message.from_user.id):
        await message.reply_text("Admins only!")
        return
    await message.reply_text(
        "Admin Panel:\n"
        "/list_content - List all stored content\n"
        "/list_users - List allowed users\n"
        "/add_user <user_id> - Add allowed user\n"
        "/remove_user <user_id> - Remove allowed user\n"
        "/broadcast <message> - Broadcast to all users"
    )

# List stored content
@app.on_message(filters.command("list_content") & filters.private)
async def list_content(client, message):
    if not is_admin(message.from_user.id):
        await message.reply_text("Admins only!")
        return
    async with aiosqlite.connect("database.db") as db:
        async with db.execute("SELECT shortlink, message_id, batch_first_id, batch_last_id, uploader_id, upload_time, is_batch FROM content") as cursor:
            items = await cursor.fetchall()
            if not items:
                await message.reply_text("No content stored!")
                return
            response = "Stored Content:\n"
            for shortlink, msg_id, first_id, last_id, uploader_id, upload_time, is_batch in items:
                link = create_tinyurl(f"{DOMAIN}/{shortlink}")
                if is_batch:
                    response += f"Batch: {shortlink}\nMessages: {first_id}-{last_id}\nUploader: {uploader_id}\nUploaded: {upload_time}\nLink: {link}\n\n"
                else:
                    response += f"Content: {shortlink}\nMessage ID: {msg_id}\nUploader: {uploader_id}\nUploaded: {upload_time}\nLink: {link}\n\n"
            await message.reply_text(response)

# List allowed users
@app.on_message(filters.command("list_users") & filters.private)
async def list_users(client, message):
    if not is_admin(message.from_user.id):
        await message.reply_text("Admins only!")
        return
    await message.reply_text(f"Allowed Users: {', '.join(map(str, ADMIN_IDS))}")

# Add user
@app.on_message(filters.command("add_user") & filters.private)
async def add_user(client, message):
    if not is_admin(message.from_user.id):
        await message.reply_text("Admins only!")
        return
    try:
        user_id = int(message.text.split()[1])
        if user_id not in ADMIN_IDS:
            ADMIN_IDS.append(user_id)
            with open(".env", "a") as f:
                f.write(f"\nADMIN_IDS={','.join(map(str, ADMIN_IDS))}")
            await message.reply_text(f"User {user_id} added as admin!")
            await log_event(f"User {user_id} added as admin by {message.from_user.id}")
        else:
            await message.reply_text("User already an admin!")
    except Exception as e:
        await message.reply_text("Usage: /add_user <user_id>")
        await log_event(f"Error adding user: {e}")

# Remove user
@app.on_message(filters.command("remove_user") & filters.private)
async def remove_user(client, message):
    if not is_admin(message.from_user.id):
        await message.reply_text("Admins only!")
        return
    try:
        user_id = int(message.text.split()[1])
        if user_id in ADMIN_IDS:
            ADMIN_IDS.remove(user_id)
            with open(".env", "w") as f:
                f.write(f"BOT_TOKEN={BOT_TOKEN}\nADMIN_IDS={','.join(map(str, ADMIN_IDS))}\nLOG_CHANNEL_ID={LOG_CHANNEL_ID}\nDB_CHANNEL_ID={DB_CHANNEL_ID}\nDOMAIN={DOMAIN}\nTINYURL_API={TINYURL_API}")
            await message.reply_text(f"User {user_id} removed from admins!")
            await log_event(f"User {user_id} removed from admins by {message.from_user.id}")
        else:
            await message.reply_text("User not an admin!")
    except Exception as e:
        await message.reply_text("Usage: /remove_user <user_id>")
        await log_event(f"Error removing user: {e}")

# Broadcast message
@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast(client, message):
    if not is_admin(message.from_user.id):
        await message.reply_text("Admins only!")
        return
    try:
        msg = message.text.split(maxsplit=1)[1]
        async with aiosqlite.connect("database.db") as db:
            async with db.execute("SELECT DISTINCT uploader_id FROM content") as cursor:
                users = await cursor.fetchall()
                for user_id in users:
                    try:
                        await app.send_message(user_id[0], msg)
                    except Exception:
                        pass
        await message.reply_text("Broadcast sent!")
        await log_event(f"Broadcast sent by {message.from_user.id}: {msg}")
    except Exception as e:
        await message.reply_text("Usage: /broadcast <message>")
        await log_event(f"Error broadcasting: {e}")

# Start bot
async def main():
    await init_db()
    await app.start()
    await log_event("Bot started!")
    await app.run()

if __name__ == "__main__":
    asyncio.run(main())
