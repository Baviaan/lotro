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
from dwarves import show_dwarves
from database import add_setting, create_connection, create_table, select_two_columns, remove_setting

logfile = 'raid_bot.log'
print("Writing to log at: " + logfile)
logging.basicConfig(filename=logfile, level=logging.WARNING, format='%(asctime)s %(levelname)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# If testing it will skip 10s delay.
launch_on_boot = False

# log version number.
version = "v3.7.1"
logger.info("Running " + version)

# Load config file.
with open('config.json', 'r') as f:
    config = json.load(f)

# Localization settings
language = config['LANGUAGE']
if language == 'fr':
    locale.setlocale(locale.LC_TIME, "fr_FR.UTF-8")
localization = gettext.translation('messages', localedir='locale', languages=[language], fallback=True)
if language == 'en' or hasattr(localization, '_catalog'):  # Technically 'en' has no file.
    logger.info("Using language file for '{0}'.".format(language))
else:
    logger.warning("Language file '{0}' not found. Defaulting to English.".format(language))
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

# Get default server timezone and default prefix
server_tz = config['SERVER_TZ']
default_prefix = config['PREFIX']


if launch_on_boot:
    # On boot the system launches the bot faster than it gains internet access.
    # Avoid all the resulting errors.
    logger.info("Waiting 10s for system to gain internet access.")
    asyncio.sleep(10)
    logger.info("Continuing...")

launch_time = datetime.datetime.utcnow()

conn = create_connection('raid_db')
if conn:
    logger.info("main connected to raid database.")
    create_table(conn, 'settings')
    results = select_two_columns(conn, 'guild_id', 'prefix', 'Settings')
    prefixes = dict(results)
else:
    logger.error("main could not create database connection!")


def prefix_manager(bot, message):
    """Returns a guild specific prefix if it has been set. Default prefix otherwise."""
    try:
        guild_id = message.guild.id
    except AttributeError:  # If the command is used in dm there is no guild attribute
        prefix = default_prefix
    else:
        prefix = prefixes.get(guild_id, default_prefix)
        if not prefix:
            prefix = default_prefix
    return commands.when_mentioned_or(prefix)(bot, message)


launch_time = datetime.datetime.utcnow()
bot = commands.Bot(command_prefix=prefix_manager, case_insensitive=True, guild_subscriptions=False,
                   fetch_offline_members=False)


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
    logger.info("We have logged in as {0}.".format(bot.user))
    if not bot.guilds:
        logger.error("The bot is not in any guilds. Shutting down.")
        await bot.close()
        return
    for guild in bot.guilds:
        logger.info('Welcome to {0}.'.format(guild))
    bot.load_extension('dev_cog')
    bot.load_extension('raid_cog')
    bot.load_extension('role_cog')
    bot.load_extension('time_cog')
    await bot.change_presence(activity=discord.Game(name=version))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send(_("Please use this command in a server."))
    else:
        await ctx.send(error, delete_after=10)
        if not isinstance(error, commands.CommandNotFound):
            logger.warning("Error for command: " + ctx.message.content)
            logger.warning(error)


@bot.check
async def globally_block_dms(ctx):
    if ctx.guild is None:
        raise commands.NoPrivateMessage("No dm allowed!")
    else:
        return True


@bot.command()
async def dwarves(ctx):
    """Shows abilities of dwarves in Anvil"""
    await show_dwarves(ctx.channel)


@bot.command(hidden=True)
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
            _("**Default command prefix:** {0}").format(default_prefix),
            _("**Uptime:** {0}.\n").format(uptime),
            _("**Using version:** {0}").format(version),
            _("**Latest version:** {0}").format(latest_version)
            ]
    content = "\n".join(about)
    embed = discord.Embed(title=title, colour=discord.Colour(0x3498db), description=content)
    await ctx.send(embed=embed)


@bot.command()
async def prefix(ctx, prefix):
    """Sets the command prefix to be used in this guild."""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send(_("You must be an admin to change the command prefix."))
        return
    delete = _("delete")
    reset = _("reset")
    default = _("default")
    if prefix in [delete, reset, default]:
        res = remove_setting(conn, 'prefix', ctx.guild.id)
        if res:
            conn.commit()
            prefixes[ctx.guild.id] = default_prefix
            await ctx.send(_("Command prefix reset to `{0}`.").format(default_prefix))
        else:
            await ctx.send(_("An error occurred."))
        return
    res = add_setting(conn, 'prefix', ctx.guild.id, prefix)
    if res:
        conn.commit()
        prefixes[ctx.guild.id] = prefix
        await ctx.send(_("Command prefix set to `{0}`.").format(prefix))
    else:
        await ctx.send(_("An error occurred."))
    return

bot.run(token)
logger.info("Shutting down.")
