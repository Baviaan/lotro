import asyncio
import discord

async def get_channel(guild,channel_name):
    # Gets the channel. Creates the channel if it does not exist.
    channel = discord.utils.get(guild.channels, name=channel_name)
    if channel is None:
        channel = await guild.create_text_channel(name=channel_name)
        await asyncio.sleep(0.5)
    return channel 
