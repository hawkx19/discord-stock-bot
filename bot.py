import os
import random
import sqlite3
import asyncio
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
STARTING_BALANCE = 100_000
DB_PATH = os.getenv("DB_PATH", "exchange.db")
PRICE_UPDATE_MINUTES = int(os.getenv("PRICE_UPDATE_MINUTES", "5"))

if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN environment variable.")
if OWNER_ID <= 0:
    raise RuntimeError("Missing OWNER_ID environment variable (your Discord user ID).")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

DEFAULT_STOCKS = [
    ("HAWK", "Hawkx Industries", 250.0),
    ("NOVA", "Nova Technologies", 180.0),
    ("ROYA", "Royal Motors", 420.0),
    ("PIXL", "Pixel Systems", 95.0),
    ("TITN", "Titan Energy", 310.0),
]

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS stocks (
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            previous_price REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS holdings (
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            shares INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, symbol)
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        for symbol, name, price in DEFAULT_STOCKS:
            con.execute(
                "INSERT OR IGNORE INTO stocks(symbol,name,price,previous_price,active) VALUES(?,?,?,?,1)",
                (symbol, name, price, price),
            )

def ensure_user(user_id: int):
    if user_id == OWNER_ID:
        return
    with db() as con:
        con.execute(
            "INSERT OR IGNORE INTO users(user_id,balance,created_at) VALUES(?,?,?)",
            (user_id, STARTING_BALANCE, datetime.now(timezone.utc).isoformat()),
        )

def get_balance(user_id: int):
    if user_id == OWNER_ID:
        return None
    ensure_user(user_id)
    with db() as con:
        row = con.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
        return int(row["balance"]) if row else STARTING_BALANCE

def change_balance(user_id: int, amount: int, kind: str, details: str):
    if user_id == OWNER_ID:
        return
    ensure_user(user_id)
    with db() as con:
        con.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
        con.execute(
            "INSERT INTO transactions(user_id,kind,details,created_at) VALUES(?,?,?,?)",
            (user_id, kind, details, datetime.now(timezone.utc).isoformat()),
        )

def log_transaction(user_id: int, kind: str, details: str):
    with db() as con:
        con.execute(
            "INSERT INTO transactions(user_id,kind,details,created_at) VALUES(?,?,?,?)",
            (user_id, kind, details, datetime.now(timezone.utc).isoformat()),
        )

def get_stock(symbol: str):
    with db() as con:
        return con.execute("SELECT * FROM stocks WHERE symbol=? AND active=1", (symbol.upper(),)).fetchone()

def money(n):
    return f"{int(n):,} coins"

def owner_only(interaction: discord.Interaction):
    return interaction.user.id == OWNER_ID

@bot.event
async def on_ready():
    init_db()
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as exc:
        print(f"Command sync failed: {exc}")
    print("Manual-price mode enabled: only the owner can change stock prices.")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

# Stock prices are MANUALLY controlled by the configured owner.
# There is intentionally no automatic price-update task.

@bot.tree.command(name="balance", description="Check your virtual coin balance")
async def balance(interaction: discord.Interaction):
    uid = interaction.user.id
    if uid == OWNER_ID:
        await interaction.response.send_message("👑 **Owner wallet:** Unlimited virtual coins.", ephemeral=True)
        return
    bal = get_balance(uid)
    await interaction.response.send_message(f"💰 **Your balance:** {money(bal)}", ephemeral=True)

@bot.tree.command(name="pay", description="Send virtual coins to another member")
@app_commands.describe(member="Who should receive coins", amount="Number of coins to send")
async def pay(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1_000_000_000]):
    sender = interaction.user.id
    receiver = member.id
    if receiver == sender:
        await interaction.response.send_message("You can't pay yourself.", ephemeral=True); return
    if member.bot:
        await interaction.response.send_message("You can't send coins to a bot account.", ephemeral=True); return
    if sender == OWNER_ID:
        change_balance(receiver, amount, "owner_transfer", f"Received {amount} from owner")
        log_transaction(sender, "owner_transfer", f"Sent {amount} to {receiver}")
        await interaction.response.send_message(f"✅ Sent **{money(amount)}** to {member.mention}. Your owner wallet remains unlimited.")
        return
    sender_balance = get_balance(sender)
    if sender_balance < amount:
        await interaction.response.send_message("❌ You don't have enough coins.", ephemeral=True); return
    change_balance(sender, -amount, "payment_sent", f"Sent {amount} to {receiver}")
    change_balance(receiver, amount, "payment_received", f"Received {amount} from {sender}")
    await interaction.response.send_message(f"✅ {interaction.user.mention} sent **{money(amount)}** to {member.mention}.")

@bot.tree.command(name="market", description="View fictional stock prices")
async def market(interaction: discord.Interaction):
    with db() as con:
        rows = con.execute("SELECT * FROM stocks WHERE active=1 ORDER BY symbol").fetchall()
    if not rows:
        await interaction.response.send_message("No active stocks right now."); return
    lines = ["**📈 Fictional Stock Exchange**", "_Prices are simulated and update automatically._"]
    for r in rows:
        change = float(r["price"]) - float(r["previous_price"])
        arrow = "🟢" if change >= 0 else "🔴"
        sign = "+" if change >= 0 else ""
        lines.append(f"{arrow} **{r['symbol']}** — {r['name']}: **{r['price']:,.2f}** coins ({sign}{change:,.2f})")
    await interaction.response.send_message("\n".join(lines))

@bot.tree.command(name="buy", description="Buy shares with virtual coins")
@app_commands.describe(symbol="Stock symbol, e.g. HAWK", shares="Whole number of shares")
async def buy(interaction: discord.Interaction, symbol: str, shares: app_commands.Range[int, 1, 1_000_000]):
    symbol = symbol.upper()
    stock = get_stock(symbol)
    if not stock:
        await interaction.response.send_message("Unknown or inactive stock. Use `/market`.", ephemeral=True); return
    cost = round(float(stock["price"]) * shares, 2)
    uid = interaction.user.id
    if uid != OWNER_ID:
        bal = get_balance(uid)
        if bal < cost:
            await interaction.response.send_message(f"❌ Not enough coins. Cost: **{cost:,.2f}**; balance: **{bal:,}**.", ephemeral=True); return
        change_balance(uid, -int(cost), "stock_buy", f"Bought {shares} {symbol} at {stock['price']}")
    with db() as con:
        con.execute(
            """INSERT INTO holdings(user_id,symbol,shares) VALUES(?,?,?)
               ON CONFLICT(user_id,symbol) DO UPDATE SET shares=shares+excluded.shares""",
            (uid, symbol, shares),
        )
    log_transaction(uid, "stock_buy", f"Bought {shares} {symbol} at {stock['price']}")
    await interaction.response.send_message(f"📈 Bought **{shares} {symbol}** for **{cost:,.2f} coins**.")

@bot.tree.command(name="sell", description="Sell shares you own")
@app_commands.describe(symbol="Stock symbol", shares="Whole number of shares to sell")
async def sell(interaction: discord.Interaction, symbol: str, shares: app_commands.Range[int, 1, 1_000_000]):
    symbol = symbol.upper()
    stock = get_stock(symbol)
    if not stock:
        await interaction.response.send_message("Unknown or inactive stock. Use `/market`.", ephemeral=True); return
    uid = interaction.user.id
    with db() as con:
        row = con.execute("SELECT shares FROM holdings WHERE user_id=? AND symbol=?", (uid, symbol)).fetchone()
        owned = int(row["shares"]) if row else 0
        if owned < shares:
            await interaction.response.send_message(f"❌ You only own **{owned} {symbol}** shares.", ephemeral=True); return
        remaining = owned - shares
        con.execute("UPDATE holdings SET shares=? WHERE user_id=? AND symbol=?", (remaining, uid, symbol))
    proceeds = int(float(stock["price"]) * shares)
    if uid != OWNER_ID:
        change_balance(uid, proceeds, "stock_sell", f"Sold {shares} {symbol} at {stock['price']}")
    log_transaction(uid, "stock_sell", f"Sold {shares} {symbol} at {stock['price']}")
    await interaction.response.send_message(f"💵 Sold **{shares} {symbol}** for **{money(proceeds)}**.")

@bot.tree.command(name="portfolio", description="View your stock holdings and estimated value")
async def portfolio(interaction: discord.Interaction):
    uid = interaction.user.id
    with db() as con:
        rows = con.execute(
            """SELECT h.symbol,h.shares,s.price FROM holdings h
               JOIN stocks s ON s.symbol=h.symbol WHERE h.user_id=? AND h.shares>0 ORDER BY h.symbol""",
            (uid,),
        ).fetchall()
    if not rows:
        await interaction.response.send_message("Your portfolio is empty. Try `/market` and `/buy`.", ephemeral=True); return
    total = 0
    lines = ["**📊 Your Portfolio**"]
    for r in rows:
        value = int(r["shares"] * r["price"])
        total += value
        lines.append(f"**{r['symbol']}** — {r['shares']} shares · {money(value)}")
    lines.append(f"\n**Estimated total value:** {money(total)}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@bot.tree.command(name="leaderboard", description="See the richest members by coins plus stock value")
async def leaderboard(interaction: discord.Interaction):
    with db() as con:
        users = con.execute("SELECT user_id,balance FROM users ORDER BY balance DESC LIMIT 25").fetchall()
        holdings = con.execute(
            """SELECT h.user_id,SUM(h.shares*s.price) AS value FROM holdings h
               JOIN stocks s ON s.symbol=h.symbol GROUP BY h.user_id"""
        ).fetchall()
    stock_values = {int(r["user_id"]): int(r["value"] or 0) for r in holdings}
    totals = [(int(u["user_id"]), int(u["balance"]) + stock_values.get(int(u["user_id"]), 0)) for u in users]
    totals.sort(key=lambda x: x[1], reverse=True)
    if not totals:
        await interaction.response.send_message("No member balances yet."); return
    lines = ["**🏆 Virtual Wealth Leaderboard**"]
    for i, (uid, total) in enumerate(totals[:10], 1):
        lines.append(f"`{i:>2}.` <@{uid}> — **{money(total)}**")
    await interaction.response.send_message("\n".join(lines))

@bot.tree.command(name="admin_give", description="Admin: give virtual coins to a member")
@app_commands.describe(member="Recipient", amount="Number of coins")
async def admin_give(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1_000_000_000]):
    if not owner_only(interaction):
        await interaction.response.send_message("Only the configured bot owner can use this command.", ephemeral=True); return
    if member.bot:
        await interaction.response.send_message("Choose a human member.", ephemeral=True); return
    change_balance(member.id, amount, "admin_grant", f"Owner granted {amount}")
    log_transaction(OWNER_ID, "admin_grant", f"Granted {amount} to {member.id}")
    await interaction.response.send_message(f"✅ Granted **{money(amount)}** to {member.mention}.")

@bot.tree.command(name="admin_set_balance", description="Admin: set a member's balance")
@app_commands.describe(member="Member", amount="New balance")
async def admin_set_balance(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 0, 1_000_000_000]):
    if not owner_only(interaction):
        await interaction.response.send_message("Only the configured bot owner can use this command.", ephemeral=True); return
    if member.id == OWNER_ID or member.bot:
        await interaction.response.send_message("Choose a non-bot member other than the owner.", ephemeral=True); return
    ensure_user(member.id)
    with db() as con:
        con.execute("UPDATE users SET balance=? WHERE user_id=?", (amount, member.id))
    log_transaction(OWNER_ID, "admin_set_balance", f"Set {member.id} balance to {amount}")
    await interaction.response.send_message(f"✅ Set {member.mention}'s balance to **{money(amount)}**.")

@bot.tree.command(name="admin_set_price", description="Admin: set a fictional stock price")
@app_commands.describe(symbol="Stock symbol", price="New price, greater than zero")
async def admin_set_price(interaction: discord.Interaction, symbol: str, price: app_commands.Range[float, 1, 1_000_000_000]):
    if not owner_only(interaction):
        await interaction.response.send_message("Only the configured bot owner can use this command.", ephemeral=True); return
    symbol = symbol.upper()
    stock = get_stock(symbol)
    if not stock:
        await interaction.response.send_message("Unknown or inactive stock.", ephemeral=True); return
    with db() as con:
        con.execute("UPDATE stocks SET previous_price=price,price=? WHERE symbol=?", (float(price), symbol))
    log_transaction(OWNER_ID, "admin_set_price", f"Set {symbol} price to {price}")
    await interaction.response.send_message(f"✅ Set **{symbol}** to **{price:,.2f} coins**.")


@bot.tree.command(name="admin_change_price", description="Admin: move a stock price up or down")
@app_commands.describe(
    symbol="Stock symbol",
    direction="Move the price up or down",
    amount="How much to change the price",
    percent="If true, amount is a percentage; otherwise it is a coin amount",
)
@app_commands.choices(direction=[
    app_commands.Choice(name="Up", value="up"),
    app_commands.Choice(name="Down", value="down"),
])
async def admin_change_price(
    interaction: discord.Interaction,
    symbol: str,
    direction: app_commands.Choice[str],
    amount: app_commands.Range[float, 0.01, 1_000_000_000],
    percent: bool = False,
):
    if not owner_only(interaction):
        await interaction.response.send_message("Only the configured bot owner can use this command.", ephemeral=True); return
    symbol = symbol.upper()
    stock = get_stock(symbol)
    if not stock:
        await interaction.response.send_message("Unknown or inactive stock.", ephemeral=True); return
    old_price = float(stock["price"])
    delta = old_price * (amount / 100.0) if percent else amount
    new_price = old_price + delta if direction.value == "up" else old_price - delta
    if new_price < 1:
        await interaction.response.send_message("That would make the price less than 1 coin. Choose a smaller decrease.", ephemeral=True); return
    new_price = round(new_price, 2)
    with db() as con:
        con.execute("UPDATE stocks SET previous_price=?,price=? WHERE symbol=?", (old_price, new_price, symbol))
    log_transaction(OWNER_ID, "admin_change_price", f"Changed {symbol} from {old_price} to {new_price}")
    arrow = "📈" if new_price > old_price else "📉"
    await interaction.response.send_message(f"{arrow} **{symbol}** changed from **{old_price:,.2f}** to **{new_price:,.2f} coins**.")

@bot.tree.command(name="admin_halt_stock", description="Admin: halt a stock so members cannot trade it")
@app_commands.describe(symbol="Stock symbol to halt")
async def admin_halt_stock(interaction: discord.Interaction, symbol: str):
    if not owner_only(interaction):
        await interaction.response.send_message("Only the configured bot owner can use this command.", ephemeral=True); return
    symbol = symbol.upper()
    with db() as con:
        row = con.execute("SELECT symbol FROM stocks WHERE symbol=?", (symbol,)).fetchone()
        if not row:
            await interaction.response.send_message("Unknown stock symbol.", ephemeral=True); return
        con.execute("UPDATE stocks SET active=0 WHERE symbol=?", (symbol,))
    await interaction.response.send_message(f"⏸️ **{symbol}** is halted and hidden from `/market`; members cannot buy or sell it.")

@bot.tree.command(name="admin_resume_stock", description="Admin: resume a halted stock")
@app_commands.describe(symbol="Stock symbol to resume")
async def admin_resume_stock(interaction: discord.Interaction, symbol: str):
    if not owner_only(interaction):
        await interaction.response.send_message("Only the configured bot owner can use this command.", ephemeral=True); return
    symbol = symbol.upper()
    with db() as con:
        row = con.execute("SELECT symbol FROM stocks WHERE symbol=?", (symbol,)).fetchone()
        if not row:
            await interaction.response.send_message("Unknown stock symbol.", ephemeral=True); return
        con.execute("UPDATE stocks SET active=1 WHERE symbol=?", (symbol,))
    await interaction.response.send_message(f"▶️ **{symbol}** is back on the market.")

@bot.tree.command(name="admin_add_stock", description="Admin: create a fictional stock")
@app_commands.describe(symbol="Short symbol, e.g. ORBX", company_name="Fictional company name", price="Starting price")
async def admin_add_stock(interaction: discord.Interaction, symbol: str, company_name: str, price: app_commands.Range[float, 1, 1_000_000_000]):
    if not owner_only(interaction):
        await interaction.response.send_message("Only the configured bot owner can use this command.", ephemeral=True); return
    symbol = symbol.upper()
    if not symbol.isalnum() or len(symbol) > 6:
        await interaction.response.send_message("Symbol must be 1–6 letters/numbers.", ephemeral=True); return
    try:
        with db() as con:
            con.execute("INSERT INTO stocks(symbol,name,price,previous_price,active) VALUES(?,?,?,?,1)",
                        (symbol, company_name[:80], float(price), float(price)))
    except sqlite3.IntegrityError:
        await interaction.response.send_message("That symbol already exists.", ephemeral=True); return
    await interaction.response.send_message(f"✅ Added **{symbol} — {company_name}** at **{price:,.2f} coins**.")

@bot.tree.command(name="admin_pause_market", description="Admin: pause automatic stock price changes")
async def admin_pause_market(interaction: discord.Interaction):
    if not owner_only(interaction):
        await interaction.response.send_message("Only the configured bot owner can use this command.", ephemeral=True); return
    await interaction.response.send_message("ℹ️ Prices are owner-controlled; there is no automatic market movement.")

@bot.tree.command(name="admin_resume_market", description="Admin: resume automatic stock price changes")
async def admin_resume_market(interaction: discord.Interaction):
    if not owner_only(interaction):
        await interaction.response.send_message("Only the configured bot owner can use this command.", ephemeral=True); return
    await interaction.response.send_message("ℹ️ Prices are owner-controlled; use `/admin_set_price` or `/admin_change_price` to move a stock.")

@bot.tree.command(name="help_market", description="Show virtual exchange commands")
async def help_market(interaction: discord.Interaction):
    lines = [
        "**📘 Virtual Exchange Commands**",
        "`/balance` — check coins",
        "`/pay` — transfer coins",
        "`/market` — view stock prices",
        "`/buy` and `/sell` — trade shares",
        "`/portfolio` — view your shares",
        "`/leaderboard` — richest members",
        "",
        "**Owner commands**",
        "`/admin_give` — grant coins",
        "`/admin_set_balance` — set balance",
        "`/admin_set_price` — control a stock price",
        "`/admin_add_stock` — create a stock",
        "`/admin_pause_market` and `/admin_resume_market` — control market updates",
        "",
        "_All coins and companies are fictional; no real money or real investments are involved._",
    ]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

init_db()
bot.run(TOKEN)
