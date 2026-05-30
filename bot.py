import os
import subprocess
import glob
import traceback
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler

# ==================== CONFIG ====================
TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
PORT = int(os.environ.get('PORT', 8080))
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '')

# ==================== STATES ====================
(WAITING_VIDEO, WAITING_AUDIO_CHOICE, WAITING_DURATION, WAITING_SIZE) = range(4)

# ==================== USER SETTINGS ====================
user_settings = {}  # {user_id: {audio: True/False, max_duration: 60, max_size: 2.5}}

def get_user_settings(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = {
            'audio': False,
            'max_duration': 60,
            'max_size': 2.5,
            'crop_mode': 'fit'  # fit, fill, stretch
        }
    return user_settings[user_id]

# ==================== KEYBOARDS ====================
def settings_keyboard(user_id):
    s = get_user_settings(user_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔊 Audio: {'✅ ON' if s['audio'] else '❌ OFF'}", callback_data='toggle_audio')],
        [InlineKeyboardButton(f"⏱ Max Duration: {s['max_duration']}s", callback_data='set_duration')],
        [InlineKeyboardButton(f"📦 Max Size: {s['max_size']}MB", callback_data='set_size')],
        [InlineKeyboardButton(f"🖼 Crop Mode: {s['crop_mode']}", callback_data='crop_mode')],
        [InlineKeyboardButton("🔄 Reset Defaults", callback_data='reset')],
    ])

main_keyboard = ReplyKeyboardMarkup([
    ['⚙️ Settings', '📹 Convert Video'],
    ['🖼 Photo to VN', '📊 My Stats'],
    ['❌ Cancel']
], resize_keyboard=True)

# ==================== FFMPEG HELPERS ====================
def check_ffmpeg():
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
        return True
    except:
        return False

def get_video_info(input_path):
    """Get video info"""
    info = {'duration': 0, 'width': 0, 'height': 0, 'has_audio': False}
    try:
        cmd = ['ffprobe', '-v', 'error', '-show_entries',
               'format=duration:stream=width,height,codec_type',
               '-of', 'json', input_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        import json
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

def convert_to_video_note(input_path, output_path, user_id):
    """Convert video to round video message format"""
    s = get_user_settings(user_id)
    
    # Video filter based on crop mode
    if s['crop_mode'] == 'fill':
        vf = 'scale=360:360:force_original_aspect_ratio=increase,crop=360:360,setsar=1'
    elif s['crop_mode'] == 'stretch':
        vf = 'scale=360:360,setsar=1'
    else:  # fit
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
    
    # Audio settings
    if s['audio']:
        cmd.extend(['-c:a', 'aac', '-b:a', '64k', '-ac', '1'])
    else:
        cmd.extend(['-an'])
    
    cmd.extend(['-y', output_path])
    
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=120)
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            
            # If too large, compress more
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

def photo_to_video_note(input_path, output_path, user_id):
    """Convert photo to video note with zoom effect"""
    s = get_user_settings(user_id)
    
    cmd = [
        'ffmpeg', '-loop', '1', '-i', input_path,
        '-vf', 'scale=360:360:force_original_aspect_ratio=decrease,pad=360:360:(ow-iw)/2:(oh-ih)/2:black,zoompan=z=\'min(zoom+0.002,1.3)\':d=125:x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\',setsar=1',
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
    if not check_ffmpeg():
        await update.message.reply_text(
            '❌ **FFmpeg not installed!**\n\n'
            'Please install FFmpeg on your server:\n'
            '`apt install ffmpeg` (Linux)\n'
            'Or add `ffmpeg` to `packages.txt` on Railway.'
        )
        return ConversationHandler.END
    
    await update.message.reply_text(
        '📹 **Video → Video Message Converter**\n\n'
        'Send me a video/photo to convert!\n'
        'Use ⚙️ Settings to customize output.',
        reply_markup=main_keyboard
    )
    return WAITING_VIDEO

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = get_user_settings(user_id)
    
    text = (
        f'⚙️ **Settings**\n\n'
        f'🔊 Audio: {"✅ ON" if s["audio"] else "❌ OFF"}\n'
        f'⏱ Max Duration: {s["max_duration"]} seconds\n'
        f'📦 Max Size: {s["max_size"]} MB\n'
        f'🖼 Crop Mode: {s["crop_mode"]}\n\n'
        f'Choose a setting to change:'
    )
    
    await update.message.reply_text(text, reply_markup=settings_keyboard(user_id))
    return WAITING_VIDEO

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    s = get_user_settings(user_id)
    data = query.data
    
    if data == 'toggle_audio':
        s['audio'] = not s['audio']
        await query.edit_message_text(
            f'🔊 Audio: {"✅ ON" if s["audio"] else "❌ OFF"}',
            reply_markup=settings_keyboard(user_id)
        )
    
    elif data == 'set_duration':
        s['max_duration'] = s['max_duration'] + 30 if s['max_duration'] < 120 else 15
        if s['max_duration'] > 120:
            s['max_duration'] = 15
        await query.edit_message_text(
            f'⏱ Max Duration: {s["max_duration"]}s',
            reply_markup=settings_keyboard(user_id)
        )
    
    elif data == 'set_size':
        sizes = [1.0, 1.5, 2.0, 2.5, 3.0]
        current_idx = sizes.index(s['max_size']) if s['max_size'] in sizes else 3
        next_idx = (current_idx + 1) % len(sizes)
        s['max_size'] = sizes[next_idx]
        await query.edit_message_text(
            f'📦 Max Size: {s["max_size"]}MB',
            reply_markup=settings_keyboard(user_id)
        )
    
    elif data == 'crop_mode':
        modes = ['fit', 'fill', 'stretch']
        current_idx = modes.index(s['crop_mode']) if s['crop_mode'] in modes else 0
        s['crop_mode'] = modes[(current_idx + 1) % 3]
        await query.edit_message_text(
            f'🖼 Crop Mode: {s["crop_mode"]}',
            reply_markup=settings_keyboard(user_id)
        )
    
    elif data == 'reset':
        user_settings[user_id] = {
            'audio': False,
            'max_duration': 60,
            'max_size': 2.5,
            'crop_mode': 'fit'
        }
        await query.edit_message_text(
            '🔄 Settings reset to defaults!',
            reply_markup=settings_keyboard(user_id)
        )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    s = get_user_settings(user.id)
    
    # Detect file type
    file_id = None
    duration = 0
    
    if msg.video:
        video = msg.video
        file_id = video.file_id
        duration = video.duration
    elif msg.document and msg.document.mime_type and 'video' in msg.document.mime_type:
        video = msg.document
        file_id = video.file_id
    elif msg.animation:
        video = msg.animation
        file_id = video.file_id
        duration = video.duration
    elif msg.video_note:
        await msg.reply_text('✅ This is already a video message!')
        return WAITING_VIDEO
    else:
        return WAITING_VIDEO
    
    # Download
    status = await msg.reply_text('⬇️ Downloading...')
    
    input_path = f'input_{user.id}.mp4'
    output_path = f'output_{user.id}.mp4'
    
    try:
        file = await context.bot.get_file(file_id)
        await file.download_to_drive(input_path)
        
        # Get video info
        info = get_video_info(input_path)
        
        if info['duration'] > s['max_duration']:
            await status.edit_text(
                f'⚠️ Video is {info["duration"]:.0f}s.\n'
                f'Trimming to {s["max_duration"]}s...'
            )
        
        # Show audio info
        audio_text = 'with 🔊 audio' if (s['audio'] and info['has_audio']) else 'without 🔇 audio'
        await status.edit_text(f'🔄 Converting {audio_text}...\n🖼 Mode: {s["crop_mode"]}')
        
        # Convert
        result = convert_to_video_note(input_path, output_path, user.id)
        
        if result and os.path.exists(result):
            size_mb = os.path.getsize(result) / (1024 * 1024)
            
            if size_mb > s['max_size']:
                await status.edit_text(
                    f'⚠️ Result is {size_mb:.1f}MB (limit: {s["max_size"]}MB).\n'
                    'Increase max size in ⚙️ Settings or use shorter video.'
                )
            else:
                await status.edit_text('📤 Sending...')
                
                try:
                    with open(result, 'rb') as f:
                        await msg.reply_video_note(
                            video_note=f,
                            duration=min(int(info['duration']), s['max_duration']),
                            length=360
                        )
                    await status.delete()
                    
                    # Show stats
                    await msg.reply_text(
                        f'✅ **Done!**\n'
                        f'📦 Size: {size_mb:.1f}MB\n'
                        f'⏱ Duration: {min(int(info["duration"]), s["max_duration"])}s\n'
                        f'🔊 Audio: {"Yes" if s["audio"] and info["has_audio"] else "No"}\n'
                        f'🖼 Mode: {s["crop_mode"]}',
                        reply_markup=main_keyboard
                    )
                except Exception as e:
                    await status.edit_text(f'❌ Upload failed!\n{str(e)[:100]}')
        else:
            await status.edit_text('❌ Conversion failed!')
    
    except Exception as e:
        await status.edit_text(f'❌ Error: {str(e)[:100]}')
    
    finally:
        for path in [input_path, output_path]:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except:
                pass
    
    return WAITING_VIDEO

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message
    s = get_user_settings(user.id)
    
    status = await msg.reply_text('🔄 Converting photo to video message...')
    
    input_path = f'photo_{user.id}.jpg'
    output_path = f'photo_{user.id}.mp4'
    
    try:
        photo = msg.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive(input_path)
        
        result = photo_to_video_note(input_path, output_path, user.id)
        
        if result and os.path.exists(result):
            with open(result, 'rb') as f:
                await msg.reply_video_note(video_note=f, duration=4, length=360)
            await status.delete()
            await msg.reply_text('✅ Photo converted!', reply_markup=main_keyboard)
        else:
            await status.edit_text('❌ Conversion failed!')
    
    except Exception as e:
        await status.edit_text(f'❌ Error: {str(e)[:100]}')
    
    finally:
        for p in [input_path, output_path]:
            try:
                if os.path.exists(p): os.remove(p)
            except: pass
    
    return WAITING_VIDEO

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    s = get_user_settings(user_id)
    
    await update.message.reply_text(
        f'📊 **Your Settings**\n\n'
        f'🔊 Audio: {"ON" if s["audio"] else "OFF"}\n'
        f'⏱ Max Duration: {s["max_duration"]}s\n'
        f'📦 Max Size: {s["max_size"]}MB\n'
        f'🖼 Crop Mode: {s["crop_mode"]}',
        reply_markup=main_keyboard
    )
    return WAITING_VIDEO

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('👋 Bye! /start to begin again.')
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")
    print(traceback.format_exc())

# ==================== MAIN ====================
def main():
    if not check_ffmpeg():
        print("❌ FFmpeg is required! Install it first.")
        print("   Linux: apt install ffmpeg")
        print("   macOS: brew install ffmpeg")
        print("   Windows: download from ffmpeg.org")
        exit(1)
    
    print('🤖 Starting Video Note Converter...')
    
    app = Application.builder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            WAITING_VIDEO: [
                MessageHandler(filters.VIDEO | filters.Document.VIDEO | filters.ANIMATION, handle_video),
                MessageHandler(filters.PHOTO, handle_photo),
                MessageHandler(filters.Regex('(?i)settings'), settings_menu),
                MessageHandler(filters.Regex('(?i)stats'), my_stats),
                MessageHandler(filters.Regex('(?i)convert'), start),
                CommandHandler('start', start),
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            MessageHandler(filters.Regex('(?i)cancel'), cancel),
        ],
        conversation_timeout=600,
    )
    
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)
    
    print('✅ Bot is ready!')
    
    if WEBHOOK_URL:
        app.run_webhook(listen='0.0.0.0', port=PORT, webhook_url=f'{WEBHOOK_URL}/{TOKEN}')
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
