import asyncio
import discord
import json
import logging

from discord.ext import commands

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class RoleCog(commands.Cog):
    # Load config file.
    with open('config.json', 'r') as f:
        config = json.load(f)

    # Specify names for class roles.
    # These will be automatically created on the server if they do not exist.
    role_names = config['CLASSES']
    # change to immutable tuple
    role_names = tuple(role_names)

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def roles(self, ctx):
        """Shows the class roles you have and lets you remove them."""
        # Sends each role in roles_names the user has.
        author = ctx.author
        msg = _("{0} currently has the following roles: ").format(author.mention)
        has_role = False
        # Build string to send.
        for role_name in self.role_names:
            if role_name in [role.name for role in author.roles]:
                msg = msg + role_name + ", "
                has_role = True
        msg = msg[:-2]
        msg = msg + ".\nClick \u274C to delete your roles."
        if not has_role:
            msg = _("{0} does not have any roles assigned.").format(author.mention)
        message = await ctx.send(msg)
        if has_role:
            await message.add_reaction("\u274C")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) == "\u274C"
        try:
            await self.bot.wait_for('reaction_add', check=check, timeout=60)
        except asyncio.TimeoutError:
            pass
        else:
            for role in author.roles:
                if role.name in self.role_names:
                    await author.remove_roles(role)
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
    logger.info("Loaded Dev Cog.")