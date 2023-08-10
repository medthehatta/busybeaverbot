import asyncio
from contextlib import suppress
import json
from uuid import uuid1
import random
import re
import subprocess

from cytoolz import partition_all
from cytoolz import valmap

import discord
from discord.ext import commands


with open("config.json", "r") as f:
    config = json.load(f)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!"),
    intents=intents,
)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


def role_index(guild):
    roles = {}
    for member in guild.members:
        for role in member.roles:
            roles[role.name] = roles.get(role.name, []) + [member]
    return valmap(set, roles)


async def send_long(obj, text):
    for fragment in ("".join(x) for x in partition_all(1800, text)):
        await obj.send(fragment) 


def mention_list(objects):
    return " ".join(obj.mention for obj in objects)


@bot.command()
async def find(ctx: commands.Context, *users: discord.User):
    guild = bot.get_guild(int(config["guild"]))
    roles = role_index(guild)

    desired_users = set(users)

    (kind, found, meta) = match_users(roles, desired_users)

    if kind == "exact":
        await send_long(ctx, f"{found}")
    elif kind == "superset":
        await send_long(ctx, f"'{found}' matches, but also includes {mention_list(meta)}")
    elif kind == "supersets":
        await send_long(ctx, f"The following groups match:")
        for (superset, m) in meta:
            await send_long(
                ctx,
                f"'{superset}' matches, but also includes {mention_list(m['extra'])}",
            )
    elif kind == "need_add":
        await send_long(
            ctx,
            f"'{found}' nearly matches, but is missing {mention_list(meta)}",
        )
    elif kind == "need_adds":
        await send_long(ctx, f"The following groups nearly match:")
        for (group, m) in meta:
            await send_long(
                ctx,
                f"'{group}' nearly matches, but is missing {mention_list(m['missing'])}",
            )
    else:
        await send_long(ctx, f"No matching group found, create a new one.")


@bot.command()
async def create(ctx: commands.Context, name: str, *users: discord.Member):
    await assert_mod(ctx)

    guild = bot.get_guild(int(config["guild"]))
    result = await create_group(guild, name)
    await admit_users_to_role(result["role"], users)


def match_users(roles, users):
    analyzed = {
        role: {
            "missing": users.difference(role_users),
            "extra": role_users.difference(users),
        }
        for (role, role_users) in roles.items()
        if role != "@everyone"
    }

    matches = [
        (role, x) for (role, x) in analyzed.items()
        if not x["missing"] and not x["extra"]
    ]
    need_add = [
        (role, x) for (role, x) in analyzed.items()
        if x["missing"] and not x["extra"]
    ]
    different = [
        (role, x) for (role, x) in analyzed.items()
        if x["missing"] and x["extra"]
    ]
    superset = [
        (role, x) for (role, x) in analyzed.items()
        if not x["missing"] and x["extra"]
    ]

    if matches:
        return ("exact", matches[0][0], set([]))
    elif superset:
        if len(superset) == 1:
            return ("superset", superset[0][0], superset[0][1]["extra"])
        else:
            return ("supersets", [s[0] for s in superset], superset)
    elif need_add:
        if len(need_add) == 1:
            return ("need_add", need_add[0][0], need_add[0][1]["missing"])
        else:
            return ("need_adds", [s[0] for s in need_add], need_add)
    else:
        return ("none", [], different)


async def create_voice_channel_and_role_from_template(guild, new_name: str):
    template = discord.utils.get(
        guild.voice_channels,
        name=config["template_voice_channel"],
    )

    new_channel = await template.clone(name=new_name)
    role_color = discord.Color.from_rgb(
        random.randint(0, 255),
        random.randint(0, 255),
        random.randint(0, 255),
    )
    new_role = await guild.create_role(name=new_name, color=role_color)

    await new_channel.set_permissions(
        new_role,
        overwrite=discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
        ),
    )

    return {"channel": new_channel, "role": new_role}


async def create_group(guild, name: str):
    voice_template = discord.utils.get(
        guild.voice_channels,
        name=config["template_voice_channel"],
    )
    text_template = discord.utils.get(
        guild.channels,
        name=config["template_text_channel"],
    )

    voice_channel = await voice_template.clone(name=name)
    text_channel = await text_template.clone(name=name)
    role_color = discord.Color.from_rgb(
        random.randint(0, 255),
        random.randint(0, 255),
        random.randint(0, 255),
    )
    new_role = await guild.create_role(
        name=name,
        color=role_color,
        mentionable=True,
    )

    await voice_channel.set_permissions(
        new_role,
        overwrite=discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
        ),
    )
    await text_channel.set_permissions(
        new_role,
        overwrite=discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
        ),
    )

    return {"voice": voice_channel, "text": text_channel, "role": new_role}


async def admit_users_to_role(role: discord.Role, users: discord.Member):
    await asyncio.gather(*[user.add_roles(role) for user in users])


@bot.command()
async def invite(ctx: commands.Context, channel_name: str, *extra_users: discord.Member):
    await assert_mod(ctx)

    guild = bot.get_guild(int(config["guild"]))

    for channel in guild.channels:
        if isinstance(channel, discord.VoiceChannel):
            continue
        if channel.name == channel_name:
            text_channel = channel

    voice_channel = discord.utils.get(guild.voice_channels, name=channel_name)
    role = discord.utils.get(guild.roles, name=channel_name)

    await admit_users_to_role(role, extra_users)

    roles = role_index(guild)
    role_users = " ".join(user.mention for user in roles[channel_name])

    await text_channel.send(
        f":wave: Welcome {role_users}!  Please join {voice_channel.mention} "
        f"for voice chat and use this channel for text chat."
    )


async def assert_mod(ctx):
    guild = bot.get_guild(int(config["guild"]))
    mod_name = config["bot_admins"]
    mod_role = discord.utils.get(guild.roles, name=mod_name)
    is_mod = discord.utils.get(ctx.author.roles, id=mod_role.id)
    if not is_mod:
        await ctx.send(
            f"You don't have permission to do this, please ask a {mod_role.mention}"
        )
        raise


@bot.command()
async def archive(ctx: commands.Context, channel_name: str):
    await assert_mod(ctx)

    guild = bot.get_guild(int(config["guild"]))

    for channel in guild.channels:
        if isinstance(channel, discord.VoiceChannel):
            continue
        if channel.name == channel_name:
            text_channel = channel

    voice_channel = discord.utils.get(guild.voice_channels, name=channel_name)
    role = discord.utils.get(guild.roles, name=channel_name)

    archive_category = discord.utils.get(guild.channels, name=config["archive_category"])

    await text_channel.set_permissions(
        role,
        overwrite=discord.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
        ),
    )
    await text_channel.edit(category=archive_category)
    await voice_channel.delete()


@bot.command()
async def stop(ctx: commands.Context):
    await assert_mod(ctx)
    await ctx.send("Stopping...")
    await bot.close()
    exit()


@bot.command()
async def version(ctx: commands.Context):
    result = (
        subprocess.check_output(["git", "log", "--oneline", "HEAD~3.."])
        .decode("utf-8")
        .strip()
    )
    await ctx.send(result)


async def emit_bgg_url(message):
    if (matches := re.finditer(r'\[(.{,50}?)\]', message.content)):
        from scratch import bgg_query
        from scratch import _items
        for match in matches:
            name = match.group(1)
            items = _items(bgg_query(name))
            if items:
                item = items[0]
                url = f"https://boardgamegeek.com/{item['href'].lstrip('/')}"
                await message.channel.send(url)


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if "[" in message.content:
        await emit_bgg_url(message)

    else:
        await bot.process_commands(message)


if __name__ == "__main__":
    bot.run(config["token"])
