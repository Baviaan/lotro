import asyncio

from role_handling import add_role, remove_role


async def role_update(reaction, author, role_names):
    channel = reaction.message.channel
    if reaction.emoji == "\u274C":
        for role_name in role_names:
            if role_name in [role.name for role in author.roles]:
                await remove_role(channel, author, role_name)
                await asyncio.sleep(0.5)
        return
    try:
        emoji_name = reaction.emoji.name
    except AttributeError:
        print(reaction.emoji + _(" is not a class!"))
    else:
        if emoji_name in role_names:
            await add_role(channel, author, emoji_name)
