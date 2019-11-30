#!/usr/bin/env python3

import asyncio
import datetime
import discord
from discord.ext import commands
import json
import logging

from apply_handling import new_app
from channel_handling import get_channel
from dwarves import show_dwarves
from initialise import initialise
from reaction_handling import role_update
from role_handling import show_roles

logging.basicConfig(level=logging.WARNING)

# If testing it will skip 10s delay.
launch_on_boot = False

# print version number.
version = "v3.0.0"
print("Running " + version)

# Load config file.
with open('config.json', 'r') as f:
    config = json.load(f)

# Assign specified config values.
token = config['BOT_TOKEN']

# Specify names for channels the bot will respond in.
# These will be automatically created on the server if they do not exist.
channel_names = config['CHANNELS']

# Specify names for class roles.
# These will be automatically created on the server if they do not exist.
role_names = config['CLASSES']
# change to immutable tuple
role_names = tuple(role_names)

# Get server timezone
server_tz = config['SERVER_TZ']


if launch_on_boot:
    # On boot the system launches the bot faster than it gains internet access.
    # Avoid all the resulting errors.
    print("Waiting 10s for system to gain internet access.")
    asyncio.sleep(10)
print("Continuing...")

launch_time = None
prefix = "!"
bot = commands.Bot(command_prefix=prefix, case_insensitive=True)


def td_format(td_object):
    seconds = int(td_object.total_seconds())
    periods = [
        ('year', 60*60*24*365),
        ('month', 60*60*24*30),
        ('day', 60*60*24),
        ('hour', 60*60),
        ('minute', 60),
        ('second', 1)
    ]

    strings = []
    for period_name, period_seconds in periods:
        if seconds > period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            has_s = 's' if period_value > 1 else ''
            strings.append("%s %s%s" % (period_value, period_name, has_s))

    return ", ".join(strings)


@bot.event
async def on_ready():
    print("We have logged in as {0.user}".format(bot))
    print("The time is:")
    print(datetime.datetime.now())
    await bot.change_presence(activity=discord.Game(name=version))
    for guild in bot.guilds:
        print('Welcome to {0}'.format(guild))

    global launch_time
    if not launch_time:
        launch_time = datetime.datetime.utcnow()

    global role_post_ids
    role_post_ids = []
    for guild in bot.guilds:
        # Initialise the role post in the bot channel.
        try:
            bot_channel = await get_channel(guild, channel_names['BOT'])
            role_post = await initialise(guild, bot_channel, role_names)
        except discord.Forbidden:
            print("Missing permissions for {0}".format(guild.name))
        else:
            role_post_ids.append(role_post.id)
    bot.load_extension('dev_cog')
    bot.load_extension('raid_cog')


@bot.event
async def on_reaction_add(reaction, user):
    # Check if the reaction is by the bot itself.
    if user == bot.user:
        return
    # Check if the reaction is to the role post.
    if reaction.message.id in role_post_ids:
        await role_update(reaction, user, role_names)


@bot.event
async def on_command_error(ctx, error):
    print("Command given: " + ctx.message.content)
    print(error)
    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send("Please use this command in a server.")
    else:
        await ctx.send(error, delete_after=10)


@bot.check
async def globally_block_dms(ctx):
    if ctx.guild is None:
        raise commands.NoPrivateMessage("No dm allowed!")
    else:
        return True


@bot.command()
async def uptime(ctx):
    """Shows the bot's uptime"""
    uptime = datetime.datetime.utcnow() - launch_time
    uptime_str = '**Uptime:** ' + td_format(uptime) + '.'
    await ctx.send(uptime_str)


@bot.command()
@commands.is_owner()
async def load(ctx, ext):
    try:
        bot.load_extension(ext)
        await ctx.send('Extension loaded.')
    except discord.ext.commands.ExtensionAlreadyLoaded:
        bot.reload_extension(ext)
        await ctx.send('Extension reloaded.')
    except discord.ext.commands.ExtensionNotFound:
        await ctx.send('Extension not found.')
    except discord.ext.commands.ExtensionError:
        await ctx.send('Extension failed to load.')


@bot.command()
async def roles(ctx):
    """Shows the class roles you have"""
    await show_roles(ctx.channel, ctx.author, role_names)


@bot.command()
async def dwarves(ctx):
    """Shows abilities of dwarves in Anvil"""
    await show_dwarves(ctx.channel)


@bot.command()
async def apply(ctx):
    """Apply to the kin"""
    await new_app(bot, ctx.message, channel_names['APPLY'])


@bot.command()
@commands.is_owner()
async def delete(ctx, msg_id: int):
    """Deletes a message"""
    msg = await ctx.channel.fetch_message(msg_id)
    await ctx.message.delete()
    await asyncio.sleep(0.25)
    await msg.delete()

delete.update(hidden=True)


@delete.error
async def delete_error(ctx, error):
    if isinstance(error, commands.NotOwner):
        ctx.send("You do not have permission to use this command.")


bot.run(token)
print("Shutting down.")
