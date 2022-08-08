import datetime
import discord
import logging
import requests

from discord import app_commands
from discord.ext import commands
from discord.utils import find

from database import upsert

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Keep PyCharm happy.
_ = _


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
        dev = "Reesey275#4253"
        repo = "https://github.com/theangrygamershowproductions/lotro"
        code = "uqDv4RmAQ6"
        server = "https://discord.gg/" + code
        app_info = await self.bot.application_info()
        try:
            host = app_info.team.name
        except AttributeError:
            host = app_info.owner.name
        uptime = datetime.datetime.utcnow() - self.bot.launch_time
        uptime = self.td_format(uptime)

        invite_link = "https://discord.com/api/oauth2/authorize?client_id={0}&permissions=268462080&scope=bot" \
                      "%20applications.commands".format(self.bot.user.id)
        donate_link = "https://www.paypal.com/donate?hosted_button_id=YRATYZHS4G8T2"
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
            _("A Discord bot for scheduling LoTRO raids!"),
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
        msg = _("Greetings {0}! I am confined to Mordor and here to spend my days doing your raid admin. \n"
                "You can quickly schedule a raid with the `/rem` and `/ad` commands.\n" 
                "Examples: \n"
                "`/rem t2 2022-08-08 18:00:00` \n"
                "`/ad t3 2022-08-08 18:00:00` \n"
                "Use `/custom` to schedule a custom raid or meetup. \n"
                "With `/calendar` you can get an (automatically updated) overview of all scheduled raids. \n"
                "It is recommended you use a separate discord channel to display the calendar in. \n"
                "Use `/time_zones` to change the default time settings and \n"
                "you can designate a raid leader role with `/leader`, which allows non-admins to edit raids. \n"
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

    @app_commands.command(name=_("about"), description=_("Show information about this bot."))
    @app_commands.guild_only()
    async def about_respond(self, interaction: discord.Interaction):
        about = await self.about_embed()
        await interaction.response.send_message(embed=about)

    @app_commands.command(name=_("welcome"), description=_("Resend the welcome message."))
    @app_commands.guild_only()
    async def welcome_respond(self, interaction: discord.Interaction):
        welcome = self.welcome_msg(interaction.guild.name)
        await interaction.response.send_message(welcome)

    @app_commands.command(name=_("privacy"), description=_("Show information on data collection."))
    @app_commands.guild_only()
    async def privacy_respond(self, interaction: discord.Interaction):
        privacy = _("**Summary:**\n"
                    "When you sign up for a raid the bot stores the time, your discord id, "
                    "discord nickname and the (classes) you sign up with. This information is"
                    "automatically deleted 2 hours after the scheduled raid time or immediately"
                    "when you cancel your sign up. If you set a default time zone for yourself, "
                    "the bot will additionally store your time zone along with your discord id "
                    "such that it can parse times provided in your commands in your preferred time zone. \n"
                    "**Please find the full privacy policy here:** \n"
                    "https://github.com/theangrygamershowproductions/lotro#privacy-policy")
        await interaction.response.send_message(privacy)


async def setup(bot):
    await bot.add_cog(ConfigCog(bot))
    logger.info("Loaded Config Cog.")
