import React, {useCallback, useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {ArrowLeft, ArrowRight, Check, ChevronDown, Clock3, Copy, Download, Eye, FileUp, Pause, Play, Plus, RotateCcw, Settings2, Shield, ShieldAlert, Shuffle, Skull, Trash2, Users, Vote, X} from 'lucide-react';
import './style.css';

type PackCard=string|{text:string;effect?:string;bonus?:string;skill?:string};
type Category={id:string;name:string;enabled?:boolean;inventory?:boolean;medical?:boolean;experience?:'none'|'profession'|'hobby';experience_levels?:{name:string;duration:string;min_age?:number}[];draw_count?:number;items:PackCard[]};
type PackContent={title:string;categories:Category[];catastrophes:string[];bunker:Record<string,string[]>;settings:{max_rounds:number;speech_seconds:number;vote_seconds:number;bunker_fraction:number;reveal_limit:number;first_required_category:string}};
type PackSummary={id:string;title:string;revision:number;builtin:boolean;categories:number};
type PackResponse={id:string;content:PackContent;revision:number;builtin:boolean};
type RoomSummary={id:string;title:string;phase:string;pack_title:string;players:number;spectators:number};
type Card={id:string;category_id:string;category:string;value:string;effect?:string|null;bonus?:string;skill?:string;experience?:{name:string;duration:string};treatment?:string;revealed:boolean;used?:boolean};
type Person={id:string;nickname:string;seat:number;spectator:boolean;alive:boolean;host:boolean;revealed:Card[];card_count:number;voted:boolean};
type BunkerState={round:number;speaker_index:number;speaker_order:string[];timer:{remaining:number;until:number|null;running:boolean};vote_count:number;my_vote?:string;votes?:never;voting_candidates?:string[]|null;vote_attempt:number;vote_result?:string;catastrophe:string;bunker:Record<string,string>;capacity:number;initial_players:number;log:string[]};
type RoomView={id:string;title:string;phase:string;host_id:string;pack_id:string;pack_title:string;config:Record<string,number>;settings:Record<string,number>;state:BunkerState;players:Person[];me:{id:string;nickname:string;spectator:boolean;host:boolean;alive:boolean};own_hand:Card[];categories:{id:string;name:string;enabled:boolean;inventory:boolean;medical:boolean;experience:string;experience_levels:{name:string;duration:string}[]}[];can_undo:boolean};

const tokenKey=(room:string)=>`bunker-token:${room}`;
const getToken=(room:string)=>localStorage.getItem(tokenKey(room))||'';
function uri(){return decodeURIComponent(location.pathname.split('/').filter(Boolean)[1]||'');}
async function request<T>(url:string,method='GET',body?:unknown,opts?:{token?:string;password?:string}):Promise<T>{
  const res=await fetch('/api'+url,{method,headers:{'Content-Type':'application/json',...(opts?.token?{'X-Player-Token':opts.token}:{}),...(opts?.password?{'X-Admin-Password':opts.password}:{})},body:body===undefined?undefined:JSON.stringify(body)});
  if(!res.ok){let error=`HTTP ${res.status}`;try{const obj=await res.json();error=typeof obj.detail==='string'?obj.detail:JSON.stringify(obj.detail)}catch{}throw new Error(error)}
  return await res.json() as T;
}
const phaseLabel=(p:string)=>({lobby:'Ожидание',round:'Выступления',voting:'Голосование',finished:'Завершена'}[p]||p);
const clone=<T,>(v:T):T=>JSON.parse(JSON.stringify(v));
function storeNickname(name:string){localStorage.setItem('bunker-nickname',name.trim())}

const bunkerFieldLabels:Record<string,string>={
  location:'Местоположение',
  area:'Площадь',
  duration:'Автономность',
  food:'Провизия',
  water:'Вода',
  air:'Фильтрация и воздух',
  power:'Энергия',
  equipment:'Оборудование',
  defense:'Защита',
  medicine:'Медицина',
  comfort:'Бытовые условия',
  special:'Особенности',
  cache:'Найденные тайники',
};
function humanizeKey(key:string){return bunkerFieldLabels[key]||key.replace(/[_-]+/g,' ').replace(/\b\w/g,m=>m.toUpperCase())}
function splitListValue(value:string){return value.split(/\s*;\s*/).map(x=>x.trim()).filter(Boolean)}
const defaultExperience={
  profession:[['Новичок','до 3 месяцев'],['Стажёр','3 месяца — 1 год'],['Любитель','1–2 года'],['Опытный','2–5 лет'],['Профессионал','5–10 лет'],['Эксперт','более 10 лет']],
  hobby:[['Новичок','до 3 месяцев'],['Любитель','3 месяца — 1 год'],['Опытный','1–2 года'],['Продвинутый','2–5 лет'],['Мастер (гуру)','более 5 лет']],
};
const skillNames:Record<string,string>={medical_aid:'Оказать медицинскую помощь',find_item:'Найти предмет',discover_cache:'Найти склад в бункере'};
function CardMeta({card}:{card:Card}){
  return <>{card.experience&&<span className="experience-chip" title={card.experience.duration}>{card.experience.name} · {card.experience.duration}</span>}
    {card.bonus&&<div className="card-bonus"><span>ПРЕИМУЩЕСТВО</span>{card.bonus}</div>}
    {card.skill&&<div className="card-skill-info"><span>НАВЫК</span>{skillNames[card.skill]||card.skill}{card.used?' · использован':''}</div>}
    {card.treatment&&<span className="treatment-chip">✚ {card.treatment}</span>}
  </>;
}

function catastropheIntel(text:string){
  const lower=text.toLowerCase();
  const alerts:string[]=[];
  const needs:string[]=[];
  if(/холод|похолод|зима|мороз|снег/.test(lower)){alerts.push('На поверхности быстро растут риски переохлаждения и обморожения.');needs.push('Нужны тепло, топливо и утеплённое убежище.')}
  if(/вода|затоп|океан|шторм/.test(lower)){alerts.push('Чистая вода и сухие безопасные маршруты становятся критическим ресурсом.');needs.push('Важны фильтрация воды, герметичность и защита запасов.')}
  if(/пыль|пепел|токсин|атмосфер|дым|гриб/.test(lower)){alerts.push('Воздух снаружи опасен: фильтры и защита дыхания становятся вопросом жизни.');needs.push('Приоритет — вентиляция, маски и запас фильтров.')}
  if(/землетряс|удар|астероид|разруш/.test(lower)){alerts.push('Инфраструктура нестабильна, повторные обрушения и перебои снабжения вероятны.');needs.push('Понадобятся инструменты, медицина и навыки ремонта.')}
  if(/электроник|магнит|энерг|связ/.test(lower)){alerts.push('Связь и техника работают нестабильно, автономные решения ценятся особенно высоко.');needs.push('Приоритет — энергия, радиосвязь и ручные резервные инструменты.')}
  if(!alerts.length)alerts.push('Обстановка на поверхности быстро ухудшается, а любая ошибка будет стоить слишком дорого.');
  if(!needs.length)needs.push('Нужно сохранить запасы, дисциплину и людей, способных поддерживать бункер в рабочем состоянии.');
  return {summary:text,alerts,needs};
}

function App(){
  const [path,setPath]=useState(uri());const [view,setView]=useState<'rooms'|'packs'>('rooms');
  useEffect(()=>{const onPop=()=>setPath(uri());window.addEventListener('popstate',onPop);return ()=>window.removeEventListener('popstate',onPop)},[]);
  const navigate=(id='')=>{history.pushState({},'',id?`/room/${id}`:'/');setPath(id);setView('rooms')};
  return <div className="layout">
    <header className="topbar"><button className="brand" onClick={()=>navigate()}><div className="brand-icon"><Shield size={21}/></div><div><strong>ПОСЛЕДНИЙ <em>РУБЕЖ</em></strong><small>собери команду. переживи катастрофу.</small></div></button><div className="top-right"><span className="online-dot"/> <span className="micro">ЛОКАЛЬНЫЙ ИГРОВОЙ СЕРВЕР</span></div></header>
    <main>{path?<RoomPage id={path} onBack={()=>navigate()}/>:view==='rooms'?<Lobby onNavigate={navigate} openPacks={()=>setView('packs')}/>:<PackStudio goBack={()=>setView('rooms')}/>}</main>
    <footer className="footer"><span>LAST SHELTER / OPEN TABLETOP ENGINE</span><span>Ведущий управляет темпом · Решения принимают игроки</span></footer>
  </div>
}
function Badge({children,tone='muted'}:{children:React.ReactNode;tone?:string}){return <span className={`badge ${tone}`}>{children}</span>}
function Button({children,onClick,kind='ghost',disabled=false,small=false,title}:{children:React.ReactNode;onClick?:()=>void;kind?:string;disabled?:boolean;small?:boolean;title?:string}){return <button title={title} className={`btn ${kind} ${small?'small':''}`} disabled={disabled} onClick={onClick}>{children}</button>}
function Field({label,children}:{label:string;children:React.ReactNode}){return <label className="field"><span>{label}</span>{children}</label>}
function Notice({text,onClose}:{text:string;onClose:()=>void}){return <div role="alert" className="notice"><ShieldAlert size={17}/>{text}<button onClick={onClose}><X size={16}/></button></div>}
function Lobby({onNavigate,openPacks}:{onNavigate:(id:string)=>void;openPacks:()=>void}){
  const [rooms,setRooms]=useState<RoomSummary[]>([]),[packs,setPacks]=useState<PackSummary[]>([]),[nick,setNick]=useState(localStorage.getItem('bunker-nickname')||''),[title,setTitle]=useState('Новый бункер'),[pack,setPack]=useState('basic'),[join,setJoin]=useState<string|null>(null),[spectate,setSpectate]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const reload=useCallback(()=>{request<RoomSummary[]>('/rooms').then(setRooms).catch(e=>setError(e.message));request<PackSummary[]>('/packs').then(setPacks).catch(e=>setError(e.message))},[]);
  useEffect(()=>{reload();const t=setInterval(reload,8000);return ()=>clearInterval(t)},[reload]);
  async function create(){if(busy)return;setBusy(true);try{storeNickname(nick);const data=await request<{id:string;token:string}>('/rooms','POST',{title,nickname:nick,pack_id:pack});localStorage.setItem(tokenKey(data.id),data.token);onNavigate(data.id)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function enter(){if(!join)return;setBusy(true);try{if(getToken(join)){onNavigate(join);return}storeNickname(nick);const data=await request<{id:string;token:string}>(`/rooms/${join}/join`,'POST',{nickname:nick,spectator:spectate});localStorage.setItem(tokenKey(join),data.token);onNavigate(join)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  return <><section className="hero"><div className="eyebrow">ПРОТОКОЛ УБЕЖИЩЕ / 001</div><h1>Когда мир рухнет,<br/><span>кого ты возьмёшь с собой?</span></h1><p>Создавай комнаты, раскрывай карты, спорь за место под землёй. Никаких аккаунтов — только твоя компания и сложные решения.</p><div className="hero-stats"><div><strong>6—15</strong><span>рекомендуем игроков</span></div><div><strong>1/2</strong><span>мест в убежище</span></div><div><strong>∞</strong><span>вариантов историй</span></div></div></section>
  <div className="lobby-grid"><section className="panel"><div className="panel-heading"><div><div className="eyebrow">01 / НОВАЯ ПАРТИЯ</div><h2>Создать бункер</h2></div><Shield className="heading-icon" size={27}/></div><Field label="ВАШ ПОЗЫВНОЙ"><input maxLength={40} value={nick} onChange={e=>setNick(e.target.value)} placeholder="Как вас зовут?"/></Field><Field label="НАЗВАНИЕ КОМНАТЫ"><input value={title} maxLength={90} onChange={e=>setTitle(e.target.value)}/></Field><Field label="НАБОР КАРТ"><select value={pack} onChange={e=>setPack(e.target.value)}>{packs.map(p=><option value={p.id} key={p.id}>{p.title}</option>)}</select></Field><Button kind="primary" disabled={!nick.trim()||!title.trim()||busy} onClick={create}><Plus size={18}/> Создать комнату <ArrowRight size={17}/></Button></section>
  <section className="panel rooms-panel"><div className="panel-heading"><div><div className="eyebrow">02 / ОТКРЫТЫЙ СПИСОК</div><h2>Комнаты</h2></div><Badge tone="lime">{rooms.filter(r=>r.phase!=='finished').length} активных</Badge></div>{rooms.length===0?<div className="empty"><Users size={34}/><strong>Пока здесь пусто</strong><span>Самое время основать убежище.</span></div>:<div className="room-list">{rooms.map(r=><button key={r.id} className="room-item" onClick={()=>{setJoin(r.id);setSpectate(r.phase!=='lobby')}}><div className="room-symbol"><Shield size={20}/></div><div className="room-data"><strong>{r.title}</strong><small>{r.pack_title} · {r.id}</small></div><div className="room-count"><Users size={15}/> {r.players} <span>· {phaseLabel(r.phase)}</span></div><ArrowRight size={16}/></button>)}</div>}<div className="panel-bottom"><Button small onClick={reload}><RotateCcw size={15}/> Обновить список</Button><Button small onClick={openPacks}><Settings2 size={15}/> Управление паками</Button></div></section></div>
  <section className="rules-strip"><div><span className="eyebrow">КАК ЭТО РАБОТАЕТ</span><h3>Никто не знает всю правду.</h3></div><p>Каждый начинает со скрытыми характеристиками. Раскрывайте карты по своему выбору, обсуждайте, голосуйте за исключение — или пропустите голосование. Ведущий управляет временем, но не вашим решением.</p></section>
  {join&&<div className="modal-backdrop" onClick={()=>setJoin(null)}><div className="modal" onClick={e=>e.stopPropagation()}><div className="panel-heading"><h2>Вход в бункер <span className="text-accent">{join}</span></h2><button onClick={()=>setJoin(null)}><X/></button></div><Field label="ВАШ ПОЗЫВНОЙ"><input value={nick} onChange={e=>setNick(e.target.value)} autoFocus/></Field><label className="check"><input type="checkbox" checked={spectate} onChange={e=>setSpectate(e.target.checked)}/> Войти наблюдателем</label><p className="fine">Если партия уже идёт, новый участник автоматически становится зрителем. Для возврата к своей роли откройте комнату с того же браузера.</p><Button kind="primary" disabled={!nick.trim()||busy} onClick={enter}><ArrowRight size={16}/> Присоединиться</Button></div></div>}
  {error&&<Notice text={error} onClose={()=>setError('')}/>}
  </>
}
function formatClock(seconds:number){const s=Math.max(0,seconds);return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`}
function Timer({timer}:{timer:BunkerState['timer']}){const [,tick]=useState(0);useEffect(()=>{const t=setInterval(()=>tick(n=>n+1),500);return ()=>clearInterval(t)},[]);const left=timer?.running?Math.max(0,Math.ceil((timer.until||0)-Date.now()/1000)):timer?.remaining||0;return <div className={`clock ${left===0?'zero':''}`}><Clock3 size={20}/><strong>{formatClock(left)}</strong><small>{timer?.running&&left>0?'ИДЁТ ОТСЧЁТ':left===0?'ВРЕМЯ ВЫШЛО':'НА ПАУЗЕ'}</small></div>}
function RoomPage({id,onBack}:{id:string;onBack:()=>void}){
  const [room,setRoom]=useState<RoomView|null>(null);
  const [error,setError]=useState('');
  const [joinNick,setJoinNick]=useState(localStorage.getItem('bunker-nickname')||'');
  const [spectate,setSpectate]=useState(false);
  const [busy,setBusy]=useState(false);
  const [ability,setAbility]=useState<Card|null>(null);
  const [skillCard,setSkillCard]=useState<Card|null>(null);
  const [showHost,setShowHost]=useState(false);
  const [shownSettings,setShownSettings]=useState(false);
  const lastStage=useRef<{phase:string;round:number;speaker:number;voteAttempt:number;result:string|null}|null>(null);
  const token=getToken(id);
  const load=useCallback(async()=>{
    if(!token)return;
    try{setRoom(await request<RoomView>(`/rooms/${id}`,'GET',undefined,{token}))}
    catch(e){if((e as Error).message.includes('токен')||(e as Error).message.includes('Войдите')){
      localStorage.removeItem(tokenKey(id));setRoom(null);
    }else setError((e as Error).message)}
  },[id,token]);
  useEffect(()=>{load()},[load]);
  useEffect(()=>{
    if(!token)return;
    let timer:ReturnType<typeof setTimeout>|undefined;
    let ws:WebSocket|null=null;
    let active=true;
    function connect(){
      if(!active)return;
      ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/rooms/${id}`);
      ws.onopen=()=>ws?.send(JSON.stringify({token}));
      ws.onmessage=e=>{try{if(JSON.parse(e.data).type==='sync')load()}catch{}};
      ws.onclose=()=>{if(active)timer=setTimeout(connect,1500)};
    }
    connect();
    const fallback=setInterval(load,12000);
    return()=>{active=false;clearInterval(fallback);clearTimeout(timer);ws?.close()}
  },[id,token,load]);
  const cmd=async(type:string,data:Record<string,unknown>={})=>{
    setBusy(true);
    try{
      await request(`/rooms/${id}/command`,'POST',{type,data},{token});
      await load();setAbility(null);setSkillCard(null);
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  };
  // Прокрутка только при смене этапа, очереди выступлений или результата.
  // Обычные WebSocket-синхронизации, таймеры и раскрытие карт не двигают страницу.
  useEffect(()=>{
    if(!room)return;
    if(room.phase==='lobby'){lastStage.current={phase:'lobby',round:0,speaker:0,voteAttempt:0,result:null};return;}
    const current={phase:room.phase,round:room.state.round,speaker:room.state.speaker_index,
      voteAttempt:room.state.vote_attempt,result:room.state.vote_result||null};
    const previous=lastStage.current;
    lastStage.current=current;
    if(!previous)return; // При первом открытии комнаты не мешаем пользователю.
    if(current.phase===previous.phase&&current.round===previous.round&&
      current.speaker===previous.speaker&&current.voteAttempt===previous.voteAttempt&&current.result===previous.result)return;
    const destination=current.phase==='voting'?'game-vote':'game-progress';
    requestAnimationFrame(()=>document.getElementById(destination)?.scrollIntoView({behavior:'smooth',block:'start'}));
  },[room?.phase,room?.state?.round,room?.state?.speaker_index,room?.state?.vote_attempt,room?.state?.vote_result]);
  const vote=async(target:string)=>{
    setBusy(true);try{await request(`/rooms/${id}/vote`,'POST',{target},{token});await load()}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  };
  async function join(){
    setBusy(true);
    try{
      storeNickname(joinNick);
      const data=await request<{token:string}>(`/rooms/${id}/join`,'POST',{nickname:joinNick,spectator:spectate});
      localStorage.setItem(tokenKey(id),data.token);window.location.reload();
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function deleteRoom(){
    if(!confirm('Удалить эту комнату и все данные партии?'))return;
    try{await request(`/rooms/${id}`,'DELETE',undefined,{token});localStorage.removeItem(tokenKey(id));onBack()}
    catch(e){setError((e as Error).message)}
  }
  if(!token)return <section className="center-card panel"><Button small onClick={onBack}><ArrowLeft size={15}/> Назад</Button><span className="eyebrow">ВХОД ПО КОДУ {id}</span><h1>Подключиться к убежищу</h1><Field label="ПОЗЫВНОЙ"><input value={joinNick} onChange={e=>setJoinNick(e.target.value)} maxLength={40}/></Field><label className="check"><input type="checkbox" checked={spectate} onChange={e=>setSpectate(e.target.checked)}/> Только наблюдать</label><Button kind="primary" disabled={!joinNick.trim()||busy} onClick={join}>Войти <ArrowRight size={17}/></Button>{error&&<Notice text={error} onClose={()=>setError('')}/>}</section>;
  if(!room)return <div className="center-card panel"><h2>Подключение к комнате {id}…</h2><p>Если комната была удалена, вернитесь к списку.</p><Button onClick={onBack}><ArrowLeft size={15}/> К комнатам</Button>{error&&<Notice text={error} onClose={()=>setError('')}/>}</div>;
  const settings:Record<string,number>={...room.settings,...room.config};
  const active=room.players.filter(p=>!p.spectator&&p.alive);
  const participants=room.players.filter(p=>!p.spectator).sort((a,b)=>a.seat-b.seat);
  const spectators=room.players.filter(p=>p.spectator);
  const currentSpeaker=room.players.find(p=>p.id===room.state?.speaker_order?.[room.state.speaker_index % (room.state.speaker_order?.length||1)]);
  const me=room.me;
  return <>
    <div className="room-top"><Button small onClick={onBack}><ArrowLeft size={16}/> Комнаты</Button><div className="room-label"><span className="eyebrow">КОМНАТА / {room.id}</span><h1>{room.title}</h1><span className="fine">{room.pack_title} · {active.length} в лагере · {spectators.length} наблюдателей</span></div><div className="room-top-side"><Badge tone={room.phase==='finished'?'muted':'lime'}>{phaseLabel(room.phase)}</Badge><Button small onClick={()=>{copyRoomLink(location.href).catch(e=>setError((e as Error).message))}}><Copy size={15}/> Ссылка</Button></div></div>
    {room.phase!=='lobby'&&<nav className="game-jumpbar" aria-label="Разделы партии">
      <a href="#game-scenario">Сценарий</a><a href="#game-progress">Ход игры</a>
      {room.phase==='voting'&&<a href="#game-vote">Голосование</a>}
      <a href="#game-cards">Мои карты</a>{me.host&&<a href="#game-host">Ведущий</a>}
      <a href="#game-table">Общая таблица</a><a href="#game-players">Игроки</a>
    </nav>}
    {room.phase==='lobby'?<section className="lobby-room panel"><div className="panel-heading"><div><div className="eyebrow">ПОКА ВСЕ СОБИРАЮТСЯ</div><h2>Перед шлюзом</h2></div><Users className="heading-icon" size={30}/></div><p>Рекомендуем 6–15 человек. Скопируй ссылку, отправь друзьям в Discord и дождись всех.</p><div className="lobby-avatars">{room.players.map(p=><div className="lobby-person" key={p.id}><span className="avatar">{p.nickname[0].toUpperCase()}</span><div><strong>{p.nickname}</strong><small>{p.host?'Ведущий':p.spectator?'Наблюдатель':'Игрок'}</small></div>{me.host&&!p.host&&<button className="kick" title="Удалить из комнаты" onClick={()=>cmd('kick',{target_id:p.id})}><X size={15}/></button>}</div>)}</div>{me.host?<><div className="settings-row"><Button onClick={()=>setShownSettings(x=>!x)}><Settings2 size={16}/> Настройки партии <ChevronDown size={16}/></Button><Button kind="primary" onClick={()=>cmd('start')} disabled={active.length<2||busy}><Play size={17}/> Начать партию</Button></div>{shownSettings&&<SettingsForm id={id} token={token} settings={settings} onDone={()=>{load();setShownSettings(false)}} onError={setError}/>}<div className="danger-zone"><Button small kind="danger" onClick={deleteRoom}><Trash2 size={15}/> Удалить комнату</Button></div></>:<div className="hint"><Clock3 size={16}/> Ждём ведущего. Партия начнётся по его команде.</div>}</section>:<>
      <details className="panel experience-legend">
        <summary>Справка по стажу профессии и хобби <ChevronDown size={17}/></summary>
        <div className="experience-legend-grid">
          {(['profession','hobby'] as const).map(mode=>{
            const cat=room.categories.find(c=>c.enabled&&c.experience===mode);
            const levels=cat?.experience_levels?.length?cat.experience_levels:defaultExperience[mode].map(([name,duration])=>({name,duration}));
            return <div key={mode}><strong>{mode==='profession'?'Профессия':'Хобби'}</strong>
              <div className="experience-steps">{levels.map((level,i)=><div key={i}><b>{level.name}</b><span>{level.duration}</span></div>)}</div>
            </div>;
          })}
        </div>
        <p className="fine">Для пользовательских паков сроки и названия ступеней могут отличаться.</p>
      </details>
      <section id="game-scenario" className="scenario-grid compact-scenario scenario-stack">
        <div className="scenario-card catastrophe">
          <span className="eyebrow">КАТАСТРОФА</span>
          <h2>Обстановка на поверхности</h2>
          <p className="catastrophe-lead">{catastropheIntel(room.state.catastrophe).summary}</p>
          <div className="scenario-subgrid">
            <div className="scenario-subcard">
              <small>ПЕРВЫЕ ПОСЛЕДСТВИЯ</small>
              <ul>{catastropheIntel(room.state.catastrophe).alerts.map((item,index)=><li key={index}>{item}</li>)}</ul>
            </div>
            <div className="scenario-subcard">
              <small>ЧТО ОСОБЕННО ВАЖНО</small>
              <ul>{catastropheIntel(room.state.catastrophe).needs.map((item,index)=><li key={index}>{item}</li>)}</ul>
            </div>
          </div>
        </div>
        <div className="scenario-card bunker">
          <div className="between bunker-topline">
            <div>
              <span className="eyebrow">УБЕЖИЩЕ</span>
              <h2>Параметры бункера</h2>
            </div>
            <div className="capacity-badge">
              <strong>{room.state.capacity}</strong>
              <span>мест нужно сохранить из {room.state.initial_players}</span>
            </div>
          </div>
          <div className="bunker-stats">
            {Object.entries(room.state.bunker||{}).map(([k,v])=>{
              const items=splitListValue(String(v));
              return <div key={k} className="bunker-item">
                <small>{humanizeKey(k)}</small>
                {items.length>1?<ul>{items.map((item,index)=><li key={index}>{item}</li>)}</ul>:<strong>{String(v)}</strong>}
              </div>
            })}
          </div>
        </div>
      </section>
      <div className="game-sections">
        <div id="game-progress" className="section-anchor">
          <section className="panel situation dashboard-situation"><div className="situation-header"><div><span className="eyebrow">{room.phase==='finished'?'ИГРА ЗАВЕРШЕНА':`РАУНД ${room.state.round} · НЕОБЯЗАТЕЛЬНЫЙ ЭТАП`}</span><h2>{room.phase==='finished'?'Бункер закрыт':room.phase==='voting'?'Голосование':'Выступления'}</h2></div><Timer timer={room.state.timer}/></div>
            {room.phase==='round'&&<><div className="speaker-card"><span className="eyebrow">СЕЙЧАС ВЫСТУПАЕТ</span><div className="speaker-line"><span className="speaker-avatar">{currentSpeaker?.nickname[0]?.toUpperCase()||'?'}</span><div><strong>{currentSpeaker?.nickname||'Нет выступающих'}</strong><span>Раунды и таймеры — для удобства. Карты можно раскрывать в любое время.</span></div></div></div><div className="turn-sequence">{(room.state.speaker_order||[]).map((pid,index)=>{const p=room.players.find(x=>x.id===pid);return <div className={`sequence-item ${index===room.state.speaker_index?'active':''}`} key={pid}><span>{index+1}</span>{p?.nickname}</div>})}</div></>}
            {room.phase==='finished'&&<div className="winners"><h3>В убежище остаются</h3><div className="lobby-avatars">{active.map(p=><Badge tone="lime" key={p.id}><Shield size={13}/> {p.nickname}</Badge>)}</div></div>}
            {room.state.vote_result&&<div className="result"><ShieldAlert size={17}/>{room.state.vote_result}</div>}
          </section>
        </div>
        <div id="game-vote" className="section-anchor">
          {room.phase==='voting'&&<section className="panel voting-panel"><div className="panel-heading"><div><span className="eyebrow">РЕШЕНИЕ ЛАГЕРЯ</span><h2>{room.state.vote_attempt===2?'Второй тур':'Голосование'}</h2></div><Vote size={22}/></div><p className="fine">Проголосовали: {room.state.vote_count} / {active.length}. Голоса скрыты до подсчёта.</p>{me.alive&&!me.spectator?<div className="vote-options">{active.filter(p=>!room.state.voting_candidates||room.state.voting_candidates.includes(p.id)).map(p=><button key={p.id} disabled={busy} onClick={()=>vote(p.id)} className={`vote-option ${room.state.my_vote===p.id?'chosen':''}`}>{p.nickname}{room.state.my_vote===p.id&&<Check size={17}/>}</button>)}<button disabled={busy} className={`vote-option skip ${room.state.my_vote==='skip'?'chosen':''}`} onClick={()=>vote('skip')}><X size={14}/> Пропустить голосование {room.state.my_vote==='skip'&&<Check size={17}/>}</button></div>:<p className="fine">Наблюдатели и исключённые игроки не голосуют.</p>}</section>}
        </div>
        <div id="game-cards" className="section-anchor">
          <section className="panel hand dashboard-hand"><div className="panel-heading"><div><span className="eyebrow">ЛИЧНОЕ ДЕЛО / {me.nickname}</span><h2>Мои характеристики</h2></div><Badge tone={me.alive&&!me.spectator?'lime':'muted'}>{me.spectator?'Наблюдатель':me.alive?'В лагере':'Исключён'}</Badge></div>
            {me.spectator?<div className="empty"><Eye size={30}/>Зритель видит только открытые характеристики.</div>:<><p className="fine">Открывай любую карту в своём темпе. Во время партии спецвозможность срабатывает при раскрытии. После исключения или завершения игры карту можно открыть без выполнения эффекта.</p><div className="my-categories">{room.categories.filter(cat=>cat.enabled&&room.own_hand.some(c=>c.category_id===cat.id)).map(cat=><div className="my-category" key={cat.id}><div className="my-category-title"><span>{cat.name}</span><small>{room.own_hand.filter(c=>c.category_id===cat.id).length} карт.</small></div><div className="my-category-cards">{room.own_hand.filter(c=>c.category_id===cat.id).map(c=><div className={`my-card ${c.revealed?'is-open':''}`} key={c.id}><div className="my-card-content"><strong>{c.value}</strong><CardMeta card={c}/>{c.effect&&<small><Shuffle size={12}/> {c.revealed?(c.used?'Способность использована':'Эффект не применялся'):(me.alive&&room.phase!=='finished'?'Способность при раскрытии':'Только раскрытие, без эффекта')}</small>}</div><div className="my-card-action">{c.revealed?<><Badge tone="lime"><Eye size={13}/> Открыто</Badge>{c.skill&&me.alive&&room.phase!=='finished'&&!c.used&&<Button small kind="primary" disabled={busy} onClick={()=>setSkillCard(c)}><Plus size={14}/> {skillNames[c.skill]||'Использовать навык'}</Button>}</>:<Button small disabled={busy} onClick={()=>c.effect&&me.alive&&room.phase!=='finished'?setAbility(c):cmd('reveal',{card_id:c.id})}><Eye size={14}/> {c.effect&&me.alive&&room.phase!=='finished'?'Раскрыть и применить':'Раскрыть'}</Button>}</div></div>)}</div></div>)}</div></>}
          </section>
        </div>
        <div id="game-host" className="section-anchor host-section">
          {me.host&&<><div className="panel host-quick"><span className="eyebrow">БЫСТРЫЕ ДЕЙСТВИЯ ВЕДУЩЕГО</span><div className="quick-buttons"><Button small kind="primary" disabled={busy||room.phase!=='round'} onClick={()=>cmd('next_speaker')}><ArrowRight size={15}/> Следующий</Button><Button small disabled={busy||room.phase==='finished'} onClick={()=>cmd('next_round')}><Shuffle size={15}/> Раунд +1</Button><Button small disabled={busy||room.phase==='finished'} onClick={()=>cmd('open_vote')}><Vote size={15}/> Голосование</Button><Button small disabled={busy||room.phase!=='voting'||!room.state.vote_count} onClick={()=>cmd('resolve_vote')}><Check size={15}/> Итоги</Button></div></div><div className="host-toolbar"><button onClick={()=>setShowHost(x=>!x)}><Settings2 size={17}/> Управление партией <ChevronDown size={16} className={showHost?'rotated':''}/></button></div>{showHost&&<HostPanel room={room} cmd={cmd} busy={busy} close={()=>setShowHost(false)}/>}</>}
        </div>
        <div id="game-players" className="section-anchor">
          <section className="panel participants-panel"><div className="panel-heading"><h2>Игроки</h2><Badge>{active.length} активных</Badge></div><div className="mini-players">{participants.map(p=><div className={`mini-player ${p.alive?'':'is-out'}`} key={p.id}><span className="avatar">{p.nickname[0].toUpperCase()}</span><span>{p.nickname}{p.host&&<small> · ведущий</small>}</span>{!p.alive?<Skull size={15}/>:p.voted&&room.phase==='voting'?<Vote size={15}/>:<span className="alive-dot"/>}</div>)}</div>{spectators.length>0&&<p className="fine">Наблюдают: {spectators.map(p=>p.nickname).join(', ')}</p>}</section>
        </div>
      </div>
      <section id="game-table" className="panel board-panel section-anchor"><div className="panel-heading"><div><span className="eyebrow">ОБЩАЯ ИНФОРМАЦИЯ</span><h2>Таблица раскрытых характеристик</h2><p className="fine">Строки — игроки, столбцы — характеристики. Дополнительные карты одной категории остаются в той же ячейке. Текст внутри ячеек переносится на новые строки, чтобы таблица влезала по ширине без лишнего горизонтального скролла.</p></div><Badge tone="lime"><Eye size={13}/> Только раскрытое</Badge></div>
        <div className="board-scroll" tabIndex={0} role="region" aria-label="Таблица открытых характеристик игроков">
          <table className="character-matrix">
            <thead><tr><th className="matrix-player">Игрок</th>{room.categories.filter(c=>c.enabled).map(cat=><th key={cat.id} className="matrix-header-category">{cat.name}</th>)}</tr></thead>
            <tbody>{participants.map(p=><tr key={p.id} className={p.alive?'':'player-excluded'}>
              <th className="matrix-player" scope="row"><span className="matrix-person"><span className="avatar">{p.nickname[0].toUpperCase()}</span><span>{p.nickname}{!p.alive&&<small>Исключён</small>}</span></span></th>
              {room.categories.filter(c=>c.enabled).map(cat=>{const cards=p.revealed.filter(c=>c.category_id===cat.id);return <td key={cat.id}>{cards.length?<div className="matrix-values">{cards.map(c=><div className="matrix-value" key={c.id}><b>{c.value}</b><CardMeta card={c}/></div>)}</div>:<span className="matrix-hidden">—</span>}</td>})}
            </tr>)}</tbody>
          </table>
        </div>
      </section>
      <details className="panel logs dashboard-logs"><summary><span><Clock3 size={17}/> Хроника событий</span><Badge>{room.state.log?.length||0}</Badge></summary><div className="log-list">{(room.state.log||[]).slice().reverse().map((line,i)=><p key={i}><span>●</span>{line}</p>)}</div></details>
    </>}
      {skillCard&&room&&<SkillDialog room={room} card={skillCard} onClose={()=>setSkillCard(null)} onApply={data=>cmd('skill',data)}/>}
      {ability&&<EffectDialog room={room} actorId={me.id} effect={ability.effect||''} card={ability} onClose={()=>setAbility(null)} onApply={data=>cmd('reveal',{...data,source_card_id:ability.id})}/>}
    {error&&<Notice text={error} onClose={()=>setError('')}/>}
  </>;
}
function SettingsForm({id,token,settings,onDone,onError}:{id:string;token:string;settings:Record<string,number>;onDone:()=>void;onError:(s:string)=>void}){
  const [local,setLocal]=useState({speech_seconds:settings.speech_seconds||60,vote_seconds:settings.vote_seconds||60});
  return <div className="settings-form"><p className="fine">Раунды необязательны и не ограничены по количеству. Раскрывать карты можно свободно, в любом порядке.</p>{([['speech_seconds','Таймер выступления, сек'],['vote_seconds','Таймер голосования, сек']] as const).map(([key,label])=><Field key={key} label={label}><input type="number" min="10" max="3600" value={local[key]} onChange={e=>setLocal(v=>({...v,[key]:Number(e.target.value)}))}/></Field>)}<Button kind="primary" onClick={()=>request(`/rooms/${id}/settings`,'PATCH',{config:local},{token}).then(onDone).catch(e=>onError(e.message))}><Check size={16}/> Сохранить настройки</Button></div>
}
const effects:Record<string,string>={add_random:'Добавить случайную карту',reroll:'Перегенерировать карту',swap:'Обменять две карты',steal:'Украсть предмет',revive:'Вернуть игрока'};
function EffectDialog({room,actorId,effect='add_random',card,manual=false,onClose,onApply}:{room:RoomView;actorId?:string;effect?:string;card?:Card;manual?:boolean;onClose:()=>void;onApply:(data:Record<string,unknown>)=>void}){
  const [chosenEffect,setChosenEffect]=useState(effect);
  const [chosenActor,setChosenActor]=useState(manual?'':actorId||room.me.id);
  const [category,setCategory]=useState(room.categories.find(c=>c.enabled)?.id||'');
  const [own,setOwn]=useState(''),[target,setTarget]=useState(''),[other,setOther]=useState(''),[itemCategory,setItemCategory]=useState('');
  const activeEffect=manual?chosenEffect:effect;
  const actor=room.players.find(p=>p.id===chosenActor);
  // Ведущий не получает чужие закрытые карты через API: для ручного
  // переролла и обмена допустима случайная закрытая карта, но не её значение.
  const actorCards=chosenActor===room.me.id?room.own_hand:actor?.revealed||[];
  const inventoryIds=new Set(room.categories.filter(c=>c.inventory).map(c=>c.id));
  const active=room.players.filter(p=>!p.spectator&&p.alive);
  const availableTargets=room.players.filter(p=>!p.spectator&&p.id!==chosenActor&&(activeEffect==='revive'?!p.alive:p.alive)&&(activeEffect!=='steal'||p.revealed.some(c=>c.revealed&&inventoryIds.has(c.category_id))));
  const otherCards=target===room.me.id?room.own_hand:(room.players.find(p=>p.id===target)?.revealed||[]);
  const visibleItems=otherCards.filter(c=>c.revealed&&inventoryIds.has(c.category_id));
  const inventoryCategories=room.categories.filter(cat=>cat.inventory&&visibleItems.some(c=>c.category_id===cat.id));
  const listedCards=activeEffect==='steal'?visibleItems.filter(c=>c.category_id===itemCategory):otherCards.filter(c=>c.revealed);
  const needsOwn=['reroll','swap'].includes(activeEffect),needsTarget=['swap','steal','revive'].includes(activeEffect);
  const needsOther=['swap','steal'].includes(activeEffect);
  const canSubmit=!!chosenActor&&(!needsOwn||!!own)&&(!needsTarget||!!target)&&(!needsOther||!!other)&&(activeEffect!=='add_random'||!!category)&&(activeEffect!=='steal'||!!itemCategory);
  const chooseEffect=(value:string)=>{setChosenEffect(value);setTarget('');setOther('');setOwn('');setItemCategory('')};
  const chooseActor=(value:string)=>{setChosenActor(value);setTarget('');setOther('');setOwn('');setItemCategory('')};
  return <div className="modal-backdrop" onClick={onClose}>
    <div className="modal wide ability-dialog" onClick={e=>e.stopPropagation()}>
      <div className="panel-heading"><div><span className="eyebrow">{manual?'ДЕЙСТВИЕ ВЕДУЩЕГО':'СПЕЦВОЗМОЖНОСТЬ'}</span><h2>{manual?'Применить способность':effects[activeEffect]||activeEffect}</h2></div><button onClick={onClose} title="Закрыть"><X/></button></div>
      {card&&<p className="fine">{card.value}</p>}
      {manual&&<Field label="ТИП ДЕЙСТВИЯ"><select value={chosenEffect} onChange={e=>chooseEffect(e.target.value)}>{Object.entries(effects).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></Field>}
      {manual&&<Field label={activeEffect==='steal'?'КОМУ ПЕРЕДАТЬ ПРЕДМЕТ':activeEffect==='swap'?'ПЕРВЫЙ УЧАСТНИК (ОТДАЁТ СВОЮ КАРТУ)':activeEffect==='reroll'?'ЧЬЮ КАРТУ ИЗМЕНИТЬ':'К КОМУ ПРИМЕНИТЬ ЭФФЕКТ'}>
        <select value={chosenActor} onChange={e=>chooseActor(e.target.value)}><option value="">Выберите игрока</option>{active.map(p=><option key={p.id} value={p.id}>{p.nickname}</option>)}</select>
      </Field>}
      {manual&&activeEffect==='steal'&&<p className="fine">Предмет перейдёт выбранному игроку от другого участника. Оба участника задаются отдельно.</p>}
      {activeEffect==='add_random'&&<Field label="КАТЕГОРИЯ НОВОЙ КАРТЫ"><select value={category} onChange={e=>setCategory(e.target.value)}>{room.categories.filter(c=>c.enabled).map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>}
      {needsOwn&&<Field label={activeEffect==='swap'?'КАРТА ПЕРВОГО УЧАСТНИКА':'КАРТА ДЛЯ ЗАМЕНЫ'}>
        <select value={own} onChange={e=>setOwn(e.target.value)} disabled={!chosenActor}><option value="">Выберите карту</option>
          {manual&&chosenActor!==room.me.id&&<option value="__random_hidden__">Случайная закрытая карта (без просмотра)</option>}
          {actorCards.map(c=><option key={c.id} value={c.id}>{c.category}: {c.value}</option>)}
        </select>
      </Field>}
      {needsTarget&&<Field label={activeEffect==='steal'?'У КОГО УКРАСТЬ':activeEffect==='swap'?'ВТОРОЙ УЧАСТНИК':'КОГО ВЕРНУТЬ В ИГРУ'}>
        <select value={target} onChange={e=>{setTarget(e.target.value);setOther('');setItemCategory('')}} disabled={!chosenActor}><option value="">Выберите игрока</option>{availableTargets.map(p=><option key={p.id} value={p.id}>{p.nickname}</option>)}</select>
      </Field>}
      {activeEffect==='steal'&&<p className="fine">В списке только игроки с раскрытыми предметами. Закрытые характеристики, профессии и прочие неинвентарные карты украсть нельзя.</p>}
      {activeEffect==='steal'&&<Field label="ИЗ КАКОЙ КАТЕГОРИИ ПРЕДМЕТ"><select value={itemCategory} onChange={e=>{setItemCategory(e.target.value);setOther('')}} disabled={!target}><option value="">Выберите категорию</option>{inventoryCategories.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select></Field>}
      {needsOther&&<Field label={activeEffect==='steal'?'КАКОЙ ОТКРЫТЫЙ ПРЕДМЕТ ЗАБРАТЬ':'КАРТА ВТОРОГО УЧАСТНИКА'}>
        <select value={other} onChange={e=>setOther(e.target.value)} disabled={!target||(activeEffect==='steal'&&!itemCategory)}><option value="">Выберите {activeEffect==='steal'?'предмет':'карту'}</option>
          {activeEffect==='swap'&&<option value="__random_hidden__">Случайная закрытая карта (без просмотра)</option>}
          {listedCards.map(c=><option key={c.id} value={c.id}>{c.category}: {c.value}</option>)}
        </select>
      </Field>}
      {activeEffect==='steal'&&target&&!visibleItems.length&&<p className="fine">У выбранного игрока пока нет раскрытых предметов.</p>}
      <div className="modal-actions"><Button onClick={onClose}>Отмена</Button><Button kind="primary" disabled={!canSubmit} onClick={()=>onApply({category_id:category,card_id:own,target_id:target,target_card_id:other,...(manual?{actor_id:chosenActor,effect:activeEffect}:{})})}><Check size={16}/> {card?'Раскрыть и применить':'Применить к выбранным'}</Button></div>
    </div>
  </div>;
}
function SkillDialog({room,card,manual=false,onClose,onApply}:{room:RoomView;card?:Card;manual?:boolean;onClose:()=>void;onApply:(data:Record<string,unknown>)=>void}){
  const [actorId,setActorId]=useState(manual?'':room.me.id);
  const [sourceId,setSourceId]=useState(card?.id||'');
  const [targetId,setTargetId]=useState('');
  const [healthId,setHealthId]=useState('');
  const [categoryId,setCategoryId]=useState('');
  const active=room.players.filter(p=>p.alive&&!p.spectator);
  const actor=room.players.find(p=>p.id===actorId);
  const available=(actorId===room.me.id?room.own_hand:actor?.revealed||[]).filter(c=>c.revealed&&c.skill&&!c.used);
  const source=manual?available.find(c=>c.id===sourceId):card;
  const inventory=room.categories.filter(c=>c.enabled&&c.inventory);
  const healthIds=new Set(room.categories.filter(c=>c.medical).map(c=>c.id));
  const patient=room.players.find(p=>p.id===targetId);
  const health=(targetId===room.me.id?room.own_hand:patient?.revealed||[]).filter(c=>c.revealed&&healthIds.has(c.category_id)&&!c.treatment&&!['абсолютно здоров','спортивная форма','отличный иммунитет'].includes(c.value.toLowerCase()));
  const canSubmit=!!actorId&&!!source?.skill&&(source.skill==='find_item'?!!categoryId:source.skill==='discover_cache'?true:!!targetId&&!!healthId);
  return <div className="modal-backdrop" onClick={onClose}>
    <div className="modal wide" onClick={e=>e.stopPropagation()}>
      <div className="panel-heading"><div><span className="eyebrow">НАВЫК ПЕРСОНАЖА</span><h2>Применить навык</h2></div><button onClick={onClose}><X/></button></div>
      {manual&&<Field label="КТО ПРИМЕНЯЕТ"><select value={actorId} onChange={e=>{setActorId(e.target.value);setSourceId('');setTargetId('');setHealthId('');setCategoryId('')}}><option value="">Выберите игрока</option>{active.map(p=><option key={p.id} value={p.id}>{p.nickname}</option>)}</select></Field>}
      {manual&&<Field label="ИЗ КАКОЙ РАСКРЫТОЙ КАРТЫ"><select value={sourceId} onChange={e=>{setSourceId(e.target.value);setTargetId('');setHealthId('');setCategoryId('')}} disabled={!actorId}><option value="">Выберите навык</option>{available.map(c=><option key={c.id} value={c.id}>{c.category}: {c.value} — {skillNames[c.skill||'']||c.skill}</option>)}</select></Field>}
      {source&&<div className="skill-dialog-description"><strong>{source.value} · {skillNames[source.skill||'']||source.skill}</strong><p>{source.bonus||'Навык из карты персонажа'}</p><p className="fine">Одно применение на карту, пока идёт партия. Ведущий может отменить результат.</p></div>}
      {source?.skill==='find_item'&&<Field label="ГДЕ НАЙТИ ПРЕДМЕТ"><select value={categoryId} onChange={e=>setCategoryId(e.target.value)}><option value="">Выберите категорию инвентаря</option>{inventory.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>}
      {source?.skill==='discover_cache'&&<p className="fine">Система найдёт случайный запас оборудования из пака и добавит его в общий список вещей бункера. Если доступных находок не осталось, действие не потратится.</p>}
      {source?.skill==='medical_aid'&&<><Field label="КОМУ ОКАЗАТЬ ПОМОЩЬ"><select value={targetId} onChange={e=>{setTargetId(e.target.value);setHealthId('')}}><option value="">Выберите игрока</option>{active.map(p=><option key={p.id} value={p.id}>{p.nickname}</option>)}</select></Field>
        <Field label="ПО КАКОЙ РАСКРЫТОЙ КАРТЕ ЗДОРОВЬЯ"><select value={healthId} onChange={e=>setHealthId(e.target.value)} disabled={!targetId}><option value="">Выберите состояние</option>{health.map(c=><option key={c.id} value={c.id}>{c.value}</option>)}</select></Field>
        <p className="fine">Медицинская помощь стабилизирует состояние, но не удаляет диагноз.</p>
      </>}
      <div className="modal-actions"><Button onClick={onClose}>Отмена</Button><Button kind="primary" disabled={!canSubmit} onClick={()=>onApply({source_card_id:source?.id,category_id:categoryId,target_id:targetId,target_card_id:healthId,...(manual?{actor_id:actorId}:{})})}><Check size={16}/> Использовать</Button></div>
    </div>
  </div>;
}
function HostPanel({room,cmd,busy,close}:{room:RoomView;cmd:(kind:string,data?:Record<string,unknown>)=>void;busy:boolean;close:()=>void}){
  const [seconds,setSeconds]=useState(room.config.speech_seconds||room.settings.speech_seconds||60),[showEffect,setShowEffect]=useState(false),[showSkill,setShowSkill]=useState(false),[target,setTarget]=useState('');
  const alive=room.players.filter(p=>!p.spectator&&p.alive),out=room.players.filter(p=>!p.spectator&&!p.alive);
  return <section className="panel host-panel"><div className="panel-heading"><div><span className="eyebrow">ЦЕНТР УПРАВЛЕНИЯ</span><h2>Панель ведущего</h2></div><button onClick={close} title="Свернуть"><X size={20}/></button></div><div className="host-grid"><div className="host-group"><h3>Ход партии</h3><div className="action-wrap"><Button small kind="primary" disabled={busy||room.phase!=='round'} onClick={()=>cmd('next_speaker')}><ArrowRight size={15}/> Следующий игрок</Button><Button small disabled={busy||room.phase==='finished'} onClick={()=>cmd('next_round')}><Shuffle size={15}/> Следующий раунд</Button><Button small disabled={busy||room.phase==='finished'} onClick={()=>cmd('open_vote')}><Vote size={15}/> Новое голосование</Button><Button small disabled={busy||room.phase!=='voting'||room.state.vote_count===0} onClick={()=>cmd('resolve_vote')}><Check size={15}/> Подсчитать голоса</Button><Button small disabled={busy||room.phase==='finished'} onClick={()=>{if(confirm('Завершить партию?'))cmd('finish')}}><Shield size={15}/> Завершить партию</Button></div></div><div className="host-group"><h3>Таймер</h3><div className="action-wrap"><input className="seconds" type="number" min="0" max="3600" value={seconds} onChange={e=>setSeconds(Number(e.target.value))}/><Button small onClick={()=>cmd('timer',{mode:'start',seconds})}><Play size={15}/> Запустить</Button><Button small onClick={()=>cmd('timer',{mode:'pause'})}><Pause size={15}/> Пауза</Button><Button small onClick={()=>cmd('timer',{mode:'resume'})}><Play size={15}/> Продолжить</Button></div></div><div className="host-group"><h3>Управление участниками</h3><div className="action-wrap"><select value={target} onChange={e=>setTarget(e.target.value)}><option value="">Выберите участника</option>{room.players.filter(p=>!p.spectator).map(p=><option key={p.id} value={p.id}>{p.nickname} · {p.alive?'в лагере':'исключён'}</option>)}</select><Button small disabled={!alive.some(p=>p.id===target)} onClick={()=>cmd('exclude',{target_id:target})}><Skull size={15}/> Исключить</Button><Button small disabled={!out.some(p=>p.id===target)} onClick={()=>cmd('restore',{target_id:target})}>Вернуть</Button></div></div><div className="host-group"><h3>Способности и откат</h3><p className="fine">Выбери тип способности и участников прямо в окне — ведущий не назначается получателем автоматически.</p><div className="action-wrap"><Button small disabled={busy||!alive.length||room.phase==='finished'} onClick={()=>setShowEffect(true)}><Plus size={15}/> Применить эффект вручную</Button><Button small disabled={busy||!alive.length||room.phase==='finished'} onClick={()=>setShowSkill(true)}><Plus size={15}/> Навык профессии / хобби</Button><Button small kind="danger" disabled={busy||!room.can_undo} onClick={()=>cmd('undo')}><RotateCcw size={15}/> Отменить последнее</Button></div></div></div><p className="fine">Таймер не двигает игру сам. Ведущий запускает следующий ход и раунд вручную. Откат работает для игровых изменений (последние 35 действий).</p>
    {showSkill&&<SkillDialog room={room} manual onClose={()=>setShowSkill(false)} onApply={data=>{cmd('skill',data);setShowSkill(false)}}/>}
    {showEffect&&<EffectDialog room={room} manual onClose={()=>setShowEffect(false)} onApply={data=>{cmd('host_effect',data);setShowEffect(false)}}/>}
  </section>;
}

function parseItems(s:string):PackCard[]{return s.split('\n').map(x=>x.trim()).filter(Boolean).map(line=>{
  const pieces=line.split('||');
  if(pieces.length>1){const [text,bonus,skill]=pieces.map(piece=>piece.trim());return {text,bonus:bonus||'',...(pieces.length>2?{skill:skill||''}:{})};}
  const parts=line.split(' => ');
  return parts.length>1&&effects[parts.at(-1)||'']?{text:parts.slice(0,-1).join(' => '),effect:parts.at(-1)||''}:line;
})}
function showItems(items:PackCard[]){return items.map(x=>{
  if(typeof x==='string')return x;
  if(x.effect)return `${x.text} => ${x.effect}`;
  if(x.bonus!==undefined||x.skill!==undefined)return `${x.text} || ${x.bonus||''}${x.skill!==undefined?` || ${x.skill}`:''}`;
  return x.text;
}).join('\n')}
function parseExperienceLevels(value:string){return value.split('\n').map(x=>x.trim()).filter(Boolean).map(x=>{const [name,duration]=x.split(' | ').map(t=>t.trim());return {name:name||'',duration:duration??''};})}
function showExperienceLevels(levels:{name:string;duration:string}[]){return levels.map(l=>`${l.name} | ${l.duration}`).join('\n')}
function packKey(name:string){const clean=name.toLowerCase().replace(/[^a-z0-9_-]/g,'_').replace(/_+/g,'_').replace(/^_+|_+$/g,'');return clean||`custom_${Math.random().toString(36).slice(2,8)}`}
async function copyRoomLink(link:string){
  if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(link);return}
  const input=document.createElement('textarea');input.value=link;input.style.position='fixed';input.style.opacity='0';document.body.appendChild(input);input.select();
  const copied=document.execCommand('copy');input.remove();
  if(!copied)throw new Error('Скопируйте ссылку из адресной строки браузера');
}
function downloadJson(filename:string,content:unknown){const blob=new Blob([JSON.stringify(content,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename;a.click();URL.revokeObjectURL(url)}
function PackStudio({goBack}:{goBack:()=>void}){
  const [rooms,setRooms]=useState<RoomSummary[]>([]),[packs,setPacks]=useState<PackSummary[]>([]),[chosen,setChosen]=useState('basic'),[current,setCurrent]=useState<PackContent|null>(null),[builtin,setBuiltin]=useState(true),[password,setPassword]=useState(sessionStorage.getItem('bunker-admin-password')||''),[error,setError]=useState(''),[message,setMessage]=useState(''),[raw,setRaw]=useState(false),[rawJson,setRawJson]=useState('');
  const reload=()=>{request<PackSummary[]>('/packs').then(setPacks).catch(e=>setError(e.message));request<RoomSummary[]>('/rooms').then(setRooms).catch(e=>setError(e.message))};
  useEffect(()=>{reload()},[]);
  useEffect(()=>{request<PackResponse>(`/packs/${chosen}`).then(p=>{setCurrent(clone(p.content));setBuiltin(p.builtin);setRawJson(JSON.stringify(p.content,null,2))}).catch(e=>setError(e.message))},[chosen]);
  const mutate=(fn:(p:PackContent)=>void)=>{setCurrent(prev=>{if(!prev)return prev;const copy=clone(prev);fn(copy);return copy})};
  const save=async(create:boolean)=>{if(!current)return;try{sessionStorage.setItem('bunker-admin-password',password);const content=raw?JSON.parse(rawJson):current;const result=await request<{id:string}>(create?'/packs':`/packs/${chosen}`,create?'POST':'PUT',{content},{password});setMessage(create?'Создан новый пак':'Пак сохранён');setCurrent(clone(content));setRawJson(JSON.stringify(content,null,2));reload();setChosen(result.id)}catch(e){setError((e as Error).message)}};
  const importFile=async(file?:File)=>{if(!file)return;try{const json=JSON.parse(await file.text());const obj=json.content||json;setCurrent(obj);setBuiltin(true);setRawJson(JSON.stringify(obj,null,2));setRaw(false);setMessage('JSON импортирован в редактор. Для сохранения создайте новый пак.')}catch(e){setError(`Невозможно импортировать файл: ${(e as Error).message}`)}};
  const deleteRoom=async(id:string)=>{if(!confirm('Удалить комнату '+id+' без возможности восстановить?'))return;try{await request(`/rooms/${id}`,'DELETE',undefined,{password});setMessage('Комната удалена');reload()}catch(e){setError((e as Error).message)}};
  const updateCat=(index:number,field:keyof Category,value:unknown)=>mutate(p=>{(p.categories[index] as unknown as Record<string,unknown>)[field]=value});
  const moveCat=(i:number,d:number)=>mutate(p=>{const j=i+d;if(j>=0&&j<p.categories.length){const cat=p.categories.splice(i,1)[0];p.categories.splice(j,0,cat)}});
  return <><div className="room-top"><Button onClick={goBack}><ArrowLeft size={17}/> Комнаты</Button><div className="room-label"><span className="eyebrow">МАСТЕРСКАЯ СЦЕНАРИЕВ</span><h1>Редактор паков</h1><span className="fine">Меняй категории, порядок, сценарии и содержимое карт.</span></div><Badge tone="lime"><Settings2 size={13}/> JSON + визуальный редактор</Badge></div>
    <div className="studio-grid"><aside className="panel studio-aside"><div className="eyebrow">БИБЛИОТЕКА</div>{packs.map(p=><button className={`studio-pack ${chosen===p.id?'selected':''}`} key={p.id} onClick={()=>{setChosen(p.id);setRaw(false)}}><strong>{p.title}</strong><small>{p.categories} категорий · v{p.revision}{p.builtin?' · Базовый':''}</small></button>)}<div className="separator"/><span className="eyebrow">АДМИНИСТРИРОВАНИЕ КОМНАТ</span>{rooms.map(r=><div className="admin-room" key={r.id}><span><strong>{r.title}</strong><small>{r.id} · {phaseLabel(r.phase)}</small></span><button title="Удалить комнату" onClick={()=>deleteRoom(r.id)}><Trash2 size={15}/></button></div>)}<div className="separator"/><Field label="ПАРОЛЬ АДМИНИСТРАТОРА"><input type="password" value={password} onChange={e=>setPassword(e.target.value)} placeholder="Из .env"/></Field><p className="fine">Изменение паков защищено паролем. Все паки доступны друзьям в списке при создании комнаты.</p></aside>
    <section className="panel studio-editor">{current&&<><div className="panel-heading"><div><span className="eyebrow">КОНСТРУКТОР / КАРТЫ</span><h2>{current.title}</h2></div><div className="action-wrap"><Button small onClick={()=>{try{downloadJson(`${chosen}.json`,raw?JSON.parse(rawJson):current)}catch(e){setError((e as Error).message)}}}><Download size={16}/> Экспорт JSON</Button><label className="btn ghost small upload"><FileUp size={15}/> Импорт JSON <input type="file" accept=".json,application/json" onChange={e=>importFile(e.target.files?.[0])}/></label></div></div><div className="editor-actions"><Button small kind={!raw?'primary':'ghost'} onClick={()=>setRaw(false)}>Визуальный редактор</Button><Button small kind={raw?'primary':'ghost'} onClick={()=>{setRawJson(JSON.stringify(current,null,2));setRaw(true)}}>JSON-режим</Button></div>
    {raw?<Field label="СОДЕРЖИМОЕ ПАКА (JSON)"><textarea className="json-edit" value={rawJson} onChange={e=>setRawJson(e.target.value)}/></Field>:<><Field label="НАЗВАНИЕ НАБОРА"><input value={current.title} maxLength={120} onChange={e=>mutate(p=>p.title=e.target.value)}/></Field><div className="studio-section-heading"><div><span className="eyebrow">01 / КАРТОЧКИ</span><h3>Категории характеристик</h3></div><Button small onClick={()=>mutate(p=>p.categories.push({id:`category_${Math.random().toString(36).slice(2,8)}`,name:'Новая категория',enabled:true,items:['Новая карта']}))}><Plus size={15}/> Категория</Button></div><p className="fine">Один вариант на строку. Для профессий и хобби: <code>Врач || Оказывает медицинскую помощь || medical_aid</code> или <code>Фермер || Знает выращивание культур || find_item</code> или <code>Геолог || Ищет хранилища || discover_cache</code>. Для пассивного бонуса достаточно <code>Пекарь || Умеет печь хлеб</code>. Для специальных действий: <code>Описание =&gt; swap</code>, <code>steal</code>, <code>reroll</code>, <code>add_random</code> или <code>revive</code>.</p><div className="categories">{current.categories.map((cat,index)=><div className="category-editor" key={cat.id+index}><div className="category-bar"><div><strong>{index+1}. {cat.name}</strong><small>ID: {cat.id} · {cat.items.length} вариантов</small></div><div className="action-wrap"><button title="Выше" onClick={()=>moveCat(index,-1)} disabled={index===0}>↑</button><button title="Ниже" onClick={()=>moveCat(index,1)} disabled={index===current.categories.length-1}>↓</button><button title="Удалить" onClick={()=>mutate(p=>p.categories.splice(index,1))}><Trash2 size={16}/></button></div></div><div className="category-fields"><Field label="НАЗВАНИЕ"><input value={cat.name} onChange={e=>updateCat(index,'name',e.target.value)}/></Field><Field label="ID (ЛАТИНИЦА)"><input value={cat.id} onChange={e=>updateCat(index,'id',packKey(e.target.value))}/></Field><Field label="КАРТ НА ИГРОКА"><input type="number" min={1} max={5} value={cat.draw_count||1} onChange={e=>updateCat(index,'draw_count',Number(e.target.value))}/></Field><label className="check"><input type="checkbox" checked={cat.inventory??['bag','large'].includes(cat.id)} onChange={e=>updateCat(index,'inventory',e.target.checked)}/> Предметы (доступны для кражи)</label><label className="check"><input type="checkbox" checked={cat.enabled!==false} onChange={e=>mutate(p=>{p.categories[index].enabled=e.target.checked;if(!e.target.checked&&p.settings.first_required_category===p.categories[index].id)p.settings.first_required_category=''})}/> Включена</label></div>
      <div className="role-editor-options"><Field label="ШКАЛА СТАЖА"><select value={cat.experience||({'job':'profession','hobby':'hobby'} as Record<string,string>)[cat.id]||'none'} onChange={e=>updateCat(index,'experience',e.target.value)}><option value="none">Без стажа</option><option value="profession">Профессия (6 ступеней)</option><option value="hobby">Хобби (5 ступеней)</option></select></Field>
        <label className="check"><input type="checkbox" checked={cat.medical??cat.id==='health'} onChange={e=>updateCat(index,'medical',e.target.checked)}/> Карты здоровья (для лечения)</label>
      </div>
      {(cat.experience||({'job':'profession','hobby':'hobby'} as Record<string,string>)[cat.id]||'none')!=='none'&&<details className="editor-levels"><summary>Настроить названия и длительность стажа</summary><p className="fine">Один уровень на строку, формат <code>Название | Срок</code>. Если оставить пустым, используется стандартная шкала. Для точной настройки минимального возраста можно использовать JSON.</p><textarea rows={6} placeholder="Новичок | до 3 месяцев" value={showExperienceLevels(cat.experience_levels||[])} onChange={e=>mutate(p=>{const levels=parseExperienceLevels(e.target.value);if(levels.length)p.categories[index].experience_levels=levels;else delete p.categories[index].experience_levels})}/></details>}
      <Field label="ВАРИАНТЫ КАРТ"><textarea rows={Math.min(7,Math.max(3,cat.items.length))} value={showItems(cat.items)} onChange={e=>updateCat(index,'items',parseItems(e.target.value))}/></Field></div>)}</div>
    <div className="studio-section-heading"><div><span className="eyebrow">02 / СЦЕНАРИЙ</span><h3>Катастрофы</h3></div></div><Field label="ОДНА КАТАСТРОФА НА СТРОКУ"><textarea rows={7} value={current.catastrophes.join('\n')} onChange={e=>mutate(p=>p.catastrophes=e.target.value.split('\n').map(x=>x.trim()).filter(Boolean))}/></Field>
    <div className="studio-section-heading"><div><span className="eyebrow">03 / СЛУЧАЙНАЯ ГЕНЕРАЦИЯ</span><h3>Что внутри бункера</h3></div><Button small onClick={()=>mutate(p=>p.bunker[`field_${Object.keys(p.bunker).length+1}`]=['Новое значение'])}><Plus size={15}/> Параметр</Button></div><p className="fine">Из каждого списка автоматически выбирается одно случайное значение. Параметры комбинируются независимо.</p>{Object.entries(current.bunker).map(([key,values])=><div className="bunker-field" key={key}><div className="between"><input title="Имя параметра" className="key-input" value={key} onChange={e=>mutate(p=>{const name=e.target.value;const entries=Object.entries(p.bunker).map(([k,v])=>[k===key?name:k,v] as const);p.bunker=Object.fromEntries(entries)})}/><Button small kind="danger" onClick={()=>mutate(p=>{delete p.bunker[key]})}><Trash2 size={14}/></Button></div><textarea rows={3} value={values.join('\n')} onChange={e=>mutate(p=>p.bunker[key]=e.target.value.split('\n').map(x=>x.trim()).filter(Boolean))}/></div>)}
    <div className="studio-section-heading"><div><span className="eyebrow">04 / ПРАВИЛА ПО УМОЛЧАНИЮ</span><h3>Настройки пака</h3></div></div><div className="category-fields">{([['speech_seconds','Выступление, сек'],['vote_seconds','Голосование, сек'],['bunker_fraction','Доля мест (0–1)']] as const).map(([key,label])=><Field label={label} key={key}><input type="number" step={key==='bunker_fraction'?0.1:1} value={current.settings[key]} onChange={e=>mutate(p=>{p.settings[key]=Number(e.target.value)})}/></Field>)}</div></>}
    <div className="studio-save"><div><strong>{builtin?'Встроенный набор защищён от редактирования':'Все изменения применятся к новым партиям'}</strong><p className="fine">Существующие партии используют замороженную версию набора.</p></div><div className="action-wrap"><Button onClick={()=>save(true)}><Plus size={16}/> Сохранить как новый</Button>{!builtin&&<Button kind="primary" onClick={()=>save(false)}><Check size={16}/> Сохранить изменения</Button>}</div></div></>}</section></div>
    {message&&<div className="success-notice" onClick={()=>setMessage('')}><Check size={16}/>{message} <X size={14}/></div>}{error&&<Notice text={error} onClose={()=>setError('')}/>}
  </>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
