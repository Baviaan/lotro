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

    @commands.command()
    async def pl(self, ctx,*,  message):
        await self.bot.change_presence(activity=discord.Game(name=message))

    @commands.command()
    async def wa(self, ctx,*,  message):
        await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=message))
      
    @commands.command()
    async def li(self, ctx,*,  message):
        await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=message))
        


def setup(bot):
    bot.add_cog(CustomCog(bot))
    logger.info("Loaded Custom Cog.")
    
client = commands.Bot(command_prefix = '!')

