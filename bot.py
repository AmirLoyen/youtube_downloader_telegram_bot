import os
import subprocess
import glob
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ==================== CONFIG ====================
TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_TOKEN')
MAX_SIZE_MB = 2.5  # حداکثر حجم برای Video Message (حدود 2.5MB امنه)
MAX_DURATION = 60   # حداکثر 60 ثانیه

# ==================== STATES ====================
WAITING_VIDEO = 1

# ==================== FUNCTIONS ====================
def convert_to_video_message(input_path, output_path):
    """Convert video to Telegram video message format (round, 360x360, max 60s)"""
    try:
        cmd = [
            'ffmpeg', '-i', input_path,
            '-vf', 'crop=min(iw\\,ih):min(iw\\,ih),scale=360:360,setsar=1',  # Crop to square + resize
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '30',               # Compression
            '-maxrate', '500k',          # Low bitrate for small size
            '-bufsize', '1M',
            '-t', str(MAX_DURATION),     # Max 60 seconds
            '-an',                       # Remove audio (video messages are silent)
            '-y',                        # Overwrite
            output_path
        ]
        subprocess.run(cmd, capture_output=True, check=True, timeout=120)
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            if size_mb > MAX_SIZE_MB:
                # Try harder compression
                cmd2 = [
                    'ffmpeg', '-i', input_path,
                    '-vf', 'crop=min(iw\\,ih):min(iw\\,ih),scale=360:360,setsar=1',
                    '-c:v', 'libx264',
                    '-preset', 'veryfast',
                    '-crf', '40',
                    '-maxrate', '200k',
                    '-bufsize', '500k',
                    '-t', str(min(MAX_DURATION, 30)),
                    '-an', '-y',
                    output_path
                ]
                subprocess.run(cmd2, capture_output=True, timeout=120)
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return output_path
    except Exception as e:
        print(f"FFmpeg error: {e}")
    return None

def get_video_duration(input_path):
    """Get video duration in seconds"""
    try:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            input_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(result.stdout.strip())
    except:
        return 0

# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '📹 **Video → Video Message Converter**\n\n'
        'Send me a video and I\'ll convert it to a round video message!\n\n'
        '⚠️ Best results:\n'
        '• Videos under 60 seconds\n'
        '• Square videos work best\n'
        '• Final size under 2.5MB'
    )
    return WAITING_VIDEO

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Get video file
    if update.message.video:
        video = update.message.video
        file_id = video.file_id
    elif update.message.document and update.message.document.mime_type and 'video' in update.message.document.mime_type:
        video = update.message.document
        file_id = video.file_id
    elif update.message.animation:
        video = update.message.animation
        file_id = video.file_id
    else:
        await update.message.reply_text('❌ Please send a video file!')
        return WAITING_VIDEO
    
    # Check duration
    duration = getattr(video, 'duration', 0)
    if duration > 120:
        await update.message.reply_text(
            f'⚠️ Video is {duration}s long. Max 60s for video messages.\n'
            'I\'ll trim it to 60 seconds.'
        )
    
    # Download video
    msg = await update.message.reply_text('⬇️ Downloading...')
    
    input_path = f'input_{user.id}.mp4'
    output_path = f'output_{user.id}.mp4'
    
    try:
        # Download
        file = await context.bot.get_file(file_id)
        await file.download_to_drive(input_path)
        
        await msg.edit_text('🔄 Converting to video message...')
        
        # Convert
        result = convert_to_video_message(input_path, output_path)
        
        if result and os.path.exists(result):
            size_mb = os.path.getsize(result) / (1024 * 1024)
            
            if size_mb > MAX_SIZE_MB:
                await msg.edit_text(f'⚠️ Result is {size_mb:.1f}MB. Telegram limit is 2.5MB.\nTry a shorter video!')
            else:
                await msg.edit_text('📤 Sending video message...')
                
                try:
                    # Send as video note (round video message)
                    with open(result, 'rb') as f:
                        await update.message.reply_video_note(
                            video_note=f,
                            duration=min(int(duration), MAX_DURATION),
                            length=360
                        )
                    await msg.delete()
                except Exception as e:
                    await msg.edit_text(f'❌ Upload failed! File might be too large.\n{str(e)[:100]}')
        else:
            await msg.edit_text('❌ Conversion failed! Make sure FFmpeg is installed.')
    
    except Exception as e:
        await msg.edit_text(f'❌ Error: {str(e)[:100]}')
    
    finally:
        # Clean up
        for path in [input_path, output_path]:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except:
                pass
    
    await update.message.reply_text('✅ Send another video or /start to reset.')
    return WAITING_VIDEO

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Convert photo to video message with simple animation"""
    user = update.effective_user
    msg = await update.message.reply_text('🔄 Converting photo...')
    
    input_path = f'photo_{user.id}.jpg'
    output_path = f'photo_{user.id}.mp4'
    
    try:
        # Download photo
        photo = update.message.photo[-1]  # Largest size
        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive(input_path)
        
        # Create video from photo (zoom effect)
        cmd = [
            'ffmpeg', '-loop', '1', '-i', input_path,
            '-vf', 'crop=min(iw\\,ih):min(iw\\,ih),scale=360:360,setsar=1,zoompan=z=\'min(zoom+0.0015\\,1.2)\':d=125:x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\'',
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '30',
            '-t', '3',
            '-an', '-y',
            output_path
        ]
        subprocess.run(cmd, capture_output=True, timeout=30)
        
        if os.path.exists(output_path):
            with open(output_path, 'rb') as f:
                await update.message.reply_video_note(video_note=f, duration=3, length=360)
            await msg.delete()
        else:
            await msg.edit_text('❌ Conversion failed!')
    
    except Exception as e:
        await msg.edit_text(f'❌ Error: {str(e)[:100]}')
    
    finally:
        for p in [input_path, output_path]:
            try:
                if os.path.exists(p): os.remove(p)
            except: pass
    
    return WAITING_VIDEO

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('👋 Bye! /start')
    return ConversationHandler.END

# ==================== MAIN ====================
def main():
    app = Application.builder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            WAITING_VIDEO: [
                MessageHandler(filters.VIDEO | filters.Document.VIDEO | filters.ANIMATION, handle_video),
                MessageHandler(filters.PHOTO, handle_photo),
                CommandHandler('start', start),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        conversation_timeout=600,
    )
    
    app.add_handler(conv)
    print('✅ Video Note Converter Bot is running!')
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
