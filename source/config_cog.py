import datetime
import discord
import logging
import requests

from discord.ext import commands
from discord.utils import find

from database import upsert

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ConfigCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def prefix(self, ctx, prefix):
        """Sets the command prefix to be used in this guild."""
        conn = self.bot.conn
        if not ctx.author.guild_permissions.administrator:
            await ctx.send(_("You must be an admin to change the command prefix."))
            return
        res = upsert(conn, 'Settings', ['prefix'], [prefix], ['guild_id'], [ctx.guild.id])
        if res:
            conn.commit()
            self.bot.prefixes[ctx.guild.id] = prefix
            await ctx.send(_("Command prefix set to `{0}`.").format(prefix))
        else:
            await ctx.send(_("An error occurred."))
        return

    @staticmethod
    def td_format(td_object):
        seconds = int(td_object.total_seconds())
        periods = [
            ('year', 60*60*24*365),
            ('month', 60*60*24*30),
            ('day', 60*60*24),
            ('hour', 60*60),
            ('minute', 60),
            ('second', 1)
        ]

        strings = []
        for period_name, period_seconds in periods:
            if seconds > period_seconds:
                period_value, seconds = divmod(seconds, period_seconds)
                has_s = 's' if period_value > 1 else ''
                strings.append("%s %s%s" % (period_value, period_name, has_s))

        return ", ".join(strings)

    @commands.command()
    async def about(self, ctx):
        """Shows info about the bot."""
        dev = "Baviaan#4862"
        repo = "https://github.com/Baviaan/lotro"
        server = "https://discord.gg/dGcBzPN"
        app_info = await self.bot.application_info()
        host = app_info.owner.name
        uptime = datetime.datetime.utcnow() - self.bot.launch_time
        uptime = self.td_format(uptime)

        invite_link = "https://discord.com/api/oauth2/authorize?client_id={0}&permissions=268724304&scope=bot%20applications.commands".format(self.bot.user.id)
        donate_link = "https://www.paypal.com/donate?hosted_button_id=WWPCUJVJPMT7W"
        releases = repo + "/releases/latest"
        r = requests.get(releases, allow_redirects=False)
        if r.ok:
            try:
                location = r.headers['location']
            except KeyError:
                latest_version = "N/A"
            else:
                (x, y, latest_version) = location.rpartition('/')
        else:
            latest_version = "N/A"

        title = "{0}".format(self.bot.user)
        about = [
                _("A bot for scheduling raids!"),
                _("**Developer:** {0}").format(dev),
                _("**[Source code]({0})**").format(repo),
                _("**[Support server]({0})**").format(server),
                _("**[Invite me!]({0})**").format(invite_link),
                _("**[Donate]({0})**").format(donate_link),
                "",
                _("**Hosted by:** {0}").format(host),
                _("**Default command prefix:** {0}").format(self.bot.default_prefix),
                _("**Uptime:** {0}.").format(uptime),
                "",
                _("**Using version:** {0}").format(self.bot.version),
                _("**Latest version:** {0}").format(latest_version)
                ]

        content = "\n".join(about)
        embed = discord.Embed(title=title, colour=discord.Colour(0x3498db), description=content)
        await ctx.send(embed=embed)

    @commands.command()
    async def privacy(self, ctx):
        """ Information on data collection. """
        msg = _("**PII:**\n"
                "When you sign up for a raid the bot stores your discord id, discord nickname and the class(es) you "
                "sign up with. This information is automatically deleted 2 hours after the scheduled raid time or "
                "immediately when you cancel your sign up.\n"
                "If you set a default timezone for yourself, the bot will store your timezone along with your discord "
                "id such that it can parse times provided in your commands in your preferred timezone. "
                "You can delete this information with the command `{0}timezone delete`.").format(ctx.prefix)
        await ctx.send(msg)
        return

    @staticmethod
    def welcome_msg(guild_name, prefix):
        msg = _("Greetings {0}! I am confined to Orthanc and here to spend my days doing your raid admin.\n\n"
                "You will most likely want to use the `{1}rem` and `{1}ad` commands. Examples:\n"
                "`{1}rem t2 Friday 8pm`\n"
                "`{1}ad t3 26 July 1pm`\n"
                "Type `{1}help` to get an overview of all commands "
                "and for example `{1}help timezone` for help changing your time zone settings.\n\n"
                "Please consider restricting my access to only the channels I need to see. "
                "Both to protect your privacy and to reduce my computational burden: "
                "I process every message I can see to check if it contains a command."
                ).format(guild_name, prefix)
        return msg

    @commands.command()
    async def welcome(self, ctx):
        """ Resend the welcome message. """
        msg = self.welcome_msg(ctx.guild.name, ctx.prefix)
        await ctx.send(msg)
        return

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        logger.info("We have joined {0}.".format(guild))
        channels = guild.text_channels
        channel = find(lambda x: x.name == 'welcome', channels)
        if not channel or not channel.permissions_for(guild.me).send_messages:
            channel = find(lambda x: x.name == 'general', channels)
        # Otherwise pick the first channel the bot can send a message in.
        if not channel or not channel.permissions_for(guild.me).send_messages:
            for ch in channels:
                if ch.permissions_for(guild.me):
                    channel = ch
                    break
        if channel and channel.permissions_for(guild.me).send_messages:
            msg = self.welcome_msg(guild.name, self.bot.default_prefix)
            await channel.send(msg)


def setup(bot):
    bot.add_cog(ConfigCog(bot))
    logger.info("Loaded Config Cog.")
