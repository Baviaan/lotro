from subprocess import Popen, PIPE
from discord.ext import commands
import datetime
import discord
import logging
import psutil

from database import delete, select
from utils import chunks

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class DevCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conn = bot.conn

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
        self.bot.version = version
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
        await ctx.send(_("**We are in the following {0} guilds:**\n").format(len(self.bot.guilds)))
        for chunk in chunks(self.bot.guilds, 40):
            msg = "\n".join("{0} ({1})".format(guild.name, guild.id) for guild in chunk)
            await ctx.send(msg)

    @commands.command(hidden=True)
    @commands.is_owner()
    async def cleanup(self, ctx):
        res = select(self.conn, 'Settings', ['guild_id', 'last_command'])
        current_time = datetime.datetime.now().timestamp()
        cutoff = 3600 * 24 * 90
        cutoff_time = current_time - cutoff
        active = 0
        inactive = 0
        removed = 0
        for row in res:
            guild_id = row[0]
            last_command = row[1]
            guild = self.bot.get_guild(guild_id)
            if guild:
                if last_command and last_command > cutoff_time:
                    active += 1
                else:
                    inactive += 1
            else:
                logger.info('We are no longer in {0}'.format(guild_id))
                delete(self.conn, 'Settings', ['guild_id'], [guild_id])
                removed += 1
        self.conn.commit()
        logger.info('Active guild count: {0}'.format(active))
        logger.info('Inactive guild count: {0}'.format(inactive))
        logger.info('Removed from guild count: {0}'.format(removed))
        await ctx.send('Active guild count: {0}'.format(active))
        await ctx.send('Inactive guild count: {0}'.format(inactive))
        await ctx.send('Removed from guild count: {0}'.format(removed))


def setup(bot):
    bot.add_cog(DevCog(bot))
    logger.info("Loaded Dev Cog.")
