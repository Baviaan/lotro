import asyncio
import discord

async def initialise(guild,channel,role_names):
    await channel.purge(limit=60)
    msg = 'Please mute this bot command channel or lose your sanity like me.\n\nReact to this post with each class role you want to sign up for or click \u274C to remove all your class roles.\n\n*Further commands that can be used in this channel*:\n`!roles` Shows which class roles you currently have.\n`!dwarves` Shows a list of the 13 dwarves in the Anvil raid with their associated skills. (Work in progress.)\n`!apply` to apply to {0}.'.format(guild.name)
    role_post = await channel.send(msg)
    # Get the custom class emojis.
    emojis = await get_role_emojis(guild,role_names)
    # Add cancel emoji.
    emojis.append("\u274C")
    await add_emojis(emojis,role_post)
    await asyncio.sleep(0.25)
    await role_post.pin()
    return role_post

async def add_emojis(emojis,message):
    await asyncio.sleep(0.25)
    for emoji in emojis:
        await message.add_reaction(emoji)
        await asyncio.sleep(0.25)

async def get_role_emojis(guild,role_names):
    emojis = []
    for emoji in guild.emojis:
        if emoji.name in role_names:
            emojis.append(emoji)
    return emojis
