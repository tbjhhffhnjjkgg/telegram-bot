import os
import sqlite3
from typing import Dict, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

try:
    from yookassa import Configuration, Payment
except Exception:  # pragma: no cover
    Configuration = None
    Payment = None

BOT_NAME = os.getenv("BOT_NAME", "Fronzan ArizonaRP")
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "Frag_History").lower()
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "0") or 0)
DB_PATH = os.path.join(os.path.dirname(__file__), "bot_data.db")
PENDING_ACTIONS: Dict[int, str] = {}


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payment_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            method TEXT DEFAULT 'owner'
        )
        """
    )
    conn.execute("INSERT OR IGNORE INTO products (name, price) VALUES (?, ?)", ("Мод 1", 120))
    conn.execute("INSERT OR IGNORE INTO products (name, price) VALUES (?, ?)", ("Мод 2", 240))
    conn.execute("INSERT OR IGNORE INTO services (name, price) VALUES (?, ?)", ("Услуга 1", 300))
    conn.execute("INSERT OR IGNORE INTO services (name, price) VALUES (?, ?)", ("Услуга 2", 450))
    conn.commit()
    conn.close()


def ensure_user(user) -> Dict[str, object]:
    if not user:
        return {}

    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user.id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (id, username, first_name, balance) VALUES (?, ?, ?, 0)",
            (user.id, user.username or "", user.first_name or ""),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user.id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def get_user_label(user) -> str:
    if user and user.username:
        return f"@{user.username}"
    if user and user.first_name:
        return user.first_name
    return "Пользователь"


def is_owner(user) -> bool:
    if not user:
        return False
    username = (user.username or "").lower()
    return username == OWNER_USERNAME


def get_user_balance(user_id: int) -> int:
    conn = get_db_connection()
    row = conn.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def set_user_balance(user_id: int, balance: int):
    conn = get_db_connection()
    conn.execute("UPDATE users SET balance = ? WHERE id = ?", (balance, user_id))
    conn.commit()
    conn.close()


def get_products() -> List[Dict[str, object]]:
    conn = get_db_connection()
    rows = conn.execute("SELECT id, name, price FROM products ORDER BY id").fetchall()
    conn.close()
    return [{"id": row[0], "name": row[1], "price": int(row[2])} for row in rows]


def get_services() -> List[Dict[str, object]]:
    conn = get_db_connection()
    rows = conn.execute("SELECT id, name, price FROM services ORDER BY id").fetchall()
    conn.close()
    return [{"id": row[0], "name": row[1], "price": int(row[2])} for row in rows]


def add_product(name: str, price: int):
    conn = get_db_connection()
    conn.execute("INSERT INTO products (name, price) VALUES (?, ?)", (name, price))
    conn.commit()
    conn.close()


def get_pending_payment_requests() -> List[Dict[str, object]]:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, user_id, username, amount, status, created_at, method FROM payment_requests WHERE status = 'pending' ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "user_id": row[1],
            "username": row[2],
            "amount": int(row[3]),
            "status": row[4],
            "created_at": row[5],
            "method": row[6],
        }
        for row in rows
    ]


def get_payment_request(request_id: int):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT id, user_id, username, amount, status, created_at, method FROM payment_requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_payment_request(user, amount: int, method: str = "owner") -> int:
    conn = get_db_connection()
    username = get_user_label(user)
    cursor = conn.execute(
        "INSERT INTO payment_requests (user_id, username, amount, method, status) VALUES (?, ?, ?, ?, 'pending')",
        (user.id, username, int(amount), method),
    )
    conn.commit()
    request_id = cursor.lastrowid
    conn.close()
    return int(request_id)


def update_payment_request_status(request_id: int, status: str):
    conn = get_db_connection()
    conn.execute("UPDATE payment_requests SET status = ? WHERE id = ?", (status, request_id))
    conn.commit()
    conn.close()


def confirm_payment_request(request_id: int):
    request = get_payment_request(request_id)
    if not request:
        return False

    user_id = int(request["user_id"])
    amount = int(request["amount"])
    current_balance = get_user_balance(user_id)
    set_user_balance(user_id, current_balance + amount)
    update_payment_request_status(request_id, "confirmed")
    return True


def reject_payment_request(request_id: int):
    request = get_payment_request(request_id)
    if not request:
        return False
    update_payment_request_status(request_id, "rejected")
    return True


def get_yookassa_configured() -> bool:
    return bool(os.getenv("YOOKASSA_SHOP_ID") and os.getenv("YOOKASSA_SECRET_KEY"))


def create_yookassa_payment(user, amount: int, method: str = "sbp"):
    if not get_yookassa_configured() or Configuration is None or Payment is None:
        return None

    Configuration.configure(os.getenv("YOOKASSA_SHOP_ID"), os.getenv("YOOKASSA_SECRET_KEY"))

    method_map = {
        "sbp": {"type": "sbp"},
        "card": {"type": "bank_card"},
        "yoomoney": {"type": "yoo_money"},
    }

    try:
        payment = Payment.create(
            {
                "amount": {"value": f"{float(amount):.2f}", "currency": "RUB"},
                "payment_method_data": method_map.get(method, {"type": "sbp"}),
                "confirmation": {
                    "type": "redirect",
                    "return_url": os.getenv("YOOKASSA_RETURN_URL", "https://example.com/success"),
                },
                "capture": True,
                "description": f"Пополнение баланса для {get_user_label(user)}",
            },
            idempotency_key=f"topup-{user.id}-{amount}-{method}",
        )
        return payment
    except Exception:
        return None


async def send_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, user=None):
    if user is None:
        user = update.effective_user

    ensure_user(user)
    name = get_user_label(user)
    balance = get_user_balance(user.id)
    is_owner_user = is_owner(user)

    text = (
        f"👋 Привет, и добро пожаловать в ваш личный кабинет, {name}!\n\n"
        "⚙️ Ваш профиль:\n"
        f"- Юзер: {name}\n"
        f"- Баланс: {balance} ₽\n\n"
        "---\n"
        "🛠️ Панель владельца:\n"
        "Вы можете изменить настройки вашего профиля или управлять своими услугами.\n"
        "⬇️ Выберите действие:\n\n"
        "1. 💼 Изменить настройки профиля\n"
        "2. 📊 Просмотреть статистику\n"
        "3. 💳 Пополнить баланс\n"
        "4. 🛒 Аренда игровых услуг\n"
        "5. 🛍️ Продажа модов, форумов, сайтов и лаунчеров\n"
    )

    if is_owner_user:
        text += "\n✅ Вы вошли в панель владельца."

    keyboard = build_main_keyboard(is_owner_user)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, reply_markup=keyboard)


def build_main_keyboard(is_owner_user: bool):
    buttons = [
        [InlineKeyboardButton("💼 Изменить настройки профиля", callback_data="settings")],
        [InlineKeyboardButton("📊 Просмотреть статистику", callback_data="stats")],
        [InlineKeyboardButton("💳 Пополнить баланс", callback_data="wallet")],
        [InlineKeyboardButton("🛒 Аренда игровых услуг", callback_data="rent")],
        [InlineKeyboardButton("🛍️ Продажа товаров", callback_data="shop")],
        [InlineKeyboardButton("🆘 Техподдержка", callback_data="support")],
    ]
    if is_owner_user:
        buttons.append([InlineKeyboardButton("⚙️ Панель владельца", callback_data="owner_panel")])
    return InlineKeyboardMarkup(buttons)


async def show_owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner(user):
        await update.callback_query.answer("У вас нет доступа к панели владельца.")
        return

    text = "⚙️ Панель владельца\n\nВы можете управлять пользователями, пополнять баланс и добавлять товары.\n\nВыберите действие:"
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💰 Пополнить баланс человеку", callback_data="owner_top_up")],
            [InlineKeyboardButton("� Заявки на пополнение", callback_data="owner_payment_requests")],
            [InlineKeyboardButton("�🛍️ Добавить товар", callback_data="owner_add_product")],
            [InlineKeyboardButton("📦 Список товаров", callback_data="owner_list_products")],
            [InlineKeyboardButton("⬅️ Назад в профиль", callback_data="back_to_profile")],
        ]
    )
    await update.callback_query.edit_message_text(text, reply_markup=keyboard)


async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🔄 Пополнить баланс\n\nВыберите способ оплаты:\n\n• YooKassa: SBP, карта, ЮMoney\n• Через владельца: заявка на пополнение с подтверждением"
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💳 YooKassa (SBP / карта / ЮMoney)", callback_data="wallet_yookassa")],
            [InlineKeyboardButton("👤 Оплата через владельца", callback_data="wallet_owner")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")],
        ]
    )
    await update.callback_query.edit_message_text(text, reply_markup=keyboard)


async def wallet_yookassa_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "💳 Пополнение через YooKassa\n\nВыберите сумму:"
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💵 100 ₽", callback_data="pay:100:sbp")],
            [InlineKeyboardButton("💳 300 ₽", callback_data="pay:300:card")],
            [InlineKeyboardButton("🟡 500 ₽", callback_data="pay:500:yoomoney")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="wallet")],
        ]
    )
    await update.callback_query.edit_message_text(text, reply_markup=keyboard)


async def wallet_owner_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    PENDING_ACTIONS[user.id] = "wallet_owner_amount"
    await update.callback_query.edit_message_text(
        "👤 Оплата через владельца\n\nВведите сумму пополнения в рублях.\nПример: 250",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="wallet")]]),
    )


async def pay_via_yookassa(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int, method: str):
    user = update.effective_user
    payment = create_yookassa_payment(user, amount, method)
    if payment is None:
        await update.callback_query.edit_message_text(
            "⚠️ YooKassa не настроена. Добавьте YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY в .env.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="wallet")]]),
        )
        return

    confirmation_url = getattr(payment.confirmation, "confirmation_url", None)
    if not confirmation_url:
        await update.callback_query.edit_message_text(
            "⚠️ Не удалось сформировать ссылку оплаты. Проверьте настройки YooKassa.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="wallet")]]),
        )
        return

    text = (
        f"💳 Пополнение баланса: {amount} ₽\n\n"
        f"Способ оплаты: {method.upper()}\n\n"
        "Нажмите кнопку ниже, чтобы перейти к оплате через YooKassa."
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Перейти к оплате", url=confirmation_url)],
            [InlineKeyboardButton("⬅️ Назад", callback_data="wallet")],
        ]
    )
    await update.callback_query.edit_message_text(text, reply_markup=keyboard)


async def show_rent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    services = get_services()
    text = "🏆 Аренда игровых услуг:\n"
    for service in services:
        text += f"- {service['name']} - {service['price']} ₽\n"
    text += "\nВыберите услугу:"
    buttons = [[InlineKeyboardButton(f"Арендовать {service['name']}", callback_data=f"rent:{service['name']}")] for service in services]
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def show_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = get_products()
    text = "🛠️ Продажа модов и услуг:\n"
    for product in products:
        text += f"- {product['name']} - {product['price']} ₽\n"
    text += "\nВыберите товар:"
    buttons = [[InlineKeyboardButton(f"Купить {product['name']}", callback_data=f"buy:{product['name']}")] for product in products]
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = get_user_balance(user.id)
    text = (
        "📈 Статистика:\n"
        f"- Пользователь: {get_user_label(user)}\n"
        f"- Текущий баланс: {balance} ₽\n"
        f"- Услуг в аренде: {len(get_services())}\n"
        f"- Товаров в каталоге: {len(get_products())}\n"
    )
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")]]))


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💼 Изменить настройки профиля\n\n"
        "Здесь можно добавить имя, сменить никнейм или обновить профиль пользователя.\n"
        "На этом этапе это демонстрационная заглушка."
    )
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")]]))


async def support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🆘 Техподдержка\n\n"
        "В течение рабочего времени с 9:00 до 21:00 поддержка ответит на ваше обращение.\n\n"
        "Напишите ваше сообщение, и оно будет передано владельцу."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Написать в поддержку", callback_data="support_write")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")],
    ])
    await update.callback_query.edit_message_text(text, reply_markup=keyboard)


async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if PENDING_ACTIONS.get(user.id) == "support":
        text = f"📩 Новое обращение от {get_user_label(user)}\n\n{update.message.text}"
        owner_chat = context.bot_data.get("owner_chat_id") or OWNER_CHAT_ID
        if owner_chat:
            await context.bot.send_message(chat_id=owner_chat, text=text)
        await update.message.reply_text(
            "✅ Ваше обращение отправлено в техподдержку. Ответ будет получен в рабочее время с 9:00 до 21:00."
        )
        PENDING_ACTIONS.pop(user.id, None)
        return

    if user.username and user.username.lower() == OWNER_USERNAME:
        await update.message.reply_text("Вы вошли в режим владельца. Используйте кнопки в меню для управления.")
        return

    PENDING_ACTIONS[user.id] = "support"
    await update.message.reply_text(
        "🆘 Напишите ваше обращение в техподдержку. Мы ответим в рабочее время с 9:00 до 21:00."
    )


async def owner_top_up_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner(user):
        await update.callback_query.answer("Доступ только владельцу.")
        return

    PENDING_ACTIONS[user.id] = "owner_top_up"
    await update.callback_query.edit_message_text(
        "💰 Пополнение баланса\n\nВведите данные в формате: @username 250\nПример: @Ivan 250",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]),
    )


async def owner_payment_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user):
        await update.callback_query.answer("Доступ только владельцу.")
        return

    requests = get_pending_payment_requests()
    if not requests:
        await update.callback_query.edit_message_text(
            "📋 Заявки на пополнение\n\nПока нет активных заявок.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]),
        )
        return

    text = "📋 Активные заявки на пополнение:\n\n"
    buttons = []
    for item in requests:
        label = item["username"] or f"user_{item['user_id']}"
        text += f"• {label} — {item['amount']} ₽ (ID: {item['id']})\n"
        buttons.append([
            InlineKeyboardButton(f"✅ Подтвердить {item['id']}", callback_data=f"approve_payment:{item['id']}"),
            InlineKeyboardButton(f"❌ Отклонить {item['id']}", callback_data=f"reject_payment:{item['id']}"),
        ])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def owner_add_product_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner(user):
        await update.callback_query.answer("Доступ только владельцу.")
        return

    PENDING_ACTIONS[user.id] = "owner_add_product"
    await update.callback_query.edit_message_text(
        "🛍️ Добавление товара\n\nВведите товар в формате: Название|Цена\nПример: Мод 3|300",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]),
    )


async def owner_list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user):
        await update.callback_query.answer("Доступ только владельцу.")
        return

    products = get_products()
    items = "\n".join(f"- {item['name']} — {item['price']} ₽" for item in products)
    text = f"📦 Список товаров:\n{items}"
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]))


async def process_owner_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    action = PENDING_ACTIONS.get(user.id)
    if not action:
        return

    text = update.message.text.strip()

    if action == "support":
        await handle_support_message(update, context)
        return

    if action == "wallet_owner_amount":
        try:
            amount = int(text)
        except ValueError:
            await update.message.reply_text("❌ Сумма должна быть числом.")
            return

        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть больше нуля.")
            return

        request_id = create_payment_request(user, amount, method="owner")
        owner_chat = context.bot_data.get("owner_chat_id") or OWNER_CHAT_ID
        if owner_chat:
            owner_text = (
                "📩 Новая заявка на пополнение баланса\n\n"
                f"Пользователь: {get_user_label(user)}\n"
                f"Сумма: {amount} ₽\n"
                f"ID заявки: {request_id}\n\n"
                "Подтвердите или отклоните заявку."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Подтвердить", callback_data=f"approve_payment:{request_id}")],
                [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_payment:{request_id}")],
            ])
            await context.bot.send_message(chat_id=owner_chat, text=owner_text, reply_markup=keyboard)

        await update.message.reply_text(
            f"✅ Заявка на пополнение на {amount} ₽ отправлена владельцу. Ожидайте подтверждения."
        )
        PENDING_ACTIONS.pop(user.id, None)
        return

    if not is_owner(user):
        await update.message.reply_text("❌ Доступ к этому действию есть только у владельца.")
        PENDING_ACTIONS.pop(user.id, None)
        return

    if action == "owner_top_up":
        parts = text.split()
        if len(parts) != 2:
            await update.message.reply_text("❌ Неверный формат. Используйте: @username 250")
            return

        username_raw, amount_raw = parts
        try:
            amount = int(amount_raw)
        except ValueError:
            await update.message.reply_text("❌ Сумма должна быть числом.")
            return

        conn = get_db_connection()
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? OR first_name = ?",
            (username_raw.lstrip("@").lower(), username_raw.lstrip("@")),
        ).fetchone()
        conn.close()

        if row is None:
            await update.message.reply_text(f"❌ Пользователь {username_raw} не найден.")
            PENDING_ACTIONS.pop(user.id, None)
            return

        new_balance = get_user_balance(row["id"]) + amount
        set_user_balance(row["id"], new_balance)
        username_for_msg = row["username"] or row["first_name"] or str(row["id"])
        await update.message.reply_text(f"✅ Баланс пользователя {username_for_msg} пополнен на {amount} ₽.")
        PENDING_ACTIONS.pop(user.id, None)
        return

    if action == "owner_add_product":
        parts = [item.strip() for item in text.split("|")]
        if len(parts) != 2:
            await update.message.reply_text("❌ Неверный формат. Используйте: Название|Цена")
            return

        name, price_text = parts
        try:
            price = int(price_text)
        except ValueError:
            await update.message.reply_text("❌ Цена должна быть числом.")
            return

        add_product(name, price)
        await update.message.reply_text(f"✅ Товар '{name}' добавлен по цене {price} ₽.")
        PENDING_ACTIONS.pop(user.id, None)
        return


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None:
        return

    await query.answer()
    data = query.data

    if data == "back_to_profile":
        await send_profile(update, context)
        return

    if data == "settings":
        await show_settings(update, context)
        return

    if data == "stats":
        await show_stats(update, context)
        return

    if data == "wallet":
        await show_wallet(update, context)
        return

    if data == "wallet_yookassa":
        await wallet_yookassa_menu(update, context)
        return

    if data == "wallet_owner":
        await wallet_owner_request(update, context)
        return

    if data.startswith("pay:"):
        parts = data.split(":")
        if len(parts) >= 3:
            amount = int(parts[1])
            method = parts[2]
            await pay_via_yookassa(update, context, amount, method)
        return

    if data.startswith("approve_payment:"):
        request_id = int(data.split(":", 1)[1])
        if confirm_payment_request(request_id):
            request = get_payment_request(request_id)
            if request:
                await query.edit_message_text(
                    f"✅ Заявка #{request_id} подтверждена. Пользователю {request['username']} зачислено {request['amount']} ₽.")
            else:
                await query.edit_message_text("✅ Заявка подтверждена.")
        else:
            await query.edit_message_text("⚠️ Заявка уже обработана или не найдена.")
        return

    if data.startswith("reject_payment:"):
        request_id = int(data.split(":", 1)[1])
        if reject_payment_request(request_id):
            request = get_payment_request(request_id)
            if request:
                await query.edit_message_text(
                    f"❌ Заявка #{request_id} отклонена для {request['username']}.")
            else:
                await query.edit_message_text("❌ Заявка отклонена.")
        else:
            await query.edit_message_text("⚠️ Заявка уже обработана или не найдена.")
        return

    if data == "rent":
        await show_rent(update, context)
        return

    if data == "shop":
        await show_shop(update, context)
        return

    if data == "support":
        await support_menu(update, context)
        return

    if data == "support_write":
        PENDING_ACTIONS[query.from_user.id] = "support"
        await query.edit_message_text(
            "🆘 Напишите сообщение в поддержку. Мы ответим в рабочее время с 9:00 до 21:00.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="support")]]),
        )
        return

    if data == "owner_panel":
        await show_owner_panel(update, context)
        return

    if data == "owner_payment_requests":
        await owner_payment_requests(update, context)
        return

    if data == "owner_top_up":
        await owner_top_up_step(update, context)
        return

    if data == "owner_add_product":
        await owner_add_product_step(update, context)
        return

    if data == "owner_list_products":
        await owner_list_products(update, context)
        return

    if data.startswith("rent:"):
        await query.edit_message_text(f"✅ Вы выбрали {data.split(':', 1)[1]}. Услуга успешно добавлена в корзину.")
        return

    if data.startswith("buy:"):
        await query.edit_message_text(f"✅ Вы выбрали {data.split(':', 1)[1]}. Покупка оформлена.")
        return


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        ensure_user(user)
    await send_profile(update, context)


def main():
    init_db()
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is not set. Add it to .env or environment variables.")

    application = Application.builder().token(token).build()
    application.bot_data["owner_chat_id"] = OWNER_CHAT_ID
    application.bot_data["bot_name"] = BOT_NAME

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_owner_input))

    application.run_polling()


if __name__ == "__main__":
    main()
