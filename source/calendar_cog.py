import discord
import logging

from datetime import datetime, timedelta
from discord.ext import commands

from database import create_connection, select_raids
from time_cog import TimeCog

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class CalendarCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        conn = create_connection('raid_db')
        if conn:
            logger.info("RaidCog connected to raid database.")
        else:
            logger.error("RaidCog could not create database connection!")
        self.conn = conn

    def cog_unload(self):
        self.conn.close()

    @commands.command()
    async def calendar(self, ctx):
        guild_id = ctx.guild.id
        server_tz = TimeCog.get_server_time(guild_id)
        raids = select_raids(self.conn, 'channel_id, raid_id, name, tier, time', guild_id)

        title = _("Scheduled runs:")
        desc = _("For the upcoming week (in server time).\nClick the link to sign up!")
        embed = discord.Embed(title=title, description=desc, colour=discord.Colour(0x3498db))
        for raid in raids:
            timestamp = int(raid[4])
            time = datetime.utcfromtimestamp(timestamp)
            if datetime.utcnow() + timedelta(days=7) < time:  # Only show upcoming week
                break
            server_time = TimeCog.local_time(time, server_tz)
            time_string = TimeCog.calendar_time(server_time)
            msg = "[{name} {tier}](<https://discord.com/channels/{guild}/{channel}/{msg}>)\n".format(
                guild=ctx.guild.id, channel=raid[0], msg=raid[1], name=raid[2], tier=raid[3])
            embed.add_field(name=time_string, value=msg, inline=False)
        await ctx.send(embed=embed)
        try:
            await ctx.message.delete()
        except discord.Forbidden as e:
            logger.warning(e)


def setup(bot):
    bot.add_cog(CalendarCog(bot))
    logger.info("Loaded Calendar Cog.")
