async def show_dwarves(channel):
    # sends info about the 13 dwarves to channel
    ingor = _('**Ingór I the Cruel**: "How much more can your mortal form take?" - ' \
            'Applies 1 stack of incoming healing debuff.\n')
    oiko2 = _('**Óiko II Rill-Seeker**: "I seek the mithril stream." - Ice line\n')
    dobruz = _('**Dóbruz IV the Unheeding**: "You look like a weakling."/"I challenge YOU!" - ' \
             'Picks random target; requires force taunt.\n')
    mozun = _('**Mozun III Wyrmbane**: "I will not abide a worm to live." - Summons worm.\n')
    kuzek = _('**Kúzek Squint-Eye**: TBD - Stand behind him in close range to avoid stun.\n')
    luvek = _('**Lúvek I the Rueful**: "I am watching you..." - +100% melee damage and crit chance on himself.\n')
    oiko = _('**Óiko I the Bellower**: "Sumrutu Vragomu" - Induction that increases dwarfs\' damage.\n')
    kamluz = _('**Kamluz II Stoneface**: "You face the Stoneface!" - +100% crit chance and +75% damage reflect effect. \n')
    dobruz2 = _('**Dóbruz II Stark-heart**: "The Zhelruka clan is mine to protect." - ' \
              'Allies take -50% incoming damage, must be interrupted.\n')
    brantokh2 = _('**Brántokh II the Sunderer**: "I\'ll bring this mountain down on your heads!" - 20m AoE.\n')
    brunek = _('**Brúnek I Clovenbrow**: "Taste my axes!" - DoT on random person until interrupted.\n')
    rurek = _('**Rúrek VI the Shamed**: "What have I done?"/"I have failed my people." - Bubble on dwarf.\n')
    brantokh = _('**Brántokh I Cracktooth**: "Want to know why they call me cracktooth?" - AoE swipe (low damage).')
    m = ingor + oiko2 + dobruz + mozun + kuzek + luvek + oiko + kamluz + dobruz2 + brantokh2 + brunek + rurek + brantokh
    await channel.send(m)
