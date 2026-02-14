# bot.py (дополненный код)
import logging
import requests
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters, ContextTypes
import config

# Включаем логирование
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Этапы разговора
NAME, GAME, TIME = range(3)

# Твой вебхук от Make.com
WEBHOOK_URL = "https://hook.eu1.make.com/p6xhpykdytosqseygbrp3zw6c7bgvypp"

# Твой Telegram ID для уведомлений и админки
ADMIN_CHAT_ID = 518113103

# Хранилище ID пользователей (в реальном проекте лучше использовать БД)
# Но для простоты сохраняем в памяти и в файл
import os
import pickle

USERS_FILE = "users.pkl"

def load_users():
    """Загружает список пользователей из файла"""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'rb') as f:
            return pickle.load(f)
    return set()

def save_user(user_id):
    """Сохраняет нового пользователя"""
    users = load_users()
    users.add(user_id)
    with open(USERS_FILE, 'wb') as f:
        pickle.dump(users, f)

# --- ОСНОВНЫЕ ФУНКЦИИ БОТА (те, что уже были) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запускает диалог, спрашивает имя."""
    # Сохраняем пользователя при первом обращении
    user_id = update.effective_user.id
    save_user(user_id)
    
    await update.message.reply_text("Привет! Давай запишем тебя на игру. Введи своё имя:")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['player_name'] = update.message.text
    keyboard = [[InlineKeyboardButton(game, callback_data=game)] for game in config.GAME_TIMES.keys()]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Отлично! Теперь выбери игру:", reply_markup=reply_markup)
    return GAME

async def get_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chosen_game = query.data
    context.user_data['game'] = chosen_game

    available_times = config.GAME_TIMES.get(chosen_game, ["20:00"])
    keyboard = [[InlineKeyboardButton(time, callback_data=time)] for time in available_times]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(f"Ты выбрал(а) {chosen_game}. Теперь выбери время:", reply_markup=reply_markup)
    return TIME

async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chosen_time = query.data
    context.user_data['time'] = chosen_time

    user = update.effective_user
    username = user.username if user.username else "нет username"
    user_id = user.id

    player_name = context.user_data['player_name']
    game = context.user_data['game']
    time = context.user_data['time']

    result_message = f"✅ Ты записан!\n\nИмя: {player_name}\nИгра: {game}\nВремя: {time}\n\nЖдем тебя в Дискорде!"
    await query.edit_message_text(result_message)

    admin_message = (
        f"📝 Новая запись!\n\n"
        f"Имя: {player_name}\n"
        f"Игра: {game}\n"
        f"Время: {time}\n"
        f"Username: @{username}\n"
        f"Telegram ID: {user_id}"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_message)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение админу: {e}")

    data = {
        "name": player_name,
        "game": game,
        "time": time,
        "username": username,
        "user_id": user_id
    }
    try:
        requests.post(WEBHOOK_URL, json=data)
        logger.info("Данные отправлены в Make.com")
    except Exception as e:
        logger.error(f"Ошибка отправки в Make: {e}")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Запись отменена.")
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Просто нажми /start, чтобы записаться на игру.")

# --- НОВАЯ ФУНКЦИЯ: РАССЫЛКА ---

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет сообщение всем сохранённым пользователям (только для админа)"""
    user_id = update.effective_user.id
    
    # Проверяем, что команду использует админ
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ У вас нет прав для этой команды.")
        return
    
    # Получаем текст сообщения для рассылки
    message_text = ' '.join(context.args)
    if not message_text:
        await update.message.reply_text(
            "❓ Использование: /broadcast Текст сообщения\n\n"
            "Например: /broadcast Напоминаю об игре сегодня в 20:00!"
        )
        return
    
    # Загружаем список пользователей
    users = load_users()
    if not users:
        await update.message.reply_text("📭 В базе пока нет пользователей для рассылки.")
        return
    
    # Отправляем сообщение о начале рассылки
    status_msg = await update.message.reply_text(
        f"📨 Начинаю рассылку {len(users)} пользователям..."
    )
    
    success = 0
    failed = 0
    
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=message_text)
            success += 1
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {uid}: {e}")
            failed += 1
    
    # Отправляем отчёт
    await status_msg.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"📊 Всего: {len(users)}\n"
        f"✅ Успешно: {success}\n"
        f"❌ Ошибок: {failed}"
    )
    
    # Дублируем отчёт админу в личку
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"📊 Отчёт о рассылке:\nУспешно: {success}, Ошибок: {failed}"
    )

# --- ЗАПУСК БОТА ---

def main() -> None:
    application = Application.builder().token(config.BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            GAME: [CallbackQueryHandler(get_game)],
            TIME: [CallbackQueryHandler(get_time)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("broadcast", broadcast))  # Новая команда

    print("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
