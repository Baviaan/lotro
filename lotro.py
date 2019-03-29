#!/usr/bin/env python3

import asyncio
import datetime
import discord # Requires rewrite branch
from discord.ext import commands
import json
import logging
import pickle

from apply_handling import new_app
from channel_handling import get_channel
from dwarves import show_dwarves
from initialise import initialise
from raid_handling import raid_command, raid_update, Tier, Time
from raid import Raid
from reaction_handling import role_update
from role_handling import show_roles

logging.basicConfig(level=logging.INFO)

# If testing it will skip 10s delay.
launch_on_boot = False

# print version number.
version = "v2.1.1"
print("Running " + version)

# Load config file.
with open('config.json','r') as f:
    config = json.load(f)

# Assign specified config values.
token = config['DEFAULT']['BOT_TOKEN']
serverid = config['DISCORD']['SERVER_ID']

# Specify names for channels the bot will respond in.
# These will be automatically created on the server if they do not exist.
channel_names = {
    'BOT': 'saruman',
    'PUBLIC': 'lobby',
    'RAID': 'raids',
    'RAIDS2': 't3raid',
    'APPLY': 'applications'
}

# Specify names for class roles.
# These will be automatically created on the server if they do not exist.
role_names = ("Beorning","Burglar","Captain","Champion","Guardian","Hunter","Loremaster","Minstrel","Runekeeper","Warden")
raid_leader_name = "Raid Leader"

raids = []
# Load the saved raid posts from file.
try:
    with open('raids.pkl','rb') as f:
        raids = pickle.load(f)
except (OSError,IOError) as e:
    pass
print("We have the following raid data in memory.")
for raid in raids:
    print(raid)

def save(raids):
    with open('raids.pkl', 'wb') as f:
        pickle.dump(raids, f)
    print("Saved raids to file at:")
    print(datetime.datetime.now())

if launch_on_boot:
    # On boot the system launches the bot fater than it gains internet access.
    # Avoid all the resulting errors.
    print("Waiting 10s for system to gain internet access.")
    asyncio.sleep(10)
print("Continuing...")

bot = commands.Bot(command_prefix='!',case_insensitive=True)

async def background_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(3600)
        current_time = datetime.datetime.now()
        delta_time = datetime.timedelta(seconds=7200)
        # Copy the list to iterate over.
        for raid in raids[:]:
            if raid.time + delta_time < current_time:
                # Look for the channel in which the raid post is.
                for guild in bot.guilds:
                    for channel in guild.text_channels:
                        try:
                            post = await channel.fetch_message(raid.post_id)
                        except (discord.NotFound, discord.Forbidden):
                            continue
                        else:
                            await post.delete()
                            print("Deleted old raid post.")
                            break
                raids.remove(raid)
                print("Deleted old raid.")
        # Save raids to file
        save(raids)

@bot.event
async def on_ready():
    print("We have logged in as {0.user}".format(bot))
    await bot.change_presence(activity=discord.Game(name=version))
    guild = bot.get_guild(serverid)
    print('Welcome to {0}'.format(guild))
    print("The time is:")
    print(datetime.datetime.now())

    # Initialise the role post in the bot channel.
    bot_channel = await get_channel(guild,channel_names['BOT'])
    global role_post
    role_post = await initialise(guild,bot_channel,role_names)
    
@bot.event
async def on_reaction_add(reaction,user):
    # Check if the reaction is by the bot itself.
    if user == bot.user:
        return 
    # Check if the reaction is to the role post.
    if reaction.message.id == role_post.id:
        await role_update(reaction,user,role_names)

@bot.event
async def on_raw_reaction_add(payload):
    guild = bot.get_guild(payload.guild_id)
    update = False
    for raid in raids:
        if payload.message_id == raid.post_id:
            update = await raid_update(bot,payload,guild,raid,role_names,raid_leader_name)
            break
    if update:
        save(raids)

@bot.event
async def on_reaction_remove(reaction,user):
    pass

@bot.event
async def on_command_error(ctx,error):
    print("Command given: " + ctx.message.content)
    print(error)
    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send("Please use this command in a server.")
    else:
        await ctx.send(error,delete_after=10)

@bot.check
async def globally_block_dms(ctx):
    if ctx.guild is None:
        raise commands.NoPrivateMessage("No dm allowed!")
    else:
        return True

@bot.command()
async def roles(ctx):
    await show_roles(ctx.channel,ctx.author,role_names)

@bot.command()
async def dwarves(ctx):
    await show_dwarves(ctx.channel)

@bot.command()
async def apply(ctx):
    await new_app(bot,ctx.message,channel_names['APPLY'])

@bot.command()
async def raid(ctx,name,tier: Tier,boss,*,time: Time):
    raid = await raid_command(ctx,name,tier,boss,time,role_names)
    raids.append(raid)
    save(raids)

@bot.command()
async def anvil(ctx,tier: Tier,*,time: Time):
    raid = await raid_command(ctx,"Anvil",tier,"All",time,role_names)
    raids.append(raid)
    save(raids)

@bot.command()
@commands.is_owner()
async def delete(ctx,msg_id: int):
    msg = await ctx.channel.fetch_message(msg_id)
    await ctx.message.delete()
    await asyncio.sleep(0.25)
    await msg.delete()

@delete.error
async def delete_error(ctx,error):
    if isinstance(error, commands.NotOwner):
        ctx.send("You do not have permission to use this command.")

bot.loop.create_task(background_task())
bot.run(token)

# Save raids if bot unexpectedly closes.
save(raids)
print("Shutting down.")
