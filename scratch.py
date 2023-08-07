import json

import discord
from discord.ext import commands


import pydoc
pydoc.pager = pydoc.plainpager


intents = discord.Intents.default()
intents.message_content = True

with open("config.json", "r") as f:
    config = json.load(f)

bot = commands.Bot(command_prefix="!", intents=intents)
