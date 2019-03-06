import discord
import asyncio

async def parse_error(client,argument,value,channel):
        text = 'I did not understand the specified ' + argument + ': "{0}". Please try again.'.format(value)
        msg = await client.send_message(channel, text)
        await asyncio.sleep(20)
        await client.delete_message(msg)

async def create_raid(client,name,tier,boss,time,channel):
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
    await client.add_reaction(post,'\u274C')
    raid['POST'] = post
    return raid

async def update_raid_post(client,raid,reaction,user):
    # Takes the raid dictionary, a reaction and user as input.
    # Stores the new data and edits the raid message.
    if reaction.emoji == '\u274C':
        raid['AVAILABLE'].pop(user.name, None)
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
        await client.send_message(reaction.message.channel,'I failed to process your request.')
    raid['POST'] = post
    return raid
