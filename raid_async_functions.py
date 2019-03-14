import discord
import asyncio
from raid_string_functions import build_raid_message, build_raid_message_players, usr_str2time
from channel_functions import add_emoji_pin

async def parse_error(client,argument,value,channel):
    text = 'I did not understand the specified ' + argument + ': "{0}". Please try again.'.format(value)
    print(text)
    msg = await client.send_message(channel, text)
    await asyncio.sleep(20)
    await client.delete_message(msg)

async def create_raid(client,emojis,name,tier,boss,time,channel):
    raid = {
    'NAME': name,
    'TIER': tier,
    'BOSS': boss,
    'TIME': time,
    'AVAILABLE': {}
    }
    embed = build_raid_message(raid,'\u200b') # discord doesn't allow empty embeds
    post = await client.send_message(channel, embed=embed)
    # Add the class emojis and pin the post
    await add_emoji_pin(client,emojis,post)
    await client.add_reaction(post,'\u274C') # cancel emoji
    await client.add_reaction(post,'\u23F2') # timer emoji
    raid['POST'] = post
    return raid

async def update_raid_post(client,emojis,raid,reaction,user,is_raid_leader):
    # Takes the raid dictionary, a reaction and user as input.
    # Stores the new data and edits the raid message.
    channel = reaction.message.channel
    if reaction.emoji == '\u274C':
        raid['AVAILABLE'].pop(user.name, None)
    elif reaction.emoji == '\u23F2' and is_raid_leader:
        await client.send_message(channel,"Please specify the new raid time.")
        response = await client.wait_for_message(author=user,timeout=300)
        if response is None:
            return
        time = usr_str2time(response.content)
        if time is None:
            await parse_error(client,'time',response.content,channel)
            return
        raid['TIME'] = time
    elif not user.name in raid['AVAILABLE'] and reaction.emoji in emojis.values():
        raid['AVAILABLE'][user.name] = {}
        raid['AVAILABLE'][user.name]['CLASSES'] = {reaction.emoji}
        raid['AVAILABLE'][user.name]['DISPLAY_NAME'] = user.display_name
        print('Added ' + reaction.emoji.name + ' to ' + user.name)
    elif reaction.emoji in emojis.values():
        raid['AVAILABLE'][user.name]['CLASSES'] = raid['AVAILABLE'][user.name]['CLASSES'].union({reaction.emoji})
        print('Added ' + reaction.emoji.name + ' to ' + user.name)
    msg = build_raid_message_players(raid['AVAILABLE'])
    for partial_msg in msg:
        print(partial_msg)
    embed = build_raid_message(raid,msg)
    try:
        post = await client.edit_message(raid['POST'], embed=embed)
    except (discord.errors.HTTPException) as e:
        await client.send_message(channel,'I failed to process your request.')
    raid['POST'] = post
    return raid

async def add_message(client,channel,msg_id):
    found = False
    try:
        message = await client.get_message(channel,msg_id)
    except discord.errors.NotFound:
        pass
    else:
        client.messages.append(message)
        found = True
        print("Added raid post back to cache!")
    return found
