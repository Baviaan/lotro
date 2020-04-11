from subprocess import Popen, PIPE
from discord.ext import commands


class Dev(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._last_member = None


    @commands.command()
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


    @commands.group()
    @commands.is_owner()
    async def git(self, ctx):
        ctx.git_cmd = ['git']

    @git.command()
    async def pull(self, ctx):
        ctx.git_cmd.append('pull')
        p = Popen(ctx.git_cmd, stdout=PIPE)
        await ctx.send(p.stdout.read().decode("utf-8"))


def setup(bot):
    bot.add_cog(Dev(bot))
    print("Loaded Dev Cog.")
