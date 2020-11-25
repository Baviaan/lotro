import discord
import logging

from datetime import datetime, timedelta
from discord.ext import commands

from database import add_setting, create_connection, remove_setting, select_one, select_raids
from time_cog import TimeCog

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class CalendarCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        conn = create_connection('raid_db')
        if conn:
            logger.info("CalendarCog connected to raid database.")
        else:
            logger.error("CalendarCog could not create database connection!")
        self.conn = conn

    def cog_unload(self):
        self.conn.close()

    @commands.command()
    async def calendar(self, ctx):
        try:
            await ctx.message.delete()
        except discord.Forbidden as e:
            logger.warning(e)
        embed = self.calendar_embed(ctx.guild.id)
        msg = await ctx.send(embed=embed)
        ids = "{chn_id}/{msg_id}".format(chn_id=ctx.channel.id, msg_id=msg.id)
        res = add_setting(self.conn, 'calendar', ctx.guild.id, ids)
        if res:
            self.conn.commit()
            await ctx.send(_("The Calendar will be updated in this channel."), delete_after=20)
        else:
            await ctx.send(_("An error occurred."))
        return

    async def update_calendar(self, guild_id):
        res = select_one(self.conn, 'Settings', 'calendar', guild_id, 'guild_id')
        if not res:
            return
        result = res.split("/")
        chn_id = int(result[0])
        msg_id = int(result[1])
        chn = self.bot.get_channel(chn_id)
        try:
            msg = await chn.fetch_message(msg_id)
        except (AttributeError, discord.NotFound):
            logger.warning("Calendar post not found.")
            res = remove_setting(self.conn, 'calendar', guild_id)
            self.conn.commit()
            return
        embed = self.calendar_embed(guild_id)
        await msg.edit(embed=embed)
        await chn.send(_("A new run has been posted!"))


    def calendar_embed(self, guild_id):
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
                guild=guild_id, channel=raid[0], msg=raid[1], name=raid[2], tier=raid[3])
            embed.add_field(name=time_string, value=msg, inline=False)
        time = datetime.utcnow()
        embed.set_footer(text=_("Last updated"))
        embed.timestamp = time
        return embed


def setup(bot):
    bot.add_cog(CalendarCog(bot))
    logger.info("Loaded Calendar Cog.")
