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

TOKEN = os.getenv("TOKEN")

PARTNER_ID = "45016810383"
PARTNER_KEY = "0c8672410bf6ba8caeb009508b026ed9"

API_URL = "https://doithe1s.vn/chargingws/v2"

CATEGORY_NAME = "orders-card"
LOG_CHANNEL_ID = 1479880771274674259  # ID kênh card-logs

orders = {}

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

app = FastAPI()


def random_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


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
            return await resp.json()


# ================= CALLBACK =================

@app.api_route("/callback", methods=["GET", "POST"])
async def callback(request: Request):

    if request.method == "POST":
        data = await request.json()
    else:
        data = dict(request.query_params)

    request_id = data.get("request_id")
    status = int(data.get("status", 0))
    amount = data.get("amount", "0")

    if request_id in orders:

        order = orders[request_id]

        channel = bot.get_channel(order["channel"])
        log_channel = bot.get_channel(LOG_CHANNEL_ID)

        if not channel:
            return {"ok": True}

        if status == 1:

            embed = discord.Embed(
                title="🎉 THANH TOÁN THÀNH CÔNG",
                description=f"""
📦 **Tên đơn:** {order['product']}

💰 **Số tiền:** {amount}

🧾 **Mã đơn:** {request_id}

🔗 **Link:** {order['link']}
""",
                color=0x00ff00
            )

            await channel.send(embed=embed)

            if log_channel:

                log = discord.Embed(
                    title="💰 TIỀN ĐÃ VÀO",
                    description=f"""
👤 User: {order['user']}
💵 Số tiền: {amount}
🧾 Mã đơn: {request_id}
""",
                    color=0x2ecc71
                )

                await log_channel.send(embed=log)

        elif status == 2:

            await channel.send("⚠️ Thẻ sai mệnh giá")

        elif status == 3:

            await channel.send("❌ Thẻ sai hoặc đã sử dụng")

        elif status == 99:

            await channel.send("⏳ Thẻ đang chờ duyệt")

    return {"ok": True}


# ================= DISCORD =================

@bot.event
async def on_ready():
    print(f"Bot online: {bot.user}")


@bot.command()
async def sellcard(ctx, amount: int, link: str):

    if not isinstance(ctx.channel, discord.Thread):
        await ctx.send("❌ Lệnh phải dùng trong forum")
        return

    product = ctx.channel.name

    embed = discord.Embed(
        title="💳 THANH TOÁN BẰNG CARD",
        description=f"""
📦 **Tên hàng:** {product}

💰 **Số tiền:** {amount}

👉 Nhấn **MUA NGAY**
"""
    )

    view = BuyView(product, amount, link)

    await ctx.send(embed=embed, view=view)


class BuyView(discord.ui.View):

    def __init__(self, product, amount, link):
        super().__init__(timeout=None)

        self.product = product
        self.amount = amount
        self.link = link

    @discord.ui.button(label="MUA NGAY", style=discord.ButtonStyle.green)
    async def buy(self, interaction: discord.Interaction, button):

        guild = interaction.guild
        user = interaction.user

        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)

        if not category:
            await interaction.response.send_message(
                "❌ Không tìm thấy category orders-card",
                ephemeral=True
            )
            return

        channel = await guild.create_text_channel(
            name=f"{random_code().lower()}-{user.name}",
            category=category
        )

        order_code = random_code()

        orders[order_code] = {
            "channel": channel.id,
            "product": self.product,
            "link": self.link,
            "user": user.name
        }

        embed = discord.Embed(
            title="💳 XÁC NHẬN THANH TOÁN",
            description=f"""
📦 {self.product}

💰 {self.amount}

🧾 {order_code}
"""
        )

        await channel.send(user.mention, embed=embed)

        await interaction.response.send_message(
            f"✅ Đơn đã tạo {channel.mention}",
            ephemeral=True
        )


# ================= RUN WEB SERVER =================

def run_api():
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)


threading.Thread(target=run_api).start()

bot.run(TOKEN)
