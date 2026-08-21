import static_ffmpeg
static_ffmpeg.add_paths()

import asyncio
import os
import glob
import logging
import html
import ssl
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.session.aiohttp import AiohttpSession
from yt_dlp import YoutubeDL
from shazamio import Shazam

logging.getLogger("symphonia").setLevel(logging.ERROR)
logging.getLogger("symphonia_bundle_mp3").setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8808125320:AAF0ELVtGPEiQN8G2ClFBGngPqJQhz0X2MU")

bot = None
dp = Dispatcher()

# Foydalanuvchilarning oxirgi qidiruv natijalarini saqlash
user_last_search = {}

def format_duration(seconds):
    if not seconds:
        return ""
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins}:{secs:02d}"

def create_page_response(user_id, page=0):
    data = user_last_search.get(user_id, {})
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
        video_id = entry.get('id')
        
        text += f"<b>{idx}.</b> <i>{title}</i>{duration_str}\n"
        
        if video_id:
            row_buttons.append(
                types.InlineKeyboardButton(text=str(idx), callback_data=f"dl_{video_id}")
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

async def extract_audio_from_video(video_path: str, output_audio_path: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            'ffmpeg', '-y', '-i', video_path, '-vn', '-ac', '2', '-ar', '44100', '-ab', '192k', output_audio_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        return os.path.exists(output_audio_path) and os.path.getsize(output_audio_path) > 0
    except Exception as e:
        logging.error(f"FFmpeg conversion error: {e}")
        return False

async def process_audio_and_find_song(message: types.Message, file_path: str):
    status_msg = await message.answer("🎧 Fayldagi qo'shiq Shazam orqali aniqlanmoqda...")
    
    try:
        shazam = Shazam()
        out = await shazam.recognize(file_path)

        track = out.get('track') if isinstance(out, dict) else None

        if track:
            subtitle = track.get('subtitle', '')
            title = track.get('title', '')
            song_name = f"{subtitle} - {title}".strip(" -")
        else:
            song_name = None

        if not song_name:
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
            'extractor_args': {'youtube': {'player_client': ['ios', 'android', 'mweb', 'web']}},
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            }
        }

        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: YoutubeDL(yt_opts).extract_info(song_name, download=False))
        
        raw_entries = info.get('entries', []) if info else []
        entries = [e for e in raw_entries if e is not None and e.get('id')]

        if not entries:
            await status_msg.edit_text("❌ Qo'shiq nomi aniqlandi, lekin yuklab olish uchun manbalar topilmadi.")
            return

        user_last_search[message.from_user.id] = {'query': song_name, 'entries': entries}

        text, reply_markup = create_page_response(message.from_user.id, page=0)
        await status_msg.delete()
        await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Shazam/YT Search error: {e}")
        await status_msg.edit_text("❌ Qo'shiqni aniqlashda yoki qidirishda xatolik yuz berdi.")

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer(
        "Assalomu alaykum!\n\n"
        "🎵 Musiqa nomini yozing — topib beraman.\n"
        "📹 Instagram/TikTok/YouTube havolasini yuboring — videoni yuklab beraman.\n"
        "🎙 Ovozli xabar, audio yoki video fayl yuboring — undagi musiqani Shazam orqali topib beraman!"
    )

@dp.message(F.video)
async def handle_direct_video(message: types.Message):
    file_prefix = f"tg_vid_{message.from_user.id}_{message.message_id}"
    video_path = f"{file_prefix}.mp4"
    audio_path = f"{file_prefix}.mp3"

    try:
        video_file = await bot.get_file(message.video.file_id)
        await bot.download_file(video_file.file_path, video_path)

        converted = await extract_audio_from_video(video_path, audio_path)
        target_file = audio_path if converted else video_path

        await process_audio_and_find_song(message, target_file)
    finally:
        for path in [video_path, audio_path]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

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
            try:
                os.remove(audio_path)
            except Exception:
                pass

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
            try:
                os.remove(voice_path)
            except Exception:
                pass

# --- SOCIAL MEDIA (INSTAGRAM, TIKTOK, YOUTUBE) LINKS ---
@dp.message(F.text.startswith("http://") | F.text.startswith("https://"))
async def download_social_video_and_find(message: types.Message):
    url = message.text.strip()
    status_msg = await message.answer("⏳ Video yuklanmoqda...")

    file_prefix = f"link_vid_{message.from_user.id}_{message.message_id}"
    downloaded_file = None

    ydl_opts = {
        'format': 'best',
        'outtmpl': f"{file_prefix}.%(ext)s",
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'ignoreerrors': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
    }

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: YoutubeDL(ydl_opts).download([url]))

        files = glob.glob(f"{file_prefix}.*")
        if files:
            downloaded_file = files[0]
            bot_user = await bot.get_me()
            
            builder = InlineKeyboardBuilder()
            builder.button(text="🎵 Musiqani topish", callback_data="find_music_from_video")

            await status_msg.delete()
            await message.answer_video(
                video=types.FSInputFile(downloaded_file),
                caption=f"👉 @{bot_user.username}",
                reply_markup=builder.as_markup()
            )
        else:
            await status_msg.edit_text("❌ Videoni yuklab bo'lmadi.")
    except Exception as e:
        await status_msg.edit_text("❌ Havolani qayta ishlashda xatolik yuz berdi.")
        logging.error(f"Link download error: {e}")
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except Exception:
                pass

@dp.callback_query(F.data == "find_music_from_video")
async def handle_find_music_button(callback: types.CallbackQuery):
    await callback.answer("⏳ Musiqa aniqlanmoqda...")
    
    video = callback.message.video
    if not video:
        await callback.message.answer("❌ Video fayli topilmadi.")
        return

    file_prefix = f"btn_vid_{callback.from_user.id}_{callback.message.message_id}"
    video_path = f"{file_prefix}.mp4"
    audio_path = f"{file_prefix}.mp3"

    try:
        video_file = await bot.get_file(video.file_id)
        await bot.download_file(video_file.file_path, video_path)

        converted = await extract_audio_from_video(video_path, audio_path)
        target_file = audio_path if converted else video_path

        await process_audio_and_find_song(callback.message, target_file)

    except Exception as e:
        logging.error(f"Video convert error: {e}")
        await callback.message.answer("❌ Videodan audioni ajratishda xatolik bo'ldi.")
    finally:
        for path in [video_path, audio_path]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

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
        'extractor_args': {'youtube': {'player_client': ['ios', 'android', 'mweb', 'web']}},
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        }
    }

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, lambda: YoutubeDL(ydl_opts).extract_info(song_name, download=False))
        
        raw_entries = info.get('entries', []) if info else []
        entries = [e for e in raw_entries if e is not None and e.get('id')]

        if not entries:
            await status_msg.edit_text("❌ Hech qanday qo'shiq topilmadi.")
            return

        user_last_search[message.from_user.id] = {'query': song_name, 'entries': entries}

        text, reply_markup = create_page_response(message.from_user.id, page=0)
        await status_msg.delete()
        await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Text search error: {e}")
        await status_msg.edit_text("❌ Afsuski, qidiruvda xatolik yuz berdi.")

@dp.callback_query(F.data.startswith("page_"))
async def change_page(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[1])
    text, reply_markup = create_page_response(callback.from_user.id, page=page)
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()

# --- YOUTUBE VIDEO ID ORQALI YUKLAB OLISH ---
@dp.callback_query(F.data.startswith("dl_"))
async def download_selected_music(callback: types.CallbackQuery):
    video_id = callback.data.split("_")[1]
    song_url = f"https://www.youtube.com/watch?v={video_id}"

    await callback.answer()
    status_msg = await callback.message.answer("⏳ Qo'shiq yuklanmoqda...", parse_mode="HTML")

    file_prefix = f"song_{callback.from_user.id}_{callback.message.message_id}"
    download_template = f"{file_prefix}.%(ext)s"

    ydl_opts = {
        'format': 'm4a/bestaudio/best',
        'outtmpl': download_template,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'extractor_args': {'youtube': {'player_client': ['ios', 'android', 'mweb', 'web']}},
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
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
        track_title = dl_info.get('track') or dl_info.get('title') or "Qo'shiq"

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
        logging.error(f"Yuklash xatoligi: {e}")
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except Exception:
                pass

async def main():
    global bot

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
            logging.info("Bot ishga tushmoqda...")
            await dp.start_polling(bot)
        except Exception as e:
            logging.error(f"Xatolik: {e}. 5 soniyadan keyin qayta ulanadi...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())