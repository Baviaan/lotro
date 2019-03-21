import discord
import asyncio

# Delete the last n messages from the channel.
# 100 is discord API limit.
async def clear_channel(client,channel,number):
    async for msg in client.logs_from(channel, limit = number):
        await client.delete_message(msg)

async def add_emoji_pin(client,emojis,post):
    # adds the class emojis to a post and pins the post
    for value in emojis.values():
        await client.add_reaction(post,value)
        await asyncio.sleep(0.3)
    await client.pin_message(post)

# Gets the channel from server and creates it if it does not exist.
async def get_channel(client,server,name):
    channel = discord.utils.get(server.channels, name=name)
    if channel is None:
        channel = await client.create_channel(server, name, type=discord.ChannelType.text)
    return channel
