import discord
from discord.ext import commands
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
from datetime import datetime

TOKEN = os.getenv("TOKEN")

PARTNER_ID = "86935102540"
PARTNER_KEY = "c63d72291473a68fcbb23261491a103f"
API_URL = "https://gachthe1s.com/chargingws/v2"

CATEGORY_NAME = "orders-card"
LOG_CHANNEL_ID = 1479880771274674259

orders = {}

# ===== ANTI SPAM =====
user_cooldown = {}
user_fail_count = {}
user_block_until = {}

# ===== ANTI SPAM BUY BUTTON =====
buy_cooldown = {}

# ===== LIMIT TICKET PER USER =====
user_ticket_count = {}
MAX_TICKETS_PER_USER = 3

COOLDOWN_TIME = 15
MAX_FAIL = 3
BLOCK_TIME = 300
BUY_COOLDOWN = 20

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

app = FastAPI()

def random_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# ================= API SEND CARD =================

async def send_card(telco, amount, serial, code, request_id):
    sign = hashlib.md5((PARTNER_KEY + code + serial).encode()).hexdigest()
    params = {
        "partner_id": PARTNER_ID,
        "request_id": request_id,
        "telco": telco.upper(),
        "code": code,
        "serial": serial,
        "amount": amount,
        "command": "charging",
        "sign": sign
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(API_URL, params=params) as resp:
            text = await resp.text()
            try:
                data = json.loads(text)
            except:
                print("API RAW ERROR:", text)
                return {"status": "0"}
            return data

# ================= CALLBACK (ĐÃ CẬP NHẬT LOG CHI TIẾT) =================

@app.api_route("/callback", methods=["GET", "POST"])
async def callback(request: Request):
    data = {}
    try:
        if request.method == "POST":
            try:
                data = await request.json()
            except:
                form_data = await request.form()
                data = dict(form_data)
        if not data:
            data = dict(request.query_params)
    except Exception as e:
        print(f"Lỗi đọc dữ liệu Callback: {e}")
        return {"status": 99, "message": "error"}

    print("--- CALLBACK RECEIVED ---")
    print(json.dumps(data, indent=2))

    request_id = str(data.get("request_id", "")).upper()
    status = str(data.get("status", ""))
    
    real_value = int(data.get("value") or data.get("amount") or 0)
    fee = float(data.get("fee", 0))
    receive = int(data.get("received") or data.get("receive") or 0)

    if request_id in orders:
        order = orders[request_id]
        channel = bot.get_channel(order["channel"])
        log_channel = bot.get_channel(LOG_CHANNEL_ID)

        # Log chi tiết ra kênh quản lý theo yêu cầu
        if log_channel:
            log_embed = discord.Embed(title="📥 THẺ NẠP MỚI", color=0x3498db)
            status_text = "Thẻ đúng" if status == "1" else status
            log_embed.add_field(name="Trạng thái", value=status_text, inline=True)
            log_embed.add_field(name="Mã nạp", value=order.get("code_card", "N/A"), inline=True)
            log_embed.add_field(name="Serial", value=order.get("serial_card", "N/A"), inline=True)
            
            log_embed.add_field(name="Mạng", value=order.get("telco_card", "N/A"), inline=True)
            log_embed.add_field(name="Tổng gửi", value=f"{order['amount']:,}", inline=True)
            log_embed.add_field(name="Tổng thực", value=f"{real_value:,}", inline=True)
            
            log_embed.add_field(name="Phí", value=f"{fee}%", inline=True)
            log_embed.add_field(name="Nhận", value=f"{receive:,}", inline=True)
            log_embed.add_field(name="Mã Đơn", value=request_id, inline=False)
            
            log_embed.set_footer(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            bot.loop.create_task(log_channel.send(embed=log_embed))

        if not channel:
            return {"status": 1, "message": "channel not found"}

        order_amount = int(order["amount"])

        if status == "1" and real_value == order_amount:
            user_id = order.get("user_id")
            if user_id and user_ticket_count.get(user_id, 0) > 0:
                user_ticket_count[user_id] -= 1

            embed = discord.Embed(
                title="🎉 THANH TOÁN THÀNH CÔNG",
                description=f"📦 **Tên hàng:** {order['product']}\n\n💰 **Số tiền:** {real_value:,} VND\n\n🧾 **Mã đơn:** {request_id}\n\n🔗 **Link tải:** {order['link']}\n\n❤️ Cảm ơn vì đã tin tưởng sử dụng dịch vụ!",
                color=0x2ecc71
            )
            bot.loop.create_task(channel.send(embed=embed))
            del orders[request_id]

        elif status == "1" and real_value != order_amount:
            bot.loop.create_task(channel.send(
                f"⚠️ Thẻ đúng nhưng **sai mệnh giá**\n"
                f"📥 Thẻ: {real_value:,} VND\n"
                f"🛒 Đơn yêu cầu: {order_amount:,} VND\n"
                f"❌ Không hoàn tiền."
            ))

        elif status == "2":
            bot.loop.create_task(channel.send("⚠️ Sai mệnh giá thẻ"))
        elif status == "3":
            bot.loop.create_task(channel.send("❌ Thẻ đã qua sử dụng hoặc không hợp lệ"))
        elif status == "99":
            bot.loop.create_task(channel.send("⏳ Thẻ đang được xử lý..."))
    
    return {"status": 1, "message": "success"}

@bot.event
async def on_ready():
    print(f"Bot đang chạy: {bot.user}")

@bot.command()
@commands.has_permissions(administrator=True)
async def daxong(ctx, order_id: str):
    order_id = order_id.upper()
    if order_id not in orders:
        await ctx.send("❌ Không tìm thấy đơn")
        return
    order = orders[order_id]
    channel = bot.get_channel(order["channel"])
    embed = discord.Embed(
        title="🎉 XÁC NHẬN THANH TOÁN THÀNH CÔNG (ADMIN)",
        description=f"📦 **Tên hàng:** {order['product']}\n\n🧾 **Mã đơn:** {order_id}\n\n🔗 **Link tải:** {order['link']}",
        color=0x2ecc71
    )
    await channel.send(embed=embed)
    await ctx.send("❤️ **Cảm ơn vì đã tin tưởng sử dụng dịch vụ!**")

@bot.command()
async def sellcard(ctx, amount: int, link: str):
    product = ctx.channel.name
    embed = discord.Embed(
        title="💳 THANH TOÁN BẰNG CARD TẠI ĐÂY",
        description=f"📦 **Tên hàng:** {product}\n\n💳 **Số tiền:** {amount:,} VND\n\n👇 **Nhấn nút MUA NGAY bên dưới để bắt đầu thanh toán**",
        color=0xf1c40f
    )
    await ctx.send(embed=embed, view=BuyView(product, amount, link))

class BuyView(discord.ui.View):
    def __init__(self, product, amount, link):
        super().__init__(timeout=None)
        self.product = product
        self.amount = amount
        self.link = link

    @discord.ui.button(label="🛒 MUA NGAY", style=discord.ButtonStyle.green)
    async def buy(self, interaction: discord.Interaction, button):
        user_id = interaction.user.id
        now = time.time()
        if user_id in buy_cooldown and now - buy_cooldown[user_id] < BUY_COOLDOWN:
            return await interaction.response.send_message(f"⏳ Bạn đang tạo đơn quá nhanh, vui lòng chờ {int(BUY_COOLDOWN-(now-buy_cooldown[user_id]))}s.", ephemeral=True)
        if user_ticket_count.get(user_id, 0) >= MAX_TICKETS_PER_USER:
            return await interaction.response.send_message("🚫 Bạn đã đạt giới hạn 3 đơn hàng đang mở. Hãy hoàn thành hoặc hủy đơn trước.", ephemeral=True)

        buy_cooldown[user_id] = now
        guild = interaction.guild
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
        code = random_code()
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }
        channel = await guild.create_text_channel(name=f"{code.lower()}-{interaction.user.name}", category=category, overwrites=overwrites)
        
        orders[code.upper()] = {
            "channel": channel.id, "product": self.product, "link": self.link,
            "user_id": user_id, "amount": self.amount, "user": interaction.user.name
        }
        user_ticket_count[user_id] = user_ticket_count.get(user_id, 0) + 1

        embed = discord.Embed(title="# 💳 XÁC NHẬN THANH TOÁN BẰNG CARD", description=f"📦 **Tên hàng:** {self.product}\n💳 **Số tiền:** {self.amount:,} VND\n🧾 **Mã đơn:** {code}\n\n⚠️ **LƯU Ý: NẠP SAI NỘI DUNG THẺ HOẶC SAI MỆNH GIÁ TIỀN SẼ KHÔNG ĐƯỢC HOÀN TRẢ LẠI!**\n\n👇 **Chọn phương thức thanh toán**", color=0x3498db)
        await channel.send(interaction.user.mention, embed=embed, view=OrderView(code, self.amount))
        await interaction.response.send_message(f"✅ Đơn hàng đã tạo {channel.mention}", ephemeral=True)

class OrderView(discord.ui.View):
    def __init__(self, order_id, amount):
        super().__init__(timeout=None)
        self.order_id, self.amount = order_id, amount

    @discord.ui.button(label="💳 NẠP CARD", style=discord.ButtonStyle.green)
    async def nap(self, interaction: discord.Interaction, button):
        view = discord.ui.View().add_item(TelcoSelect(self.order_id, self.amount))
        await interaction.response.send_message(f"## 📡Chọn nhà mạng (mệnh giá {self.amount:,} VND)\n\n-# thời gian tự động xác thực mã thẻ sẽ lâu nếu nằm ngoài giờ làm việc[7h30-22h mỗi ngày].", view=view, ephemeral=True)

    @discord.ui.button(label="❌ HỦY ĐƠN", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button):
        await interaction.response.send_message("⚠️ Bạn chắc chắn muốn hủy?", view=CancelView(), ephemeral=True)

class CancelView(discord.ui.View):
    @discord.ui.button(label="CÓ", style=discord.ButtonStyle.red)
    async def yes(self, interaction: discord.Interaction, button):
        if user_ticket_count.get(interaction.user.id, 0) > 0: user_ticket_count[interaction.user.id] -= 1
        await interaction.response.send_message("🗑️ Kênh sẽ bị xóa sau 5 giây")
        await asyncio.sleep(5)
        try: await interaction.channel.delete()
        except: pass

    @discord.ui.button(label="KHÔNG", style=discord.ButtonStyle.green)
    async def no(self, interaction: discord.Interaction, button):
        await interaction.response.send_message("✅ Tiếp tục thanh toán.", ephemeral=True)

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
        
        # Lưu thông tin thẻ vào order để Callback hiển thị Log
        if self.order_id in orders:
            orders[self.order_id]["serial_card"] = self.serial.value
            orders[self.order_id]["code_card"] = self.code.value
            orders[self.order_id]["telco_card"] = self.telco

        if user_id in user_block_until and now < user_block_until[user_id]:
            return await interaction.response.send_message(f"🚫 Bạn đã nhập sai quá nhiều. Thử lại sau {int(user_block_until[user_id]-now)}s", ephemeral=True)
        if user_id in user_cooldown and now - user_cooldown[user_id] < COOLDOWN_TIME:
            return await interaction.response.send_message(f"⏳ Vui lòng chờ {int(COOLDOWN_TIME-(now-user_cooldown[user_id]))}s trước khi gửi thẻ tiếp", ephemeral=True)

        user_cooldown[user_id] = now
        await interaction.response.send_message("⏳ Đang gửi thẻ...", ephemeral=True)
        
        result = await send_card(self.telco, self.amount, self.serial.value, self.code.value, self.order_id)
        status = str(result.get("status", "0"))

        if status == "99":
            await interaction.followup.send("✅ Hệ thống đã nhận thẻ\n⏳ Đang xử lý, vui lòng chờ kết quả...\n\n-# thời gian tự động xác thực mã thẻ sẽ lâu nếu nằm ngoài giờ làm việc [7h30-22h mỗi ngày]", ephemeral=True)
        elif status == "1":
            await interaction.followup.send("🎉 Thẻ hợp lệ, chờ callback", ephemeral=True)
            user_fail_count[user_id] = 0
        else:
            fails = user_fail_count.get(user_id, 0) + 1
            user_fail_count[user_id] = fails
            if fails >= MAX_FAIL: user_block_until[user_id] = now + BLOCK_TIME
            await interaction.followup.send(f"❌ Thẻ sai. Quá 3 lần thử sẽ bị cấm nạp thẻ 5 phút [số lần thử: ({fails}/{MAX_FAIL})]", ephemeral=True)

def start_bot():
    bot.run(TOKEN)

threading.Thread(target=start_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
