import copy
import math
import random
import secrets
import time
from fastapi import HTTPException
from .db import Room, Player

EFFECTS = {'add_random','reroll','swap','steal','revive'}
SKILLS = {'medical_aid', 'find_item', 'discover_cache'}
EXPERIENCE = {
    'profession': [
        {'name':'Новичок','duration':'до 3 месяцев','min_age':16},
        {'name':'Стажёр','duration':'3 месяца — 1 год','min_age':16},
        {'name':'Любитель','duration':'1–2 года','min_age':17},
        {'name':'Опытный','duration':'2–5 лет','min_age':18},
        {'name':'Профессионал','duration':'5–10 лет','min_age':21},
        {'name':'Эксперт','duration':'более 10 лет','min_age':26},
    ],
    'hobby': [
        {'name':'Новичок','duration':'до 3 месяцев','min_age':12},
        {'name':'Любитель','duration':'3 месяца — 1 год','min_age':12},
        {'name':'Опытный','duration':'1–2 года','min_age':13},
        {'name':'Продвинутый','duration':'2–5 лет','min_age':14},
        {'name':'Мастер (гуру)','duration':'более 5 лет','min_age':17},
    ],
}

def experience_mode(cat):
    return cat.get('experience', {'job':'profession','hobby':'hobby'}.get(cat['id'],'none'))

def experience_levels(cat):
    mode=experience_mode(cat)
    if mode=='none': return []
    return cat.get('experience_levels') or EXPERIENCE.get(mode, [])


def error(message: str, status: int = 400):
    raise HTTPException(status_code=status, detail=message)

def validate_pack(content):
    if not isinstance(content, dict): error('Пак должен быть JSON-объектом')
    title = content.get('title')
    if not isinstance(title,str) or not (2 <= len(title.strip()) <= 120): error('Введите название пака (2–120 символов)')
    cats = content.get('categories')
    if not isinstance(cats,list) or not (1 <= len(cats) <= 30): error('Нужно от 1 до 30 категорий')
    names = set()
    for cat in cats:
        if not isinstance(cat,dict): error('Категория должна быть объектом')
        key = cat.get('id')
        if not isinstance(key,str) or not (1 <= len(key) <= 35) or not all(c.isascii() and (c.isalnum() or c in '_-') for c in key): error('id категории: латиница, цифры, _ или -')
        if key in names: error('Повторяются id категорий')
        names.add(key)
        if not isinstance(cat.get('name'),str) or not (1 <= len(cat['name']) <= 60): error('У категории должно быть имя')
        if not isinstance(cat.get('enabled', True),bool): error('enabled должен быть true/false')
        if not isinstance(cat.get('inventory', cat['id'] in ('large','bag')), bool): error('inventory должен быть true/false')
        mode = experience_mode(cat)
        if mode not in ('none', 'profession', 'hobby'): error('experience: none/profession/hobby')
        levels = cat.get('experience_levels')
        if levels is not None:
            if not isinstance(levels,list) or not (1 <= len(levels) <= 15): error('experience_levels: 1–15 ступеней')
            for level in levels:
                if not isinstance(level,dict) or not isinstance(level.get('name'),str) or not (1<=len(level['name'])<=50) or not isinstance(level.get('duration'),str) or not (1<=len(level['duration'])<=80): error('Опыт: нужна ступень {name, duration}')
                if 'min_age' in level and (type(level['min_age']) is not int or not (0<=level['min_age']<=120)): error('min_age: 0–120')
        if not isinstance(cat.get('medical',cat['id']=='health'), bool): error('medical: true/false')
        count = cat.get('draw_count', 1)
        if type(count) is not int or not (1 <= count <= 5): error('draw_count: от 1 до 5')
        items = cat.get('items')
        if not isinstance(items,list) or not (1 <= len(items) <= 500): error('В каждой категории нужно 1–500 карт')
        for item in items:
            if isinstance(item,str):
                if not (1 <= len(item) <= 250): error('Текст карты: 1–250 символов')
            elif isinstance(item,dict):
                if not isinstance(item.get('text'),str) or not (1 <= len(item['text']) <= 250): error('У карты должно быть текстовое поле')
                effect=item.get('effect')
                if effect is not None and effect not in EFFECTS: error('Неизвестный тип спец. действия')
                skill=item.get('skill')
                if skill is not None and skill not in SKILLS: error('Неизвестный тип профессионального навыка')
                if effect and skill: error('Нельзя одновременно задавать effect и skill')
                if 'bonus' in item and (not isinstance(item['bonus'],str) or len(item['bonus'])>350): error('bonus: строка до 350 символов')
            else: error('Карта: строка или объект {text,effect}')
    catastrophes=content.get('catastrophes')
    if not isinstance(catastrophes,list) or not catastrophes or any(not isinstance(x,str) or len(x)>1000 or not x.strip() for x in catastrophes): error('catastrophes: непустой список строк')
    bunker=content.get('bunker')
    if not isinstance(bunker,dict) or not bunker or len(bunker)>20: error('bunker: объект со списками вариантов')
    for name, values in bunker.items():
        if not isinstance(name,str) or len(name)>40 or not isinstance(values,list) or not values or any(not isinstance(v,str) or not v.strip() or len(v)>250 for v in values): error('Некорректные варианты бункера')
    settings = content.get('settings',{})
    if not isinstance(settings,dict): error('settings: объект')
    rounds=settings.get('max_rounds',7)
    if type(rounds) is not int or not (0<=rounds<=1000000): error('max_rounds: 0–1000000 (0 = без ограничения)')
    for field in ('speech_seconds','vote_seconds'):
        value=settings.get(field,60)
        if type(value) is not int or not (10<=value<=3600): error(field+': 10–3600')
    fraction=settings.get('bunker_fraction',0.5)
    if type(fraction) not in (float,int) or not (0 < fraction <= 1): error('bunker_fraction: от 0 до 1')
    limit=settings.get('reveal_limit',0)
    if type(limit) is not int or not (-1 <= limit <= 20): error('reveal_limit: -1–20; 0 = классическая таблица, -1 = без лимита')
    required=settings.get('first_required_category')
    if required and (required not in names or not any(x['id']==required and x.get('enabled',True) for x in cats)): error('Обязательная категория должна быть включена')
    return content

def choose_card(cat, avoid_values=None, require_new=False, age=None):
    avoid_values = set(avoid_values or ())
    choices = [item for item in cat['items'] if (item if isinstance(item,str) else item['text']) not in avoid_values]
    if require_new and not choices:
        error(f'В категории «{cat["name"]}» больше нет новых вариантов для этого игрока')
    item=random.choice(choices or cat['items'])
    val=item if isinstance(item,str) else item['text']
    card={'id':secrets.token_hex(5),'category_id':cat['id'],'category':cat['name'],
          'value':val,'revealed':False,'effect':None}
    if isinstance(item,dict):
        for field in ('effect','bonus','skill'):
            if item.get(field): card[field]=item[field]
    levels=experience_levels(cat)
    if levels:
        possible=[level for level in levels if age is None or age>=level.get('min_age',0)]
        level=random.choice(possible or levels)
        card['experience']={'name':level['name'],'duration':level['duration']}
    return card


def category(pack, cat_id):
    cat=next((x for x in pack['categories'] if x['id']==cat_id and x.get('enabled',True)),None)
    if not cat: error('Нет такой активной категории')
    return cat

def player_by_id(room, id):
    found=next((p for p in room.players if p.id==id),None)
    if not found: error('Игрок не найден',404)
    return found

def card_by_id(player, id):
    found=next((x for x in player.hand if x['id']==id),None)
    if not found: error('Карта не найдена')
    return found

def rotate_order(room, state=None):
    state=state or room.state
    players=sorted([p for p in room.players if not p.spectator],key=lambda p:p.seat)
    if not players: return []
    # Смещение относительно ПЕРВОНАЧАЛЬНОГО порядка, исключённые пропускаются.
    offset=(state.get('round',1)-1)%len(players)
    rotated=players[offset:]+players[:offset]
    return [p.id for p in rotated if p.alive]

def checkpoint(room):
    stack=list(room.undo_stack or [])
    stack.append({'phase':room.phase,'state':copy.deepcopy(room.state),
                  'players':{p.id:{'hand':copy.deepcopy(p.hand),'alive':p.alive,'used':copy.deepcopy(p.used_abilities)} for p in room.players}})
    room.undo_stack=stack[-35:]

def undo(room):
    if not room.undo_stack: error('Больше нечего отменять')
    stack=list(room.undo_stack)
    previous=stack.pop()
    room.undo_stack=stack
    room.phase=previous['phase']
    room.state=previous['state']
    for p in room.players:
        snap=previous['players'].get(p.id)
        if snap:
            p.hand=snap['hand']; p.alive=snap['alive']; p.used_abilities=snap['used']

def log(state, string):
    state.setdefault('log',[]).append(string)
    state['log']=state['log'][-70:]

def stopped_timer(seconds=0):
    return {'running':False,'remaining':max(0,int(seconds)),'until':None}

def start(room):
    players=[p for p in room.players if not p.spectator]
    if len(players)<2: error('Для старта нужно хотя бы 2 игрока')
    if room.phase!='lobby': error('Партия уже началась')
    pack=copy.deepcopy(room.pack_snapshot)
    validate_pack(pack)
    checkpoint(room)
    for p in players:
        hand=[]
        for cat in pack['categories']:
            if not cat.get('enabled',True):
                continue
            for _ in range(cat.get('draw_count',1)):
                existing={c['value'] for c in hand if c['category_id']==cat['id']}
                gender=next((c['value'] for c in hand if c['category_id']=='gender'), '')
                import re
                match=re.search(r'(\d{2,3})\s*(?:года?|лет)',gender)
                age=int(match.group(1)) if match else None
                hand.append(choose_card(cat,avoid_values=existing,age=age))
        p.hand=hand
        p.alive=True
        p.used_abilities=[]
    room.phase='round'
    settings={**pack.get('settings',{}),**room.config}
    state={'round':1,'speaker_index':0,'timer':{'running':True,'remaining':settings.get('speech_seconds',60),'until':time.time()+settings.get('speech_seconds',60)},
           'votes':{},'voting_candidates':None,'vote_attempt':0,'vote_result':None,
           'bunker':{key:random.choice(values) for key,values in pack['bunker'].items()},
           'catastrophe':random.choice(pack['catastrophes']),
           'capacity':max(1,math.floor(len(players)*float(settings.get('bunker_fraction',0.5)))),
           'initial_players':len(players),'log':[]}
    log(state,'Партия началась. Первый раунд!')
    room.state=state

def configure_timer(room, secs=None, mode='start'):
    state=copy.deepcopy(room.state)
    timer=state.get('timer',stopped_timer(60))
    now=time.time()
    if mode=='pause':
        timer=stopped_timer(math.ceil(timer['until']-now) if timer['running'] else timer['remaining'])
    elif mode=='resume':
        if not timer['running']:
            timer={'running':True,'remaining':timer['remaining'],'until':now+timer['remaining']}
    elif mode=='start':
        if type(secs) is not int or not (0<=secs<=3600): error('Некорректная длительность таймера')
        timer={'running':True,'remaining':secs,'until':now+secs}
    elif mode=='reset': timer=stopped_timer(0)
    else: error('Неизвестная команда таймера')
    checkpoint(room)
    state['timer']=timer
    room.state=state

def inventory_category_ids(pack):
    """Custom packs mark item categories explicitly. Older snapshots keep basic IDs."""
    return {
        cat['id'] for cat in pack.get('categories', [])
        if cat.get('inventory', cat['id'] in ('large', 'bag'))
    }


def item_card_is_public(room, card):
    return card.get('revealed', False) and card.get('category_id') in inventory_category_ids(room.pack_snapshot)


def apply_effect(room, actor, effect, data, is_host=False, checkpoint_before=True):
    if effect not in EFFECTS: error('Неизвестный эффект')
    if room.phase not in ('round','voting'): error('Действия доступны во время партии')
    if not actor.alive and not is_host: error('Исключённый игрок не может использовать возможности')
    state=copy.deepcopy(room.state)
    target_id=data.get('target_id')
    target=player_by_id(room,target_id) if target_id else None
    own_card_id=data.get('card_id')
    target_card_id=data.get('target_card_id')
    cat_id=data.get('category_id')
    if effect=='add_random':
        cat=category(room.pack_snapshot,cat_id)
        new_hand=copy.deepcopy(actor.hand)
        # Не создаём копию уже имеющейся характеристики этой категории.
        existing = {c['value'] for c in actor.hand if c['category_id']==cat_id}
        new_hand.append(choose_card(cat, avoid_values=existing, require_new=True))
        if checkpoint_before: checkpoint(room)
        actor.hand=new_hand
    elif effect=='reroll':
        if own_card_id=='__random_hidden__' and is_host:
            candidates=[x for x in actor.hand if not x['revealed']]
            if not candidates: error('У игрока нет закрытых карт')
            old=random.choice(candidates)
        else:
            old=card_by_id(actor,own_card_id)
            if is_host and actor.id!=room.host_id and not old['revealed']: error('Выберите открытую или случайную закрытую карту')
        cat=category(room.pack_snapshot,old['category_id'])
        avoid={x['value'] for x in actor.hand if x['category_id']==old['category_id']}
        new=choose_card(cat, avoid_values=avoid)
        new['revealed']=old['revealed']
        if 'revealed_round' in old: new['revealed_round']=old['revealed_round']
        new['id']=old['id']
        new_hand=[new if c['id']==old['id'] else c for c in actor.hand]
        if checkpoint_before: checkpoint(room)
        actor.hand=new_hand
        # A new occupational card replaces the old one. Its ability has not been spent.
        actor.used_abilities=[id for id in actor.used_abilities if id!=old['id']]
    elif effect in ('swap','steal'):
        if not target or target.id==actor.id or target.spectator or not target.alive: error('Выберите другого активного игрока')
        if effect=='steal':
            # Кража всегда адресная: только известный всем предмет из инвентарной категории.
            # Никакого случайного выбора из закрытой руки, даже для ведущего.
            if not target_card_id or target_card_id=='__random_hidden__':
                error('Выберите конкретный открытый предмет другого игрока')
            other=card_by_id(target,target_card_id)
            if not item_card_is_public(room, other):
                error('Можно украсть только раскрытый предмет из инвентаря')
        elif target_card_id=='__random_hidden__':
            hidden=[c for c in target.hand if not c['revealed']]
            if not hidden: error('У цели нет закрытых карт')
            other=random.choice(hidden)
        else:
            other=card_by_id(target,target_card_id)
            if not other['revealed']:
                error('Нельзя выбрать конкретную закрытую карту')
        if effect=='swap':
            if own_card_id=='__random_hidden__' and is_host:
                candidates=[x for x in actor.hand if not x['revealed']]
                if not candidates: error('У игрока нет закрытых карт')
                mine=random.choice(candidates)
            else:
                mine=card_by_id(actor,own_card_id)
                if is_host and actor.id!=room.host_id and not mine['revealed']: error('Выберите открытую или случайную закрытую карту')
            # Контейнер раскрытости остаётся у игрока, содержимое меняется местами.
            a=copy.deepcopy(other); b=copy.deepcopy(mine)
            a['id']=mine['id']; a['revealed']=mine['revealed']
            a.pop('revealed_round',None)
            if 'revealed_round' in mine: a['revealed_round']=mine['revealed_round']
            b['id']=other['id']; b['revealed']=other['revealed']
            b.pop('revealed_round',None)
            if 'revealed_round' in other: b['revealed_round']=other['revealed_round']
            # Used abilities follow the moved card, not the slot whose ID is retained.
            mine_spent=mine.get('skill_used',False) or mine['id'] in actor.used_abilities
            other_spent=other.get('skill_used',False) or other['id'] in target.used_abilities
            if checkpoint_before: checkpoint(room)
            actor.hand=[a if c['id']==mine['id'] else c for c in actor.hand]
            target.hand=[b if c['id']==other['id'] else c for c in target.hand]
            actor.used_abilities=[id for id in actor.used_abilities if id!=mine['id']]+([mine['id']] if other_spent else [])
            target.used_abilities=[id for id in target.used_abilities if id!=other['id']]+([other['id']] if mine_spent else [])
        else:
            if checkpoint_before: checkpoint(room)
            taken=copy.deepcopy(other); taken['id']=secrets.token_hex(5)
            # Предмет уже раскрыт всем; при краже открытость сохраняется и в новой руке.
            actor.hand=[*actor.hand,taken]
            target.hand=[c for c in target.hand if c['id']!=other['id']]
    elif effect=='revive':
        if not target or target.spectator or target.alive: error('Выберите исключённого игрока')
        if checkpoint_before: checkpoint(room)
        target.alive=True
        state['speaker_index']=0
    # NOTE: Special abilities are consumed in caller after effect validation.
    log(state,f'{actor.nickname}: эффект «{effect}»'+(f' → {target.nickname}' if target else ''))
    room.state=state

def finish_if_ready(room):
    active=[p for p in room.players if p.alive and not p.spectator]
    if len(active)<=room.state.get('capacity',0):
        state=copy.deepcopy(room.state)
        log(state,'Места в бункере распределены. Партия завершена!')
        state['timer']=stopped_timer(0)
        room.state=state; room.phase='finished'

def use_skill(room, actor, data, host=False):
    """An active occupational or hobby ability. Never inspect closed cards in the UI."""
    if room.phase not in ('round','voting'): error('Навыки действуют только во время партии')
    if actor.spectator or not actor.alive: error('Навык доступен активному игроку')
    card=card_by_id(actor,data.get('source_card_id'))
    skill=card.get('skill')
    if skill not in SKILLS or not card['revealed']: error('Раскройте карту с навыком перед применением')
    if card.get('skill_used') or card['id'] in actor.used_abilities: error('Навык этой карты уже использован')
    state=copy.deepcopy(room.state)
    if skill=='find_item':
        cat=category(room.pack_snapshot,data.get('category_id'))
        if cat['id'] not in inventory_category_ids(room.pack_snapshot): error('Для находки нужна категория предметов')
        existing={c['value'] for c in actor.hand if c['category_id']==cat['id']}
        item=choose_card(cat,avoid_values=existing,require_new=True)
        item['revealed']=True
        item['revealed_round']=state.get('round',1)
        checkpoint(room)
        actor.hand=[*actor.hand,item]
        log(state,f'{actor.nickname} обнаружил тайник: {item["category"]} — {item["value"]}')
    elif skill=='discover_cache':
        variants=[part.strip() for item in room.pack_snapshot.get('bunker',{}).get('equipment',[]) for part in item.split(';')]
        variants=[item for item in variants if item]
        existing=[part.strip() for part in state.get('bunker',{}).get('cache','').split(';') if part.strip()]
        available=[item for item in variants if item not in existing]
        if not available: error('В этом бункере больше нет доступных тайников с оборудованием')
        found=random.choice(available)
        checkpoint(room)
        bunker={**state.get('bunker',{})}
        bunker['cache']='; '.join([*existing,found])
        state['bunker']=bunker
        log(state,f'{actor.nickname} нашёл тайник в бункере: {found}')
    elif skill=='medical_aid':
        target=player_by_id(room,data.get('target_id'))
        if target.spectator or not target.alive: error('Помочь можно только активному участнику')
        health=card_by_id(target,data.get('target_card_id'))
        medical={cat['id'] for cat in room.pack_snapshot['categories'] if cat.get('medical',cat['id']=='health')}
        if health['category_id'] not in medical or not health['revealed']: error('Выберите раскрытую карту здоровья')
        if health.get('treatment'): error('По этой карте уже оказана помощь')
        if health['value'].strip().lower() in ('абсолютно здоров','спортивная форма','отличный иммунитет'):
            error('Помощь по этой карте не требуется')
        checkpoint(room)
        target.hand=[{**c,'treatment':f'Помощь оказал {actor.nickname}'} if c['id']==health['id'] else c for c in target.hand]
        log(state,f'{actor.nickname} оказал медицинскую помощь игроку {target.nickname}')
    actor.hand=[{**c,'skill_used':True} if c['id']==card['id'] else c for c in actor.hand]
    actor.used_abilities=[*actor.used_abilities,card['id']]
    room.state=state

def action(room, actor, kind, data):
    host=actor.id==room.host_id
    state=copy.deepcopy(room.state)
    if kind=='skill':
        if host and data.get('actor_id'):
            source=player_by_id(room,data['actor_id'])
        else:
            source=actor
        use_skill(room,source,data,host=host)
        return
    if kind=='kick':
        if not host: error('Только ведущий может удалить участника',403)
        target=player_by_id(room,data.get('target_id'))
        if target.id==room.host_id: error('Ведущий не может удалить себя')
        if room.phase!='lobby' and not target.spectator: error('В ходе партии можно удалить только зрителя')
        room.players.remove(target)
        return
    if kind=='undo':
        if not host: error('Только ведущий может отменить действия',403)
        undo(room); return
    if kind=='reveal':
        if room.phase=='lobby': error('Партия ещё не началась')
        p=player_by_id(room,data.get('reveal_target_id')) if host and data.get('reveal_target_id') else actor
        if p.spectator: error('Наблюдатель не может раскрывать характеристики')
        c=card_by_id(p,data.get('source_card_id') or data.get('card_id'))
        if c['revealed']: error('Карта уже раскрыта')
        # Исключённые и участники завершённой партии по-прежнему могут открывать свои карты.
        # Это просмотр личной руки: способности не изменяют уже завершённую игру.
        # Для активных игроков спецэффект применяется при раскрытии атомарно.
        live_reveal = p.alive and room.phase in ('round','voting')
        if c.get('effect') and live_reveal:
            if c['id'] in p.used_abilities: error('Способность этой карты уже использована')
            checkpoint(room)
            p.hand=[{**x,'revealed':True,'revealed_round':state.get('round',1)} if x['id']==c['id'] else x for x in p.hand]
            apply_effect(room,p,c['effect'],data,is_host=host and p.id!=actor.id,checkpoint_before=False)
            p.used_abilities=[*p.used_abilities,c['id']]
            state=copy.deepcopy(room.state)
            log(state,f'{p.nickname} раскрывает: {c["category"]} и применяет способность')
        else:
            checkpoint(room)
            p.hand=[{**x,'revealed':True,'revealed_round':state.get('round',1)} if x['id']==c['id'] else x for x in p.hand]
            suffix=' (без применения эффекта)' if c.get('effect') and not live_reveal else ''
            log(state,f'{p.nickname} раскрывает: {c["category"]}{suffix}')
    elif kind=='ability':
        if room.phase not in ('round','voting'): error('Партия не идёт')
        card=card_by_id(actor,data.get('ability_id'))
        if not card.get('effect'): error('Это не спец. возможность')
        if not card['revealed']: error('Спецвозможность срабатывает при раскрытии карты')
        if card['id'] in actor.used_abilities: error('Возможность уже использована')
        apply_effect(room,actor,card['effect'],data)
        actor.used_abilities=[*actor.used_abilities,card['id']]
        return
    else:
        if not host: error('Команда доступна только ведущему',403)
        if kind=='start': start(room); return
        if kind=='timer':
            configure_timer(room,data.get('seconds'),data.get('mode','start')); return
        if kind=='host_effect':
            source=player_by_id(room,data.get('actor_id') or actor.id)
            apply_effect(room,source,data.get('effect'),data,is_host=True)
            return
        if kind=='next_speaker':
            if room.phase!='round': error('Сейчас не раунд выступлений')
            order=rotate_order(room)
            if not order: error('Нет выступающих')
            checkpoint(room)
            state['speaker_index']=(state.get('speaker_index',0)+1)%len(order)
            secs=room.config.get('speech_seconds',room.pack_snapshot.get('settings',{}).get('speech_seconds',60))
            state['timer']={'running':True,'remaining':secs,'until':time.time()+secs}
        elif kind=='open_vote':
            if room.phase not in ('round','voting'): error('Нельзя открыть голосование')
            checkpoint(room)
            state['votes']={};state['voting_candidates']=None;state['vote_attempt']=1;state['vote_result']=None
            secs=room.config.get('vote_seconds',room.pack_snapshot.get('settings',{}).get('vote_seconds',60))
            state['timer']={'running':True,'remaining':secs,'until':time.time()+secs}
            room.phase='voting'
            log(state,'Ведущий открыл голосование')
        elif kind=='resolve_vote':
            if room.phase!='voting': error('Сейчас нет голосования')
            votes=list(state.get('votes',{}).values())
            if not votes: error('Пока нет голосов')
            checkpoint(room)
            counts={x:votes.count(x) for x in set(votes)}
            if counts.get('skip',0)>len([p for p in room.players if p.alive and not p.spectator])/2:
                state['vote_result']='Большинство проголосовало за пропуск'
                state['votes']={};room.phase='round'
                log(state,'Голосование пропущено большинством')
            else:
                contenders={k:v for k,v in counts.items() if k!='skip'}
                if not contenders:
                    state['vote_result']='Пропуск (нет голосов за кандидатов)'
                    state['votes']={};room.phase='round'
                else:
                    top=max(contenders.values())
                    leaders=[k for k,v in contenders.items() if v==top]
                    if len(leaders)>1 and state.get('vote_attempt',1)==1:
                        state['vote_attempt']=2;state['voting_candidates']=leaders;state['votes']={}
                        state['vote_result']='Ничья! Второй тур между кандидатами'
                        log(state,'Ничья: назначен второй тур')
                    elif len(leaders)>1:
                        state['vote_result']='Повторная ничья. Ведущий решает, как поступить.'
                        state['votes']={};room.phase='round'
                        log(state,'Повторная ничья: без автоматического исключения')
                    else:
                        removed=player_by_id(room,leaders[0]);removed.alive=False
                        state['vote_result']=f'Исключён игрок: {removed.nickname} ({top} голосов)'
                        state['votes']={};room.phase='round'
                        log(state,state['vote_result'])
            state['timer']=stopped_timer(0)
        elif kind=='vote':
            error('Голосование отправляется отдельной командой')
        elif kind=='exclude':
            if room.phase not in ('round','voting'): error('Партия не идёт')
            target=player_by_id(room,data.get('target_id'))
            if target.spectator or not target.alive: error('Выберите активного игрока')
            checkpoint(room)
            target.alive=False
            state['votes']={}; room.phase='round'
            state['vote_result']=f'Ведущий исключил: {target.nickname}'
            log(state,state['vote_result'])
        elif kind=='restore':
            target=player_by_id(room,data.get('target_id'))
            if target.spectator or target.alive: error('Выберите исключённого игрока')
            checkpoint(room);target.alive=True
            state['speaker_index']=0
            log(state,f'{target.nickname} вернулся в лагерь')
        elif kind=='next_round':
            if room.phase not in ('round','voting'): error('Нельзя переключать раунд')
            # Раунды — необязательная навигация ведущего; жёсткого потолка нет.
            checkpoint(room)
            state['round']+=1;state['speaker_index']=0;state['votes']={};state['vote_attempt']=0
            secs=room.config.get('speech_seconds',room.pack_snapshot.get('settings',{}).get('speech_seconds',60))
            state['timer']={'running':True,'remaining':secs,'until':time.time()+secs}
            state['vote_result']=None;state['voting_candidates']=None
            room.phase='round'
            log(state,f'Раунд {state["round"]}. Порядок выступлений смещён.')
        elif kind=='finish':
            if room.phase not in ('round','voting'): error('Партия не идёт')
            checkpoint(room)
            state['timer']=stopped_timer(0)
            room.phase='finished'
            log(state,'Ведущий завершил партию')
        else: error('Неизвестная команда')
    room.state=state
    if kind in ('resolve_vote','exclude'): finish_if_ready(room)

def cast_vote(room, actor, target):
    if room.phase!='voting' or not actor.alive or actor.spectator: error('Голосовать сейчас нельзя')
    state=copy.deepcopy(room.state)
    if target!='skip':
        candidate=player_by_id(room,target)
        if candidate.spectator or not candidate.alive: error('Нельзя голосовать за этого игрока')
        if state.get('voting_candidates') and target not in state['voting_candidates']: error('Второй тур: выбирайте финалиста')
    checkpoint(room)
    state.setdefault('votes',{})[actor.id]=target
    room.state=state

def public_state(room, viewer):
    state=copy.deepcopy(room.state or {})
    # НИКОГДА не отдаём чужие закрытые карты или личные выборы голосования.
    votes=state.pop('votes',{})
    state['vote_count']=len(votes)
    state['my_vote']=votes.get(viewer.id) if viewer else None
    state['speaker_order']=rotate_order(room) if room.phase!='lobby' else []
    players=[]
    for p in room.players:
        revealed=[{**{k:v for k,v in card.items() if k!='effect'},'used':card.get('skill_used',False) or card['id'] in p.used_abilities} for card in p.hand if card['revealed']]
        players.append({'id':p.id,'nickname':p.nickname,'seat':p.seat,'spectator':p.spectator,'alive':p.alive,
                        'host':p.id==room.host_id,'revealed':revealed,'card_count':len(p.hand),'voted':p.id in votes})
    own_hand=copy.deepcopy(viewer.hand) if viewer else []
    if viewer:
        # One can see one's own cards, even if excluded; nobody else can.
        for c in own_hand:
            c['used']=c.get('skill_used',False) or c['id'] in viewer.used_abilities
    return {'id':room.id,'title':room.title,'phase':room.phase,'host_id':room.host_id,
            'pack_id':room.pack_id,'pack_title':room.pack_snapshot.get('title'),
            'config':room.config,'settings':room.pack_snapshot.get('settings',{}),'state':state,
            'players':players,'me':{'id':viewer.id,'nickname':viewer.nickname,'spectator':viewer.spectator,'host':viewer.id==room.host_id,'alive':viewer.alive} if viewer else None,
            'own_hand':own_hand,'categories':[{'id':c['id'],'name':c['name'],'enabled':c.get('enabled',True),'inventory':c.get('inventory',c['id'] in ('large','bag')),'medical':c.get('medical',c['id']=='health'),'experience':experience_mode(c),'experience_levels':experience_levels(c)} for c in room.pack_snapshot.get('categories',[])],
            'can_undo':bool(room.undo_stack) if viewer and viewer.id==room.host_id else False}
