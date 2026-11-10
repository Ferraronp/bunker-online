import os
from urllib.parse import quote_plus
from sqlalchemy import create_engine, String, Integer, Boolean, ForeignKey, JSON, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

URL = (f"postgresql+psycopg://bunker:{quote_plus(os.environ['POSTGRES_PASSWORD'])}@{os.environ['DATABASE_HOST']}:5432/bunker"
       if os.environ.get('DATABASE_HOST') else os.getenv('DATABASE_URL', 'sqlite:///./bunker-dev.db'))
engine = create_engine(URL, connect_args={'check_same_thread': False} if URL.startswith('sqlite') else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Pack(Base):
    __tablename__ = 'packs'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    content: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)

class Room(Base):
    __tablename__ = 'rooms'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(String(90))
    phase: Mapped[str] = mapped_column(String(20), default='lobby')
    host_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pack_id: Mapped[str] = mapped_column(String(40))
    pack_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    undo_stack: Mapped[list] = mapped_column(JSON, default=list)
    players: Mapped[list['Player']] = relationship(back_populates='room', cascade='all,delete-orphan', order_by='Player.seat')

class Player(Base):
    __tablename__ = 'players'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey('rooms.id', ondelete='CASCADE'))
    token: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(40))
    seat: Mapped[int] = mapped_column(Integer)
    spectator: Mapped[bool] = mapped_column(Boolean, default=False)
    alive: Mapped[bool] = mapped_column(Boolean, default=True)
    hand: Mapped[list] = mapped_column(JSON, default=list)
    used_abilities: Mapped[list] = mapped_column(JSON, default=list)
    room: Mapped[Room] = relationship(back_populates='players')
