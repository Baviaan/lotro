import asyncio
import discord

async def show_roles(channel,author,role_names):
    # Prints each role in roles_names the user has.
    msg = "{0} has the following roles: ".format(author.mention)
    has_role = False
    # Build string to send.
    for role_name in role_names:
        if role_name in [role.name for role in author.roles]:
            msg = msg + role_name + ", "
            has_role = True
    msg = msg[:-2]
    msg = msg + "."
    if not has_role:
        msg = "{0} does not have any roles assigned.".format(author.mention)
    print(msg)
    await channel.send(msg)

async def add_role(channel,author,role_name):
    # Adds role to author.
    role = await get_role(channel.guild,role_name)
    await author.add_roles(role)
    await channel.send("Added {0} to @{1}".format(author.mention,role.name))

async def remove_role(channel,author,role_name):
    # Removes role from author.
    role = await get_role(channel.guild,role_name)
    await author.remove_roles(role)
    await channel.send("Removed {0} from @{1}".format(author.mention,role.name))

async def get_role(guild,role_name):
    # Gets the role. Creates the role if it does not exist.
    role = discord.utils.get(guild.roles, name=role_name)
    if role is None:
        role = await guild.create_role(mentionable=True, name=role_name)
        await asyncio.sleep(0.5)
    return role
