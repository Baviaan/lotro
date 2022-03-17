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
        self.conn = self.bot.conn

    @staticmethod
    def td_format(td_object):
        seconds = int(td_object.total_seconds())
        periods = [
            ('year', 60 * 60 * 24 * 365),
            ('month', 60 * 60 * 24 * 30),
            ('day', 60 * 60 * 24),
            ('hour', 60 * 60),
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

    async def about_embed(self):
        dev = "Baviaan#4862"
        repo = "https://github.com/Baviaan/lotro"
        code = "dGcBzPN"
        server = "https://discord.gg/"+code
        app_info = await self.bot.application_info()
        try:
            host = app_info.team.name
        except AttributeError:
            host = app_info.owner.name
        uptime = datetime.datetime.utcnow() - self.bot.launch_time
        uptime = self.td_format(uptime)

        invite_link = "https://discord.com/api/oauth2/authorize?client_id={0}&permissions=268462080&scope=bot" \
                      "%20applications.commands".format(self.bot.user.id)
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
            _("**Uptime:** {0}.").format(uptime),
            "",
            _("**Using version:** {0}").format(self.bot.version),
            _("**Latest version:** {0}").format(latest_version)
        ]

        content = "\n".join(about)
        embed = discord.Embed(title=title, colour=discord.Colour(0x3498db), description=content)
        return embed

    @staticmethod
    def welcome_msg(guild_name):
        msg = _("Greetings {0}! I am confined to Orthanc and here to spend my days doing your raid admin.\n\n"
                "You can quickly schedule a raid with the `/rem` and `/ad` commands. Examples:\n"
                "`/rem t2 Friday 8pm`\n"
                "`/ad t3 26 July 1pm`\n"
                "Use `/custom` to schedule a custom raid or meetup.\n\n"
                "With `/calendar` you can get an (automatically updated) overview of all scheduled raids. "
                "It is recommended you use a separate discord channel to display the calendar in.\n"
                "Use `/time_zones` to change the default time settings and "
                "you can designate a raid leader role with `/leader`, which allows non-admins to edit raids."
                ).format(guild_name)
        return msg

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        logger.info("We have joined {0}.".format(guild))
        timestamp = int(datetime.datetime.now().timestamp())
        upsert(self.conn, 'Settings', ['last_command'], [timestamp], ['guild_id'], [guild.id])
        self.conn.commit()
        channels = guild.text_channels
        channel = find(lambda x: x.name == 'welcome', channels)
        if not channel or not channel.permissions_for(guild.me).send_messages:
            channel = find(lambda x: x.name == 'general', channels)
        # Otherwise pick the first channel the bot can send a message in.
        if not channel or not channel.permissions_for(guild.me).send_messages:
            for ch in channels:
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break
        if channel and channel.permissions_for(guild.me).send_messages:
            msg = self.welcome_msg(guild.name)
            await channel.send(msg)


async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
    logger.info("Loaded Config Cog.")
