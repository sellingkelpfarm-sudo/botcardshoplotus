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

user_cooldown = {}
user_fail_count = {}
user_block_until = {}

buy_cooldown = {}

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
                print("API RAW:", text)
                return {"status": "0"}

            return data


# ================= CALLBACK =================

@app.api_route("/callback", methods=["GET", "POST"])
async def callback(request: Request):

    try:
        if request.method == "POST":
            data = await request.json()
        else:
            data = dict(request.query_params)
    except:
        data = dict(request.query_params)

    print("CALLBACK:", data)

    request_id = data.get("request_id")
    status = str(data.get("status", "0"))
    amount = data.get("amount", "0")

    # ===== FIX CHÍNH Ở ĐÂY =====
    real_value = int(data.get("amount", 0))

    fee = float(data.get("fee", 0))
    receive = int(data.get("received", 0))

    if request_id in orders:

        order = orders[request_id]

        channel = bot.get_channel(order["channel"])
        log_channel = bot.get_channel(LOG_CHANNEL_ID)

        if not channel:
            return {"ok": True}

        order_amount = int(order["amount"])

        if log_channel:

            log_embed = discord.Embed(
                title="📥 THẺ NẠP MỚI",
                color=0x3498db
            )

            log_embed.add_field(name="Trạng thái", value="Thẻ đúng" if status == "1" else status, inline=True)
            log_embed.add_field(name="Mã nạp", value=order.get("code", "N/A"), inline=True)
            log_embed.add_field(name="Serial", value=order.get("serial", "N/A"), inline=True)

            log_embed.add_field(name="Mạng", value=order.get("telco", "N/A"), inline=True)
            log_embed.add_field(name="Tổng gửi", value=f"{order_amount:,}", inline=True)
            log_embed.add_field(name="Tổng thực", value=f"{real_value:,}", inline=True)

            log_embed.add_field(name="Phí", value=f"{fee}%", inline=True)
            log_embed.add_field(name="Nhận", value=f"{receive:,}", inline=True)
            log_embed.add_field(name="Mã Đơn", value=request_id, inline=False)

            log_embed.set_footer(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            await log_channel.send(embed=log_embed)

        if status == "1" and real_value == order_amount:

            user_id = order.get("user_id")
            if user_id and user_ticket_count.get(user_id, 0) > 0:
                user_ticket_count[user_id] -= 1

            embed = discord.Embed(
                title="🎉 THANH TOÁN THÀNH CÔNG",
                description=f"""
📦 **Tên hàng:** {order['product']}

💰 **Số tiền:** {int(amount):,} VND

🧾 **Mã đơn:** {request_id}

🔗 **Link tải:** {order['link']}

❤️ Cảm ơn vì đã tin tưởng sử dụng dịch vụ!
""",
                color=0x2ecc71
            )

            await channel.send(embed=embed)

        elif status == "1" and real_value != order_amount:

            await channel.send(
                f"⚠️ Thẻ đúng nhưng **sai mệnh giá**\n"
                f"📥 Thẻ: {real_value:,} VND\n"
                f"🛒 Đơn yêu cầu: {order_amount:,} VND\n"
                f"❌ Không hoàn tiền."
            )

        elif status == "2":
            await channel.send("⚠️ Sai mệnh giá thẻ")

        elif status == "3":
            await channel.send("❌ Thẻ đã qua sử dụng hoặc không hợp lệ")

        elif status == "99":
            await channel.send("⏳ Thẻ đang được xử lý...")

    return {"ok": True}


@bot.event
async def on_ready():
    print(f"Bot online: {bot.user}")
