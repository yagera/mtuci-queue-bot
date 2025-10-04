import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database import Database
from models import User, Queue, QueueMember

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = Database()

queue_locks = {}
user_states = {}


async def get_queue_lock(queue_id: int):
    if queue_id not in queue_locks:
        queue_locks[queue_id] = asyncio.Lock()
    return queue_locks[queue_id]


def create_queue_actions_keyboard(queue_id: int, user_id: int, is_creator: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="👀 Посмотреть очередь", callback_data=f"view_queue_{queue_id}")],
        [InlineKeyboardButton(text="📊 Мой статус", callback_data=f"status_{queue_id}")],
        [InlineKeyboardButton(text="🚪 Выйти из очереди", callback_data=f"leave_{queue_id}")]
    ]
    
    if is_creator:
        buttons.extend([
            [InlineKeyboardButton(text="⏭️ Следующий", callback_data=f"next_{queue_id}")],
            [InlineKeyboardButton(text="👤 Удалить участника", callback_data=f"remove_user_{queue_id}")],
            [InlineKeyboardButton(text="🗑️ Удалить очередь", callback_data=f"delete_queue_{queue_id}")]
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_join_queue_keyboard(queue_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Встать в очередь", callback_data=f"join_{queue_id}")],
        [InlineKeyboardButton(text="👀 Посмотреть очередь", callback_data=f"view_queue_{queue_id}")]
    ])


def create_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Создать очередь", callback_data="create_queue")],
        [InlineKeyboardButton(text="📝 Список очередей", callback_data="list_queues")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])


async def notify_all_users_about_new_queue(queue_name: str, queue_id: int, exclude_user: int = None):
    try:
        users = await db.get_all_users()
        notification_text = f"🔔 Новая очередь создана!\n\n📋 {queue_name}\n🆔 ID: {queue_id}\n\n👆 Нажми кнопку, чтобы присоединиться!"
        
        keyboard = create_join_queue_keyboard(queue_id)
        
        for user in users:
            if exclude_user and user.id == exclude_user:
                continue  # Пропускаем исключенного пользователя
            
            try:
                await bot.send_message(user.id, notification_text, reply_markup=keyboard)
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление пользователю {user.id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений о новой очереди: {e}")


async def notify_user_about_queue_position(user_id: int, queue_name: str, position: int, total: int, queue_id: int):
    try:
        notification_text = f"📍 Ты добавлен в очередь!\n\n📋 {queue_name}\n🎯 Позиция: {position} из {total}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Мой статус", callback_data=f"status_{queue_id}")],
            [InlineKeyboardButton(text="👀 Посмотреть очередь", callback_data=f"view_queue_{queue_id}")],
            [InlineKeyboardButton(text="🚪 Выйти из очереди", callback_data=f"leave_{queue_id}")]
        ])
        
        await bot.send_message(user_id, notification_text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление о позиции пользователю {user_id}: {e}")


async def notify_user_about_turn(user_id: int, queue_name: str):
    try:
        notification_text = f"🎉 Твоя очередь подошла!\n\n📋 {queue_name}\n⏰ Подходи к сдаче лабораторной работы!"
        await bot.send_message(user_id, notification_text)
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление о вызове пользователю {user_id}: {e}")


@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Неизвестный"
    
    try:
        user = await db.get_user(user_id)
        if user:
            welcome_text = f"🎉 Привет, {user.username}!\n\n📋 Бот для управления очередями лабораторных работ готов к работе!"
        else:
            await db.create_user(user_id, username)
            welcome_text = f"🎉 Добро пожаловать, {username}!\n\n📋 Ты успешно зарегистрирован в системе управления очередями!"
        
        keyboard = create_main_menu_keyboard()
        await message.answer(welcome_text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Ошибка при регистрации пользователя {user_id}: {e}")
        await message.answer("❌ Произошла ошибка при регистрации. Попробуй позже.")


@dp.message(Command("create_queue"))
async def cmd_create_queue(message: Message):
    user_id = message.from_user.id
    
    user = await db.get_user(user_id)
    if not user:
        await message.answer("Сначала зарегистрируйся командой /start")
        return
    
    queue_name = message.text.replace("/create_queue", "").strip()
    if not queue_name:
        await message.answer("Укажи название очереди: /create_queue <название>")
        return
    
    try:
        queue_id = await db.create_queue(queue_name, user_id)
        success_text = f"✅ Очередь '{queue_name}' создана!\n\n🆔 ID очереди: {queue_id}\n⏰ Автоматически удалится через 24 часа\n\n👥 Поделись ID с участниками, чтобы они могли присоединиться!"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Встать в очередь", callback_data=f"join_{queue_id}")],
            [InlineKeyboardButton(text="👀 Посмотреть очередь", callback_data=f"view_queue_{queue_id}")],
            [InlineKeyboardButton(text="📋 Главное меню", callback_data="main_menu")]
        ])
        
        await message.answer(success_text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Ошибка при создании очереди: {e}")
        await message.answer("❌ Произошла ошибка при создании очереди. Попробуй позже.")


@dp.message(Command("join"))
async def cmd_join_queue(message: Message):
    user_id = message.from_user.id
    
    user = await db.get_user(user_id)
    if not user:
        await message.answer("Сначала зарегистрируйся командой /start")
        return
    
    try:
        queue_id = int(message.text.replace("/join", "").strip())
    except ValueError:
        await message.answer("Укажи корректный ID очереди: /join <queue_id>")
        return
    
    lock = await get_queue_lock(queue_id)
    async with lock:
        try:
            queue = await db.get_queue(queue_id)
            if not queue:
                await message.answer("Очередь с таким ID не найдена.")
                return
            
            existing_member = await db.get_queue_member(queue_id, user_id)
            if existing_member:
                await message.answer("Ты уже в этой очереди!")
                return
            
            position = await db.add_to_queue(queue_id, user_id)
            total_members = await db.get_queue_member_count(queue_id)
            
            updated_text = f"✅ Ты добавлен в очередь '{queue.name}'!\n\n🎯 Позиция: {position} из {total_members}"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📊 Мой статус", callback_data=f"status_{queue_id}")],
                [InlineKeyboardButton(text="👀 Посмотреть очередь", callback_data=f"view_queue_{queue_id}")],
                [InlineKeyboardButton(text="🚪 Выйти из очереди", callback_data=f"leave_{queue_id}")]
            ])
            
            await message.answer(updated_text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error(f"Ошибка при добавлении в очередь: {e}")
            await message.answer("Произошла ошибка. Попробуй позже.")


@dp.message(Command("next"))
async def cmd_next(message: Message):
    user_id = message.from_user.id
    
    try:
        queue_id = int(message.text.replace("/next", "").strip())
    except ValueError:
        await message.answer("Укажи корректный ID очереди: /next <queue_id>")
        return
    
    lock = await get_queue_lock(queue_id)
    async with lock:
        try:
            queue = await db.get_queue(queue_id)
            if not queue:
                await message.answer("Очередь с таким ID не найдена.")
                return
            
            if queue.creator_id != user_id:
                await message.answer("Только создатель очереди может вызывать следующего.")
                return
            
            next_member = await db.get_next_in_queue(queue_id)
            if not next_member:
                await message.answer("Очередь пуста.")
                return
            
            await db.remove_from_queue(queue_id, next_member.user_id)
            
            await message.answer(f"✅ Участник {next_member.user.username} вызван!")
            await notify_user_about_turn(next_member.user_id, queue.name)
            
        except Exception as e:
            logger.error(f"Ошибка при вызове следующего: {e}")
            await message.answer("Произошла ошибка. Попробуй позже.")


@dp.message(Command("status"))
async def cmd_status(message: Message):
    user_id = message.from_user.id
    
    try:
        queue_id = int(message.text.replace("/status", "").strip())
    except ValueError:
        await message.answer("Укажи корректный ID очереди: /status <queue_id>")
        return
    
    try:
        member = await db.get_queue_member(queue_id, user_id)
        if not member:
            await message.answer("Ты не в этой очереди.")
            return
        
        queue = await db.get_queue(queue_id)
        total_members = await db.get_queue_member_count(queue_id)
        
        await message.answer(
            f"Очередь: {queue.name}\n"
            f"Твоя позиция: {member.position}\n"
            f"Всего участников: {total_members}"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при получении статуса: {e}")
        await message.answer("Произошла ошибка. Попробуй позже.")


@dp.message(Command("leave"))
async def cmd_leave_queue(message: Message):
    user_id = message.from_user.id
    
    try:
        queue_id = int(message.text.replace("/leave", "").strip())
    except ValueError:
        await message.answer("Укажи корректный ID очереди: /leave <queue_id>")
        return
    
    lock = await get_queue_lock(queue_id)
    async with lock:
        try:
            member = await db.get_queue_member(queue_id, user_id)
            if not member:
                await message.answer("Ты не в этой очереди.")
                return
            
            await db.remove_from_queue(queue_id, user_id)
            await message.answer("✅ Ты покинул очередь.")
            
        except Exception as e:
            logger.error(f"Ошибка при выходе из очереди: {e}")
            await message.answer("Произошла ошибка. Попробуй позже.")


@dp.message(Command("list_queues"))
async def cmd_list_queues(message: Message):
    try:
        queues = await db.get_all_queues()
        if not queues:
            await message.answer("Нет активных очередей.")
            return
        
        response = "Доступные очереди:\n\n"
        for queue in queues:
            member_count = await db.get_queue_member_count(queue.id)
            response += f"ID: {queue.id} - {queue.name} ({member_count} участников)\n"
        
        await message.answer(response)
        
    except Exception as e:
        logger.error(f"Ошибка при получении списка очередей: {e}")
        await message.answer("Произошла ошибка. Попробуй позже.")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """ℹ️ Помощь по боту

📋 Основные команды:
/start - регистрация и главное меню
/create_queue <название> - создать очередь
/join <queue_id> - встать в очередь
/next <queue_id> - вызвать следующего (создатель)
/status <queue_id> - твоя позиция
/leave <queue_id> - выйти из очереди
/view_queue <queue_id> - посмотреть очередь
/delete_queue <queue_id> - удалить очередь (создатель)
/remove_user <queue_id> <username> - удалить участника (создатель)

👆 Или используй кнопки для удобства!"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Главное меню", callback_data="main_menu")],
        [InlineKeyboardButton(text="📝 Список очередей", callback_data="list_queues")]
    ])
    
    await message.answer(help_text, reply_markup=keyboard)


@dp.message(Command("view_queue"))
async def cmd_view_queue(message: Message):
    try:
        queue_id = int(message.text.replace("/view_queue", "").strip())
    except ValueError:
        await message.answer("Укажи корректный ID очереди: /view_queue <queue_id>")
        return
    
    try:
        queue = await db.get_queue(queue_id)
        if not queue:
            await message.answer("Очередь с таким ID не найдена или истекла.")
            return
        
        members = await db.get_queue_members(queue_id)
        if not members:
            await message.answer(f"Очередь '{queue.name}' пуста.")
            return
        
        response = f"Очередь: {queue.name}\n\n"
        for member in members:
            response += f"{member.position}. {member.user.username}\n"
        
        await message.answer(response)
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре очереди: {e}")
        await message.answer("Произошла ошибка. Попробуй позже.")


@dp.message(Command("delete_queue"))
async def cmd_delete_queue(message: Message):
    user_id = message.from_user.id
    
    try:
        queue_id = int(message.text.replace("/delete_queue", "").strip())
    except ValueError:
        await message.answer("Укажи корректный ID очереди: /delete_queue <queue_id>")
        return
    
    lock = await get_queue_lock(queue_id)
    async with lock:
        try:
            success = await db.delete_queue(queue_id, user_id)
            if success:
                await message.answer("Очередь удалена.")
            else:
                await message.answer("Очередь не найдена или ты не являешься её создателем.")
        except Exception as e:
            logger.error(f"Ошибка при удалении очереди: {e}")
            await message.answer("Произошла ошибка. Попробуй позже.")


@dp.message(Command("remove_user"))
async def cmd_remove_user(message: Message):
    user_id = message.from_user.id
    
    try:
        parts = message.text.replace("/remove_user", "").strip().split()
        if len(parts) != 2:
            await message.answer("Формат: /remove_user <queue_id> <username>")
            return
        
        queue_id = int(parts[0])
        target_username = parts[1]
    except ValueError:
        await message.answer("Укажи корректные данные: /remove_user <queue_id> <username>")
        return
    
    lock = await get_queue_lock(queue_id)
    async with lock:
        try:
            queue = await db.get_queue(queue_id)
            if not queue:
                await message.answer("Очередь с таким ID не найдена или истекла.")
                return
            
            if queue.creator_id != user_id:
                await message.answer("Только создатель очереди может удалять участников.")
                return
            
            target_user = await db.get_user_by_username(target_username)
            if not target_user:
                await message.answer(f"Пользователь с именем '{target_username}' не найден.")
                return
            
            success = await db.remove_user_from_queue(queue_id, target_user.id, user_id)
            if success:
                await message.answer(f"Пользователь {target_username} удален из очереди.")
                
                try:
                    await bot.send_message(
                        target_user.id,
                        f"⚠️ Ты был удален из очереди '{queue.name}' администратором."
                    )
                except:
                    pass
            else:
                await message.answer("Пользователь не найден в очереди.")
        except Exception as e:
            logger.error(f"Ошибка при удалении пользователя: {e}")
            await message.answer("Произошла ошибка. Попробуй позже.")


@dp.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in user_states:
        del user_states[user_id]
    
    await callback.message.edit_text(
        "📋 Главное меню\n\nВыбери действие:",
        reply_markup=create_main_menu_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "list_queues")
async def callback_list_queues(callback: CallbackQuery):
    try:
        queues = await db.get_all_queues()
        if not queues:
            await callback.message.edit_text(
                "📝 Нет активных очередей",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
                ])
            )
            return
        
        response = "📝 Доступные очереди:\n\n"
        keyboard_buttons = []
        user_id = callback.from_user.id
        
        for queue in queues:
            member_count = await db.get_queue_member_count(queue.id)
            response += f"🆔 {queue.id} - {queue.name} ({member_count} участников)\n"
            
            is_member = await db.get_queue_member(queue.id, user_id) is not None
            
            if is_member:
                button_text = f"📋 {queue.name} (ты в очереди)"
            else:
                button_text = f"📋 {queue.name}"
            
            keyboard_buttons.append([InlineKeyboardButton(
                text=button_text,
                callback_data=f"queue_info_{queue.id}"
            )])
        
        keyboard_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
        
        await callback.message.edit_text(
            response,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        )
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при получении списка очередей: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("queue_info_"))
async def callback_queue_info(callback: CallbackQuery):
    try:
        queue_id = int(callback.data.split("_")[2])
        queue = await db.get_queue(queue_id)
        
        if not queue:
            await callback.answer("❌ Очередь не найдена", show_alert=True)
            return
        
        members = await db.get_queue_members(queue_id)
        is_creator = queue.creator_id == callback.from_user.id
        user_id = callback.from_user.id
        is_member = any(member.user_id == user_id for member in members)
        
        response = f"📋 {queue.name}\n🆔 ID: {queue.id}\n👥 Участников: {len(members)}\n"
        
        if members:
            response += "\n👥 Участники:\n"
            for member in members[:10]:
                response += f"{member.position}. {member.user.username}\n"
            if len(members) > 10:
                response += f"... и еще {len(members) - 10} участников"
        
        if is_member:
            keyboard = create_queue_actions_keyboard(queue_id, callback.from_user.id, is_creator)
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Встать в очередь", callback_data=f"join_{queue_id}")],
                [InlineKeyboardButton(text="👀 Посмотреть очередь", callback_data=f"view_queue_{queue_id}")]
            ])
            if is_creator:
                keyboard.inline_keyboard.extend([
                    [InlineKeyboardButton(text="⏭️ Следующий", callback_data=f"next_{queue_id}")],
                    [InlineKeyboardButton(text="👤 Удалить участника", callback_data=f"remove_user_{queue_id}")],
                    [InlineKeyboardButton(text="🗑️ Удалить очередь", callback_data=f"delete_queue_{queue_id}")]
                ])
        
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="list_queues")])
        
        await callback.message.edit_text(response, reply_markup=keyboard)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при получении информации об очереди: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("join_"))
async def callback_join_queue(callback: CallbackQuery):
    queue_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("❌ Сначала зарегистрируйся командой /start", show_alert=True)
        return
    
    lock = await get_queue_lock(queue_id)
    async with lock:
        try:
            queue = await db.get_queue(queue_id)
            if not queue:
                await callback.answer("❌ Очередь не найдена", show_alert=True)
                return
            
            existing_member = await db.get_queue_member(queue_id, user_id)
            if existing_member:
                await callback.answer("⚠️ Ты уже в этой очереди!", show_alert=True)
                return
            
            position = await db.add_to_queue(queue_id, user_id)
            total_members = await db.get_queue_member_count(queue_id)
            
            updated_text = f"✅ Ты добавлен в очередь '{queue.name}'!\n\n🎯 Позиция: {position} из {total_members}"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📊 Мой статус", callback_data=f"status_{queue_id}")],
                [InlineKeyboardButton(text="👀 Посмотреть очередь", callback_data=f"view_queue_{queue_id}")],
                [InlineKeyboardButton(text="🚪 Выйти из очереди", callback_data=f"leave_{queue_id}")]
            ])
            
            await callback.message.edit_text(updated_text, reply_markup=keyboard)
            await callback.answer(f"✅ Ты добавлен в очередь на позицию {position}!")
            
        except Exception as e:
            logger.error(f"Ошибка при добавлении в очередь: {e}")
            await callback.answer("❌ Произошла ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("leave_"))
async def callback_leave_queue(callback: CallbackQuery):
    queue_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    lock = await get_queue_lock(queue_id)
    async with lock:
        try:
            member = await db.get_queue_member(queue_id, user_id)
            if not member:
                await callback.answer("❌ Ты не в этой очереди", show_alert=True)
                return
            
            await db.remove_from_queue(queue_id, user_id)
            await callback.answer("✅ Ты покинул очередь!")
            
        except Exception as e:
            logger.error(f"Ошибка при выходе из очереди: {e}")
            await callback.answer("❌ Произошла ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("next_"))
async def callback_next_user(callback: CallbackQuery):
    queue_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    lock = await get_queue_lock(queue_id)
    async with lock:
        try:
            queue = await db.get_queue(queue_id)
            if not queue:
                await callback.answer("❌ Очередь не найдена", show_alert=True)
                return
            
            if queue.creator_id != user_id:
                await callback.answer("❌ Только создатель очереди может вызывать следующего", show_alert=True)
                return
            
            next_member = await db.get_next_in_queue(queue_id)
            if not next_member:
                await callback.answer("❌ Очередь пуста", show_alert=True)
                return
            
            await db.remove_from_queue(queue_id, next_member.user_id)
            await callback.answer(f"✅ Участник {next_member.user.username} вызван!")
            await notify_user_about_turn(next_member.user_id, queue.name)
            
        except Exception as e:
            logger.error(f"Ошибка при вызове следующего: {e}")
            await callback.answer("❌ Произошла ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("view_queue_"))
async def callback_view_queue(callback: CallbackQuery):
    queue_id = int(callback.data.split("_")[2])
    
    try:
        queue = await db.get_queue(queue_id)
        if not queue:
            await callback.answer("❌ Очередь не найдена", show_alert=True)
            return
        
        members = await db.get_queue_members(queue_id)
        if not members:
            await callback.answer("❌ Очередь пуста", show_alert=True)
            return
        
        response = f"📋 {queue.name}\n\n"
        for member in members:
            response += f"{member.position}. {member.user.username}\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"queue_info_{queue_id}")]
        ])
        
        await callback.message.edit_text(response, reply_markup=keyboard)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при просмотре очереди: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("status_"))
async def callback_status(callback: CallbackQuery):
    queue_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    try:
        member = await db.get_queue_member(queue_id, user_id)
        if not member:
            await callback.answer("❌ Ты не в этой очереди", show_alert=True)
            return
        
        queue = await db.get_queue(queue_id)
        total_members = await db.get_queue_member_count(queue_id)
        
        response = f"📊 Твой статус в очереди:\n\n📋 {queue.name}\n🎯 Позиция: {member.position}\n👥 Всего участников: {total_members}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"queue_info_{queue_id}")]
        ])
        
        await callback.message.edit_text(response, reply_markup=keyboard)
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при получении статуса: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@dp.callback_query(F.data == "help")
async def callback_help(callback: CallbackQuery):
    help_text = """ℹ️ Помощь по боту

📋 Основные команды:
/start - регистрация и главное меню
/create_queue <название> - создать очередь
/join <queue_id> - встать в очередь
/next <queue_id> - вызвать следующего (создатель)
/status <queue_id> - твоя позиция
/leave <queue_id> - выйти из очереди
/view_queue <queue_id> - посмотреть очередь
/delete_queue <queue_id> - удалить очередь (создатель)
/remove_user <queue_id> <username> - удалить участника (создатель)

👆 Или используй кнопки для удобства!"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(help_text, reply_markup=keyboard)
    await callback.answer()


@dp.callback_query(F.data == "create_queue")
async def callback_create_queue(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_states[user_id] = {
        "state": "waiting_queue_name",
        "instruction_message_id": callback.message.message_id
    }
    
    await callback.message.edit_text(
        "📋 Создание новой очереди\n\n✍️ Отправь название очереди текстом (без команд):\n\nНапример: Лабораторная по программированию",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delete_queue_"))
async def callback_delete_queue(callback: CallbackQuery):
    queue_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    lock = await get_queue_lock(queue_id)
    async with lock:
        try:
            success = await db.delete_queue(queue_id, user_id)
            if success:
                await callback.message.edit_text(
                    "✅ Очередь удалена!",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📋 Главное меню", callback_data="main_menu")]
                    ])
                )
            else:
                await callback.answer("❌ Очередь не найдена или ты не являешься её создателем", show_alert=True)
        except Exception as e:
            logger.error(f"Ошибка при удалении очереди: {e}")
            await callback.answer("❌ Произошла ошибка", show_alert=True)
    
    await callback.answer()


@dp.callback_query(F.data.startswith("remove_user_"))
async def callback_remove_user(callback: CallbackQuery):
    queue_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    await callback.message.edit_text(
        f"👤 Удаление участника из очереди\n\nОтправь команду:\n/remove_user {queue_id} <username>\n\nГде <username> - имя пользователя, которого нужно удалить.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data=f"queue_info_{queue_id}")]
        ])
    )
    await callback.answer()


@dp.message()
async def handle_unknown_message(message: Message):
    user_id = message.from_user.id
    
    if user_id in user_states and user_states[user_id].get("state") == "waiting_queue_name":
        queue_name = message.text.strip()
        if not queue_name:
            await message.answer("❌ Название очереди не может быть пустым. Попробуй еще раз:")
            return
        
        if len(queue_name) > 100:
            await message.answer("❌ Название очереди слишком длинное (максимум 100 символов). Попробуй еще раз:")
            return
        
        try:
            queue_id = await db.create_queue(queue_name, user_id)
            
            instruction_message_id = user_states[user_id].get("instruction_message_id")
            if instruction_message_id:
                try:
                    await bot.delete_message(user_id, instruction_message_id)
                except:
                    pass
            
            del user_states[user_id]
            
            success_text = f"✅ Очередь '{queue_name}' создана!\n\n🆔 ID очереди: {queue_id}\n⏰ Автоматически удалится через 24 часа\n\n👥 Поделись ID с участниками, чтобы они могли присоединиться!"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Встать в очередь", callback_data=f"join_{queue_id}")],
                [InlineKeyboardButton(text="👀 Посмотреть очередь", callback_data=f"view_queue_{queue_id}")],
                [InlineKeyboardButton(text="📋 Главное меню", callback_data="main_menu")]
            ])
            
            await message.delete()
            await message.answer(success_text, reply_markup=keyboard)
            
        except Exception as e:
            logger.error(f"Ошибка при создании очереди: {e}")
            await message.answer("❌ Произошла ошибка при создании очереди. Попробуй позже.")
            if user_id in user_states:
                del user_states[user_id]
        return
    
    help_text = """🤔 Не понял, что ты хочешь сделать.

📋 Доступные команды:
/start - главное меню
/create_queue <название> - создать очередь
/join <queue_id> - встать в очередь
/next <queue_id> - вызвать следующего (создатель)
/status <queue_id> - твоя позиция
/leave <queue_id> - выйти из очереди
/view_queue <queue_id> - посмотреть очередь
/delete_queue <queue_id> - удалить очередь (создатель)
/remove_user <queue_id> <username> - удалить участника (создатель)

👆 Или используй /start для доступа к интерактивному меню!"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Главное меню", callback_data="main_menu")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])
    
    await message.answer(help_text, reply_markup=keyboard)


async def cleanup_task():
    while True:
        try:
            await db.cleanup_expired_queues()
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Ошибка при очистке устаревших очередей: {e}")
            await asyncio.sleep(3600)

async def main():
    await db.init_db()
    
    cleanup_task_handle = asyncio.create_task(cleanup_task())
    
    try:
        logger.info("Запуск бота...")
        await dp.start_polling(bot)
    finally:
        cleanup_task_handle.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")