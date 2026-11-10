import asyncio
import copy
import hmac
import os
import re
import secrets
from contextlib import asynccontextmanager
from collections import defaultdict
from typing import Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .db import Base, engine, SessionLocal, Pack, Room, Player
from .seed import ensure_seed
from .game import action, cast_vote, error, public_state, validate_pack

MAX_ROOMS=int(os.environ.get('MAX_ROOMS','2'))
PASSWORD=os.environ.get('ADMIN_PASSWORD','')

class Hub:
    def __init__(self): self.sockets=defaultdict(set)
    async def notify(self, room_id):
        stale=[]
        for ws in list(self.sockets[room_id]):
            try: await ws.send_json({'type':'sync'})
            except Exception: stale.append(ws)
        for ws in stale: self.sockets[room_id].discard(ws)
hub=Hub()

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with SessionLocal() as db: ensure_seed(db)
    yield

app=FastAPI(title='Bunker · Last Shelter API',version='0.3.0',lifespan=lifespan)

class CreateRoom(BaseModel):
    title:str=Field(min_length=2,max_length=90)
    nickname:str=Field(min_length=1,max_length=40)
    pack_id:str='basic'
    config:dict[str,Any]=Field(default_factory=dict)

class JoinRoom(BaseModel):
    nickname:str=Field(min_length=1,max_length=40)
    spectator:bool=False

class GameCommand(BaseModel):
    type:str
    data:dict[str,Any]=Field(default_factory=dict)

class VoteRequest(BaseModel):
    target:str=Field(min_length=1,max_length=40)

class SavePack(BaseModel):
    content:dict[str,Any]

class UpdateSettings(BaseModel):
    config:dict[str,Any]

class RenameRequest(BaseModel):
    nickname:str=Field(min_length=1,max_length=40)


def auth_admin(password):
    if not PASSWORD or PASSWORD in ('change-me-before-play','change-me'):
        error('Установите ADMIN_PASSWORD в .env перед редактированием паков',503)
    if not password or not hmac.compare_digest(password,PASSWORD): error('Неверный пароль администратора',403)

def load_room(db:Session,room_id:str,lock=False):
    query=select(Room).where(Room.id==room_id)
    if lock: query=query.with_for_update()
    room=db.scalars(query).first()
    if room is None: error('Комната не найдена',404)
    # refresh on mutations after row lock; no stale objects across requests
    _=room.players
    return room

def authorized(room:Room,token:str|None):
    if not token: error('Войдите в комнату',401)
    player=next((p for p in room.players if hmac.compare_digest(p.token,token)),None)
    if not player: error('Неизвестный токен игрока',401)
    return player

def clean_nick(s):
    s=s.strip()
    if not s: error('Введите ник')
    return s

def validate_config(values,pack):
    if not isinstance(values,dict): error('Некорректные настройки комнаты')
    allowed={'max_rounds':(0,1000000),'speech_seconds':(10,3600),'vote_seconds':(10,3600),'reveal_limit':(-1,20)}
    if set(values)-set(allowed): error('Неизвестный параметр настройки')
    for key,value in values.items():
        lo,hi=allowed[key]
        if type(value) is not int or not lo<=value<=hi: error(f'Некорректное значение {key} ({lo}–{hi})')
    return values

@app.get('/api/health')
def health(): return {'ok':True}

@app.get('/api/packs')
def packs():
    with SessionLocal() as db:
        return [{'id':p.id,'title':p.title,'revision':p.revision,'builtin':p.is_builtin,
                 'categories':len([c for c in p.content.get('categories',[]) if c.get('enabled',True)])}
                for p in db.scalars(select(Pack).order_by(Pack.title))]

@app.get('/api/packs/{pack_id}')
def get_pack(pack_id:str):
    with SessionLocal() as db:
        p=db.get(Pack,pack_id)
        if not p: error('Пак не найден',404)
        return {'id':p.id,'content':p.content,'revision':p.revision,'builtin':p.is_builtin}

@app.post('/api/packs')
def create_pack(body:SavePack,x_admin_password:str|None=Header(default=None)):
    auth_admin(x_admin_password)
    validate_pack(body.content)
    with SessionLocal() as db:
        pack_id=secrets.token_hex(6)
        p=Pack(id=pack_id,title=body.content['title'].strip(),content=body.content,revision=1,is_builtin=False)
        db.add(p);db.commit()
        return {'id':pack_id,'revision':1}

@app.put('/api/packs/{pack_id}')
def edit_pack(pack_id:str,body:SavePack,x_admin_password:str|None=Header(default=None)):
    auth_admin(x_admin_password)
    validate_pack(body.content)
    with SessionLocal() as db:
        p=db.get(Pack,pack_id)
        if not p: error('Пак не найден',404)
        if p.is_builtin: error('Базовый пак нельзя перезаписывать. Создайте его копию.')
        p.content=body.content;p.title=body.content['title'].strip();p.revision+=1
        db.commit()
        return {'id':p.id,'revision':p.revision}

@app.delete('/api/packs/{pack_id}')
def delete_pack(pack_id:str,x_admin_password:str|None=Header(default=None)):
    auth_admin(x_admin_password)
    with SessionLocal() as db:
        p=db.get(Pack,pack_id)
        if not p: error('Пак не найден',404)
        if p.is_builtin: error('Нельзя удалить базовый пак')
        db.delete(p);db.commit()
        return {'ok':True}

@app.get('/api/rooms')
def rooms():
    with SessionLocal() as db:
        records=db.scalars(select(Room).order_by(Room.id.desc())).all()
        return [{'id':r.id,'title':r.title,'phase':r.phase,'pack_title':r.pack_snapshot.get('title'),
                 'players':len([p for p in r.players if not p.spectator]),
                 'spectators':len([p for p in r.players if p.spectator])} for r in records]

@app.post('/api/rooms')
async def create_room(body:CreateRoom):
    with SessionLocal() as db:
        active=db.scalar(select(func.count()).select_from(Room).where(Room.phase!='finished'))
        if active>=MAX_ROOMS: error(f'Одновременно допускается не больше {MAX_ROOMS} активных комнат')
        pack=db.get(Pack,body.pack_id)
        if not pack: error('Пак не найден',404)
        config=validate_config(body.config,pack.content)
        player_id=secrets.token_hex(10)
        for _ in range(5):
            code=secrets.token_hex(3).upper()
            if not db.get(Room,code): break
        else: error('Не удалось создать код комнаты',500)
        room=Room(id=code,title=body.title.strip(),phase='lobby',host_id=player_id,
                  pack_id=pack.id,pack_snapshot=copy.deepcopy(pack.content),config=config,state={},undo_stack=[])
        p=Player(id=player_id,room_id=code,token=secrets.token_urlsafe(32),nickname=clean_nick(body.nickname),seat=0,spectator=False)
        db.add_all([room,p]);db.commit()
        return {'id':code,'token':p.token,'player_id':p.id}

@app.post('/api/rooms/{room_id}/join')
async def join_room(room_id:str,body:JoinRoom):
    with SessionLocal() as db:
        r=load_room(db,room_id,lock=True)
        spectator=body.spectator or r.phase!='lobby'
        if not spectator and len([p for p in r.players if not p.spectator])>=30: error('Слишком много игроков (лимит 30)')
        if len(r.players)>=60: error('Комната заполнена')
        nickname=clean_nick(body.nickname)
        if any(p.nickname.lower()==nickname.lower() for p in r.players): error('Такой ник уже занят')
        seat=max((p.seat for p in r.players),default=-1)+1
        p=Player(id=secrets.token_hex(10),room_id=r.id,token=secrets.token_urlsafe(32),nickname=nickname,seat=seat,spectator=spectator)
        db.add(p);db.commit()
        result={'id':r.id,'token':p.token,'player_id':p.id,'spectator':spectator}
    await hub.notify(room_id)
    return result

@app.get('/api/rooms/{room_id}')
def get_room(room_id:str,x_player_token:str|None=Header(default=None)):
    with SessionLocal() as db:
        r=load_room(db,room_id)
        player=authorized(r,x_player_token)
        return public_state(r,player)

@app.post('/api/rooms/{room_id}/command')
async def command(room_id:str,body:GameCommand,x_player_token:str|None=Header(default=None)):
    with SessionLocal() as db:
        r=load_room(db,room_id,lock=True)
        p=authorized(r,x_player_token)
        if p.spectator: error('Зрители не могут управлять игрой',403)
        action(r,p,body.type,body.data)
        db.commit()
    await hub.notify(room_id)
    return {'ok':True}

@app.post('/api/rooms/{room_id}/vote')
async def vote(room_id:str,body:VoteRequest,x_player_token:str|None=Header(default=None)):
    with SessionLocal() as db:
        r=load_room(db,room_id,lock=True)
        p=authorized(r,x_player_token)
        cast_vote(r,p,body.target)
        db.commit()
    await hub.notify(room_id)
    return {'ok':True}

@app.patch('/api/rooms/{room_id}/settings')
async def settings(room_id:str,body:UpdateSettings,x_player_token:str|None=Header(default=None)):
    with SessionLocal() as db:
        r=load_room(db,room_id,lock=True)
        p=authorized(r,x_player_token)
        if p.id!=r.host_id: error('Только ведущий может менять настройки',403)
        if r.phase!='lobby': error('Настройки меняются до начала игры')
        r.config=validate_config(body.config,r.pack_snapshot)
        db.commit()
    await hub.notify(room_id)
    return {'ok':True}

@app.patch('/api/rooms/{room_id}/nickname')
async def nickname(room_id:str,body:RenameRequest,x_player_token:str|None=Header(default=None)):
    with SessionLocal() as db:
        r=load_room(db,room_id,lock=True)
        p=authorized(r,x_player_token)
        value=clean_nick(body.nickname)
        if any(x.id!=p.id and x.nickname.lower()==value.lower() for x in r.players): error('Такой ник уже занят')
        p.nickname=value;db.commit()
    await hub.notify(room_id)
    return {'ok':True}

@app.delete('/api/rooms/{room_id}')
async def delete_room(room_id:str,x_admin_password:str|None=Header(default=None),x_player_token:str|None=Header(default=None)):
    with SessionLocal() as db:
        r=load_room(db,room_id,lock=True)
        if x_admin_password: auth_admin(x_admin_password)
        else:
            p=authorized(r,x_player_token)
            if p.id!=r.host_id: error('Только ведущий может удалить комнату',403)
        db.delete(r);db.commit()
    await hub.notify(room_id)
    return {'ok':True}

@app.websocket('/ws/rooms/{room_id}')
async def websocket(websocket:WebSocket,room_id:str):
    await websocket.accept()
    try:
        # First message authenticates socket: token is NEVER put into the WebSocket URL.
        hello=await asyncio.wait_for(websocket.receive_json(),timeout=12)
        token=hello.get('token') if isinstance(hello,dict) else None
        with SessionLocal() as db:
            room=load_room(db,room_id)
            authorized(room,token)
        hub.sockets[room_id].add(websocket)
        await websocket.send_json({'type':'sync'})
        while True:
            await websocket.receive_text() # optional keepalive messages
    except (WebSocketDisconnect,asyncio.TimeoutError,HTTPException,ValueError):
        try: await websocket.close()
        except Exception: pass
    finally:
        hub.sockets[room_id].discard(websocket)
