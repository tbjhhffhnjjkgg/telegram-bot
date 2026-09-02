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
YOOMONEY_WALLET = os.getenv("YOOMONEY_WALLET", "")
YOOMONEY_PHONE = os.getenv("YOOMONEY_PHONE", "")
YOOMONEY_PAYMENT_URL = os.getenv("YOOMONEY_PAYMENT_URL", "")
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
            price INTEGER,
            description TEXT DEFAULT '',
            photo_url TEXT DEFAULT '',
            vip_only INTEGER DEFAULT 0,
            script_only INTEGER DEFAULT 0
        )
        """
    )
    product_columns = {row[1] for row in conn.execute("PRAGMA table_info(products)").fetchall()}
    if "description" not in product_columns:
        conn.execute("ALTER TABLE products ADD COLUMN description TEXT DEFAULT ''")
    if "photo_url" not in product_columns:
        conn.execute("ALTER TABLE products ADD COLUMN photo_url TEXT DEFAULT ''")
    if "vip_only" not in product_columns:
        conn.execute("ALTER TABLE products ADD COLUMN vip_only INTEGER DEFAULT 0")
    if "script_only" not in product_columns:
        conn.execute("ALTER TABLE products ADD COLUMN script_only INTEGER DEFAULT 0")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price INTEGER,
            description TEXT DEFAULT '',
            photo_url TEXT DEFAULT ''
        )
        """
    )
    service_columns = {row[1] for row in conn.execute("PRAGMA table_info(services)").fetchall()}
    if "description" not in service_columns:
        conn.execute("ALTER TABLE services ADD COLUMN description TEXT DEFAULT ''")
    if "photo_url" not in service_columns:
        conn.execute("ALTER TABLE services ADD COLUMN photo_url TEXT DEFAULT ''")
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vip_users (
            user_id INTEGER PRIMARY KEY,
            price INTEGER NOT NULL,
            purchased_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            price INTEGER NOT NULL,
            status TEXT DEFAULT 'ready',
            purchased_at TEXT DEFAULT CURRENT_TIMESTAMP,
            received_at TEXT
        )
        """
    )
    conn.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('vip_price', '500')")
    conn.execute("INSERT OR IGNORE INTO products (name, price, description, photo_url) VALUES (?, ?, ?, ?)", ("Мод 1", 120, "Игровой мод для ArizonaRP", "https://placehold.co/800x500/png?text=ArizonaRP+Mod+1"))
    conn.execute("INSERT OR IGNORE INTO products (name, price, description, photo_url) VALUES (?, ?, ?, ?)", ("Мод 2", 240, "Расширенный игровой мод", "https://placehold.co/800x500/png?text=ArizonaRP+Mod+2"))
    conn.execute("INSERT OR IGNORE INTO services (name, price, description, photo_url) VALUES (?, ?, ?, ?)", ("Услуга 1", 300, "Аренда игровой услуги", "https://placehold.co/800x500/png?text=ArizonaRP+Service+1"))
    conn.execute("INSERT OR IGNORE INTO services (name, price, description, photo_url) VALUES (?, ?, ?, ?)", ("Услуга 2", 450, "Расширенная аренда игровой услуги", "https://placehold.co/800x500/png?text=ArizonaRP+Service+2"))
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
    if OWNER_CHAT_ID and user.id == OWNER_CHAT_ID:
        return True
    username = (user.username or "").lower()
    return username == OWNER_USERNAME


def get_user_balance(user_id: int) -> int:
    conn = get_db_connection()
    row = conn.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def get_vip_price() -> int:
    conn = get_db_connection()
    row = conn.execute("SELECT value FROM bot_settings WHERE key = 'vip_price'").fetchone()
    conn.close()
    return int(row[0]) if row else 500


def set_vip_price(price: int):
    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES ('vip_price', ?)", (str(price),))
    conn.commit()
    conn.close()


def is_vip(user_id: int) -> bool:
    conn = get_db_connection()
    row = conn.execute("SELECT 1 FROM vip_users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row is not None


def get_vip_users() -> List[Dict[str, object]]:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT v.user_id, v.price, v.purchased_at, u.username, u.first_name "
        "FROM vip_users v LEFT JOIN users u ON u.id = v.user_id ORDER BY v.purchased_at DESC"
    ).fetchall()
    conn.close()
    return [
        {"user_id": row[0], "price": int(row[1]), "purchased_at": row[2], "username": row[3], "first_name": row[4]}
        for row in rows
    ]


def purchase_vip(user_id: int):
    conn = get_db_connection()
    if conn.execute("SELECT 1 FROM vip_users WHERE user_id = ?", (user_id,)).fetchone():
        conn.close()
        return "already"
    price = get_vip_price()
    cursor = conn.execute(
        "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
        (price, user_id, price),
    )
    if cursor.rowcount != 1:
        conn.rollback()
        conn.close()
        return False
    conn.execute("INSERT INTO vip_users (user_id, price) VALUES (?, ?)", (user_id, price))
    conn.commit()
    conn.close()
    return price


def set_user_balance(user_id: int, balance: int):
    conn = get_db_connection()
    conn.execute("UPDATE users SET balance = ? WHERE id = ?", (balance, user_id))
    conn.commit()
    conn.close()


def get_all_users() -> List[Dict[str, object]]:
    conn = get_db_connection()
    rows = conn.execute("SELECT id, username, first_name, balance FROM users ORDER BY id DESC").fetchall()
    conn.close()
    return [{"id": row[0], "username": row[1], "first_name": row[2], "balance": int(row[3])} for row in rows]


def get_user_by_username(username: str):
    conn = get_db_connection()
    username_clean = username.lstrip("@").lower()
    row = conn.execute(
        "SELECT * FROM users WHERE LOWER(username) = ? OR LOWER(first_name) = ?",
        (username_clean, username_clean),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_products(vip_only=None, script_only=None) -> List[Dict[str, object]]:
    conn = get_db_connection()
    query = "SELECT id, name, price, description, photo_url, vip_only, script_only FROM products"
    params = ()
    filters = []
    if vip_only is not None:
        filters.append("vip_only = ?")
        params += (1 if vip_only else 0,)
    if script_only is not None:
        filters.append("script_only = ?")
        params += (1 if script_only else 0,)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    rows = conn.execute(query + " ORDER BY id", params).fetchall()
    conn.close()
    return [{"id": row[0], "name": row[1], "price": int(row[2]), "description": row[3] or "", "photo_url": row[4] or "", "vip_only": bool(row[5]), "script_only": bool(row[6])} for row in rows]


def get_services() -> List[Dict[str, object]]:
    conn = get_db_connection()
    rows = conn.execute("SELECT id, name, price, description, photo_url FROM services ORDER BY id").fetchall()
    conn.close()
    return [{"id": row[0], "name": row[1], "price": int(row[2]), "description": row[3] or "", "photo_url": row[4] or ""} for row in rows]


def get_service(service_id: int):
    conn = get_db_connection()
    row = conn.execute("SELECT id, name, price, description, photo_url FROM services WHERE id = ?", (service_id,)).fetchone()
    conn.close()
    return {"id": row[0], "name": row[1], "price": int(row[2]), "description": row[3] or "", "photo_url": row[4] or ""} if row else None


def get_product(product_id: int):
    conn = get_db_connection()
    row = conn.execute("SELECT id, name, price, description, photo_url, vip_only, script_only FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    return {"id": row[0], "name": row[1], "price": int(row[2]), "description": row[3] or "", "photo_url": row[4] or "", "vip_only": bool(row[5]), "script_only": bool(row[6])} if row else None


def add_product(name: str, price: int, description: str, photo_url: str, vip_only: bool = False, script_only: bool = False):
    conn = get_db_connection()
    conn.execute("INSERT INTO products (name, price, description, photo_url, vip_only, script_only) VALUES (?, ?, ?, ?, ?, ?)", (name, price, description, photo_url, int(vip_only), int(script_only)))
    conn.commit()
    conn.close()


def update_product(product_id: int, name: str, price: int, description: str, photo_url: str, vip_only: bool, script_only: bool):
    conn = get_db_connection()
    conn.execute(
        "UPDATE products SET name = ?, price = ?, description = ?, photo_url = ?, vip_only = ?, script_only = ? WHERE id = ?",
        (name, price, description, photo_url, int(vip_only), int(script_only), product_id),
    )
    conn.commit()
    conn.close()


def delete_product(product_id: int):
    conn = get_db_connection()
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()


def purchase_product(user_id: int, product_id: int):
    conn = get_db_connection()
    product = conn.execute("SELECT name, price, description, vip_only FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        conn.close()
        return None
    if product[3] and not conn.execute("SELECT 1 FROM vip_users WHERE user_id = ?", (user_id,)).fetchone():
        conn.close()
        return "vip_required"
    cursor = conn.execute(
        "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
        (int(product[1]), user_id, int(product[1])),
    )
    if cursor.rowcount == 1:
        conn.execute(
            "INSERT INTO purchases (user_id, product_id, name, description, price) VALUES (?, ?, ?, ?, ?)",
            (user_id, product_id, product[0], product[2] or "", int(product[1])),
        )
    conn.commit()
    conn.close()
    if cursor.rowcount != 1:
        return False
    return {"name": product[0], "price": int(product[1])}


def get_user_purchases(user_id: int) -> List[Dict[str, object]]:
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, name, description, price, status, purchased_at, received_at "
        "FROM purchases WHERE user_id = ? ORDER BY id DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [
        {"id": row[0], "name": row[1], "description": row[2] or "", "price": int(row[3]), "status": row[4], "purchased_at": row[5], "received_at": row[6]}
        for row in rows
    ]


def receive_purchase(user_id: int, purchase_id: int):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT name, description FROM purchases WHERE id = ? AND user_id = ? AND status = 'ready'",
        (purchase_id, user_id),
    ).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute(
        "UPDATE purchases SET status = 'received', received_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? AND status = 'ready'",
        (purchase_id, user_id),
    )
    conn.commit()
    conn.close()
    return {"name": row[0], "description": row[1] or ""}


def purchase_service(user_id: int, service_id: int):
    conn = get_db_connection()
    service = conn.execute("SELECT name, price FROM services WHERE id = ?", (service_id,)).fetchone()
    if not service:
        conn.close()
        return None
    cursor = conn.execute(
        "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
        (int(service[1]), user_id, int(service[1])),
    )
    if cursor.rowcount != 1:
        conn.rollback()
        conn.close()
        return False
    conn.commit()
    conn.close()
    return {"name": service[0], "price": int(service[1])}


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


def get_total_users() -> int:
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return int(count)


def get_total_revenue() -> int:
    conn = get_db_connection()
    total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM payment_requests WHERE status = 'confirmed'"
    ).fetchone()[0]
    conn.close()
    return int(total)


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
    conn = get_db_connection()
    request = conn.execute(
        "SELECT user_id, amount FROM payment_requests WHERE id = ? AND status = 'pending'",
        (request_id,),
    ).fetchone()
    if not request:
        conn.close()
        return False

    user_id = int(request[0])
    amount = int(request[1])
    conn.execute("UPDATE payment_requests SET status = 'confirmed' WHERE id = ?", (request_id,))
    conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
    conn.commit()
    conn.close()
    return True


def reject_payment_request(request_id: int):
    conn = get_db_connection()
    cursor = conn.execute(
        "UPDATE payment_requests SET status = 'rejected' WHERE id = ? AND status = 'pending'",
        (request_id,),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount == 1


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
        f"👋 Привет, *{name}*!\n"
        f"Добро пожаловать в *{BOT_NAME}*!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 *ВАШ ПРОФИЛЬ*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Юзер: `{name}`\n"
        f"💰 Баланс: `{balance} ₽`\n"
        f"⭐ VIP: `{'активен' if is_vip(user.id) else 'нет'}`\n"
        f"🆔 ID: `{user.id}`\n\n"
    )

    if is_owner_user:
        text += (
            "👑 *ВЫ АДМИНИСТРАТОР*\n"
            "Полный доступ ко всем функциям!\n\n"
        )

    text += (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎮 *ВЫБЕРИТЕ ДЕЙСТВИЕ*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    keyboard = build_main_keyboard(is_owner_user, is_vip(user.id))
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


def build_main_keyboard(is_owner_user: bool, is_vip_user: bool):
    buttons = [
        [InlineKeyboardButton("✏️ Редактировать профиль", callback_data="settings")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("💳 Пополнить баланс", callback_data="wallet")],
        [InlineKeyboardButton("🛍️ Магазин товаров", callback_data="shop")],
        [InlineKeyboardButton("💻 Магазин скриптов", callback_data="scripts")],
        [InlineKeyboardButton("🎁 Мои покупки", callback_data="my_purchases")],
        [InlineKeyboardButton("🛒 Аренда услуг", callback_data="rent")],
        [InlineKeyboardButton("⭐ VIP-статус", callback_data="vip")],
        [InlineKeyboardButton("🆘 Поддержка", callback_data="support")],
    ]
    if is_vip_user:
        buttons.append([InlineKeyboardButton("⭐ VIP-магазин", callback_data="vip_shop")])
    if is_owner_user:
        buttons.append([InlineKeyboardButton("👑 ПАНЕЛЬ АДМИНИСТРАТОРА", callback_data="owner_panel")])
    return InlineKeyboardMarkup(buttons)


async def show_owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner(user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return

    text = (
        "👑 *ПАНЕЛЬ АДМИНИСТРАТОРА*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Управляйте всеми аспектами бота:\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💰 Пополнить баланс пользователю", callback_data="owner_top_up")],
            [InlineKeyboardButton("📋 Заявки на пополнение", callback_data="owner_payment_requests")],
            [InlineKeyboardButton(" Список пользователей", callback_data="owner_users_list")],
                [InlineKeyboardButton("📈 Статистика бота", callback_data="owner_stats")],
                [InlineKeyboardButton("📢 Рассылка", callback_data="owner_broadcast")],
                [InlineKeyboardButton("⭐ Настройки VIP", callback_data="owner_vip_price")],
                [InlineKeyboardButton("👑 VIP-пользователи", callback_data="owner_vip_users")],
                [InlineKeyboardButton("⭐ VIP-магазин", callback_data="owner_vip_products")],
                    [InlineKeyboardButton("💻 Магазин скриптов", callback_data="owner_script_products")],
            [InlineKeyboardButton("🛍️ Управление товарами", callback_data="owner_add_product")],
            [InlineKeyboardButton("📦 Каталог товаров", callback_data="owner_list_products")],
            [InlineKeyboardButton("⚙️ Настройки бота", callback_data="owner_settings")],
            [InlineKeyboardButton("⬅️ Назад в профиль", callback_data="back_to_profile")],
        ]
    )
    await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💳 *ПОПОЛНИТЬ БАЛАНС*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Выберите способ оплаты:\n\n"
        "💳 *Оплата картой или СБП* — через платёжную ссылку\n\n"
        "� *ЮMoney вручную* — перевод на кошелёк\n"
        "Без YooKassa, через подтверждение\n\n"
        "👤 *Через владельца* — заявка\n"
        "Ждёте подтверждения\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    buttons = []
    if YOOMONEY_PAYMENT_URL:
        buttons.append([InlineKeyboardButton("💳 Оплатить картой / СБП", url=YOOMONEY_PAYMENT_URL)])
    elif get_yookassa_configured():
        buttons.append([InlineKeyboardButton("💳 Оплатить картой / СБП", callback_data="wallet_yookassa")])
    buttons.extend([
        [InlineKeyboardButton("💸 ЮMoney вручную", callback_data="wallet_yoomoney_manual")],
        [InlineKeyboardButton("👤 Оплата через владельца", callback_data="wallet_owner")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")],
    ])
    keyboard = InlineKeyboardMarkup(buttons)
    await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def wallet_yoomoney_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallet = YOOMONEY_WALLET or "не указан"
    phone = YOOMONEY_PHONE or "не указан"

    text = (
        "💸 *ЮMoney вручную*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 Кошелёк: `{wallet}`\n"
        f"📱 Телефон: `{phone}`\n\n"
        "1. Переведите нужную сумму\n"
        "2. В комментарии укажите: `Fronzan ArizonaRP`\n"
        "3. Нажмите кнопку «Я оплатил» и укажите сумму\n"
        "4. Баланс будет зачислен после проверки владельцем\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Я оплатил", callback_data="yoomoney_paid")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="wallet")],
        ]),
        parse_mode="Markdown"
    )


async def wallet_yoomoney_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    PENDING_ACTIONS[user.id] = "wallet_yoomoney_amount"
    await update.callback_query.edit_message_text(
        "✅ *ПОДТВЕРЖДЕНИЕ ПЕРЕВОДА*\n\n"
        "Введите сумму, которую вы перевели на ЮMoney.\n"
        "Владелец проверит перевод и подтвердит зачисление.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="wallet_yoomoney_manual")]]),
        parse_mode="Markdown",
    )


async def wallet_yookassa_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💳 *ПОПОЛНЕНИЕ ЧЕРЕЗ YOOKASSA*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Выберите сумму для пополнения:\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💵 100 ₽ (SBP)", callback_data="pay:100:sbp")],
            [InlineKeyboardButton("💳 300 ₽ (Карта)", callback_data="pay:300:card")],
            [InlineKeyboardButton("🟡 500 ₽ (ЮMoney)", callback_data="pay:500:yoomoney")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="wallet")],
        ]
    )
    await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def wallet_owner_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    PENDING_ACTIONS[user.id] = "wallet_owner_amount"
    text = (
        "👤 *ПОПОЛНЕНИЕ ЧЕРЕЗ ВЛАДЕЛЬЦА*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Введите сумму пополнения в рублях.\n\n"
        "Пример: `250`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="wallet")]]),
        parse_mode="Markdown"
    )


async def show_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    price = get_vip_price()
    if is_vip(user.id):
        text = "⭐ *VIP уже активен*\n\nУ вас есть доступ к VIP-статусу."
        buttons = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")]]
    else:
        text = (
            "⭐ *VIP-СТАТУС*\n\n"
            "VIP отмечает вас как особого пользователя бота.\n"
            f"Стоимость: *{price} ₽*\n"
            f"Ваш баланс: `{get_user_balance(user.id)} ₽`"
        )
        buttons = [
            [InlineKeyboardButton(f"⭐ Купить VIP за {price} ₽", callback_data="buy_vip")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")],
        ]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")


async def owner_vip_price_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return
    PENDING_ACTIONS[update.effective_user.id] = "owner_vip_price"
    await update.callback_query.edit_message_text(
        f"⭐ *ЦЕНА VIP*\n\nТекущая цена: `{get_vip_price()} ₽`\n\nВведите новую цену в рублях.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]),
        parse_mode="Markdown",
    )


async def owner_vip_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return
    users = get_vip_users()
    text = f"👑 *VIP-ПОЛЬЗОВАТЕЛИ*\n\nЦена VIP сейчас: `{get_vip_price()} ₽`\n\n"
    if not users:
        text += "Покупок пока нет."
    else:
        for item in users[:30]:
            label = item["username"] or item["first_name"] or str(item["user_id"])
            text += f"• `{label}` — купил за `{item['price']} ₽`\n"
        if len(users) > 30:
            text += f"\n... и ещё {len(users) - 30}"
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]),
        parse_mode="Markdown",
    )


async def pay_via_yookassa(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int, method: str):
    user = update.effective_user
    payment = create_yookassa_payment(user, amount, method)
    if payment is None:
        await update.callback_query.edit_message_text(
            "⚠️ *YooKassa не настроена*\n\n"
            "Добавьте `YOOKASSA_SHOP_ID` и `YOOKASSA_SECRET_KEY` в .env",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="wallet")]]),
            parse_mode="Markdown"
        )
        return

    confirmation_url = getattr(payment.confirmation, "confirmation_url", None)
    if not confirmation_url:
        await update.callback_query.edit_message_text(
            "⚠️ *Не удалось сформировать ссылку оплаты*\n\n"
            "Проверьте настройки YooKassa.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="wallet")]]),
            parse_mode="Markdown"
        )
        return

    text = (
        f"💳 *ПОПОЛНЕНИЕ БАЛАНСА*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Сумма: *{amount} ₽*\n"
        f"Способ: *{method.upper()}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Нажмите кнопку ниже для оплаты:"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Перейти к оплате", url=confirmation_url)],
            [InlineKeyboardButton("⬅️ Назад", callback_data="wallet")],
        ]
    )
    await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def show_rent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    services = get_services()
    text = (
        "🛒 *АРЕНДА УСЛУГ*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    for service in services:
        text += f"• *{service['name']}* — `{service['price']} ₽`\n  {service['description']}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nВыберите услугу:"
    buttons = [[InlineKeyboardButton(f"🛒 {service['name']}", callback_data=f"rent:{service['id']}")] for service in services]
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")


async def show_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = get_products(False, False)
    text = (
        "🛍️ *КАТАЛОГ ТОВАРОВ*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    for product in products:
        text += f"• *{product['name']}* — `{product['price']} ₽`\n  {product['description']}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nВыберите товар:"
    buttons = [[InlineKeyboardButton(f"🛍️ {product['name']} — {product['price']} ₽", callback_data=f"buy:{product['id']}")] for product in products]
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")


async def show_my_purchases(update: Update, context: ContextTypes.DEFAULT_TYPE):
    purchases = get_user_purchases(update.effective_user.id)
    if not purchases:
        text = "🎁 *МОИ ПОКУПКИ*\n\nУ вас пока нет купленных товаров."
        buttons = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")]]
    else:
        text = "🎁 *МОИ ПОКУПКИ*\n\nЗдесь сохраняются все ваши покупки. Нажмите «Забрать», чтобы получить товар.\n\n"
        buttons = []
        for purchase in purchases:
            status = "✅ получен" if purchase["status"] == "received" else "📦 готов к получению"
            text += f"• *{purchase['name']}* — `{purchase['price']} ₽`\n  {status}\n"
            if purchase["status"] == "ready":
                buttons.append([InlineKeyboardButton(f"🎁 Забрать: {purchase['name']}", callback_data=f"receive_purchase:{purchase['id']}")])
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")


async def show_scripts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scripts = get_products(False, True)
    text = "💻 *МАГАЗИН СКРИПТОВ*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for script in scripts:
        text += f"• *{script['name']}* — `{script['price']} ₽`\n  {script['description']}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nВыберите скрипт для просмотра карточки:"
    buttons = [[InlineKeyboardButton(f"💻 {script['name']} — {script['price']} ₽", callback_data=f"script:{script['id']}")] for script in scripts]
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")


async def show_vip_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_vip(update.effective_user):
        await update.callback_query.answer("⭐ VIP-магазин доступен после покупки VIP.", show_alert=True)
        return
    products = get_products(True)
    text = "⭐ *VIP-МАГАЗИН*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for product in products:
        text += f"• *{product['name']}* — `{product['price']} ₽`\n  {product['description']}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nВыберите VIP-товар:"
    buttons = [[InlineKeyboardButton(f"⭐ {product['name']} — {product['price']} ₽", callback_data=f"buy:{product['id']}")] for product in products]
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")


async def send_catalog_card(update: Update, context: ContextTypes.DEFAULT_TYPE, item: Dict[str, object], kind: str):
    query = update.callback_query
    if item.get("vip_only") and not is_vip(query.from_user.id):
        await query.answer("⭐ Сначала купите VIP-статус.", show_alert=True)
        return
    card_text = (
        f"{item['name']}\n\n"
        f"Что это: {item['description']}\n\n"
        f"Цена: {item['price']} ₽"
    )
    if kind in ("product", "script"):
        back_callback = "scripts" if kind == "script" else "shop"
        buttons = [
            [InlineKeyboardButton("✅ Купить", callback_data=f"confirm_buy:{item['id']}")],
            [InlineKeyboardButton("⬅️ В каталог", callback_data=back_callback)],
        ]
    else:
        buttons = [
            [InlineKeyboardButton("✅ Оплатить аренду", callback_data=f"confirm_rent:{item['id']}")],
            [InlineKeyboardButton("⬅️ К аренде", callback_data="rent")],
        ]
    markup = InlineKeyboardMarkup(buttons)
    if item["photo_url"]:
        try:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=item["photo_url"],
                caption=card_text,
                reply_markup=markup,
            )
            await query.edit_message_text("📸 Карточка отправлена ниже.", parse_mode="Markdown")
            return
        except Exception:
            pass
    await query.edit_message_text(card_text, reply_markup=markup)


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = get_user_balance(user.id)
    text = (
        "📊 *СТАТИСТИКА*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Пользователь: `{get_user_label(user)}`\n"
        f"💰 Текущий баланс: *{balance} ₽*\n"
        f"🛒 Услуг доступно: *{len(get_services())}*\n"
        f"🛍️ Товаров в каталоге: *{len(get_products())}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")]]), parse_mode="Markdown")


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    current_name = get_user_label(user)
    
    text = (
        "✏️ *РЕДАКТИРОВАТЬ ПРОФИЛЬ*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Текущее имя: *{current_name}*\n\n"
        "Что вы хотите изменить?"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Изменить имя", callback_data="edit_name")],
        [InlineKeyboardButton("🔐 Изменить username", callback_data="edit_username")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")],
    ])
    await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🆘 *ТЕХПОДДЕРЖКА*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏰ Рабочее время: 9:00 - 21:00\n\n"
        "Напишите ваше сообщение,\n"
        "и оно будет отправлено\n"
        "в поддержку."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Написать сообщение", callback_data="support_write")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_profile")],
    ])
    await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if PENDING_ACTIONS.get(user.id) == "support":
        text = f"📩 *НОВОЕ ОБРАЩЕНИЕ В ПОДДЕРЖКУ*\n\n от {get_user_label(user)}\n\n━━━━━━━━━━━━━━━━━━\n\n{update.message.text}"
        owner_chat = context.bot_data.get("owner_chat_id") or OWNER_CHAT_ID
        if owner_chat:
            await context.bot.send_message(chat_id=owner_chat, text=text, parse_mode="Markdown")
        await update.message.reply_text(
            "✅ *Ваше обращение отправлено в поддержку.*\n\n"
            "Ответ будет получен в рабочее время 9:00 - 21:00.",
            parse_mode="Markdown"
        )
        PENDING_ACTIONS.pop(user.id, None)
        return

    PENDING_ACTIONS[user.id] = "support"
    await update.message.reply_text(
        "🆘 *Напишите ваше обращение в техподдержку.*\n\n"
        "Мы ответим в рабочее время с 9:00 до 21:00.",
        parse_mode="Markdown"
    )


async def owner_top_up_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner(user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return

    PENDING_ACTIONS[user.id] = "owner_top_up"
    text = (
        "💰 *ПОПОЛНИТЬ БАЛАНС ПОЛЬЗОВАТЕЛЮ*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Введите данные в формате:\n"
        "`@username 250`\n\n"
        "Пример: `@Ivan 500`"
    )
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]),
        parse_mode="Markdown"
    )


async def owner_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return

    users = get_all_users()
    if not users:
        text = "👥 *СПИСОК ПОЛЬЗОВАТЕЛЕЙ*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nПользователей нет."
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]),
            parse_mode="Markdown"
        )
        return

    text = "👥 *СПИСОК ПОЛЬЗОВАТЕЛЕЙ*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for u in users[:20]:  # Максимум 20 пользователей
        username = u["username"] or u["first_name"] or f"ID: {u['id']}"
        text += f"• `{username}` — {u['balance']} ₽\n"
    
    if len(users) > 20:
        text += f"\n... и ещё {len(users) - 20} пользователей"
    
    text += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]),
        parse_mode="Markdown"
    )


async def owner_payment_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return

    requests = get_pending_payment_requests()
    if not requests:
        text = (
            "📋 *ЗАЯВКИ НА ПОПОЛНЕНИЕ*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Активных заявок нет."
        )
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]),
            parse_mode="Markdown"
        )
        return

    text = "📋 *АКТИВНЫЕ ЗАЯВКИ НА ПОПОЛНЕНИЕ*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    buttons = []
    for item in requests:
        label = item["username"] or f"user_{item['user_id']}"
        text += f"• {label} — *{item['amount']} ₽* (ID: `{item['id']}`)\n"
        buttons.append([
            InlineKeyboardButton(f"✅ {item['id']}", callback_data=f"approve_payment:{item['id']}"),
            InlineKeyboardButton(f"❌ {item['id']}", callback_data=f"reject_payment:{item['id']}"),
        ])
    
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")


async def owner_add_product_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner(user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return

    PENDING_ACTIONS[user.id] = "owner_add_product"
    text = (
        "🛍️ *ДОБАВИТЬ ТОВАР*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Введите товар в формате:\n"
        "`Название|Цена|Описание|URL-фото|VIP`\n\n"
        "Пример: `Мод 3|300|Новый игровой мод|https://site.ru/mod.jpg|да`\n"
        "Для обычного товара укажите `нет`."
    )
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]),
        parse_mode="Markdown"
    )


async def owner_list_products(update: Update, context: ContextTypes.DEFAULT_TYPE, vip_only=None, script_only=None):
    if not is_owner(update.effective_user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return

    products = get_products(vip_only, script_only)
    title = "💻 *СКРИПТЫ*" if script_only else "⭐ *VIP-ТОВАРЫ*" if vip_only else "📦 *КАТАЛОГ ТОВАРОВ*"
    text = f"{title}\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    buttons = []
    for item in products:
        text += f"• *{item['name']}* — `{item['price']} ₽`\n  {item['description']}\n"
        buttons.append([
            InlineKeyboardButton(f"✏️ Изменить: {item['name']}", callback_data=f"edit_product:{item['id']}"),
            InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_product:{item['id']}"),
        ])
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    buttons.append([InlineKeyboardButton("➕ Добавить товар", callback_data="owner_add_product")])
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")


async def owner_vip_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return
    await owner_list_products(update, context, True)


async def edit_product_step(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int):
    if not is_owner(update.effective_user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return
    product = get_product(product_id)
    if not product:
        await update.callback_query.answer("Товар не найден.", show_alert=True)
        return
    PENDING_ACTIONS[update.effective_user.id] = f"owner_edit_product:{product_id}"
    await update.callback_query.edit_message_text(
        "✏️ *РЕДАКТИРОВАНИЕ ПОЗИЦИИ*\n\n"
        "Введите данные в формате:\n"
        "`Название|Цена|Описание|URL-фото|VIP|СКРИПТ`\n\n"
        f"Текущие данные:\n`{product['name']}|{product['price']}|{product['description']}|{product['photo_url']}|{'да' if product['vip_only'] else 'нет'}|{'да' if product['script_only'] else 'нет'}`",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_list_products")]]),
        parse_mode="Markdown",
    )


async def owner_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return

    text = (
        "⚙️ *НАСТРОЙКИ БОТА*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📛 Имя бота: *{BOT_NAME}*\n"
        f"👤 Владелец: *@{OWNER_USERNAME}*\n"
        f"💬 ID для уведомлений: `{OWNER_CHAT_ID}`\n"
        f"💸 ЮMoney кошелёк: `{YOOMONEY_WALLET or 'не указан'}`\n"
        f"📱 ЮMoney телефон: `{YOOMONEY_PHONE or 'не указан'}`\n"
        f"🔗 Ссылка оплаты: `{'настроена' if YOOMONEY_PAYMENT_URL else 'не настроена'}`\n\n"
        "Настройки можно изменить через `.env` файл"
    )
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]), parse_mode="Markdown")


async def owner_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return

    users = get_total_users()
    revenue = get_total_revenue()
    requests = len(get_pending_payment_requests())
    text = (
        "📈 *СТАТИСТИКА БОТА*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Пользователей: *{users}*\n"
        f"💰 Общий доход: *{revenue} ₽*\n"
        f"📋 Активных заявок: *{requests}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]),
        parse_mode="Markdown"
    )


async def owner_broadcast_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_owner(user):
        await update.callback_query.answer("❌ Доступ только владельцу.")
        return

    PENDING_ACTIONS[user.id] = "owner_broadcast"
    text = (
        "📢 *РАССЫЛКА СООБЩЕНИЯ*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Введите текст для отправки всем пользователям бота.\n"
        "Поддерживается обычный текст и Markdown."
    )
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="owner_panel")]]),
        parse_mode="Markdown"
    )


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

    if action == "edit_name":
        conn = get_db_connection()
        conn.execute("UPDATE users SET first_name = ? WHERE id = ?", (text, user.id))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ *Имя изменено на:* `{text}`", parse_mode="Markdown")
        PENDING_ACTIONS.pop(user.id, None)
        return

    if action == "wallet_owner_amount":
        try:
            amount = int(text)
        except ValueError:
            await update.message.reply_text("❌ Сумма должна быть числом.", parse_mode="Markdown")
            return

        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть больше нуля.", parse_mode="Markdown")
            return

        request_id = create_payment_request(user, amount, method="owner")
        owner_chat = context.bot_data.get("owner_chat_id") or OWNER_CHAT_ID
        if owner_chat:
            owner_text = (
                "📩 *НОВАЯ ЗАЯВКА НА ПОПОЛНЕНИЕ*\n\n"
                f"👤 Пользователь: {get_user_label(user)}\n"
                f"💰 Сумма: *{amount} ₽*\n"
                f"🆔 ID заявки: `{request_id}`\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Подтвердить", callback_data=f"approve_payment:{request_id}")],
                [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_payment:{request_id}")],
            ])
            await context.bot.send_message(chat_id=owner_chat, text=owner_text, reply_markup=keyboard, parse_mode="Markdown")

        await update.message.reply_text(
            f"✅ *Заявка отправлена владельцу*\n\n"
            f"Сумма: `{amount} ₽`\n"
            "Ожидайте подтверждения...",
            parse_mode="Markdown"
        )
        PENDING_ACTIONS.pop(user.id, None)
        return

    if action == "wallet_yoomoney_amount":
        try:
            amount = int(text)
        except ValueError:
            await update.message.reply_text("❌ Сумма должна быть числом.", parse_mode="Markdown")
            return

        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть больше нуля.", parse_mode="Markdown")
            return

        request_id = create_payment_request(user, amount, method="yoomoney_manual")
        owner_chat = context.bot_data.get("owner_chat_id") or OWNER_CHAT_ID
        if owner_chat:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Подтвердить", callback_data=f"approve_payment:{request_id}")],
                [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_payment:{request_id}")],
            ])
            await context.bot.send_message(
                chat_id=owner_chat,
                text=(
                    "💸 *НОВЫЙ ПЕРЕВОД ЮMONEY НА ПРОВЕРКУ*\n\n"
                    f"👤 Пользователь: {get_user_label(user)}\n"
                    f"💰 Сумма: *{amount} ₽*\n"
                    f"🆔 ID заявки: `{request_id}`\n"
                    "Проверьте перевод в кошельке перед подтверждением."
                ),
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
        await update.message.reply_text(
            "✅ Заявка отправлена владельцу. Баланс будет пополнен после проверки перевода.",
            parse_mode="Markdown",
        )
        PENDING_ACTIONS.pop(user.id, None)
        return

    if action == "owner_vip_price":
        try:
            price = int(text)
        except ValueError:
            await update.message.reply_text("❌ Цена должна быть числом.", parse_mode="Markdown")
            return
        if price <= 0:
            await update.message.reply_text("❌ Цена должна быть больше нуля.", parse_mode="Markdown")
            return
        set_vip_price(price)
        await update.message.reply_text(f"✅ Цена VIP изменена на `{price} ₽`.", parse_mode="Markdown")
        PENDING_ACTIONS.pop(user.id, None)
        return

    if not is_owner(user):
        await update.message.reply_text("❌ Доступ к этому действию есть только у владельца.", parse_mode="Markdown")
        PENDING_ACTIONS.pop(user.id, None)
        return

    if action == "owner_top_up":
        parts = text.split()
        if len(parts) != 2:
            await update.message.reply_text("❌ Неверный формат. Используйте: `@username 250`", parse_mode="Markdown")
            return

        username_raw, amount_raw = parts
        try:
            amount = int(amount_raw)
        except ValueError:
            await update.message.reply_text("❌ Сумма должна быть числом.", parse_mode="Markdown")
            return

        if amount <= 0:
            await update.message.reply_text("❌ Сумма должна быть больше нуля.", parse_mode="Markdown")
            return

        user_data = get_user_by_username(username_raw)

        if user_data is None:
            await update.message.reply_text(f"❌ Пользователь `{username_raw}` не найден.", parse_mode="Markdown")
            PENDING_ACTIONS.pop(user.id, None)
            return

        new_balance = get_user_balance(user_data["id"]) + amount
        set_user_balance(user_data["id"], new_balance)
        username_for_msg = user_data["username"] or user_data["first_name"] or str(user_data["id"])
        
        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=user_data["id"],
                text=f"💰 *ПОПОЛНЕНИЕ БАЛАНСА*\n\nВас пополнил администратор на `{amount} ₽`\n\nТекущий баланс: `{new_balance} ₽`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        
        await update.message.reply_text(
            f"✅ *Баланс пополнен*\n\n"
            f"Пользователь: `{username_for_msg}`\n"
            f"Сумма: `{amount} ₽`\n"
            f"Новый баланс: `{new_balance} ₽`",
            parse_mode="Markdown"
        )
        PENDING_ACTIONS.pop(user.id, None)
        return

    if action == "owner_add_product":
        parts = [item.strip() for item in text.split("|")]
        if len(parts) not in (3, 4, 5, 6):
            await update.message.reply_text("❌ Неверный формат. Используйте: `Название|Цена|Описание|URL-фото|VIP|СКРИПТ`", parse_mode="Markdown")
            return

        name, price_text, description = parts[:3]
        photo_url = parts[3] if len(parts) >= 4 else ""
        vip_only = len(parts) >= 5 and parts[4].lower() in ("да", "yes", "1", "vip")
        script_only = len(parts) == 6 and parts[5].lower() in ("да", "yes", "1", "script", "скрипт")
        try:
            price = int(price_text)
        except ValueError:
            await update.message.reply_text("❌ Цена должна быть числом.", parse_mode="Markdown")
            return

        if price <= 0:
            await update.message.reply_text("❌ Цена должна быть больше нуля.", parse_mode="Markdown")
            return
        if not name or not description:
            await update.message.reply_text("❌ Название и описание не должны быть пустыми.", parse_mode="Markdown")
            return

        add_product(name, price, description, photo_url, vip_only, script_only)
        await update.message.reply_text(
            f"✅ *Товар добавлен*\n\n"
            f"Название: `{name}`\n"
            f"Цена: `{price} ₽`\n"
            f"Описание: `{description}`\n"
            f"Фото: `{photo_url or 'не указано'}`\n"
            f"Категория: `{'VIP' if vip_only else 'Обычный товар'}`",
            parse_mode="Markdown"
        )
        PENDING_ACTIONS.pop(user.id, None)
        return

    if action.startswith("owner_edit_product:"):
        parts = [item.strip() for item in text.split("|")]
        if len(parts) not in (3, 4, 5, 6):
            await update.message.reply_text("❌ Неверный формат. Используйте: `Название|Цена|Описание|URL-фото|VIP|СКРИПТ`", parse_mode="Markdown")
            return
        name, price_text, description = parts[:3]
        photo_url = parts[3] if len(parts) >= 4 else ""
        try:
            price = int(price_text)
        except ValueError:
            await update.message.reply_text("❌ Цена должна быть числом.", parse_mode="Markdown")
            return
        if price <= 0 or not name or not description:
            await update.message.reply_text("❌ Название и описание обязательны, цена должна быть больше нуля.", parse_mode="Markdown")
            return
        product_id = int(action.split(":", 1)[1])
        current_product = get_product(product_id)
        if not current_product:
            await update.message.reply_text("❌ Товар не найден.", parse_mode="Markdown")
            PENDING_ACTIONS.pop(user.id, None)
            return
        if len(parts) < 4:
            photo_url = current_product["photo_url"]
        vip_only = current_product["vip_only"]
        if len(parts) >= 5:
            vip_only = parts[4].lower() in ("да", "yes", "1", "vip")
        script_only = current_product["script_only"]
        if len(parts) == 6:
            script_only = parts[5].lower() in ("да", "yes", "1", "script", "скрипт")
        update_product(product_id, name, price, description, photo_url, vip_only, script_only)
        await update.message.reply_text("✅ Товар обновлён.", parse_mode="Markdown")
        PENDING_ACTIONS.pop(user.id, None)
        return

    if action == "owner_broadcast":
        sent = 0
        for u in get_all_users():
            try:
                await context.bot.send_message(chat_id=u["id"], text=text, parse_mode="Markdown")
                sent += 1
            except Exception:
                continue
        await update.message.reply_text(f"✅ *Рассылка отправлена*\n\nПользователям: `{sent}`", parse_mode="Markdown")
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

    if data == "profile":
        await send_profile(update, context)
        return

    if data == "settings":
        await show_settings(update, context)
        return

    if data == "edit_name":
        PENDING_ACTIONS[query.from_user.id] = "edit_name"
        await query.edit_message_text(
            "📝 *Введите ваше новое имя:*\n\nПример: `Иван`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="settings")]]),
            parse_mode="Markdown"
        )
        return

    if data == "edit_username":
        await query.edit_message_text(
            "ℹ️ *Username меняется через Telegram*\n\n"
            "Откройте настройки профиля в Telegram\n"
            "и измените username там.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="settings")]]),
            parse_mode="Markdown"
        )
        return

    if data == "stats":
        await show_stats(update, context)
        return

    if data == "wallet":
        await show_wallet(update, context)
        return

    if data == "vip":
        await show_vip(update, context)
        return

    if data == "buy_vip":
        result = purchase_vip(query.from_user.id)
        if result == "already":
            await query.edit_message_text("⭐ VIP у вас уже активен.", parse_mode="Markdown")
        elif result is False:
            await query.answer("Недостаточно средств на балансе.", show_alert=True)
        else:
            await query.edit_message_text(
                f"✅ *VIP успешно куплен за {result} ₽!*\n\n"
                f"Остаток баланса: `{get_user_balance(query.from_user.id)} ₽`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ В профиль", callback_data="back_to_profile")]]),
                parse_mode="Markdown",
            )
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
        if not is_owner(query.from_user):
            await query.answer("❌ Доступ только владельцу.", show_alert=True)
            return
        request_id = int(data.split(":", 1)[1])
        if confirm_payment_request(request_id):
            request = get_payment_request(request_id)
            if request:
                await query.edit_message_text(
                    f"✅ *ЗАЯВКА ПОДТВЕРЖДЕНА*\n\n"
                    f"Пользователю {request['username']}\n"
                    f"зачислено `{request['amount']} ₽`",
                    parse_mode="Markdown"
                )
                # Уведомляем пользователя
                try:
                    await context.bot.send_message(
                        chat_id=request["user_id"],
                        text=f"✅ *ПОПОЛНЕНИЕ ПОДТВЕРЖДЕНО*\n\nНа ваш счёт зачислено `{request['amount']} ₽`",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
            else:
                await query.edit_message_text("✅ Заявка подтверждена.", parse_mode="Markdown")
        else:
            await query.edit_message_text("⚠️ Заявка уже обработана или не найдена.", parse_mode="Markdown")
        return

    if data.startswith("reject_payment:"):
        if not is_owner(query.from_user):
            await query.answer("❌ Доступ только владельцу.", show_alert=True)
            return
        request_id = int(data.split(":", 1)[1])
        if reject_payment_request(request_id):
            request = get_payment_request(request_id)
            if request:
                await query.edit_message_text(
                    f"❌ *ЗАЯВКА ОТКЛОНЕНА*\n\n"
                    f"Заявка пользователя {request['username']}\n"
                    f"на сумму `{request['amount']} ₽` отклонена",
                    parse_mode="Markdown"
                )
                # Уведомляем пользователя
                try:
                    await context.bot.send_message(
                        chat_id=request["user_id"],
                        text=f"❌ *ЗАЯВКА НА ПОПОЛНЕНИЕ ОТКЛОНЕНА*\n\nВаша заявка на `{request['amount']} ₽` была отклонена.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
            else:
                await query.edit_message_text("❌ Заявка отклонена.", parse_mode="Markdown")
        else:
            await query.edit_message_text("⚠️ Заявка уже обработана или не найдена.", parse_mode="Markdown")
        return

    if data == "rent":
        await show_rent(update, context)
        return

    if data == "shop":
        await show_shop(update, context)
        return

    if data == "my_purchases":
        await show_my_purchases(update, context)
        return

    if data == "scripts":
        await show_scripts(update, context)
        return

    if data.startswith("script:"):
        script = get_product(int(data.split(":", 1)[1]))
        if script and script["script_only"] and not script["vip_only"]:
            await send_catalog_card(update, context, script, "script")
        else:
            await query.edit_message_text("❌ Скрипт больше не доступен.", parse_mode="Markdown")
        return

    if data == "vip_shop":
        await show_vip_shop(update, context)
        return

    if data == "support":
        await support_menu(update, context)
        return

    if data == "support_write":
        PENDING_ACTIONS[query.from_user.id] = "support"
        await query.edit_message_text(
            "🆘 *Напишите сообщение в поддержку.*\n\n"
            "Мы ответим в рабочее время с 9:00 до 21:00.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="support")]]),
            parse_mode="Markdown"
        )
        return

    if data == "wallet_yoomoney_manual":
        await wallet_yoomoney_manual(update, context)
        return

    if data == "yoomoney_paid":
        await wallet_yoomoney_paid(update, context)
        return

    if data == "owner_panel":
        await show_owner_panel(update, context)
        return

    if data == "owner_payment_requests":
        await owner_payment_requests(update, context)
        return

    if data == "owner_users_list":
        await owner_users_list(update, context)
        return

    if data == "owner_top_up":
        await owner_top_up_step(update, context)
        return

    if data == "owner_stats":
        await owner_stats(update, context)
        return

    if data == "owner_broadcast":
        await owner_broadcast_step(update, context)
        return

    if data == "owner_vip_price":
        await owner_vip_price_step(update, context)
        return

    if data == "owner_vip_users":
        await owner_vip_users(update, context)
        return

    if data == "owner_add_product":
        await owner_add_product_step(update, context)
        return

    if data == "owner_list_products":
        await owner_list_products(update, context)
        return

    if data == "owner_vip_products":
        await owner_vip_products(update, context)
        return

    if data == "owner_script_products":
        await owner_list_products(update, context, None, True)
        return

    if data == "owner_settings":
        await owner_settings(update, context)
        return

    if data.startswith("rent:"):
        service = get_service(int(data.split(":", 1)[1]))
        if service:
            await send_catalog_card(update, context, service, "service")
        else:
            await query.edit_message_text("❌ Услуга больше не доступна.", parse_mode="Markdown")
        return

    if data.startswith("order_rent:"):
        service = get_service(int(data.split(":", 1)[1]))
        if service:
            await query.edit_message_text(
                f"✅ Заявка на аренду услуги *{service['name']}* принята.\n\n"
                "Владелец свяжется с вами для уточнения деталей.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ К аренде", callback_data="rent")]]),
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text("❌ Услуга больше не доступна.", parse_mode="Markdown")
        return

    if data.startswith("confirm_rent:"):
        service_id = int(data.split(":", 1)[1])
        result = purchase_service(query.from_user.id, service_id)
        if result is None:
            await query.edit_message_text("❌ Услуга больше не доступна.", parse_mode="Markdown")
        elif result is False:
            await query.answer("Недостаточно средств на балансе.", show_alert=True)
        else:
            await query.edit_message_text(
                f"✅ *Аренда оплачена*\n\nУслуга: `{result['name']}`\n"
                f"Списано: `{result['price']} ₽`\n"
                f"Остаток: `{get_user_balance(query.from_user.id)} ₽`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ К аренде", callback_data="rent")]]),
                parse_mode="Markdown",
            )
        return

    if data.startswith("buy:"):
        product_id = int(data.split(":", 1)[1])
        product = get_product(product_id)
        if not product:
            await query.edit_message_text("❌ Товар больше не доступен.", parse_mode="Markdown")
            return
        await send_catalog_card(update, context, product, "product")
        return

    if data.startswith("confirm_buy:"):
        product_id = int(data.split(":", 1)[1])
        result = purchase_product(query.from_user.id, product_id)
        if result is None:
            await query.edit_message_text("❌ Товар больше не доступен.", parse_mode="Markdown")
        elif result == "vip_required":
            await query.answer("⭐ Сначала купите VIP-статус.", show_alert=True)
        elif result is False:
            await query.answer("Недостаточно средств на балансе.", show_alert=True)
        else:
            await query.edit_message_text(
                f"✅ *Покупка оформлена*\n\nТовар: `{result['name']}`\nСписано: `{result['price']} ₽`\n"
                f"Остаток: `{get_user_balance(query.from_user.id)} ₽`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ В каталог", callback_data="shop")]]),
                parse_mode="Markdown",
            )
        return

    if data.startswith("receive_purchase:"):
        purchase_id = int(data.split(":", 1)[1])
        purchase = receive_purchase(query.from_user.id, purchase_id)
        if not purchase:
            await query.answer("Покупка уже получена или не найдена.", show_alert=True)
            await show_my_purchases(update, context)
            return
        await query.edit_message_text(
            f"🎁 *ТОВАР ПОЛУЧЕН*\n\n"
            f"Название: *{purchase['name']}*\n\n"
            f"Описание и содержимое:\n{purchase['description']}\n\n"
            "Сохраните эту информацию. Открыть покупки можно в разделе «Мои покупки».",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎁 Мои покупки", callback_data="my_purchases")],
                [InlineKeyboardButton("⬅️ В профиль", callback_data="back_to_profile")],
            ]),
            parse_mode="Markdown",
        )
        return

    if data.startswith("edit_product:"):
        await edit_product_step(update, context, int(data.split(":", 1)[1]))
        return

    if data.startswith("delete_product:"):
        if not is_owner(query.from_user):
            await query.answer("❌ Доступ только владельцу.", show_alert=True)
            return
        product_id = int(data.split(":", 1)[1])
        product = get_product(product_id)
        if product:
            delete_product(product_id)
            await query.answer("Товар удалён.")
            await owner_list_products(update, context)
        else:
            await query.answer("Товар уже удалён.", show_alert=True)
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
