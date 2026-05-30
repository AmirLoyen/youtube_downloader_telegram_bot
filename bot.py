import os
import subprocess
import sys
import json
import traceback
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler

# ==================== AUTO INSTALL FFMPEG ====================
def ensure_ffmpeg():
    """Check and auto-install FFmpeg"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
        print("✅ FFmpeg found!")
        return True
    except:
        print("⚠️ FFmpeg not found! Installing...")
        try:
            subprocess.run(['apt-get', 'update', '-qq'], capture_output=True, timeout=30)
            subprocess.run(['apt-get', 'install', '-y', '-qq', 'ffmpeg'], capture_output=True, timeout=60)
            subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
            print("✅ FFmpeg installed!")
            return True
        except Exception as e:
            print(f"❌ Failed to install FFmpeg: {e}")
            return False

if not ensure_ffmpeg():
    print("⚠️ FFmpeg not available. Bot may not work properly.")

# ==================== CONFIG ====================
TOKEN = os.environ.get('BOT_TOKEN', '')
if not TOKEN:
    print("❌ BOT_TOKEN not set!")
    exit(1)

PORT = int(os.environ.get('PORT', 8080))

# ==================== STATES ====================
WAITING_VIDEO = 1

# ==================== USER SETTINGS ====================
user_settings = {}

def get_settings(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = {
            'audio': False,
            'max_duration': 60,
            'max_size': 2.5,
            'crop_mode': 'fit'
        }
    return user_settings[user_id]

# ==================== KEYBOARDS ====================
def settings_menu(user_id):
    s = get_settings(user_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔊 Audio: {'✅ ON' if s['audio'] else '❌ OFF'}", callback_data='audio')],
        [InlineKeyboardButton(f"⏱ Duration: {s['max_duration']}s", callback_data='duration')],
        [InlineKeyboardButton(f"📦 Max Size: {s['max_size']}MB", callback_data='size')],
        [InlineKeyboardButton(f"🖼 Crop: {s['crop_mode']}", callback_data='crop')],
        [InlineKeyboardButton("🔄 Reset Defaults", callback_data='reset')],
    ])

main_kb = ReplyKeyboardMarkup([
    ['⚙️ Settings', '📹 Convert Video'],
    ['🖼 Photo to VN', '📊 My Stats'],
    ['❌ Cancel']
], resize_keyboard=True)

# ==================== FFMPEG HELPERS ====================
def get_video_info(path):
    info = {'duration': 0, 'width': 0, 'height': 0, 'has_audio': False}
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries', 
               'format=duration:stream=width,height,codec_type', 
               '-of', 'json', path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        data = json.loads(result.stdout)
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                info['width'] = stream.get('width', 0)
                info['height'] = stream.get('height', 0)
            elif stream.get('codec_type') == 'audio':
                info['has_audio'] = True
        info['duration'] = float(data.get('format', {}).get('duration', 0))
    except:
        pass
    return info

def convert_video(input_path, output_path, user_id):
    s = get_settings(user_id)
    
    if s['crop_mode'] == 'fill':
        vf = 'scale=360:360:force_original_aspect_ratio=increase,crop=360:360,setsar=1'
    elif s['crop_mode'] == 'stretch':
        vf = 'scale=360:360,setsar=1'
    else:
        vf = 'scale=360:360:force_original_aspect_ratio=decrease,pad=360:360:(ow-iw)/2:(oh-ih)/2:black,setsar=1'
    
    cmd = [
        'ffmpeg', '-i', input_path,
        '-vf', vf,
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '30',
        '-maxrate', '500k',
        '-bufsize', '1M',
        '-t', str(s['max_duration']),
    ]
    
    if s['audio']:
        cmd.extend(['-c:a', 'aac', '-b:a', '64k', '-ac', '1'])
    else:
        cmd.extend(['-an'])
    
    cmd.extend(['-y', output_path])
    
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=120)
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            
            if size_mb > s['max_size']:
                cmd2 = [
                    'ffmpeg', '-i', input_path,
                    '-vf', vf,
                    '-c:v', 'libx264',
                    '-preset', 'veryfast',
                    '-crf', '40',
                    '-maxrate', '200k',
                    '-bufsize', '500k',
                    '-t', str(min(s['max_duration'], 30)),
                ]
                if s['audio']:
                    cmd2.extend(['-c:a', 'aac', '-b:a', '32k', '-ac', '1'])
                else:
                    cmd2.extend(['-an'])
                cmd2.extend(['-y', output_path])
                subprocess.run(cmd2, capture_output=True, timeout=120)
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return output_path
    except Exception as e:
        print(f"FFmpeg error: {e}")
    return None

def photo_to_vn(input_path, output_path, user_id):
    cmd = [
        'ffmpeg', '-loop', '1', '-i', input_path,
        '-vf', 'scale=360:360:force_original_aspect_ratio=decrease,pad=360:360:(ow-iw)/2:(oh-ih)/2:black,zoompan=z=\'min(zoom+0.002,1.3)\':d=125:s=360x360',
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '30',
        '-t', '4',
        '-an', '-y',
        output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=30)
        if os.path.exists(output_path):
            return output_path
    except:
        pass
    return None

# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '📹 **Video → Video Message Converter**\n\n'
        'Send me a video or photo to convert!\n\n'
        '• 🎬 Video → Round Video Message\n'
        '• 🖼 Photo → Video Message with zoom\n\n'
        'Use ⚙️ **Settings** to customize:\n'
        '🔊 Audio | ⏱ Duration | 📦 Size | 🖼 Crop',
        reply_markup=main_kb
    )
    return WAITING_VIDEO

async def settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = get_settings(user_id)
    
    text = (
        f'⚙️ **Current Settings**\n\n'
        f'🔊 Audio: {"✅ ON" if s["audio"] else "❌ OFF"}\n'
        f'⏱ Max Duration: {s["max_duration"]} seconds\n'
        f'📦 Max Size: {s["max_size"]} MB\n'
        f'🖼 Crop Mode: {s["crop_mode"]}\n\n'
        f'Tap a button to change:'
    )
    
    await update.message.reply_text(text, reply_markup=settings_menu(user_id))
    return WAITING_VIDEO

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    s = get_settings(user_id)
    data = query.data
    
    if data == 'audio':
        s['audio'] = not s['audio']
    elif data == 'duration':
        durations = [15, 30, 45, 60, 90, 120]
        idx = durations.index(s['max_duration']) if s['max_duration'] in durations else 3
        s['max_duration'] = durations[(idx + 1) % len(durations)]
    elif data == 'size':
        sizes = [1.0, 1.5, 2.0, 2.5, 3.0]
        idx = sizes.index(s['max_size']) if s['max_size'] in sizes else 3
        s['max_size'] = sizes[(idx + 1) % len(sizes)]
    elif data == 'crop':
        modes = ['fit', 'fill', 'stretch']
        idx = modes.index(s['crop_mode']) if s['crop_mode'] in modes else 0
        s['crop_mode'] = modes[(idx + 1) % 3]
    elif data == 'reset':
        user_settings[user_id] = {'audio': False, 'max_duration': 60, 'max_size': 2.5, 'crop_mode': 'fit'}
    
    s = get_settings(user_id)
    text = (
        f'⚙️ **Current Settings**\n\n'
        f'🔊 Audio: {"✅ ON" if s["audio"] else "❌ OFF"}\n'
        f'⏱ Max Duration: {s["max_duration"]} seconds\n'
        f'📦 Max Size: {s["max_size"]} MB\n'
        f'🖼 Crop Mode: {s["crop_mode"]}'
    )
    
    await query.edit_message_text(text, reply_markup=settings_menu(user_id))

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    s = get_settings(user.id)
    
    file_id = None
    duration = 0
    
    if msg.video:
        file_id = msg.video.file_id
        duration = msg.video.duration
    elif msg.document and msg.document.mime_type and 'video' in msg.document.mime_type:
        file_id = msg.document.file_id
    elif msg.animation:
        file_id = msg.animation.file_id
        duration = msg.animation.duration
    elif msg.video_note:
        await msg.reply_text('✅ Already a video message! Send a regular video to convert.')
        return WAITING_VIDEO
    else:
        return WAITING_VIDEO
    
    status = await msg.reply_text('⬇️ Downloading video...')
    
    input_path = f'input_{user.id}.mp4'
    output_path = f'output_{user.id}.mp4'
    
    try:
        file = await context.bot.get_file(file_id)
        await file.download_to_drive(input_path)
        
        info = get_video_info(input_path)
        
        if info['duration'] > s['max_duration']:
            await status.edit_text(f'⚠️ Video is {info["duration"]:.0f}s. Trimming to {s["max_duration"]}s...')
        
        audio_text = 'with 🔊 audio' if (s['audio'] and info['has_audio']) else 'without 🔊 audio'
        await status.edit_text(f'🔄 Converting {audio_text}...\n🖼 Mode: {s["crop_mode"]}')
        
        result = convert_video(input_path, output_path, user.id)
        
        if result and os.path.exists(result):
            size_mb = os.path.getsize(result) / (1024 * 1024)
            
            if size_mb > s['max_size']:
                await status.edit_text(
                    f'⚠️ Result is {size_mb:.1f}MB (limit: {s["max_size"]}MB).\n'
                    'Increase max size in ⚙️ Settings or try a shorter video.'
                )
            else:
                await status.edit_text('📤 Sending video message...')
                
                with open(result, 'rb') as f:
                    await msg.reply_video_note(
                        video_note=f,
                        duration=min(int(info['duration']), s['max_duration']),
                        length=360
                    )
                await status.delete()
                
                await msg.reply_text(
                    f'✅ **Done!**\n'
                    f'📦 Size: {size_mb:.1f}MB\n'
                    f'⏱ Duration: {min(int(info["duration"]), s["max_duration"])}s\n'
                    f'🔊 Audio: {"ON" if s["audio"] and info["has_audio"] else "OFF"}\n'
                    f'🖼 Crop: {s["crop_mode"]}',
                    reply_markup=main_kb
                )
        else:
            await status.edit_text('❌ Conversion failed! Try a different video or check FFmpeg installation.')
    
    except Exception as e:
        await status.edit_text(f'❌ Error: {str(e)[:100]}')
    
    finally:
        for p in [input_path, output_path]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except:
                pass
    
    return WAITING_VIDEO

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    
    status = await msg.reply_text('🔄 Converting photo to video message...')
    
    input_path = f'photo_{user.id}.jpg'
    output_path = f'photo_{user.id}.mp4'
    
    try:
        photo = msg.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive(input_path)
        
        result = photo_to_vn(input_path, output_path, user.id)
        
        if result and os.path.exists(result):
            with open(result, 'rb') as f:
                await msg.reply_video_note(video_note=f, duration=4, length=360)
            await status.delete()
            await msg.reply_text('✅ Photo converted to video message!', reply_markup=main_kb)
        else:
            await status.edit_text('❌ Conversion failed! Make sure FFmpeg is installed.')
    
    except Exception as e:
        await status.edit_text(f'❌ Error: {str(e)[:100]}')
    
    finally:
        for p in [input_path, output_path]:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except:
                pass
    
    return WAITING_VIDEO

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = get_settings(user_id)
    
    await update.message.reply_text(
        f'📊 **Your Settings**\n\n'
        f'🔊 Audio: {"ON" if s["audio"] else "OFF"}\n'
        f'⏱ Max Duration: {s["max_duration"]}s\n'
        f'📦 Max Size: {s["max_size"]}MB\n'
        f'🖼 Crop Mode: {s["crop_mode"]}',
        reply_markup=main_kb
    )
    return WAITING_VIDEO

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('👋 Goodbye! Send /start to begin again.')
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")
    print(traceback.format_exc())
    if update and hasattr(update, 'message') and update.message:
        try:
            await update.message.reply_text('❌ An error occurred. Please try /start again.')
        except:
            pass

# ==================== MAIN ====================
def main():
    print('🤖 Starting Video Note Converter Bot...')
    
    app = Application.builder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            WAITING_VIDEO: [
                MessageHandler(filters.VIDEO | filters.Document.VIDEO | filters.ANIMATION, handle_video),
                MessageHandler(filters.PHOTO, handle_photo),
                MessageHandler(filters.Regex('(?i)^⚙️ Settings$'), settings_handler),
                MessageHandler(filters.Regex('(?i)^📊 My Stats$'), stats_handler),
                MessageHandler(filters.Regex('(?i)^📹 Convert Video$'), start),
                MessageHandler(filters.Regex('(?i)^🖼 Photo to VN$'), start),
                CommandHandler('start', start),
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            MessageHandler(filters.Regex('(?i)^❌ Cancel$'), cancel),
        ],
    )
    
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)
    
    print('✅ Bot is running...')
    
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
