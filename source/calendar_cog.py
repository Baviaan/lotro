import discord
import logging

from datetime import datetime
from discord.ext import commands

from database import select_one, select_order, upsert

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class CalendarCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def is_raid_leader(self, ctx):
        conn = self.bot.conn
        if ctx.author.guild_permissions.administrator:
            return True
        raid_leader_id = select_one(conn, 'Settings', ['raid_leader'], ['guild_id'], [ctx.guild.id])
        if raid_leader_id in [role.id for role in ctx.author.roles]:
            return True
        error_msg = _("You do not have permission to change the settings.")
        await ctx.send(error_msg, delete_after=15)
        return False

    @commands.command()
    async def calendar(self, ctx):
        """ Sets the channel to post the calendar in. """
        if not await self.is_raid_leader(ctx):
            return
        conn = self.bot.conn
        try:
            await ctx.message.delete()
        except discord.Forbidden as e:
            logger.info(e)
        embed = self.calendar_embed(ctx.guild.id)
        msg = await ctx.send(embed=embed)
        ids = "{0}/{1}".format(ctx.channel.id, msg.id)
        res = upsert(conn, 'Settings', ['calendar'], [ids], ['guild_id'], [ctx.guild.id])
        if res:
            conn.commit()
            await ctx.send(_("The Calendar will be updated in this channel."), delete_after=20)
        else:
            await ctx.send(_("An error occurred."))
        return

    async def update_calendar(self, guild_id, new_run=True):
        conn = self.bot.conn
        res = select_one(conn, 'Settings', ['calendar'], ['guild_id'], [guild_id])
        if not res:
            return
        result = res.split("/")
        chn_id = int(result[0])
        msg_id = int(result[1])
        chn = self.bot.get_channel(chn_id)
        try:
            msg = chn.get_partial_message(msg_id)
        except (AttributeError, discord.NotFound):
            logger.warning("Calendar post not found for guild {0}.".format(guild_id))
            res = upsert(conn, 'Settings', ['calendar'], [None], ['guild_id'], [guild_id])
            if res:
                conn.commit()
            return

        embed = self.calendar_embed(guild_id)
        try:
            await msg.edit(embed=embed)
        except discord.HTTPException:
            logger.warning("Failed to update calendar for guild {0}.".format(guild_id))
            return
        except discord.Forbidden:
            logger.warning("Calendar access restricted for guild {0}.".format(guild_id))
            return
        if new_run:
            try:
                await chn.send(_("A new run has been posted!"), delete_after=3600)
            except discord.Forbidden:
                logger.warning("No write access to calendar channel for guild {0}.".format(guild_id))


    def calendar_embed(self, guild_id):
        time_cog = self.bot.get_cog('TimeCog')
        conn = self.bot.conn
        server_tz = time_cog.get_server_time(guild_id)
        raids = select_order(conn, 'Raids', ['channel_id', 'raid_id', 'name', 'tier', 'time'], 'time', ['guild_id'],
                             [guild_id])

        title = _("Scheduled runs:")
        desc = _("Time displayed in server time.\nClick the link to sign up!")
        embed = discord.Embed(title=title, description=desc, colour=discord.Colour(0x3498db))
        fmt_24hr = time_cog.get_24hr_fmt(guild_id)
        for raid in raids[:20]:
            timestamp = int(raid[4])
            time = datetime.utcfromtimestamp(timestamp)
            server_time = time_cog.local_time(time, server_tz)
            time_string = time_cog.calendar_time(server_time, fmt_24hr)
            msg = "[{name} {tier}](<https://discord.com/channels/{guild}/{channel}/{msg}>)\n".format(
                guild=guild_id, channel=raid[0], msg=raid[1], name=raid[2], tier=raid[3])
            embed.add_field(name=time_string, value=msg, inline=False)
        time = datetime.utcnow()
        embed.set_footer(text=_("Last updated"))
        embed.timestamp = time
        return embed


def setup(bot):
    bot.add_cog(CalendarCog(bot))
    logger.info("Loaded Calendar Cog.")
