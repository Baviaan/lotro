from subprocess import Popen, PIPE
from discord.ext import commands
from discord.utils import find
import datetime
import discord
import json
import logging
import psutil

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class DevCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_member = None

        with open('config.json', 'r') as f:
            config = json.load(f)
            default_prefix = config['PREFIX']
        self.default_prefix = default_prefix

    @commands.command(hidden=True)
    @commands.is_owner()
    async def load(self, ctx, ext):
        ext = ext + "_cog"
        try:
            self.bot.load_extension(ext)
            await ctx.send(_('Extension loaded.'))
        except commands.ExtensionAlreadyLoaded:
            self.bot.reload_extension(ext)
            await ctx.send(_('Extension reloaded.'))
        except commands.ExtensionNotFound:
            await ctx.send(_('Extension not found.'))
        except commands.ExtensionError:
            await ctx.send(_('Extension failed to load.'))

    @commands.command(hidden=True)
    @commands.is_owner()
    async def version(self, ctx, version):
        await self.bot.change_presence(activity=discord.Game(name=version))

    @commands.group(hidden=True)
    @commands.is_owner()
    async def git(self, ctx):
        ctx.git_cmd = ['git']

    @git.command()
    async def pull(self, ctx):
        ctx.git_cmd.append('pull')
        p = Popen(ctx.git_cmd, stdout=PIPE)
        await ctx.send(p.stdout.read().decode("utf-8"))

    @commands.command(hidden=True)
    @commands.is_owner()
    async def stats(self, ctx):
        """Shows stats about the bot"""
        guild_count = len(self.bot.guilds)
        member_count = sum([guild.member_count for guild in self.bot.guilds])

        available_memory = psutil.virtual_memory().available
        bot_process = psutil.Process()
        process_memory = bot_process.memory_info().vms
        cpu = bot_process.cpu_times()
        cpu_time = cpu.system + cpu.user
        cpu_time = str(datetime.timedelta(seconds=cpu_time))

        data_sizes = {
            'B': 1,
            'KB': 1024,
            'MB': 1048576,
            'GB': 1073741824
        }
        for size, value in data_sizes.items():
            if (process_memory / value) > 1 < 1024:
                process_memory_str = "{} {}".format(
                    round(process_memory / value, 2), size)
            if (available_memory / value) > 1 < 1024:
                available_memory_str = "{} {}".format(
                    round(available_memory / value, 2), size)

        title = "Bot stats"
        about = [
            _("Resource usage:"),
            _("**CPU time:** {0}").format(cpu_time),
            _("**Memory:** {0}/{1}\n").format(process_memory_str, available_memory_str),
            _("**Servers:** {0}").format(guild_count),
            _("**Members:** {0}").format(member_count)
        ]
        content = "\n".join(about)
        embed = discord.Embed(title=title, colour=discord.Colour(0x3498db), description=content)
        await ctx.send(embed=embed)

    @commands.command(hidden=True)
    @commands.is_owner()
    async def list(self, ctx):
        msg = "\n".join(guild.name for guild in self.bot.guilds)
        await ctx.send(_("**We are in the following {0} guilds:**\n").format(len(self.bot.guilds)) + msg)

    @commands.command()
    async def privacy(self, ctx):
        """ Information on data collection. """
        msg = _("**PII:**\n"
                "When you sign up for a raid the bot stores your discord id, discord nickname and the class(es) you "
                "sign up with. This information is automatically deleted 2 hours after the scheduled raid time or "
                "immediately when you cancel your sign up.\n"
                "If you set a default timezone for yourself, the bot will store your timezone along with your discord "
                "id such that it can parse times provided in your commands in your preferred timezone. "
                "You can delete this information with the command `!timezone delete`.")
        await ctx.send(msg)
        return

    @commands.command()
    async def welcome(self, ctx):
        """ Resend the welcome message. """
        msg = _("Greetings {0}! I am confined to Orthanc and here to spend my days doing your raid admin.\n\n"
                "You will most likely want to use the `{1}raid` command. "
                "Type `{1}help raid` to get started.\n"
                "There are more commands that will let you modify the default settings "
                "or let you schedule raids faster: e.g. the `{1}rem` alias.\n"
                "Type `{1}help` to get an overview of all commands.\n\n"
                "Please consider restricting my access to only the channels I need to see. "
                "Both to protect your privacy and to reduce my computational burden: "
                "I process every message I can see to check if it contains a command."
                ).format(ctx.guild.name, ctx.prefix)
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
            msg = _("Greetings {0}! I am confined to Orthanc and here to spend my days doing your raid admin.\n\n"
                    "You will most likely want to use the `{1}raid` command. "
                    "Type `{1}help raid` to get started.\n"
                    "There are more commands that will let you modify the default settings "
                    "or let you schedule raids faster: e.g. the `{1}rem` alias.\n"
                    "Type `{1}help` to get an overview of all commands.\n\n"
                    "Please consider restricting my access to only the channels I need to see. "
                    "Both to protect your privacy and to reduce my computational burden: "
                    "I process every message I can see to check if it contains a command."
                    ).format(guild.name, self.default_prefix)
            await channel.send(msg)


def setup(bot):
    bot.add_cog(DevCog(bot))
    logger.info("Loaded Dev Cog.")
