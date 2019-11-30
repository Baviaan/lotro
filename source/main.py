#!/usr/bin/env python3

import asyncio
import datetime
import discord
from discord.ext import commands
import json
import logging
import pickle

from apply_handling import new_app
from channel_handling import get_channel
from dwarves import show_dwarves
from initialise import initialise
from raid_handling import raid_command, raid_update, Tier, Time
from reaction_handling import role_update
from role_handling import show_roles

logging.basicConfig(level=logging.INFO)

# If testing it will skip 10s delay.
launch_on_boot = False

# print version number.
version = "v3.0.0"
print("Running " + version)

# Get local timezone using mad hacks.
local_tz = str(datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo)
print("Default timezone: " + local_tz)

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
raid_leader_name = config['LEADER']

# change to immutable tuple
role_names = tuple(role_names)

# Get server timezone
server_tz = config['SERVER_TZ']

raids = []
# Load the saved raid posts from file.
try:
    with open('raids.pkl', 'rb') as f:
        raids = pickle.load(f)
except (OSError, IOError) as e:
    pass
print("We have the following raid data in memory.")
for raid in raids:
    print(raid)


def save(raids):
    with open('raids.pkl', 'wb') as f:
        pickle.dump(raids, f)
    print("Saved raids to file at: " + str(datetime.datetime.now()))


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

    strings=[]
    for period_name, period_seconds in periods:
        if seconds > period_seconds:
            period_value , seconds = divmod(seconds, period_seconds)
            has_s = 's' if period_value > 1 else ''
            strings.append("%s %s%s" % (period_value, period_name, has_s))

    return ", ".join(strings)

async def background_task():
    await bot.wait_until_ready()
    sleep_time = 300  # Run background task every five minutes.
    save_time = 24  # Save to file every two hours.
    expiry_time = datetime.timedelta(seconds=7200)  # Delete raids after 2 hours.
    notify_time = datetime.timedelta(seconds=sleep_time)
    counter = 0
    while not bot.is_closed():
        await asyncio.sleep(sleep_time)
        counter = counter + 1
        current_time = datetime.datetime.utcnow()  # Raid time is stored in UTC.
        # Copy the list to iterate over.
        for raid in raids[:]:
            if current_time > raid.time + expiry_time:
                # Find the raid post and delete it.
                channel = bot.get_channel(raid.channel_id)
                try:
                    post = await channel.fetch_message(raid.post_id)
                except discord.NotFound:
                    print("Raid post already deleted.")
                except discord.Forbidden:
                    print("We are missing required permissions to delete raid post.")
                except AttributeError:
                    print("Raid channel has been deleted.")
                else:
                    await post.delete()
                    print("Deleted old raid post.")
                finally:
                    raids.remove(raid)
                    print("Deleted old raid.")
            elif current_time < raid.time - notify_time and current_time >= raid.time - notify_time * 2:
                channel = bot.get_channel(raid.channel_id)
                try:
                    await channel.fetch_message(raid.post_id)
                except discord.NotFound:
                    print("Raid post already deleted.")
                    raids.remove(raid)
                    print("Deleted old raid.")
                except discord.Forbidden:
                    print("We are missing required permissions to see raid post.")
                except AttributeError:
                    print("Raid channel has been deleted.")
                    raids.remove(raid)
                    print("Deleted old raid.")
                else:
                    if raid.roster:
                        raid_start_msg = "Gondor calls for aid! "
                        for player in raid.assigned_players:
                            if player:
                                raid_start_msg = raid_start_msg + "<@{0}> ".format(player.id)
                        raid_start_msg = raid_start_msg + "will you answer the call? We are forming for the raid now."
                        await channel.send(raid_start_msg, delete_after=sleep_time * 2)
        if counter >= save_time:
            save(raids)  # Save raids to file.
            counter = 0  # Reset counter to 0.


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


@bot.event
async def on_reaction_add(reaction, user):
    # Check if the reaction is by the bot itself.
    if user == bot.user:
        return
        # Check if the reaction is to the role post.
    if reaction.message.id in role_post_ids:
        await role_update(reaction, user, role_names)


@bot.event
async def on_raw_reaction_add(payload):
    update = False
    guild = bot.get_guild(payload.guild_id)
    user = guild.get_member(payload.user_id)
    if user == bot.user:
        return
    for raid in raids:
        if payload.message_id == raid.post_id:
            update = await raid_update(bot, payload, raid, role_names, raid_leader_name, server_tz)
            emoji = payload.emoji
            channel = guild.get_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            await message.remove_reaction(emoji, user)
            break
    if update:
        save(raids)


@bot.event
async def on_reaction_remove(reaction, user):
    pass


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


@bot.command(aliases=['instance', 'r'])
async def raid(ctx, name, tier: Tier, *, time: Time(server_tz)):
    """Schedules a raid"""
    raid = await raid_command(ctx, name, tier, "All", time, role_names, server_tz)
    raids.append(raid)
    save(raids)


raid_brief = "Schedules a raid"
raid_description = "Schedules a raid. Day/timezone will default to today/{0} if not specified. " \
                   "You can use 'server' as timezone. Usage:".format(local_tz)
raid_example = "Examples:\n!raid Anvil 2 Friday 4pm server\n!raid throne t3 21:00"
raid.update(help=raid_example, brief=raid_brief, description=raid_description)


@bot.command()
async def anvil(ctx, *, time: Time(server_tz)):
    """Shortcut to schedule Anvil raid"""
    try:
        tier = await Tier().converter(ctx.channel.name)
    except commands.BadArgument:
        await ctx.send("Channel name does not specify tier.")
    else:
        if '1' in tier or '2' in tier:
            roster = False
        else:
            roster = True
        raid = await raid_command(ctx, "Anvil", tier, "All", time, role_names, server_tz, roster=roster)
        raids.append(raid)
        save(raids)


anvil_brief = "Shortcut to schedule an Anvil raid"
anvil_description = "Schedules a raid with name 'Anvil', tier from channel name and bosses 'All'. " \
                    "Day/timezone will default to today/{0} if not specified. You can use 'server' as timezone. " \
                    "Usage:".format(local_tz)
anvil_example = "Examples:\n!anvil Friday 4pm server\n!anvil 21:00 BST"
anvil.update(help=anvil_example, brief=anvil_brief, description=anvil_description)


@bot.command()
async def thrang(ctx, *, time: Time(server_tz)):
    """Shortcut to schedule Thrang run"""
    tier = 'T2'
    raid = await raid_command(ctx, "Boss from the Vaults", tier, "Thrang", time, role_names, server_tz)
    raids.append(raid)
    save(raids)


thrang_brief = "Shortcut to schedule a Thrang run"
thrang_description = "Schedules a raid with name 'Boss from the Vaults', tier 2 and boss 'Thrang'. " \
                     "Day/timezone will default to today/{0} if not specified. You can use 'server' as timezone. " \
                     "Usage: ".format(local_tz)
thrang_example = "Examples:\n!thrang Friday 4pm server\n!thrang 21:00 BST"
thrang.update(help=thrang_example, brief=thrang_brief, description=thrang_description)


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


bot.loop.create_task(background_task())
bot.run(token)

# Save raids if bot unexpectedly closes.
save(raids)
print("Shutting down.")
