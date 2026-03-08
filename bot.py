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
LOG_CHANNEL_ID = 1479880771274674259

orders = {}

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

app = FastAPI()


def random_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


# ================= API =================

async def send_card(telco, amount, serial, code, request_id):

    sign = hashlib.md5((PARTNER_KEY + code + serial).encode()).hexdigest()

    params = {
        "partner_id": PARTNER_ID,
        "request_id": request_id,
        "telco": telco,
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

        if status == 1:

            embed = discord.Embed(
                title="🎉 THANH TOÁN THÀNH CÔNG",
                description=f"""
📦 **Tên đơn hàng:** {order['product']}

💰 **Số tiền:** {amount}

🧾 **Mã đơn:** {request_id}

🔗 **Link tải:** {order['link']}

❤️ Cảm ơn vì đã tin tưởng sử dụng dịch vụ!
""",
                color=0x2ecc71
            )

            await channel.send(embed=embed)

        elif status == 2:
            await channel.send("⚠️ **Sai mệnh giá thẻ!**")

        elif status == 3:
            await channel.send("❌ **Thẻ đã qua sử dụng hoặc không hợp lệ!**")

        elif status == 99:
            await channel.send("⏳ **Thẻ đang chờ duyệt...**")

    return {"ok": True}


# ================= BOT READY =================

@bot.event
async def on_ready():
    print(f"Bot online: {bot.user}")


# ================= SELL CARD =================

@bot.command()
async def sellcard(ctx, amount: int, link: str):

    if not isinstance(ctx.channel, discord.Thread):
        await ctx.send("❌ Lệnh phải dùng trong forum")
        return

    product = ctx.channel.name

    embed = discord.Embed(
        title="💳 THANH TOÁN BẰNG CARD TẠI ĐÂY",
        description=f"""
📦 **Tên hàng:** {product}

💰 **Số tiền:** {amount}

👉 **Vui lòng nhấn nút MUA NGAY bên dưới để bắt đầu thanh toán**
""",
        color=0xf1c40f
    )

    view = BuyView(product, amount, link)

    await ctx.send(embed=embed, view=view)


# ================= BUY BUTTON =================

class BuyView(discord.ui.View):

    def __init__(self, product, amount, link):
        super().__init__(timeout=None)
        self.product = product
        self.amount = amount
        self.link = link

    @discord.ui.button(label="🛒 MUA NGAY", style=discord.ButtonStyle.green)
    async def buy(self, interaction: discord.Interaction, button):

        guild = interaction.guild
        user = interaction.user

        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)

        code = random_code()

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True)
        }

        channel = await guild.create_text_channel(
            name=f"{code.lower()}-{user.name}",
            category=category,
            overwrites=overwrites
        )

        orders[code] = {
            "channel": channel.id,
            "product": self.product,
            "link": self.link,
            "user": user.name
        }

        embed = discord.Embed(
            title="💳 XÁC NHẬN THANH TOÁN BẰNG CARD",
            description=f"""
📦 **Tên hàng:** {self.product}

💰 **Số tiền:** {self.amount}

🧾 **Mã đơn hàng:** {code}

⚠️ Nhấn **NẠP CARD** để thanh toán
""",
            color=0x3498db
        )

        view = OrderView(code, self.amount)

        await channel.send(user.mention, embed=embed, view=view)

        await interaction.response.send_message(
            f"✅ Đơn hàng đã tạo {channel.mention}",
            ephemeral=True
        )


# ================= ORDER VIEW =================

class OrderView(discord.ui.View):

    def __init__(self, order_id, amount):
        super().__init__(timeout=None)
        self.order_id = order_id
        self.amount = amount

    @discord.ui.button(label="💳 NẠP CARD", style=discord.ButtonStyle.green)
    async def nap(self, interaction: discord.Interaction, button):

        view = discord.ui.View()
        view.add_item(TelcoSelect(self.order_id, self.amount))

        await interaction.response.send_message(
            "📡 **Vui lòng chọn nhà mạng**",
            view=view
        )

    @discord.ui.button(label="❌ HỦY ĐƠN", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button):

        await interaction.response.send_message(
            "⚠️ **BẠN CÓ CHẮC HỦY ĐƠN CHỨ?**",
            view=CancelView()
        )


# ================= CANCEL =================

class CancelView(discord.ui.View):

    @discord.ui.button(label="CÓ", style=discord.ButtonStyle.red)
    async def yes(self, interaction: discord.Interaction, button):

        await interaction.response.send_message("🗑️ Kênh sẽ bị xóa sau 5 giây...")

        await asyncio.sleep(5)
        await interaction.channel.delete()

    @discord.ui.button(label="KHÔNG", style=discord.ButtonStyle.green)
    async def no(self, interaction: discord.Interaction, button):

        await interaction.response.send_message("✅ Tiếp tục thanh toán.")


# ================= TELCO SELECT =================

class TelcoSelect(discord.ui.Select):

    def __init__(self, order_id, amount):

        options = [
            discord.SelectOption(label="Viettel", value="VIETTEL"),
            discord.SelectOption(label="Vinaphone", value="VINAPHONE"),
            discord.SelectOption(label="Mobifone", value="MOBIFONE"),
            discord.SelectOption(label="Vcoin", value="VCOIN"),
            discord.SelectOption(label="Scoin", value="SCOIN"),
            discord.SelectOption(label="Zing", value="ZING")
        ]

        super().__init__(placeholder="📡 Chọn nhà mạng", options=options)

        self.order_id = order_id
        self.amount = amount

    async def callback(self, interaction: discord.Interaction):

        view = discord.ui.View()
        view.add_item(AmountSelect(self.values[0], self.order_id))

        await interaction.response.send_message(
            "💰 **Chọn mệnh giá thẻ**",
            view=view
        )


# ================= AMOUNT =================

class AmountSelect(discord.ui.Select):

    def __init__(self, telco, order_id):

        options = [
            discord.SelectOption(label="10.000", value="10000"),
            discord.SelectOption(label="20.000", value="20000"),
            discord.SelectOption(label="50.000", value="50000"),
            discord.SelectOption(label="100.000", value="100000"),
            discord.SelectOption(label="200.000", value="200000"),
            discord.SelectOption(label="500.000", value="500000")
        ]

        super().__init__(placeholder="💰 Chọn mệnh giá[Lưu ý:Chọn mệnh giá đúng với số tiền của đơn hàng.Nếu nhập sai sẽ không hoàn lại tiền!", options=options)

        self.telco = telco
        self.order_id = order_id

    async def callback(self, interaction: discord.Interaction):

        await interaction.response.send_modal(
            CardModal(self.telco, self.values[0], self.order_id)
        )


# ================= CARD MODAL =================

class CardModal(discord.ui.Modal, title="💳 Nhập thông tin thẻ"):

    serial = discord.ui.TextInput(label="SERIAL")
    code = discord.ui.TextInput(label="MÃ THẺ")

    def __init__(self, telco, amount, order_id):
        super().__init__()
        self.telco = telco
        self.amount = amount
        self.order_id = order_id

    async def on_submit(self, interaction: discord.Interaction):

        await interaction.response.send_message(
            "⏳ **Đang kiểm tra thẻ...**\n\n⚠️ Lưu ý: Nạp đúng mệnh giá thẻ.",
            ephemeral=True
        )

        try:

            result = await send_card(
                self.telco,
                self.amount,
                self.serial.value,
                self.code.value,
                self.order_id
            )

            status = result["status"]

            if status == 99:
                await interaction.followup.send("⏳ Thẻ đang chờ duyệt")

            elif status == 1:
                await interaction.followup.send("🎉 Thẻ hợp lệ, đang chờ callback")

            else:
                await interaction.followup.send(
                    "❌ Thẻ đã qua sử dụng hoặc không hợp lệ"
                )

        except:

            await interaction.followup.send(
                "🚨 HỆ THỐNG NẠP CARD ĐANG GẶP SỰ CỐ. VUI LÒNG BÁO ADMIN!"
            )


# ================= RUN API =================

def run_api():
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)


threading.Thread(target=run_api).start()

bot.run(TOKEN)

