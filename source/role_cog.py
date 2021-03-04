import asyncio
import discord
import logging

from discord.ext import commands

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class RoleCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def roles(self, ctx):
        """Shows the class roles you have and lets you remove them."""
        # Sends each role in roles_names the user has.
        author = ctx.author
        partial_msg = [
                _("{0} currently has the following roles: ").format(author.mention),
                ", ".join([role.name for role in author.roles if role.name in self.bot.role_names]),
                ".\n",
                _("Click \u274C to delete your roles.")
              ]
        if partial_msg[1]:
            msg = "".join(partial_msg)
        else:
            msg = _("{0} does not have any roles assigned.").format(author.mention)
        message = await ctx.send(msg)
        if partial_msg[1]:
            await message.add_reaction("\u274C")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) == "\u274C"
        try:
            await self.bot.wait_for('reaction_add', check=check, timeout=60)
        except asyncio.TimeoutError:
            pass
        else:
            try:
                await author.remove_roles(*[role for role in author.roles if role.name in self.bot.role_names])
            except discord.Forbidden:
                await ctx.send(_("Missing permissions to manage the class roles!"), delete_after=30)
            else:
                await ctx.send(_("Removed all class roles for {0}.").format(author.mention), delete_after=30)
        await message.delete()


async def get_role(guild, role_name):
    # Gets the role. Creates the role if it does not exist.
    role = discord.utils.get(guild.roles, name=role_name)
    if role is None:
        role = await guild.create_role(mentionable=True, name=role_name)
        await asyncio.sleep(0.5)
    return role


def setup(bot):
    bot.add_cog(RoleCog(bot))
    logger.info("Loaded Role Cog.")
