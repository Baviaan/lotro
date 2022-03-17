# You can edit this file to add custom bot commands
# without creating conflicts

import discord
import logging

from discord.ext import commands

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class CustomCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(CustomCog(bot))
    logger.info("Loaded Custom Cog.")
