import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import main
import asyncio

if __name__ == "__main__":
    try:
        print("🚀 Запуск Telegram-бота для управления очередью...")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1)
