"""Run with: cd backend && pytest -q"""
import os
import tempfile
os.environ['DATABASE_URL']='sqlite:///'+tempfile.mktemp(suffix='.sqlite3')
os.environ['ADMIN_PASSWORD']='test-secret-password'
os.environ['MAX_ROOMS']='2'

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Base, engine

@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as test:
        yield test


def create(client, nick='Хозяин', title='Бункер друзей', pack='basic'):
    response=client.post('/api/rooms',json={'nickname':nick,'title':title,'pack_id':pack})
    assert response.status_code==200,response.text
    return response.json()

def join(client,room,nick,spectator=False):
    response=client.post(f'/api/rooms/{room}/join',json={'nickname':nick,'spectator':spectator})
    assert response.status_code==200,response.text
    return response.json()

def state(client,who):
    r=client.get(f'/api/rooms/{who["id"]}',headers={'X-Player-Token':who['token']})
    assert r.status_code==200,r.text
    return r.json()

def cmd(client,who,kind,data=None):
    return client.post(f'/api/rooms/{who["id"]}/command',json={'type':kind,'data':data or {}},headers={'X-Player-Token':who['token']})

def cast(client,who,target):
    return client.post(f'/api/rooms/{who["id"]}/vote',json={'target':target},headers={'X-Player-Token':who['token']})

def make_players(client,num=4):
    host=create(client)
    players=[host]+[join(client,host['id'],f'Друг_{i}') for i in range(1,num)]
    return players

def test_lobby_private_hand_reconnect_and_spectator(client):
    players=make_players(client,4)
    h=players[0]
    assert cmd(client,h,'start').status_code==200
    own=state(client,h)
    assert len(own['own_hand'])==12
    assert len([c for c in own['own_hand'] if c['category_id']=='special'])==2
    assert own['state']['capacity']==2
    assert own['state']['timer']['running']
    assert own['state']['speaker_order'][0]==h['player_id']
    another=state(client,players[1])
    assert 'value' not in repr(another['players'][0])
    first=own['own_hand'][0]
    # Any non-special card may be revealed first, with no required profession.
    assert cmd(client,h,'reveal',{'card_id':first['id']}).status_code==200
    job=next(c for c in own['own_hand'] if c['category_id']=='job')
    assert cmd(client,h,'reveal',{'card_id':job['id']}).status_code==200
    others=state(client,players[1])
    assert [c['value'] for c in others['players'][0]['revealed']]==[first['value'],job['value']]
    assert all('value' not in p for p in others['players'][0]['revealed'] if not p['revealed'])
    spectator=join(client,h['id'],'Поздний')
    assert spectator['spectator'] is True
    assert not state(client,spectator)['own_hand']
    assert cmd(client,spectator,'start').status_code==403
    assert cmd(client,players[1],'next_round').status_code==403
    # Два последовательных запроса возвращают одну и ту же руку (возврат по токену).
    assert state(client,h)['own_hand']==state(client,h)['own_hand']


def test_round_order_rotates_and_removes_only_excluded(client):
    players=make_players(client,5)
    host=players[0]
    assert cmd(client,host,'start').status_code==200
    order=state(client,host)['state']['speaker_order']
    assert cmd(client,host,'next_round').status_code==200
    order2=state(client,host)['state']['speaker_order']
    assert order2==order[1:]+order[:1]
    assert cmd(client,host,'exclude',{'target_id':order[2]}).status_code==200
    assert cmd(client,host,'next_round').status_code==200
    order3=state(client,host)['state']['speaker_order']
    assert order3==[order[3],order[4],order[0],order[1]]
    assert all(not p['revealed'] for p in state(client,host)['players'] if p['id']==order[2])
    assert cmd(client,host,'undo').status_code==200
    assert state(client,host)['state']['round']==2


def test_skip_and_tie_runoff(client):
    players=make_players(client,4)
    host=players[0]
    assert cmd(client,host,'start').status_code==200
    assert cmd(client,host,'open_vote').status_code==200
    assert cast(client,players[0],'skip').status_code==200
    assert cast(client,players[1],'skip').status_code==200
    assert cast(client,players[2],'skip').status_code==200
    assert cast(client,players[3],players[0]['player_id']).status_code==200
    assert cmd(client,host,'resolve_vote').status_code==200
    assert state(client,host)['phase']=='round'
    assert len([p for p in state(client,host)['players'] if p['alive']])==4
    assert cmd(client,host,'open_vote').status_code==200
    for i,p in enumerate(players):
        assert cast(client,p,players[i%2]['player_id']).status_code==200
    assert cmd(client,host,'resolve_vote').status_code==200
    a=state(client,host)
    assert a['phase']=='voting'
    assert a['state']['vote_attempt']==2
    assert len(a['state']['voting_candidates'])==2
    assert a['state']['vote_count']==0
    assert cmd(client,host,'undo').status_code==200
    assert state(client,host)['state']['vote_count']==4
    assert state(client,host)['state']['vote_attempt']==1


def test_host_manual_effect_uses_selected_recipient_and_explicit_revealed_item(client):
    players=make_players(client,4)
    host,receiver,owner=players[:3]
    assert cmd(client,host,'start').status_code==200
    host_before=state(client,host)['own_hand']
    receiver_before=state(client,receiver)['own_hand']
    owner_before=state(client,owner)['own_hand']
    item=next(c for c in owner_before if c['category_id']=='large')
    job=next(c for c in owner_before if c['category_id']=='job')
    # Cannot steal a hidden item or a profession, even as host.
    steal={'actor_id':receiver['player_id'],'effect':'steal','target_id':owner['player_id'],'target_card_id':item['id']}
    assert cmd(client,host,'host_effect',steal).status_code==400
    assert cmd(client,host,'host_effect',{**steal,'target_card_id':'__random_hidden__'}).status_code==400
    assert cmd(client,owner,'reveal',{'card_id':job['id']}).status_code==200
    assert cmd(client,host,'host_effect',{**steal,'target_card_id':job['id']}).status_code==400
    assert cmd(client,owner,'reveal',{'card_id':item['id']}).status_code==200
    result=cmd(client,host,'host_effect',steal)
    assert result.status_code==200,result.text
    assert len(state(client,host)['own_hand'])==len(host_before)
    assert len(state(client,receiver)['own_hand'])==len(receiver_before)+1
    assert len(state(client,owner)['own_hand'])==len(owner_before)-1
    taken=next(c for c in state(client,receiver)['own_hand'] if c['value']==item['value'] and c['category_id']=='large' and c['revealed'])
    assert taken['revealed'] is True
    public=state(client,host)
    assert any(c['id']==taken['id'] for c in next(p for p in public['players'] if p['id']==receiver['player_id'])['revealed'])
    assert not any(c['id']==item['id'] for c in next(p for p in public['players'] if p['id']==owner['player_id'])['revealed'])
    assert cmd(client,host,'undo').status_code==200
    assert len(state(client,receiver)['own_hand'])==len(receiver_before)
    assert len(state(client,owner)['own_hand'])==len(owner_before)


def test_packs_snapshot_and_admin(client):
    base=client.get('/api/packs/basic').json()['content']
    user_content={**base,'title':'Модульный пак', 'categories':[{**base['categories'][3],'name':'Должность в Зоне'}]}
    assert client.post('/api/packs',json={'content':user_content}).status_code==403
    result=client.post('/api/packs',json={'content':user_content},headers={'X-Admin-Password':'test-secret-password'})
    assert result.status_code==200,result.text
    pack_id=result.json()['id']
    host=create(client,pack=pack_id)
    user_content['title']='Переименовано'
    result=client.put('/api/packs/'+pack_id,json={'content':user_content},headers={'X-Admin-Password':'test-secret-password'})
    assert result.status_code==200
    assert state(client,host)['pack_title']=='Модульный пак'
    assert client.put('/api/packs/basic',json={'content':base},headers={'X-Admin-Password':'test-secret-password'}).status_code==400


def test_room_cap_and_host_delete(client):
    a=create(client)
    b=create(client,title='Ещё бункер')
    assert client.post('/api/rooms',json={'nickname':'Другой','title':'Третий бункер'}).status_code==400
    assert client.delete(f'/api/rooms/{a["id"]}',headers={'X-Player-Token':a['token']}).status_code==200
    assert create(client,title='Освободилось')['id']
    assert client.get('/api/rooms').status_code==200


def test_unrestricted_reveal_rounds_and_elimination(client):
    players=make_players(client,6)
    host=players[0]
    assert cmd(client,host,'start').status_code==200
    cards=state(client,host)['own_hand']
    job=next(c for c in cards if c['category_id']=='job')
    assert cmd(client,host,'reveal',{'card_id':job['id']}).status_code==200
    others=[c for c in cards if c['category_id']!='job']
    assert cmd(client,host,'reveal',{'card_id':others[0]['id']}).status_code==200
    assert cmd(client,host,'reveal',{'card_id':others[1]['id']}).status_code==200
    assert cmd(client,host,'reveal',{'card_id':others[2]['id']}).status_code==200
    # No ceiling of 7, 30 or any other number of rounds.
    for _ in range(40):
        assert cmd(client,host,'next_round').status_code==200
    assert state(client,host)['state']['round']==41
    victim=players[1]
    assert cmd(client,host,'exclude',{'target_id':victim['player_id']}).status_code==200
    assert cmd(client,victim,'reveal',{'card_id':state(client,victim)['own_hand'][0]['id']}).status_code==200
    viewer=state(client,host)['players'][1]
    assert len(viewer['revealed'])==1
    assert viewer['alive'] is False


def test_special_once_and_undo(client):
    base=client.get('/api/packs/basic').json()['content']
    special=next(c for c in base['categories'] if c['id']=='special')
    special['items']=[{'text':'Перегенерируй свою карту','effect':'reroll'}]
    res=client.post('/api/packs',json={'content':{**base,'title':'Тест способности'}},headers={'X-Admin-Password':'test-secret-password'})
    assert res.status_code==200
    host=create(client,pack=res.json()['id'])
    join(client,host['id'],'Друг')
    assert cmd(client,host,'start').status_code==200
    own=state(client,host)['own_hand']
    power=next(c for c in own if c['effect']=='reroll')
    job=next(c for c in own if c['category_id']=='job')
    data={'source_card_id':power['id'],'card_id':job['id']}
    assert cmd(client,host,'ability',{'ability_id':power['id'],'card_id':job['id']}).status_code==400
    assert cmd(client,host,'reveal',data).status_code==200
    assert next(c for c in state(client,host)['own_hand'] if c['id']==power['id'])['used'] is True
    assert cmd(client,host,'reveal',data).status_code==400
    assert cmd(client,host,'undo').status_code==200
    restored=next(c for c in state(client,host)['own_hand'] if c['id']==power['id'])
    assert restored['used'] is False and restored['revealed'] is False
    assert cmd(client,host,'reveal',data).status_code==200


def test_lobby_kick_and_spectator_kick(client):
    host=create(client)
    guest=join(client,host['id'],'Временный')
    assert cmd(client,guest,'kick',{'target_id':host['player_id']}).status_code==403
    assert cmd(client,host,'kick',{'target_id':guest['player_id']}).status_code==200
    assert len(state(client,host)['players'])==1
    assert client.get(f'/api/rooms/{host["id"]}',headers={'X-Player-Token':guest['token']}).status_code==401
    join(client,host['id'],'Второй')
    assert cmd(client,host,'start').status_code==200
    spectator=join(client,host['id'],'Смотрящий')
    assert cmd(client,host,'kick',{'target_id':spectator['player_id']}).status_code==200
    assert client.get(f'/api/rooms/{host["id"]}',headers={'X-Player-Token':spectator['token']}).status_code==401


def test_websocket_sync_never_pushes_private_cards(client):
    host=create(client)
    join(client,host['id'],'Друг')
    with client.websocket_connect(f'/ws/rooms/{host["id"]}') as ws:
        ws.send_json({'token':host['token']})
        assert ws.receive_json()=={'type':'sync'}
        assert cmd(client,host,'start').status_code==200
        # WebSocket only announces a change; private state is fetched via authenticated HTTP.
        assert ws.receive_json()=={'type':'sync'}


def test_add_random_never_duplicates_own_category_and_exhaustion_is_atomic(client):
    base=client.get('/api/packs/basic').json()['content']
    big=next(c for c in base['categories'] if c['id']=='large')
    big['items']=['Солнечная панель','Электрогенератор']
    special=next(c for c in base['categories'] if c['id']=='special')
    special['items']=[{'text':'Новая крупная вещь','effect':'add_random'}]
    special['draw_count']=2
    saved=client.post('/api/packs',json={'content':{**base,'title':'Без дубликатов'}},headers={'X-Admin-Password':'test-secret-password'}).json()
    host=create(client,pack=saved['id'])
    join(client,host['id'],'Друг')
    assert cmd(client,host,'start').status_code==200
    cards=state(client,host)['own_hand']
    powers=[c for c in cards if c['category_id']=='special']
    old=next(c for c in cards if c['category_id']=='large')
    assert cmd(client,host,'reveal',{'source_card_id':powers[0]['id'],'category_id':'large'}).status_code==200
    new_hand=state(client,host)['own_hand']
    large=[c for c in new_hand if c['category_id']=='large']
    assert len(large)==2 and len({c['value'] for c in large})==2
    assert old['value'] in [c['value'] for c in large]
    assert cmd(client,host,'reveal',{'source_card_id':powers[1]['id'],'category_id':'large'}).status_code==400
    assert not next(c for c in state(client,host)['own_hand'] if c['id']==powers[1]['id'])['revealed']
    assert cmd(client,host,'undo').status_code==200
    after_undo=state(client,host)['own_hand']
    assert len([c for c in after_undo if c['category_id']=='large'])==1
    assert not next(c for c in after_undo if c['id']==powers[0]['id'])['revealed']
    assert cmd(client,host,'reveal',{'source_card_id':powers[0]['id'],'category_id':'large'}).status_code==200
    current=state(client,host)['own_hand']
    for card in current:
        if card['category_id']=='large':
            assert cmd(client,host,'reveal',{'card_id':card['id']}).status_code==200
    other_view=state(client,join(client,host['id'],'Смотрящий',spectator=True))
    revealed=next(p for p in other_view['players'] if p['id']==host['player_id'])['revealed']
    assert len([c for c in revealed if c['category_id']=='large'])==2


def test_reveal_target_does_not_conflict_with_special_effect_target(client):
    base=client.get('/api/packs/basic').json()['content']
    special=next(c for c in base['categories'] if c['id']=='special')
    special['items']=[{'text':'Забрать чужой предмет','effect':'steal'}]
    saved=client.post('/api/packs',json={'content':{**base,'title':'Тест цели'}},headers={'X-Admin-Password':'test-secret-password'}).json()
    host=create(client,pack=saved['id'])
    guest=join(client,host['id'],'Гость')
    assert cmd(client,host,'start').status_code==200
    host_start=state(client,host)['own_hand']
    guest_start=state(client,guest)['own_hand']
    power=next(c for c in host_start if c['category_id']=='special')
    item=next(c for c in guest_start if c['category_id']=='bag')
    assert cmd(client,guest,'reveal',{'card_id':item['id']}).status_code==200
    assert cmd(client,host,'reveal',{'source_card_id':power['id']}).status_code==400
    assert not next(c for c in state(client,host)['own_hand'] if c['id']==power['id'])['revealed']
    assert cmd(client,host,'reveal',{'source_card_id':power['id'],'target_id':guest['player_id'],'target_card_id':'__random_hidden__'}).status_code==400
    result=cmd(client,host,'reveal',{'source_card_id':power['id'],'target_id':guest['player_id'],'target_card_id':item['id']})
    assert result.status_code==200,result.text
    assert len(state(client,host)['own_hand'])==len(host_start)+1
    assert len(state(client,guest)['own_hand'])==len(guest_start)-1
    assert next(c for c in state(client,host)['own_hand'] if c['id']==power['id'])['used']
    assert state(client,guest)['players'][0]['revealed'][0]['category_id']=='special'
    assert cmd(client,host,'undo').status_code==200
    assert len(state(client,host)['own_hand'])==len(host_start)
    assert len(state(client,guest)['own_hand'])==len(guest_start)


def test_cards_can_be_revealed_after_game_ends_without_changing_outcome(client):
    players=make_players(client,4)
    host,guest=players[:2]
    assert cmd(client,host,'start').status_code==200
    assert cmd(client,host,'finish').status_code==200
    before=state(client,guest)
    assert before['phase']=='finished'
    assert before['players'][1]['revealed']==[]
    ordinary=next(c for c in before['own_hand'] if c['category_id']=='job')
    assert cmd(client,guest,'reveal',{'card_id':ordinary['id']}).status_code==200
    after=state(client,host)
    assert after['phase']=='finished'
    assert after['players'][1]['revealed'][0]['value']==ordinary['value']
    assert cmd(client,guest,'reveal',{'card_id':ordinary['id']}).status_code==400
    assert cmd(client,host,'undo').status_code==200
    assert state(client,host)['phase']=='finished'
    assert state(client,guest)['own_hand'] == before['own_hand']


def test_revealing_special_after_elimination_or_finish_does_not_apply_effect(client):
    base=client.get('/api/packs/basic').json()['content']
    special=next(c for c in base['categories'] if c['id']=='special')
    special['items']=[{'text':'Получите ещё крупную вещь','effect':'add_random'}]
    pack=client.post('/api/packs',json={'content':{**base,'title':'Открыть после исключения'}},
                     headers={'X-Admin-Password':'test-secret-password'}).json()['id']
    host=create(client,pack=pack)
    excluded=join(client,host['id'],'Исключённый')
    finished=join(client,host['id'],'После финала')
    assert cmd(client,host,'start').status_code==200
    assert cmd(client,host,'exclude',{'target_id':excluded['player_id']}).status_code==200
    excluded_before=state(client,excluded)
    excluded_special=next(c for c in excluded_before['own_hand'] if c['effect']=='add_random')
    assert cmd(client,excluded,'reveal',{'card_id':excluded_special['id']}).status_code==200
    excluded_after=state(client,excluded)
    assert len(excluded_after['own_hand'])==len(excluded_before['own_hand'])
    assert next(c for c in excluded_after['own_hand'] if c['id']==excluded_special['id'])['revealed']
    assert not next(c for c in excluded_after['own_hand'] if c['id']==excluded_special['id'])['used']
    # Even after finished, neither 'add_random' nor a special targeting effect should run.
    assert cmd(client,host,'finish').status_code==200
    finished_before=state(client,finished)
    finished_special=next(c for c in finished_before['own_hand'] if c['effect']=='add_random')
    assert cmd(client,finished,'reveal',{'card_id':finished_special['id']}).status_code==200
    finished_after=state(client,finished)
    assert len(finished_after['own_hand'])==len(finished_before['own_hand'])
    assert not next(c for c in finished_after['own_hand'] if c['id']==finished_special['id'])['used']
    assert state(client,host)['phase']=='finished'
    # Spectator cannot reveal cards (no cards to reveal) or issue game commands.
    spectator=join(client,host['id'],'Наблюдатель')
    assert cmd(client,spectator,'reveal',{'card_id':excluded_special['id']}).status_code==403

def test_manual_add_random_applies_to_guest_not_host(client):
    players=make_players(client,3)
    host,recipient=players[:2]
    assert cmd(client,host,'start').status_code==200
    host_before=state(client,host)['own_hand']
    guest_before=state(client,recipient)['own_hand']
    result=cmd(client,host,'host_effect',{'actor_id':recipient['player_id'],'effect':'add_random','category_id':'bag'})
    assert result.status_code==200,result.text
    host_after=state(client,host)['own_hand']
    guest_after=state(client,recipient)['own_hand']
    assert host_after==host_before
    assert len(guest_after)==len(guest_before)+1
    assert len([c for c in guest_after if c['category_id']=='bag'])==2
    assert cmd(client,host,'undo').status_code==200
    assert state(client,recipient)['own_hand']==guest_before


def test_custom_inventory_category_stealable_only_if_marked(client):
    base=client.get('/api/packs/basic').json()['content']
    categories=base['categories']
    categories.append({'id':'artifacts','name':'Артефакты','inventory':True,'items':['Компас','Каменный цветок']})
    custom=client.post('/api/packs',json={'content':{**base,'title':'Артефакты Зоны'}},headers={'X-Admin-Password':'test-secret-password'})
    assert custom.status_code==200,custom.text
    host=create(client,pack=custom.json()['id'])
    thief=join(client,host['id'],'Сталкер_1')
    owner=join(client,host['id'],'Сталкер_2')
    assert cmd(client,host,'start').status_code==200
    assert next(x for x in state(client,host)['categories'] if x['id']=='artifacts')['inventory'] is True
    artifact=next(c for c in state(client,owner)['own_hand'] if c['category_id']=='artifacts')
    assert cmd(client,owner,'reveal',{'card_id':artifact['id']}).status_code==200
    stolen=cmd(client,host,'host_effect',{'actor_id':thief['player_id'],'effect':'steal','target_id':owner['player_id'],'target_card_id':artifact['id']})
    assert stolen.status_code==200,stolen.text
    assert any(c['value']==artifact['value'] for c in state(client,thief)['own_hand'])


def test_pack_inventory_flag_is_validated(client):
    base=client.get('/api/packs/basic').json()['content']
    base['categories'][0]['inventory']='yes'
    resp=client.post('/api/packs',json={'content':{**base,'title':'Неверный пак'}},headers={'X-Admin-Password':'test-secret-password'})
    assert resp.status_code==400


def test_two_special_cards_are_distinct_when_possible(client):
    players=make_players(client,3)
    host=players[0]
    assert cmd(client,host,'start').status_code==200
    for p in players:
        cards=[c for c in state(client,p)['own_hand'] if c['category_id']=='special']
        assert len(cards)==2
        assert cards[0]['value']!=cards[1]['value']


def test_host_manual_swap_two_other_players_leaves_host_untouched(client):
    host,first,second=make_players(client,4)[:3]
    assert cmd(client,host,'start').status_code==200
    initial_host=state(client,host)['own_hand']
    first_card=next(c for c in state(client,first)['own_hand'] if c['category_id']=='job')
    second_card=next(c for c in state(client,second)['own_hand'] if c['category_id']=='bag')
    assert cmd(client,first,'reveal',{'card_id':first_card['id']}).status_code==200
    assert cmd(client,second,'reveal',{'card_id':second_card['id']}).status_code==200
    response=cmd(client,host,'host_effect',{
        'actor_id':first['player_id'], 'effect':'swap',
        'card_id':first_card['id'], 'target_id':second['player_id'],
        'target_card_id':second_card['id']
    })
    assert response.status_code==200,response.text
    assert state(client,host)['own_hand']==initial_host
    assert any(c['value']==second_card['value'] for c in state(client,first)['own_hand'])
    assert any(c['value']==first_card['value'] for c in state(client,second)['own_hand'])
    assert cmd(client,host,'undo').status_code==200
    assert any(c['value']==first_card['value'] for c in state(client,first)['own_hand'])
    assert any(c['value']==second_card['value'] for c in state(client,second)['own_hand'])

# v0.6: occupational skills and experience progression.
def role_test_pack(client):
    base=client.get('/api/packs/basic').json()['content']
    for cat in base['categories']:
        if cat['id']=='job':
            cat['items']=[{'text':'Полевой врач','bonus':'Умеет оказать помощь','skill':'medical_aid'}]
        if cat['id']=='hobby':
            cat['items']=[{'text':'Искатель тайников','bonus':'Умеет искать запасы','skill':'find_item'}]
        if cat['id']=='health': cat['items']=['Больное колено']
        if cat['id']=='large': cat['items']=['Генератор','Солнечная панель','Аптечный шкаф']
    r=client.post('/api/packs',json={'content':{**base,'title':'Тест стажа и навыков'}},headers={'X-Admin-Password':'test-secret-password'})
    assert r.status_code==200,r.text
    return r.json()['id']


def test_experience_levels_and_narrative_bonuses_are_private_until_reveal(client):
    pack=role_test_pack(client)
    h=create(client,pack=pack)
    friend=join(client,h['id'],'Напарник')
    assert cmd(client,h,'start').status_code==200
    own=state(client,h)
    job=next(c for c in own['own_hand'] if c['category_id']=='job')
    hobby=next(c for c in own['own_hand'] if c['category_id']=='hobby')
    assert job['bonus'] and job['skill']=='medical_aid'
    assert hobby['bonus'] and hobby['skill']=='find_item'
    assert job['experience']['name'] in ['Новичок','Стажёр','Любитель','Опытный','Профессионал','Эксперт']
    assert hobby['experience']['duration']
    public_before=state(client,friend)
    assert all(c['id']!=job['id'] for p in public_before['players'] for c in p['revealed'])
    assert cmd(client,h,'reveal',{'card_id':job['id']}).status_code==200
    public_after=state(client,friend)
    found=next(c for p in public_after['players'] for c in p['revealed'] if c['id']==job['id'])
    assert found['bonus']==job['bonus']
    assert found['experience']==job['experience']
    assert found['skill']=='medical_aid'


def test_medical_aid_requires_open_health_and_is_undoable(client):
    pack=role_test_pack(client)
    host=create(client,pack=pack)
    friend=join(client,host['id'],'Пациент')
    assert cmd(client,host,'start').status_code==200
    job=next(c for c in state(client,host)['own_hand'] if c.get('skill')=='medical_aid')
    health=next(c for c in state(client,friend)['own_hand'] if c['category_id']=='health')
    args={'source_card_id':job['id'],'target_id':friend['player_id'],'target_card_id':health['id']}
    assert cmd(client,host,'skill',args).status_code==400
    assert cmd(client,host,'reveal',{'card_id':job['id']}).status_code==200
    assert cmd(client,host,'skill',args).status_code==400  # not yet revealed health
    assert cmd(client,friend,'reveal',{'card_id':health['id']}).status_code==200
    assert cmd(client,host,'skill',args).status_code==200
    patient=state(client,friend)
    treated=next(c for c in patient['own_hand'] if c['id']==health['id'])
    assert 'Помощь оказал' in treated['treatment']
    assert state(client,host)['own_hand'][3]['category_id']=='job'
    assert next(c for c in state(client,host)['own_hand'] if c['id']==job['id'])['used']
    assert cmd(client,host,'skill',args).status_code==400  # cannot repeat
    assert cmd(client,host,'undo').status_code==200
    assert not next(c for c in state(client,friend)['own_hand'] if c['id']==health['id']).get('treatment')
    assert not next(c for c in state(client,host)['own_hand'] if c['id']==job['id'])['used']


def test_find_item_adds_public_inventory_only_once_and_no_duplicates(client):
    pack=role_test_pack(client)
    host=create(client,pack=pack)
    friend=join(client,host['id'],'Друг')
    assert cmd(client,host,'start').status_code==200
    hobby=next(c for c in state(client,friend)['own_hand'] if c.get('skill')=='find_item')
    assert cmd(client,friend,'reveal',{'card_id':hobby['id']}).status_code==200
    before=state(client,friend)['own_hand']
    args={'source_card_id':hobby['id'],'category_id':'large'}
    assert cmd(client,friend,'skill',{**args,'category_id':'job'}).status_code==400
    assert cmd(client,friend,'skill',args).status_code==200
    after=state(client,friend)['own_hand']
    assert len(after)==len(before)+1
    added=[c for c in after if c['id'] not in {x['id'] for x in before}]
    assert len(added)==1 and added[0]['revealed']
    assert added[0]['category_id']=='large'
    assert added[0]['value'] not in {c['value'] for c in before if c['category_id']=='large'}
    assert cmd(client,friend,'skill',args).status_code==400
    assert next(c for c in state(client,host)['players'] if c['id']==friend['player_id'])['revealed'][-1]['id']==added[0]['id']
    assert cmd(client,host,'undo').status_code==200
    assert len(state(client,friend)['own_hand'])==len(before)
    assert not next(c for c in state(client,friend)['own_hand'] if c['id']==hobby['id'])['used']


def test_host_can_use_other_player_skill_without_spoofing(client):
    pack=role_test_pack(client)
    host=create(client,pack=pack)
    friend=join(client,host['id'],'Искатель')
    assert cmd(client,host,'start').status_code==200
    hobby=next(c for c in state(client,friend)['own_hand'] if c.get('skill')=='find_item')
    assert cmd(client,friend,'reveal',{'card_id':hobby['id']}).status_code==200
    payload={'actor_id':friend['player_id'],'source_card_id':hobby['id'],'category_id':'bag'}
    assert cmd(client,host,'skill',payload).status_code==200
    # Non-host cannot forge actor_id and use the other player's card.
    host_hobby=next(c for c in state(client,host)['own_hand'] if c['category_id']=='hobby')
    assert cmd(client,host,'reveal',{'card_id':host_hobby['id']}).status_code==200
    as_friend={'actor_id':host['player_id'],'source_card_id':host_hobby['id'],'category_id':'bag'}
    assert cmd(client,friend,'skill',as_friend).status_code==400


def test_custom_experience_options_and_pack_validation(client):
    base=client.get('/api/packs/basic').json()['content']
    job=next(c for c in base['categories'] if c['id']=='job')
    job['experience']='profession'
    job['experience_levels']=[{'name':'Дозорный','duration':'2 зимы'}]
    pack={**base,'title':'Стаж выживших'}
    result=client.post('/api/packs',json={'content':pack},headers={'X-Admin-Password':'test-secret-password'})
    assert result.status_code==200,result.text
    host=create(client,pack=result.json()['id'])
    join(client,host['id'],'Друг')
    assert cmd(client,host,'start').status_code==200
    job_card=next(c for c in state(client,host)['own_hand'] if c['category_id']=='job')
    assert job_card['experience']=={'name':'Дозорный','duration':'2 зимы'}
    job['experience_levels']=[{'name':'Слишком долгий '+'x'*70,'duration':'один год'}]
    assert client.post('/api/packs',json={'content':pack},headers={'X-Admin-Password':'test-secret-password'}).status_code==400


def test_discover_cache_updates_shared_bunker_and_undo(client):
    base=client.get('/api/packs/basic').json()['content']
    job=next(c for c in base['categories'] if c['id']=='job')
    job['items']=[{'text':'Разведчик запасов','bonus':'Ищет тайники','skill':'discover_cache'}]
    base['bunker']['equipment']=['огнетушитель; батареи','фонари; запас фильтров']
    pack=client.post('/api/packs',json={'content':{**base,'title':'Склад на базе'}},headers={'X-Admin-Password':'test-secret-password'}).json()['id']
    host=create(client,pack=pack)
    friend=join(client,host['id'],'Напарник')
    assert cmd(client,host,'start').status_code==200
    card=next(c for c in state(client,friend)['own_hand'] if c.get('skill')=='discover_cache')
    assert cmd(client,friend,'reveal',{'card_id':card['id']}).status_code==200
    assert cmd(client,friend,'skill',{'source_card_id':card['id']}).status_code==200
    got=state(client,host)['state']['bunker']['cache']
    assert got in ('огнетушитель','батареи','фонари','запас фильтров')
    assert cmd(client,host,'undo').status_code==200
    assert not state(client,host)['state']['bunker'].get('cache')
    assert not next(c for c in state(client,friend)['own_hand'] if c['id']==card['id'])['used']


def test_professional_experience_respects_age_and_can_be_disabled(client):
    base=client.get('/api/packs/basic').json()['content']
    gender=next(c for c in base['categories'] if c['id']=='gender')
    job=next(c for c in base['categories'] if c['id']=='job')
    gender['items']=['Женщина, 19 лет']
    pack=client.post('/api/packs',json={'content':{**base,'title':'Возраст и стаж'}},headers={'X-Admin-Password':'test-secret-password'}).json()['id']
    host=create(client,pack=pack)
    join(client,host['id'],'Друг')
    assert cmd(client,host,'start').status_code==200
    value=next(c for c in state(client,host)['own_hand'] if c['category_id']=='job')['experience']['name']
    assert value in ('Новичок','Стажёр','Любитель','Опытный')
    job['experience']='none'
    pack2=client.post('/api/packs',json={'content':{**base,'title':'Стаж выключен'}},headers={'X-Admin-Password':'test-secret-password'}).json()['id']
    assert cmd(client,host,'finish').status_code==200
    next_host=create(client,pack=pack2)
    join(client,next_host['id'],'Напарник')
    assert cmd(client,next_host,'start').status_code==200
    assert 'experience' not in next(c for c in state(client,next_host)['own_hand'] if c['category_id']=='job')


def test_contract_vote_skip_updates_only_voters_private_state(client):
    """Lab 4: successful US-5/FR-5 vote follows the documented HTTP contract."""
    host, alice, observer = make_players(client, 3)
    assert cmd(client, host, 'start').status_code == 200
    assert cmd(client, host, 'open_vote').status_code == 200

    response = cast(client, alice, 'skip')
    assert response.status_code == 201  # Lab 4 CI demonstration: intentionally wrong; fix in next commit.
    assert response.json() == {'ok': True}

    alice_state = state(client, alice)['state']
    observer_state = state(client, observer)['state']
    assert alice_state['my_vote'] == 'skip'
    assert alice_state['vote_count'] == 1
    assert observer_state['my_vote'] is None
    assert observer_state['vote_count'] == 1
    assert 'votes' not in alice_state
    assert 'votes' not in observer_state

    # Changing the vote replaces it; it does not add a second ballot.
    response = cast(client, alice, host['player_id'])
    assert response.status_code == 200
    assert response.json() == {'ok': True}
    assert state(client, alice)['state']['my_vote'] == host['player_id']
    assert state(client, alice)['state']['vote_count'] == 1


def test_contract_vote_before_voting_is_http_400_without_recording(client):
    """Lab 4: voting in phase round is rejected without mutating the tally."""
    host, alice = make_players(client, 2)
    assert cmd(client, host, 'start').status_code == 200
    assert state(client, alice)['phase'] == 'round'

    response = cast(client, alice, 'skip')
    assert response.status_code == 400
    assert response.json() == {'detail': 'Голосовать сейчас нельзя'}

    snapshot = state(client, alice)
    assert snapshot['phase'] == 'round'
    assert snapshot['state']['vote_count'] == 0
    assert snapshot['state']['my_vote'] is None
