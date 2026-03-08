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


# ================= API SEND CARD =================

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

    if request.method == "GET":
        data = dict(request.query_params)
    else:
        data = await request.json()

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

❤️ Cảm ơn vì đã sử dụng dịch vụ!
""",
                color=0x2ecc71
            )

            await channel.send(embed=embed)

            # đổi ❌ thành ✅
            new_name = channel.name.replace("❌", "✅")
            await channel.edit(name=new_name)

        elif status == 3:

            await channel.send("❌ Thẻ đã qua sử dụng hoặc không hợp lệ. Vui lòng thử lại!")

        elif status == 2:

            await channel.send("⚠️ Sai mệnh giá thẻ!")

    return {"ok": True}


# ================= MODAL NHẬP THẺ =================

class CardModal(discord.ui.Modal, title="💳 Nhập thông tin thẻ"):

    serial = discord.ui.TextInput(label="SERIAL", placeholder="Nhập serial thẻ")
    code = discord.ui.TextInput(label="MÃ THẺ", placeholder="Nhập mã thẻ")

    def __init__(self, telco, amount, order_id):
        super().__init__()
        self.telco = telco
        self.amount = amount
        self.order_id = order_id

    async def on_submit(self, interaction: discord.Interaction):

        await interaction.response.send_message("⏳ Đang kiểm tra thẻ...", ephemeral=True)

        try:

            result = await send_card(
                self.telco,
                self.amount,
                self.serial.value,
                self.code.value,
                self.order_id
            )

            if result["status"] == 99:
                await interaction.followup.send("⌛ Thẻ đang chờ duyệt...")

            elif result["status"] == 1:
                await interaction.followup.send("🎉 Thẻ hợp lệ! Đang chờ callback.")

            else:
                await interaction.followup.send("❌ Thẻ đã qua sử dụng hoặc không hợp lệ!")

        except:
            await interaction.followup.send("⚠️ HỆ THỐNG NẠP CARD ĐANG GẶP SỰ CỐ. VUI LÒNG BÁO ADMIN!")


# ================= SELECT MỆNH GIÁ =================

class AmountSelect(discord.ui.Select):

    def __init__(self, telco, order_id):

        options = [
            discord.SelectOption(label="10.000 VND", value="10000"),
            discord.SelectOption(label="20.000 VND", value="20000"),
            discord.SelectOption(label="50.000 VND", value="50000"),
            discord.SelectOption(label="100.000 VND", value="100000"),
            discord.SelectOption(label="200.000 VND", value="200000"),
            discord.SelectOption(label="500.000 VND", value="500000"),
        ]

        super().__init__(placeholder="💰 Chọn mệnh giá", options=options)

        self.telco = telco
        self.order_id = order_id

    async def callback(self, interaction: discord.Interaction):

        await interaction.response.send_modal(
            CardModal(self.telco, self.values[0], self.order_id)
        )


# ================= SELECT TELCO =================

class TelcoSelect(discord.ui.Select):

    def __init__(self, order_id):

        options = [
            discord.SelectOption(label="Viettel", value="VIETTEL"),
            discord.SelectOption(label="Mobifone", value="MOBIFONE"),
            discord.SelectOption(label="Vinaphone", value="VINAPHONE"),
            discord.SelectOption(label="Vietnamobile", value="VIETNAMOBILE"),
            discord.SelectOption(label="Garena", value="GARENA"),
            discord.SelectOption(label="Zing", value="ZING"),
        ]

        super().__init__(placeholder="📡 Chọn nhà mạng", options=options)

        self.order_id = order_id

    async def callback(self, interaction: discord.Interaction):

        view = discord.ui.View()
        view.add_item(AmountSelect(self.values[0], self.order_id))

        await interaction.response.send_message(
            "💰 **Vui lòng chọn mệnh giá thẻ**",
            view=view
        )


# ================= BUTTON VIEW =================

class OrderView(discord.ui.View):

    def __init__(self, order_id):
        super().__init__(timeout=None)
        self.order_id = order_id

    @discord.ui.button(label="💳 NẠP CARD", style=discord.ButtonStyle.green)
    async def napcard(self, interaction: discord.Interaction, button):

        view = discord.ui.View()
        view.add_item(TelcoSelect(self.order_id))

        await interaction.response.send_message(
            "📡 **Vui lòng chọn nhà mạng**",
            view=view
        )

    @discord.ui.button(label="❌ HỦY ĐƠN", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button):

        view = ConfirmCancelView()

        await interaction.response.send_message(
            "⚠️ **BẠN CÓ CHẮC HỦY ĐƠN CHỨ?**",
            view=view
        )


# ================= CONFIRM HỦY =================

class ConfirmCancelView(discord.ui.View):

    @discord.ui.button(label="CÓ", style=discord.ButtonStyle.red)
    async def yes(self, interaction: discord.Interaction, button):

        await interaction.response.send_message("🗑️ Đơn sẽ bị xóa sau 5 giây...")

        await asyncio.sleep(5)

        await interaction.channel.delete()

    @discord.ui.button(label="KHÔNG", style=discord.ButtonStyle.green)
    async def no(self, interaction: discord.Interaction, button):

        await interaction.response.send_message("✅ Tiếp tục thanh toán.")


# ================= DISCORD =================

@bot.command()
async def sellcard(ctx, amount: int, link: str):

    if not isinstance(ctx.channel, discord.Thread):
        await ctx.send("❌ Lệnh phải dùng trong forum")
        return

    product = ctx.channel.name
    order_id = random_code()

    username = ctx.author.name

    new_channel_name = f"❌{order_id}-{username}"

    await ctx.channel.edit(name=new_channel_name)

    embed = discord.Embed(
        title="📦 XÁC NHẬN THANH TOÁN",
        description=f"""
📦 **Tên hàng:** {product}

💰 **Số tiền:** {amount}

🧾 **Mã đơn:** {order_id}

⚠️ Lưu ý: Nạp đúng mệnh giá thẻ!
""",
        color=0xf1c40f
    )

    orders[order_id] = {
        "channel": ctx.channel.id,
        "product": product,
        "link": link
    }

    view = OrderView(order_id)

    await ctx.send(embed=embed, view=view)


# ================= RUN SERVER =================

def run_api():
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)


threading.Thread(target=run_api).start()

bot.run(TOKEN)
