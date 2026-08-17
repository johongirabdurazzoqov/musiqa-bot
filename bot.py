import static_ffmpeg
static_ffmpeg.add_paths()

import asyncio
import os
import glob
import logging
import html
import ssl
import re
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.session.aiohttp import AiohttpSession
from yt_dlp import YoutubeDL
from shazamio import Shazam

# Symphonia va ffmpeg warning xabarlarini bostirish
logging.getLogger("symphonia").setLevel(logging.ERROR)
logging.getLogger("symphonia_bundle_mp3").setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8808125320:AAF0ELVtGPEiQN8G2ClFBGngPqJQhz0X2MU"

bot = None
connector = None
dp = Dispatcher()

user_search_data = {}

def format_duration(seconds):
    if not seconds:
        return ""
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins}:{secs:02d}"

def create_page_response(user_id, page=0):
    data = user_search_data.get(user_id, {})
    entries = data.get('entries', [])
    query = data.get('query', '')

    start_idx = page * 10
    end_idx = start_idx + 10
    page_entries = entries[start_idx:end_idx]

    safe_query = html.escape(query)
    text = f"🎧 Topilgan qo'shiq: <b>{safe_query}</b>\n\nYuklab olish uchun raqamni tanlang:\n\n"
    
    builder = InlineKeyboardBuilder()
    row_buttons = []

    for idx, entry in enumerate(page_entries, start=start_idx + 1):
        title = html.escape(entry.get('title', 'Noma\'lum'))
        duration = format_duration(entry.get('duration'))
        duration_str = f" <b>{duration}</b>" if duration else ""
        
        text += f"<b>{idx}.</b> <i>{title}</i>{duration_str}\n"
        row_buttons.append(
            types.InlineKeyboardButton(text=str(idx), callback_data=f"dl_{idx-1}")
        )

    for i in range(0, len(row_buttons), 5):
        builder.row(*row_buttons[i:i+5])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(text="⬅️", callback_data=f"page_{page-1}"))
    if end_idx < len(entries):
        nav_buttons.append(types.InlineKeyboardButton(text="➡️", callback_data=f"page_{page+1}"))

    if nav_buttons:
        builder.row(*nav_buttons)

    return text, builder.as_markup()

async def process_audio_and_find_song(message: types.Message, file_path: str):
    status_msg = await message.answer("🎧 Fayldagi qo'shiq Shazam orqali aniqlanmoqda...")
    
    try:
        shazam = Shazam()
        out = await shazam.recognize(file_path)

        track = out.get('track') if isinstance(out, dict) else None

        if track:
            song_name = f"{track.get('subtitle', '')} - {track.get('title', '')}".strip()
        else:
            song_name = None

        if not song_name or song_name == "-":
            await status_msg.edit_text("❌ Afsuski, Shazam fayldagi qo'shiqni aniqlay olmadi.")
            return

        await status_msg.edit_text(f"🔎 Qo'shiq topildi: <b>{html.escape(song_name)}</b>\nVariantlar qidirilmoqda...", parse_mode="HTML")

        yt_opts = {
            'default_search': 'ytsearch20:',
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'geo_bypass': True,
            'noplaylist': True,
            'ignoreerrors': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web']
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            }
        }

        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: YoutubeDL(yt_opts).extract_info(song_name, download=False))
        
        raw_entries = info.get('entries', []) if info else []
        entries = [e for e in raw_entries if e is not None]

        if not entries:
            await status_msg.edit_text("❌ Qo'shiq nomi aniqlandi, lekin yuklab olish uchun fayllar topilmadi.")
            return

        user_search_data[message.from_user.id] = {
            'query': song_name,
            'entries': entries
        }

        text, reply_markup = create_page_response(message.from_user.id, page=0)
        await status_msg.delete()
        await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")

    except Exception as e:
        print(f"Shazam search error: {e}")
        await status_msg.edit_text("❌ Qo'shiqni aniqlashda xatolik yuz berdi.")

# --- START COMMAND ---
@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer(
        "Assalomu alaykum!\n\n"
        "🎵 Musiqa nomini yozing — topib beraman.\n"
        "🎙 Ovozli xabar, audio yoki video fayl yuboring — undagi musiqani Shazam orqali topib beraman!"
    )

# --- 1. TELEGRAM'DAN YUBORILGAN VIDEO FAYL ---
@dp.message(F.video)
async def handle_direct_video(message: types.Message):
    file_prefix = f"tg_vid_{message.from_user.id}_{message.message_id}"
    video_path = f"{file_prefix}.mp4"

    try:
        video_file = await bot.get_file(message.video.file_id)
        await bot.download_file(video_file.file_path, video_path)
        await process_audio_and_find_song(message, video_path)
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)

# --- 2. TELEGRAM'DAN YUBORILGAN AUDIO FAYL (MP3, M4A va h.k.) ---
@dp.message(F.audio)
async def handle_direct_audio(message: types.Message):
    file_prefix = f"tg_aud_{message.from_user.id}_{message.message_id}"
    audio_path = f"{file_prefix}.mp3"

    try:
        audio_file = await bot.get_file(message.audio.file_id)
        await bot.download_file(audio_file.file_path, audio_path)
        await process_audio_and_find_song(message, audio_path)
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)

# --- 3. TELEGRAM'DAN YUBORILGAN OVOZLI XABAR (VOICE) ---
@dp.message(F.voice)
async def handle_direct_voice(message: types.Message):
    file_prefix = f"tg_voice_{message.from_user.id}_{message.message_id}"
    voice_path = f"{file_prefix}.ogg"

    try:
        voice_file = await bot.get_file(message.voice.file_id)
        await bot.download_file(voice_file.file_path, voice_path)
        await process_audio_and_find_song(message, voice_path)
    finally:
        if os.path.exists(voice_path):
            os.remove(voice_path)

# --- 4. LINK ORQALI VIDEO/AUDIO ---
@dp.message(F.text.startswith("http://") | F.text.startswith("https://"))
async def download_social_video_and_find(message: types.Message):
    url = message.text.strip()
    status_msg = await message.answer("⏳ Video/Audio yuklanmoqda va tahlil qilinmoqda...")

    file_prefix = f"link_vid_{message.from_user.id}_{message.message_id}"
    downloaded_file = None

    ydl_opts = {
        'format': 'm4a/bestaudio/best',
        'outtmpl': f"{file_prefix}.%(ext)s",
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'ignoreerrors': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        }
    }

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: YoutubeDL(ydl_opts).download([url]))

        files = glob.glob(f"{file_prefix}.*")
        if files:
            downloaded_file = files[0]
            await status_msg.delete()
            await process_audio_and_find_song(message, downloaded_file)
        else:
            await status_msg.edit_text("❌ Faylni yuklab bo'lmadi.")
    except Exception as e:
        await status_msg.edit_text("❌ Havolani qayta ishlashda xatolik yuz berdi.")
        print(f"Link download error: {e}")
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            os.remove(downloaded_file)

# --- 5. NOMI BO'YICHA QIDIRUV ---
@dp.message(F.text)
async def search_music(message: types.Message):
    song_name = message.text
    status_msg = await message.answer("🔎 Qo'shiqlar qidirilmoqda, kuting...")

    ydl_opts = {
        'default_search': 'ytsearch20:',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'noplaylist': True,
        'ignoreerrors': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        }
    }

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: YoutubeDL(ydl_opts).extract_info(song_name, download=False))
        
        raw_entries = info.get('entries', []) if info else []
        entries = [e for e in raw_entries if e is not None]

        if not entries:
            await status_msg.edit_text("❌ Hech qanday qo'shiq topilmadi.")
            return

        user_search_data[message.from_user.id] = {
            'query': song_name,
            'entries': entries
        }

        text, reply_markup = create_page_response(message.from_user.id, page=0)
        await status_msg.delete()
        await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")

    except Exception as e:
        await status_msg.edit_text("❌ Afsuski, qidiruvda xatolik yuz berdi.")

# --- PAGINATION & DOWNLOAD ---
@dp.callback_query(F.data.startswith("page_"))
async def change_page(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[1])
    text, reply_markup = create_page_response(callback.from_user.id, page=page)
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data.startswith("dl_"))
async def download_selected_music(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    choice_idx = int(callback.data.split("_")[1])

    data = user_search_data.get(user_id)
    if not data or choice_idx >= len(data['entries']):
        await callback.answer("❌ Ma'lumot topilmadi, iltimos qayta qidiring.", show_alert=True)
        return

    entry = data['entries'][choice_idx]
    song_url = entry.get('webpage_url') or entry.get('url')
    song_title = entry.get('title', 'Qo\'shiq')

    await callback.answer()
    status_msg = await callback.message.answer(f"⏳ <b>{html.escape(song_title)}</b> yuklanmoqda...", parse_mode="HTML")

    file_prefix = f"song_{user_id}_{callback.message.message_id}"
    download_template = f"{file_prefix}.%(ext)s"

    ydl_opts = {
        'format': 'm4a/bestaudio/best',
        'outtmpl': download_template,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        }
    }

    downloaded_file = None

    try:
        loop = asyncio.get_event_loop()
        
        dl_info = None
        for attempt in range(3):
            try:
                dl_info = await loop.run_in_executor(None, lambda: YoutubeDL(ydl_opts).extract_info(song_url, download=True))
                if dl_info:
                    break
            except Exception as e:
                if ("403" in str(e) or "Forbidden" in str(e)) and attempt < 2:
                    await asyncio.sleep(1)
                    continue
                raise e

        uploader = dl_info.get('uploader') or dl_info.get('artist') or "Musiqa Bot"
        track_title = dl_info.get('track') or dl_info.get('title') or song_title

        files = glob.glob(f"{file_prefix}.*")
        if files:
            downloaded_file = files[0]

        if downloaded_file and os.path.exists(downloaded_file):
            bot_user = await bot.get_me()
            await callback.message.answer_audio(
                audio=types.FSInputFile(downloaded_file),
                title=track_title,
                performer=uploader,
                caption=f"👉 @{bot_user.username}"
            )
            try:
                await status_msg.delete()
            except Exception:
                pass
        else:
            await status_msg.edit_text("❌ Faylni yuklab bo'lmadi.")

    except Exception as e:
        try:
            await status_msg.edit_text("❌ Qo'shiqni yuklashda xatolik yuz berdi.")
        except Exception:
            pass
        print(f"Yuklash xatoligi: {e}")
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            os.remove(downloaded_file)

# --- MAIN LOOP ---
async def main():
    global bot, connector

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    connector = aiohttp.TCPConnector(ssl=ssl_context)
    raw_session = aiohttp.ClientSession(connector=connector)
    bot_session = AiohttpSession()
    bot_session._session = raw_session

    bot = Bot(token=BOT_TOKEN, session=bot_session)

    while True:
        try:
            print("Bot ishga tushmoqda...")
            await dp.start_polling(bot)
        except Exception as e:
            print(f"Xatolik: {e}. 5 soniyadan keyin qayta ulanadi...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())