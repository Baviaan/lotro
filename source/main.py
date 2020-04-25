#!/usr/bin/env python3

import asyncio
import datetime
import discord
from discord.ext import commands
import gettext
import json
import locale
import logging
import requests

from apply_handling import new_app
from channel_handling import get_channel
from dwarves import show_dwarves
from initialise import initialise
from role_handling import show_roles, role_update

logging.basicConfig(level=logging.WARNING)

# If testing it will skip 10s delay.
launch_on_boot = False

# print version number.
version = "v3.4.0"
print("Running " + version)

# Load config file.
with open('config.json', 'r') as f:
    config = json.load(f)

# Localization settings
language = config['LANGUAGE']
if language == 'fr':
    locale.setlocale(locale.LC_TIME, "fr_FR.UTF-8")
localization = gettext.translation('messages', localedir='locale', languages=[language], fallback=True)
if language == 'en' or hasattr(localization, '_catalog'): # Technically 'en' has no file.
    print("Using language file for '{0}'.".format(language))
else:
    print("Language file '{0}' not found. Defaulting to English.".format(language))
localization.install()

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

launch_time = datetime.datetime.utcnow()
prefix = config['PREFIX']
bot = commands.Bot(command_prefix=prefix, case_insensitive=True)
bot.load_extension('dev_cog')
bot.load_extension('raid_cog')


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

    global role_post_ids
    role_post_ids = []
    for guild in bot.guilds:
        # Initialise the role post in the bot channel.
        try:
            bot_channel = await get_channel(guild, channel_names['BOT'])
            role_post = await initialise(guild, bot_channel, prefix, role_names)
        except discord.Forbidden:
            print("Missing permissions for {0}".format(guild.name))
        else:
            role_post_ids.append(role_post.id)


@bot.event
async def on_reaction_add(reaction, user):
    # Check if the reaction is by the bot itself.
    if user == bot.user:
        return
    # Check if the reaction is to the role post.
    message = reaction.message
    if message.id in role_post_ids:
        await role_update(message.channel, user, reaction.emoji, role_names)


@bot.event
async def on_command_error(ctx, error):
    print("Command given: " + ctx.message.content)
    print(error)
    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send(_("Please use this command in a server."))
    else:
        await ctx.send(error, delete_after=10)


@bot.check
async def globally_block_dms(ctx):
    if ctx.guild is None:
        raise commands.NoPrivateMessage("No dm allowed!")
    else:
        return True


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
async def about(ctx):
    """Shows info about the bot"""
    bot = ctx.bot
    dev = "Baviaan#4862"
    repo = "https://github.com/Baviaan/lotro"
    server = "https://discord.gg/dGcBzPN"
    app_info = await bot.application_info()
    host = app_info.owner.name
    uptime = datetime.datetime.utcnow() - launch_time
    uptime = td_format(uptime)

    releases = repo + "/releases/latest"
    r = requests.get(releases, allow_redirects=False)
    if r.ok:
        try:
            location = r.headers['location']
        except KeyError:
            latest_version = "N/A"
        else:
            (x, y, latest_version) = location.rpartition('/')
    else:
        latest_version = "N/A"
    title = "{0}".format(bot.user)
    about = [
            _("A bot for scheduling raids!"),
            _("**Developer:** {0}").format(dev),
            _("**[Source code]({0})**").format(repo),
            _("**[Support server]({0})**\n").format(server),
            _("**Hosted by:** {0}").format(host),
            _("**Command prefix:** {0}").format(prefix),
            _("**Uptime:** {0}.\n").format(uptime),
            _("**Using version:** {0}").format(version),
            _("**Latest version:** {0}").format(latest_version)
            ]
    content = "\n".join(about)
    embed = discord.Embed(title=title, colour=discord.Colour(0x3498db), description=content)
    await ctx.send(embed=embed)


bot.run(token)
print("Shutting down.")
