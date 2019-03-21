#!/usr/bin/env python3

import asyncio
import discord
import json
import time
import datetime
import re
import pickle
import logging

from collections import OrderedDict
from text_functions import dwarves, bid_five
from channel_functions import get_channel, add_emoji_pin
from role_functions import prepare_channel, add_role, remove_role, show_class_roles
from raid_string_functions import usr_str2time
from raid_async_functions import parse_error, create_raid, update_raid_post, add_message
from apply_functions import kin_app

logging.basicConfig(level=logging.INFO)

testing = False
if not testing:
    # On boot the pi launches the bot faster than it gets internet access.
    # Avoid all resulting host not found errors
    print('Waiting for system to fully boot')
    time.sleep(10)
    print('Continuing')

client = discord.Client()
version = "v1.3.3"
print("Running " + version)

# Load the config file
with open('config.json', 'r') as f:
    config = json.load(f)

token = config['DEFAULT']['BOT_TOKEN']
serverid = config['DISCORD']['SERVER_ID']
ownerid = config['DISCORD']['OWNER_ID']

# These class roles will be automatically created if they don't exist on the server.
role_names = {
    'BEORNING': 'Beorning',
    'BURGLAR': 'Burglar',
    'CAPTAIN': 'Captain',
    'CHAMPION': 'Champion',
    'GUARDIAN': 'Guardian',
    'HUNTER': 'Hunter',
    'LOREMASTER': 'Loremaster',
    'MINSTREL': 'Minstrel',
    'RUNEKEEPER': 'Runekeeper',
    'WARDEN': 'Warden'
}

# The pi runs Python 3.5 where dictionaries aren't ordered yet.
# Maintain consistency with Python 3.6
class_roles = OrderedDict()
emojis = OrderedDict()

# List that will contain the raid posts
try:
    with open('raids.pkl','rb') as f:
        raids = pickle.load(f)
except (OSError,IOError) as e:
    raids = list()

print('We have the following raid data in memory:')
print(raids)

async def background_task():
    await client.wait_until_ready()
    await asyncio.sleep(10) # Wait while on_ready() initialises variables
    while not client.is_closed:
        current_time = datetime.datetime.now()
        delta_time = datetime.timedelta(seconds=7200)
        # Copy the list to iterate over.
        for raid in raids[:]:
            if raid['TIME'] + delta_time < current_time:
                await client.delete_message(raid['POST'])
                raids.remove(raid)
        # Save raids to file
        with open('raids.pkl', 'wb') as f:
            pickle.dump(raids, f)
        await asyncio.sleep(3600)

# Process commands for command channel
async def command(message):
    global role_post
    # Clear the posts in the channel.
    if message.content.startswith('!clear'):
        # Check if user has sufficient permissions for this command
        if message.author.server_permissions.administrator or message.author.id == ownerid:
            # Reset the channel
            role_post = await prepare_channel(client,emojis,message.channel)
    # Return class roles for the user.
    elif message.content.startswith('!roles'):
        await show_class_roles(client,class_roles,message)
    elif message.content.startswith('!dwarves'):
        await dwarves(client,message.channel)
    elif message.content.startswith('!apply'):
        await kin_app(client,message,apply_channel)

# Process commands for the raid channel
async def raid_command(message):
    global raids
    # Takes a message as input and if successfully parsed sends a raid message and stores the raid dictionary.
    if message.content.startswith('!raid'):
        arguments = message.content.split(" ",4)
        if len(arguments) < 5:
            await client.send_message(message.channel, 'Usage: !raid <name> <tier> <bosses> <time>\nExamples:\n`!raid Anvil 2 all Friday 4pm server`\n`!raid anvil t3 2-4 21:00`\nDay/timezone will default to today/UTC if not specified.\nUse `!anvil` to quickly set up an Anvil raid.')
            return
        time = usr_str2time(arguments[4])
        if time is None:
            await parse_error(client,'time',arguments[4],message.channel)
            return
        tier = re.search(r'\d+',arguments[2]) # Filter out non-numbers
        if tier is None:
            await parse_error(client,'tier',arguments[2],message.channel)
            return
        raid = await create_raid(client,emojis,arguments[1].capitalize(),tier.group(),arguments[3].capitalize(),time,message.channel)
        raids.append(raid)
    if message.content.startswith('!anvil'):
        arguments = message.content.split(" ",2)
        if len(arguments) < 3:
            await client.send_message(message.channel, 'Usage: !anvil <tier> <time>\nExample:\n`!anvil 2 Friday 4pm server`\nDay/timezone will default to today/UTC if not specified.\nUse `!raid` to specify a custom raid.')
            return
        time = usr_str2time(arguments[2])
        if time is None:
            await parse_error(client,'time',arguments[2],message.channel)
            return
        tier = re.search(r'\d+',arguments[1]) # Filter out non-numbers
        if tier is None:
            await parse_error(client,'tier',arguments[1],message.channel)
            return
        raid = await create_raid(client,emojis,'Anvil',tier.group(),'All',time,message.channel)
        raids.append(raid)

@client.event
async def on_ready():
    print('We have logged in as {0.user}'.format(client))
    await client.change_presence(game=discord.Game(name=version))

    server = client.get_server(id=serverid)
    print('Welcome to {0}'.format(server))
    print('The time is:')
    print(datetime.datetime.now())

    global class_roles
    global raid_leader_role
    global emojis
    global role_post
    global command_channel
    global raid_channel
    global raid3_channel
    global lobby_channel
    global apply_channel

    # Initialise class roles and create roles if they do not exist yet.
    for key, value in role_names.items():
        class_role = discord.utils.get(server.roles, name=value)
        if class_role is None:
            class_role = await client.create_role(server, name=value, mentionable=True)
        class_roles[key] = class_role

    # Initialise raid leader role.
    raid_leader_role = discord.utils.get(server.roles, name="Raid Leader")
    if raid_leader_role is None:
        raid_leader_role = await client.create_role(server, name="Raid Leader")

    # Initialise the class emojis in the emoji dictionary.
    # Assumes class emoji name is equal to class role name.
    # Quadratic runtime is poor performance for this. // Should rewrite
    for emoji in server.emojis:
        for key, value in role_names.items():
            if emoji.name == value:
                emojis[key] = emoji

    # Get the channels that will be used to issue commands by users.
    # Creates the channel if it does not yet exist.
    command_channel = await get_channel(client,server,'saruman')
    raid_channel = await get_channel(client,server,'raids')
    raid3_channel = await get_channel(client,server,'t3raid')
    lobby_channel = await get_channel(client,server,'lobby')
    apply_channel = await get_channel(client,server,'applications')

    # Wait a bit to give Discord time to create the channel before we start using it.
    await asyncio.sleep(0.5)
    role_post = await prepare_channel(client,emojis,command_channel)

    # Add old raid messages to cache.
    for raid in raids[:]:
        found = await add_message(client,raid_channel,raid['POST'].id)
        if not found:
            found = await add_message(client,raid3_channel,raid['POST'].id)
        if not found:
            found = await add_message(client,lobby_channel,raid['POST'].id)
        if not found:
            raids.remove(raid)
            print('Removed raid from raids as the raid post {0} no longer exists.'.format(raid['POST'].id))

@client.event
async def on_reaction_add(reaction,user):
    global raids
    # Check if the reaction isn't made by the bot.
    if user == client.user:
        return
    # Check if the reaction is to the bot's role post.
    if reaction.message.id == role_post.id:
        await add_role(client,emojis,class_roles,reaction,user)
    # Check if the reaction is to the bot's raid posts.
    for raid in raids:
        if reaction.message.id == raid['POST'].id:
            if raid_leader_role in user.roles:
                is_raid_leader = True
            else:
                is_raid_leader = False
            print(is_raid_leader)
            raid = await update_raid_post(client,emojis,raid,reaction,user,is_raid_leader)

@client.event
async def on_reaction_remove(reaction,user):
    # Check if the reaction isn't made by the bot.
    if user == client.user:
        return
    # Check if the reaction is to the bot's role post.
    if reaction.message.id == role_post.id:
        await remove_role(client,emojis,class_roles,reaction,user)
    # Check if the reaction is to the bot's raid posts.

@client.event
async def on_message(message):
    # Check if the message isn't sent by the bot.
    if message.author == client.user:
        return
    # Check if message is sent in command channel
    if message.channel == command_channel:
        await command(message)
    # Check if message is sent in raid channel
    elif message.channel == raid_channel or message.channel == lobby_channel or message.channel == raid3_channel:
        await raid_command(message)

    if message.content.startswith("!delete"):
        if message.author.server_permissions.administrator or message.author.id == ownerid:
            command = message.content.split(" ",2)
            msg_id = command[1]
            msg = await client.get_message(message.channel,msg_id)
            await client.delete_message(msg)

    if message.content.startswith("!save"):
        with open('raids.pkl', 'wb') as f:
            pickle.dump(raids, f)
        await client.send_message(message.channel,"Saved the raids to file.")

    # Saruman has the last word!
    await bid_five(client,message)

client.loop.create_task(background_task())
client.run(token)

# Save raids if client closes
with open('raids.pkl', 'wb') as f:
    pickle.dump(raids, f)
