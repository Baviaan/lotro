#!/usr/bin/env python3

import asyncio
import discord
import json
import datetime
import dateparser
import re

from collections import OrderedDict

testing = True

if not testing:
    # On boot the pi launches the bot faster than it gets internet access.
    # Avoid all resulting host not found errors
    print('Waiting for system to fully boot')
    time.sleep(10)
    print('Continuing')

client = discord.Client()
version = "v1.2.0"

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
raids = list()

# Delete the last n messages from the channel.
# 100 is discord API limit.
async def clear_channel(channel,number):
    async for msg in client.logs_from(channel, limit = number):
        await client.delete_message(msg)

async def add_emoji_pin(post):
    # adds the class emojis to a post and pins the post
    for key, value in emojis.items():
        await client.add_reaction(post,value)
    await client.pin_message(post)

# Cleans up the channel, adds the initial post, adds reactions and pins the post.
async def prepare_channel(channel):
    await clear_channel(channel,100)

    global role_post
    message_content = 'Please mute this bot command channel or lose your sanity like me.\n\nReact to this post with each class you want to sign up for or click \u274C to remove all your class roles.\n\n*Further commands that can be used in this channel*:\n`!roles` Shows which class roles you currently have.\n`!dwarves` Shows a list of the 13 dwarves in the Anvil raid with their associated skills. (Work in progress.)'
    role_post = await client.send_message(channel, message_content)
    await add_emoji_pin(role_post)
    await client.add_reaction(role_post,'\u274C')

async def add_role(reaction,user):
    # Check if the reaction emoji matches any of our class emojis.
    for key,value in emojis.items():
        if reaction.emoji == value:
            # Add user to the class role.
            await client.add_roles(user, class_roles[key])
            # Send confirmation message.
            await client.send_message(reaction.message.channel, 'Added {0} to @{1}.'.format(user.mention,class_roles[key]))
    # Check if the reaction emoji is the cancel emoji
    if reaction.emoji == '\u274C':
        # Send a message because this will take 5s.
        await client.send_message(reaction.message.channel, 'Removing...')
        # Remove the user from all class roles.
        for key,value in class_roles.items():
            await client.remove_roles(user, value)
            # Discord rate limits requests; drops requests if too fast.
            await asyncio.sleep(0.5)
        # Send confirmation message.
        await client.send_message(reaction.message.channel, 'Removed {0} from all class roles.'.format(user.mention))

async def remove_role(reaction,user):
    # Check if the reaction emoji matches any of our class emojis.
    for key,value in emojis.items():
        if reaction.emoji == value:
            # Remove user from the class role.
            await client.remove_roles(user, class_roles[key])
            # Send confirmation message.
            await client.send_message(reaction.message.channel, 'Removed {0} from @{1}.'.format(user.mention,class_roles[key]))

# Checks which class roles the user has and sends these to the class roles channel.
async def show_class_roles(user):
    send = '{0} has the following class roles: '.format(user.mention)
    has_class_role = False
    # Build string to send
    for key,value in class_roles.items():
        if value in user.roles:
            send = send + value.name + ', '
            has_class_role = True
    # leet formatting skills
    send = send[:-2]
    send = send + '.'
    if has_class_role:
        await client.send_message(command_channel,send)
    else:
        await client.send_message(command_channel,'{0} does not have any class roles assigned.'.format(user.mention))

async def dwarves(channel):
        ingor = '**Ingór I the Cruel**: "How much more can your mortal form take?" - Applies 1 stack of incoming healing debuff.\n'
        oiko2 = '**Óiko II Rill-Seeker**: "I seek the mithril stream." - Ice line\n'
        dobruz = '**Dóbruz IV the Unheeding**: "You look like a weakling."/"I challenge you." - Picks random target; requires force taunt.\n'
        mozun = '**Mozun III Wyrmbane**: "I will not abide a worm to live." - Summons worm.\n'
        kuzek = '**Kúzek Squint-Eye**: TBD - Stand behind him in close range to avoid stun.\n'
        luvek = '**Lúvek I the Rueful**: TBD - +100% melee damage and crit chance.\n'
        oiko = '**Óiko I the Bellower**: TBD - TBD \n'
        kamluz = '**Kamluz II Stoneface**: TBD - TBD \n'
        dobruz2 = '**Dóbruz II Stark-heart**: "The Zhelruka clan is mine to protect." - Allies take -50% incoming damage, must be interrupted.\n'
        brantokh2 = '**Brántokh II the Sunderer**: "Cower before the might of the Zhelruka."/"I will bring this mountain down." - 20m AoE.\n'
        brunek = '**Brúnek I Clovenbow**: "Taste my axes!" - DoT on random person until interrupted.\n'
        rurek = '**Rúrek VI the Shamed**: "What have I done?"/"I have failed my people." - Bubble on dwarf.\n'
        brantokh = '**Brántokh I Cracktooth**: "Want to know why they call me cracktooth?" - AoE swipe (low damage).'
        text = ingor+oiko2+dobruz+mozun+kuzek+luvek+oiko+kamluz+dobruz2+brantokh2+brunek+rurek+brantokh
        await client.send_message(channel,text)

# Process commands for class role channel
async def command(message):
    # Clear the posts in the channel.
    if message.content.startswith('!clear'):
        # Check if user has sufficient permissions for this command
        if message.author.server_permissions.administrator or message.author.id == ownerid:
            # Reset the channel
            await prepare_channel(message.channel)
    # Return class roles for the user.
    elif message.content.startswith('!roles'):
        await show_class_roles(message.author)
    elif message.content.startswith('!dwarves'):
        await dwarves(message.channel)

def usr_str2time(time_string):
    if 'server' in time_string:
        #strip off server (time) and return as US Eastern time
        time_string = time_string.partition('server')[0]
        time = dateparser.parse(time_string, settings={'PREFER_DATES_FROM': 'future','TIMEZONE': 'US/Eastern', 'RETURN_AS_TIMEZONE_AWARE': True})
    else:
        time = dateparser.parse(time_string, settings={'PREFER_DATES_FROM': 'future'})
    return time

def build_raid_message(raid,text):
    embed = discord.Embed(title='{0} T{1} at {2}'.format(raid['NAME'],raid['TIER'],raid['TIME']), colour = discord.Colour(0x3498db), description='Bosses: {0}'.format(raid['BOSS']))
    embed.add_field(name='The following {0} players are available:'.format(len(raid['AVAILABLE'])),value=text)
    return embed

def build_raid_message_players(available):
    msg = ''
    for user,value in available.items():
        msg = msg + value['DISPLAY_NAME'] + ' '
        for emoji in value['CLASSES']:
            msg = msg + str(emoji)
        msg = msg + '\n'
    return msg

async def update_raid_post(raid,reaction,user):
    if not user.name in raid['AVAILABLE']:
        raid['AVAILABLE'][user.name] = {}
        raid['AVAILABLE'][user.name]['CLASSES'] = {reaction.emoji}
        raid['AVAILABLE'][user.name]['DISPLAY_NAME'] = user.display_name
    else:
        raid['AVAILABLE'][user.name]['CLASSES'] = raid['AVAILABLE'][user.name]['CLASSES'].union({reaction.emoji})
    msg = build_raid_message_players(raid['AVAILABLE'])
    embed = build_raid_message(raid,msg)
    post = await client.edit_message(raid['POST'], embed=embed)
    raid['POST'] = post
    return raid

# Process commands for the raid channel
async def raid_command(message):
    if message.content.startswith('!raid'):
        arguments = message.content.split(" ",4)
        if len(arguments) != 5:
            await client.send_message(message.channel, 'Usage: !raid <name> <tier> <bosses> <time>\nExamples:\n`!raid Anvil 2 all Friday 4pm server`\n`!raid anvil t3 2-4 21:00`\nDay/timezone will default to today/UTC if not specified.')
            return
        time = usr_str2time(arguments[4])
        if time is None:
            msg = await client.send_message(message.channel, 'I did not understand the specified time. Please try again.')
            await asyncio.sleep(20)
            await client.delete_message(msg)
            return
        tier = re.search(r'\d+',arguments[2]) # Filter out non-numbers
        raid = {
        'NAME': arguments[1].capitalize(),
        'TIER': tier.group(), # Get the string from the match object
        'BOSS': arguments[3],
        'TIME': time,
        'AVAILABLE': {}
        }
        embed = build_raid_message(raid,'\u200b')
        post = await client.send_message(message.channel, embed=embed) # Should format output
        await add_emoji_pin(post)
        raid['POST'] = post
        raids.append(raid)

async def bid_five(message):
    # I wonder what unexpected words this is going to trigger on
    trigger = ['bid','offer','COD','selling','buying']
    if any(word in message.content.lower() for word in trigger):
        await client.send_message(message.channel,'Isengard bids five!')

@client.event
async def on_ready():
    print('We have logged in as {0.user}'.format(client))
    await client.change_presence(game=discord.Game(name=version))

    server = client.get_server(id=serverid)
    print('Welcome to {0}'.format(server))

    global class_roles
    global emojis
    global command_channel
    global raid_channel

    # Get the custom emojis.
    all_emojis = list(client.get_all_emojis())

    # Initialise class roles and create roles if they do not exist yet.
    for key, value in role_names.items():
        class_role = discord.utils.get(server.roles, name=value)
        if class_role is None:
            class_role = await client.create_role(server, name=value, mentionable=True)
        class_roles[key] = class_role
    # Initialise the class emojis in the emoji dictionary.
    # Assumes class emoji name is equal to class role name.
    # Quadratic runtime is poor performance for this. // Should rewrite
    for e in all_emojis:
        for key, value in role_names.items():
            if e.name == value:
                emojis[key] = e

    # Get the channels that will be used to issue commands by users.
    # Creates the channel if it does not yet exist.
    command_channel = discord.utils.get(server.channels, name='saruman')
    if command_channel is None:
        command_channel = await client.create_channel(server, 'saruman', type=discord.ChannelType.text)
    raid_channel = discord.utils.get(server.channels, name='raids')
    if raid_channel is None:
        raid_channel = await client.create_channel(server, 'raids', type=discord.ChannelType.text)

    # Wait a bit to give Discord time to create the channel before we start using it.
    await asyncio.sleep(1)
    await prepare_channel(command_channel)

@client.event
async def on_reaction_add(reaction,user):
    global raids
    # Check if the reaction isn't made by the bot.
    if user == client.user:
        return
    # Check if the reaction is to the bot's role post.
    if reaction.message.id == role_post.id:
        await add_role(reaction,user)
    # Check if the reaction is to the bot's raid posts.
    for raid in raids:
        if reaction.message.id == raid['POST'].id:
            raid = await update_raid_post(raid,reaction,user)

@client.event
async def on_reaction_remove(reaction,user):
    # Check if the reaction isn't made by the bot.
    if user == client.user:
        return
    # Check if the reaction is to the bot's role post.
    if reaction.message.id == role_post.id:
        await remove_role(reaction,user)
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
    elif message.channel == raid_channel:
        await raid_command(message)

    # Saruman has the last word!
    await bid_five(message)

client.run(token)
