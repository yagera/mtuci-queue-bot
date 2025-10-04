import asyncio
import logging
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
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


async def get_queue_lock(queue_id: int):
    if queue_id not in queue_locks:
        queue_locks[queue_id] = asyncio.Lock()
    return queue_locks[queue_id]


@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "Неизвестный"
    
    try:
        user = await db.get_user(user_id)
        if user:
            await message.answer(f"Привет, {user.username}! Ты уже зарегистрирован.")
        else:
            await db.create_user(user_id, username)
            await message.answer(f"Добро пожаловать, {username}! Ты успешно зарегистрирован в системе.")
    except Exception as e:
        logger.error(f"Ошибка при регистрации пользователя {user_id}: {e}")
        await message.answer("Произошла ошибка при регистрации. Попробуй позже.")


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
        await message.answer(f"Очередь '{queue_name}' создана! ID очереди: {queue_id}\nОчередь автоматически удалится через 24 часа.")
    except Exception as e:
        logger.error(f"Ошибка при создании очереди: {e}")
        await message.answer("Произошла ошибка при создании очереди. Попробуй позже.")


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
            await message.answer(f"Ты добавлен в очередь '{queue.name}' на позицию {position}!")
            
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
            
            try:
                await bot.send_message(
                    next_member.user_id,
                    f"Твоя очередь подошла! Подходи к сдаче лабораторной работы."
                )
                await message.answer(f"Участник {next_member.user.username} вызван.")
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление пользователю {next_member.user_id}: {e}")
                await message.answer("Участник вызван, но уведомление не удалось отправить.")
            
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
            await message.answer("Ты покинул очередь.")
            
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
            await message.answer("Формат: /remove_user <queue_id> <user_id>")
            return
        
        queue_id = int(parts[0])
        target_user_id = int(parts[1])
    except ValueError:
        await message.answer("Укажи корректные ID: /remove_user <queue_id> <user_id>")
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
            
            success = await db.remove_user_from_queue(queue_id, target_user_id, user_id)
            if success:
                target_user = await db.get_user(target_user_id)
                username = target_user.username if target_user else f"ID{target_user_id}"
                await message.answer(f"Пользователь {username} удален из очереди.")
                
                try:
                    await bot.send_message(
                        target_user_id,
                        f"Ты был удален из очереди '{queue.name}'."
                    )
                except:
                    pass
            else:
                await message.answer("Пользователь не найден в очереди.")
        except Exception as e:
            logger.error(f"Ошибка при удалении пользователя: {e}")
            await message.answer("Произошла ошибка. Попробуй позже.")


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