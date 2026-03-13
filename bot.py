import discord
from discord.ext import commands, tasks
import aiohttp
import hashlib
import random
import string
import asyncio
from fastapi import FastAPI, Request
import uvicorn
import threading
import os
import json
import time
import sqlite3
from datetime import datetime, timedelta

TOKEN = os.getenv("TOKEN")
PARTNER_ID = "86935102540"
PARTNER_KEY = "c63d72291473a68fcbb23261491a103f"
API_URL = "https://gachthe1s.com/chargingws/v2"

CATEGORY_NAME = "orders-card"
LOG_CHANNEL_ID = 1479880771274674259
HISTORY_CHANNEL_ID = 1481239066115571885 
WARRANTY_ROLE_ID = 1479550698982215852  
FEEDBACK_CHANNEL_MENTION = "<#1481245879607492769>"

# ===== DATABASE SETUP =====
def init_db():
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS orders 
                 (request_id TEXT PRIMARY KEY, channel_id INTEGER, product TEXT, link TEXT, 
                  user_id INTEGER, amount INTEGER, user_name TEXT, serial TEXT, code TEXT, telco TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS warranty 
                 (user_id INTEGER, guild_id INTEGER, expiry_timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS leaderboard (user_id INTEGER PRIMARY KEY, total_spent INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    conn.close()

def save_order(request_id, channel_id, product, link, user_id, amount, user_name):
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO orders (request_id, channel_id, product, link, user_id, amount, user_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (request_id, channel_id, product, link, user_id, amount, user_name))
    conn.commit()
    conn.close()

def update_leaderboard(user_id, amount):
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("INSERT INTO leaderboard (user_id, total_spent) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET total_spent = total_spent + ?", (user_id, amount, amount))
    conn.commit()
    conn.close()

def get_order(request_id):
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE request_id = ?", (request_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"request_id": row[0], "channel": row[1], "product": row[2], "link": row[3], 
                "user_id": row[4], "amount": row[5], "user_name": row[6]}
    return None

def delete_order(request_id):
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("DELETE FROM orders WHERE request_id = ?", (request_id,))
    conn.commit()
    conn.close()

def update_card_info(request_id, serial, code, telco):
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("UPDATE orders SET serial = ?, code = ?, telco = ? WHERE request_id = ?", (serial, code, telco, request_id))
    conn.commit()
    conn.close()

init_db()

user_cooldown, user_fail_count, user_block_until, buy_cooldown, user_ticket_count = {}, {}, {}, {}, {}
MAX_TICKETS_PER_USER, COOLDOWN_TIME, MAX_FAIL, BLOCK_TIME, BUY_COOLDOWN = 3, 15, 3, 300, 20

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
app = FastAPI()

def random_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# Lệnh duyệt thủ công cho Admin
@bot.command(name="daxong")
@commands.has_permissions(administrator=True)
async def daxong(ctx, request_id: str):
    request_id = request_id.upper()
    order = get_order(request_id)
    
    if not order:
        return await ctx.send(f"❌ Không tìm thấy mã đơn: **{request_id}**")

    user_id = order["user_id"]
    product = order["product"]
    amount = order["amount"]
    link = order["link"]
    channel = bot.get_channel(order["channel"])
    history_channel = bot.get_channel(HISTORY_CHANNEL_ID)

    update_leaderboard(user_id, amount)

    embed = discord.Embed(
        title="🎉 THANH TOÁN THÀNH CÔNG (ADMIN)",
        description="Admin đã xác nhận giao dịch!",
        color=0x2ecc71
    )
    embed.add_field(name="📦 Tên hàng", value=f"{product}", inline=False)
    embed.add_field(name="💰 Số tiền", value=f"{amount:,} VND", inline=True)
    embed.add_field(name="🆔 Mã đơn", value=f"{request_id}", inline=True)
    embed.add_field(name="📥 Link tải", value=f"{link}", inline=False)
    
    if channel:
        await channel.send(embed=embed)
        await channel.send("✅ Đã xác nhận giao dịch thành công.")

    if history_channel:
        history_msg = f"<@{user_id}> đã thanh toán đơn hàng **{product}** với số tiền **{amount:,} VND**, Bạn đánh giá dịch vụ của chúng tớ tại {FEEDBACK_CHANNEL_MENTION} nhé!"
        await history_channel.send(history_msg)

    guild = ctx.guild
    if guild:
        member = guild.get_member(user_id)
        if member:
            role = guild.get_role(WARRANTY_ROLE_ID)
            if role: 
                try: await member.add_roles(role)
                except: pass
                expiry = (datetime.now() + timedelta(days=3)).timestamp()
                conn = sqlite3.connect('orders.db')
                conn.execute("INSERT OR REPLACE INTO warranty VALUES (?, ?, ?)", (user_id, guild.id, expiry))
                conn.commit()
                conn.close()

            dm_text = (f"Chúc mừng bạn đã mua thành công đơn hàng **{product}** với số tiền **{amount:,} VND**. "
                       f"Bạn có **3 ngày bảo hành** từ ***LoTuss's Schematic Shop***, sau **3 ngày bảo hành sẽ hết hạn!** "
                       f"Cảm ơn bạn đã tin tưởng và sử dụng dịch vụ của chúng tôi nhé!")
            try: await member.send(dm_text)
            except: pass

    if user_id in user_ticket_count: user_ticket_count[user_id] = max(0, user_ticket_count[user_id]-1)
    delete_order(request_id)
    await ctx.message.add_reaction("✅")

# Lệnh set kênh TOP cho Admin
@bot.command()
@commands.has_permissions(administrator=True)
async def settopcard(ctx):
    conn = sqlite3.connect('orders.db')
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('top_channel', ?)", (str(ctx.channel.id),))
    conn.commit()
    conn.close()
    await ctx.send(f"✅ Đã thiết lập kênh {ctx.channel.mention} làm nơi hiển thị bảng TOP CARD.")
    await update_top_task()

# --- Logic Bảng Top (Đã chỉnh sửa giống hệt ảnh mẫu) ---
@tasks.loop(minutes=30)
async def update_top_task():
    await bot.wait_until_ready()
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key = 'top_channel'")
    ch_res = c.fetchone()
    c.execute("SELECT value FROM config WHERE key = 'top_message'")
    msg_res = c.fetchone()
    
    if not ch_res:
        conn.close()
        return
        
    channel = bot.get_channel(int(ch_res[0]))
    if not channel:
        conn.close()
        return
        
    c.execute("SELECT user_id, total_spent FROM leaderboard ORDER BY total_spent DESC LIMIT 10")
    rows = c.fetchall()
    
    embed = discord.Embed(
        title="✨ 🏆 BẢNG VÀNG ĐẠI GIA - LOTUSS SHOP 🏆 ✨", 
        description="*Nơi vinh danh những khách hàng thân thiết và chịu chi nhất hệ thống.*\n▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬", 
        color=0xf1c40f
    )
    
    medals = ["🥇", "🥈", "🥉", "👤", "👤", "👤", "👤", "👤", "👤", "👤"]
    top_list = ""
    
    if not rows:
        top_list = "🚀 *Chưa có dữ liệu, hãy trở thành người đầu tiên!*"
    else:
        for i, r in enumerate(rows):
            user_tag = f"<@{r[0]}>"
            money = f"{r[1]:,}"
            if i < 3:
                top_list += f"{medals[i]} **Top {i+1}: {user_tag}**\n┗ 💰 Tổng chi: `{money} VND`\n\n"
            else:
                top_list += f"👤 Top {i+1}: {user_tag} | `{money} VND`\n"
                
    embed.add_field(name="💎 DANH SÁCH VINH DANH 💎", value=top_list, inline=False)
    embed.set_footer(text=f"🕒 Cập nhật tự động lúc: {datetime.now().strftime('%H:%M - %d/%m/%Y')}")
    
    message = None
    if msg_res:
        try: message = await channel.fetch_message(int(msg_res[0]))
        except: message = None
        
    if message: 
        await message.edit(embed=embed)
    else:
        new_msg = await channel.send(embed=embed)
        conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('top_message', ?)", (str(new_msg.id),))
        conn.commit()
    conn.close()

async def send_card(telco, amount, serial, code, request_id):
    sign = hashlib.md5((PARTNER_KEY + code + serial).encode()).hexdigest()
    params = {"partner_id": PARTNER_ID, "request_id": request_id, "telco": telco.upper(), "code": code, "serial": serial, "amount": amount, "command": "charging", "sign": sign}
    async with aiohttp.ClientSession() as session:
        async with session.get(API_URL, params=params) as resp:
            try: return await resp.json()
            except: return {"status": "0"}

@app.api_route("/callback", methods=["GET", "POST"])
async def callback(request: Request):
    data = {}
    try:
        if request.method == "POST":
            try: data = await request.json()
            except: data = dict(await request.form())
        if not data: data = dict(request.query_params)
    except: return {"status": 99}

    request_id = str(data.get("request_id", "")).upper()
    status = str(data.get("status", ""))
    real_value = int(data.get("value") or data.get("amount") or 0)
    receive = int(data.get("received") or data.get("receive") or 0)

    order = get_order(request_id)
    if order:
        channel = bot.get_channel(order["channel"])
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        history_channel = bot.get_channel(HISTORY_CHANNEL_ID)

        if log_channel:
            log_embed = discord.Embed(title="📥 THẺ NẠP MỚI", color=0x3498db)
            log_embed.add_field(name="Trạng thái", value="Thành công" if status == "1" else f"Lỗi ({status})")
            log_embed.add_field(name="Khách", value=order["user_name"])
            log_embed.add_field(name="Thực nhận", value=f"{receive:,} VND")
            log_embed.add_field(name="Mã Đơn", value=request_id)
            bot.loop.create_task(log_channel.send(embed=log_embed))

        if status == "1" and real_value == int(order["amount"]):
            user_id = order["user_id"]
            update_leaderboard(user_id, real_value)
            
            if user_id in user_ticket_count: user_ticket_count[user_id] = max(0, user_ticket_count[user_id]-1)
            if channel:
                embed_tkt = discord.Embed(title="🎉 THANH TOÁN THÀNH CÔNG", description=f"📦 **Tên hàng:** {order['product']}\n💰 **Tiền:** {real_value:,} VND\n🔗 **Link tải:** {order['link']}", color=0x2ecc71)
                bot.loop.create_task(channel.send(embed=embed_tkt))
            if history_channel:
                history_msg = f"<@{user_id}> đã thanh toán đơn hàng **{order['product']}** với số tiền **{real_value:,} VND**, Bạn đánh giá dịch vụ của chúng tớ tại {FEEDBACK_CHANNEL_MENTION} nhé!"
                bot.loop.create_task(history_channel.send(history_msg))
            guild = channel.guild if channel else None
            if guild:
                member = guild.get_member(user_id)
                if member:
                    role = guild.get_role(WARRANTY_ROLE_ID)
                    if role: 
                        bot.loop.create_task(member.add_roles(role))
                        expiry = (datetime.now() + timedelta(days=3)).timestamp()
                        conn = sqlite3.connect('orders.db')
                        conn.execute("INSERT OR REPLACE INTO warranty VALUES (?, ?, ?)", (user_id, guild.id, expiry))
                        conn.commit()
                        conn.close()
                    dm_text = (f"Chúc mừng bạn đã mua thành công đơn hàng **{order['product']}** với số tiền **{real_value:,} VND**. "
                               f"Bạn có **3 ngày bảo hành** từ ***LoTuss's Schematic Shop***, sau **3 ngày bảo hành sẽ hết hạn!** "
                               f"Cảm ơn bạn đã tin tưởng và sử dụng dịch vụ của chúng tôi nhé!")
                    try: bot.loop.create_task(member.send(dm_text))
                    except: pass
            delete_order(request_id)
        elif status == "1" and real_value != int(order["amount"]):
            if channel: bot.loop.create_task(channel.send(f"⚠️ Thẻ đúng nhưng sai mệnh giá. Không hoàn tiền."))
        elif status == "3" and channel: bot.loop.create_task(channel.send("❌ Thẻ đã sử dụng hoặc không hợp lệ."))
    return {"status": 1, "message": "success"}

@tasks.loop(hours=1)
async def check_warranty():
    now = datetime.now().timestamp()
    conn = sqlite3.connect('orders.db')
    c = conn.cursor()
    c.execute("SELECT user_id, guild_id FROM warranty WHERE expiry_timestamp <= ?", (now,))
    expired = c.fetchall()
    for u_id, g_id in expired:
        guild = bot.get_guild(g_id)
        if guild:
            member = guild.get_member(u_id)
            role = guild.get_role(WARRANTY_ROLE_ID)
            if member and role: 
                try: await member.remove_roles(role)
                except: pass
    c.execute("DELETE FROM warranty WHERE expiry_timestamp <= ?", (now,))
    conn.commit()
    conn.close()

@bot.event
async def on_ready():
    print(f"Bot đang chạy: {bot.user}")
    if not check_warranty.is_running(): check_warranty.start()
    if not update_top_task.is_running(): update_top_task.start()

@bot.command()
async def sellcard(ctx, amount: int, link: str):
    product = ctx.channel.name
    embed = discord.Embed(
        title="🛒 THANH TOÁN BẰNG CÁCH NẠP THẺ CÀO",
        description=(f"📦 **Tên hàng:** {product}\n\n💳 **Số tiền**: {amount:,} VND\n\n👇 **Nhấn nút MUA NGAY bên dưới để bắt đầu thanh toán**"),
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=BuyView(product, amount, link))

class BuyView(discord.ui.View):
    def __init__(self, product, amount, link):
        super().__init__(timeout=None)
        self.product, self.amount, self.link = product, amount, link
    @discord.ui.button(label="🛒 MUA NGAY", style=discord.ButtonStyle.green)
    async def buy(self, interaction: discord.Interaction, button):
        user_id = interaction.user.id
        now = time.time()
        if user_id in buy_cooldown and now - buy_cooldown[user_id] < BUY_COOLDOWN:
            return await interaction.response.send_message(f"⏳ Thử lại sau {int(BUY_COOLDOWN-(now-buy_cooldown[user_id]))}s.", ephemeral=True)
        if user_ticket_count.get(user_id, 0) >= MAX_TICKETS_PER_USER:
            return await interaction.response.send_message("🚫 Bạn đã đạt giới hạn 3 đơn hàng đang mở. Hãy hoàn thành hoặc hủy đơn trước.", ephemeral=True)
        buy_cooldown[user_id] = now
        code = random_code()
        guild = interaction.guild
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False), interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True), guild.me: discord.PermissionOverwrite(view_channel=True)}
        
        channel_name = f"{code.lower()}-{interaction.user.name.lower()}"
        channel = await guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)
        
        save_order(code.upper(), channel.id, self.product, self.link, user_id, self.amount, interaction.user.name)
        user_ticket_count[user_id] = user_ticket_count.get(user_id, 0) + 1
        embed = discord.Embed(title="# 💳 XÁC NHẬN THANH TOÁN BẰNG THẺ CÀO", description=(f"📦 **Tên hàng:** {self.product}\n💰 **Số tiền:** {self.amount:,} VND\n🆔 **Mã đơn:** {code}\n\n-# Lưu ý: Nhập sai mệnh giá thẻ thì không hoàn tiền lại nhé.\n\n\n👇 Chọn phương thức thanh toán bên dưới"), color=discord.Color.blue())
        await channel.send(interaction.user.mention, embed=embed, view=OrderView(code, self.amount))
        await interaction.response.send_message(f"✅ Đơn hàng đã tạo: {channel.mention}", ephemeral=True)

class OrderView(discord.ui.View):
    def __init__(self, order_id, amount):
        super().__init__(timeout=None)
        self.order_id, self.amount = order_id, amount
    @discord.ui.button(label="💳 NẠP CARD", style=discord.ButtonStyle.green)
    async def nap(self, interaction: discord.Interaction, button):
        await interaction.response.send_message(f"📡 Chọn nhà mạng (mệnh giá {self.amount:,} VND)", view=discord.ui.View().add_item(TelcoSelect(self.order_id, self.amount)), ephemeral=True)
    @discord.ui.button(label="❌ HỦY ĐƠN", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button):
        embed = discord.Embed(title="⚠ XÁC NHẬN HỦY ĐƠN", description="BẠN CÓ CHẮC HỦY ĐƠN HÀNG CHỨ?", color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, view=CancelConfirm(self.order_id), ephemeral=True)

class CancelConfirm(discord.ui.View):
    def __init__(self, order_id):
        super().__init__(timeout=None)
        self.order_id = order_id
    @discord.ui.button(label="✅ CÓ", style=discord.ButtonStyle.red)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        await interaction.response.send_message("⏳ Kênh sẽ bị xoá sau 5 giây.")
        if user_id in user_ticket_count and user_ticket_count[user_id] > 0: user_ticket_count[user_id] -= 1
        delete_order(self.order_id)
        await asyncio.sleep(5)
        try: await interaction.channel.delete()
        except: pass
    @discord.ui.button(label="❌ KHÔNG", style=discord.ButtonStyle.green)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("👍 Đơn hàng vẫn được giữ.", ephemeral=True)

class TelcoSelect(discord.ui.Select):
    def __init__(self, order_id, amount):
        options = [discord.SelectOption(label=x, value=x.upper()) for x in ["Viettel", "Vinaphone", "Mobifone", "Vcoin", "Scoin", "Zing"]]
        super().__init__(placeholder="📡 Chọn nhà mạng", options=options)
        self.order_id, self.amount = order_id, amount
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CardModal(self.values[0], self.amount, self.order_id))

class CardModal(discord.ui.Modal, title="💳 Nhập thông tin thẻ"):
    serial = discord.ui.TextInput(label="SERIAL")
    code = discord.ui.TextInput(label="MÃ THẺ")
    def __init__(self, telco, amount, order_id):
        super().__init__()
        self.telco, self.amount, self.order_id = telco, amount, order_id
    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        now = time.time()
        update_card_info(self.order_id, self.serial.value, self.code.value, self.telco)
        if user_id in user_block_until and now < user_block_until[user_id]:
            return await interaction.response.send_message(f"🚫 Bị chặn {int(user_block_until[user_id]-now)}s", ephemeral=True)
        if user_id in user_cooldown and now - user_cooldown[user_id] < COOLDOWN_TIME:
            return await interaction.response.send_message(f"⏳ Chờ {int(COOLDOWN_TIME-(now-user_cooldown[user_id]))}s", ephemeral=True)
        user_cooldown[user_id] = now
        await interaction.response.send_message("⏳ Đang gửi thẻ...", ephemeral=True)
        result = await send_card(self.telco, self.amount, self.serial.value, self.code.value, self.order_id)
        if str(result.get("status")) in ["1", "99"]:
            await interaction.followup.send("✅ Đã nhận thẻ, vui lòng chờ duyệt.", ephemeral=True)
            user_fail_count[user_id] = 0
        else:
            fails = user_fail_count.get(user_id, 0) + 1
            user_fail_count[user_id] = fails
            if fails >= MAX_FAIL: user_block_until[user_id] = now + BLOCK_TIME
            await interaction.followup.send(f"❌ Thẻ sai. Vui lòng nhập lại!({fails}/{MAX_FAIL}).", ephemeral=True)

def start_bot(): bot.run(TOKEN)
threading.Thread(target=start_bot, daemon=True).start()
if __name__ == "__main__": uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
