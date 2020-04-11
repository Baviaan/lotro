import asyncio


async def initialise(guild, channel, prefix, role_names):
    await channel.purge(limit=60)
    cancel_emoji = '\u274C'
    msgs = [_("Please mute this bot command channel or lose your sanity like me.\n"),
           _("React to this post with each class role you want to sign up for or click {0} to remove all your class roles.\n".format(cancel_emoji)),
           _("*Further commands that can be used in this channel*:"),
           _("`{0}roles` Shows which class roles you currently have.").format(prefix),
           _("`{0}dwarves` Shows a list of the 13 dwarves in the Anvil raid with their associated skills. (Work in progress.)").format(prefix),
           _("`{0}apply` to apply to {1}.").format(prefix, guild.name)]
    msg = "\n".join(msgs)
    role_post = await channel.send(msg)
    # Get the custom class emojis.
    emojis = await get_role_emojis(guild, role_names)
    # Add cancel emoji.
    emojis.append("\u274C")
    await add_emojis(emojis, role_post)
    await asyncio.sleep(0.25)
    await role_post.pin()
    return role_post


async def add_emojis(emojis, message):
    for emoji in emojis:
        await message.add_reaction(emoji)


async def get_role_emojis(guild, role_names):
    emojis = []
    for emoji in guild.emojis:
        if emoji.name in role_names:
            emojis.append(emoji)
    return emojis
