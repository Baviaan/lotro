async def dwarves(client,channel):
        # sends info about the 13 dwarves to channel
        ingor = '**Ingór I the Cruel**: "How much more can your mortal form take?" - Applies 1 stack of incoming healing debuff.\n'
        oiko2 = '**Óiko II Rill-Seeker**: "I seek the mithril stream." - Ice line\n'
        dobruz = '**Dóbruz IV the Unheeding**: "You look like a weakling."/"I challenge YOU!" - Picks random target; requires force taunt.\n'
        mozun = '**Mozun III Wyrmbane**: "I will not abide a worm to live." - Summons worm.\n'
        kuzek = '**Kúzek Squint-Eye**: TBD - Stand behind him in close range to avoid stun.\n'
        luvek = '**Lúvek I the Rueful**: "I am watching you..." - +100% melee damage and crit chance on himself.\n'
        oiko = '**Óiko I the Bellower**: TBD - Induction that increases dwarfs\' damage.\n'
        kamluz = '**Kamluz II Stoneface**: TBD - +100% incoming melee damage and crit chance on random player. \n'
        dobruz2 = '**Dóbruz II Stark-heart**: "The Zhelruka clan is mine to protect." - Allies take -50% incoming damage, must be interrupted.\n'
        brantokh2 = '**Brántokh II the Sunderer**: "I\'ll bring this mountain down on your heads!" - 20m AoE.\n'
        brunek = '**Brúnek I Clovenbow**: "Taste my axes!" - DoT on random person until interrupted.\n'
        rurek = '**Rúrek VI the Shamed**: "What have I done?"/"I have failed my people." - Bubble on dwarf.\n'
        brantokh = '**Brántokh I Cracktooth**: "Want to know why they call me cracktooth?" - AoE swipe (low damage).'
        text = ingor+oiko2+dobruz+mozun+kuzek+luvek+oiko+kamluz+dobruz2+brantokh2+brunek+rurek+brantokh
        await client.send_message(channel,text)

async def bid_five(client,message):
    # I wonder what unexpected words this is going to trigger on
    trigger = ['bid','offer','selling','buying','wts','wtb']
    if any(word in message.content.lower() for word in trigger):
        await client.send_message(message.channel,'Isengard bids five!')
