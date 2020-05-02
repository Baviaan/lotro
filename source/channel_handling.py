import asyncio
import discord
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


async def get_channel(guild, channel_name):
    # Gets the channel. Creates the channel if it does not exist.
    channel = discord.utils.get(guild.channels, name=channel_name)
    if channel is None:
        try:
            channel = await guild.create_text_channel(name=channel_name)
        except discord.Forbidden:
            logger.warning("Missing permissions for {0} to create a channel.".format(guild.name))
        await asyncio.sleep(0.5)
    return channel 
