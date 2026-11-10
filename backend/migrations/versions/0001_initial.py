"""Initial schema for pack library, lobby and persisted game state.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
revision='0001'
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('packs',
        sa.Column('id',sa.String(length=40),primary_key=True),
        sa.Column('title',sa.String(length=120),nullable=False),
        sa.Column('content',sa.JSON(),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('is_builtin',sa.Boolean(),nullable=False))
    op.create_table('rooms',
        sa.Column('id',sa.String(length=16),primary_key=True),
        sa.Column('title',sa.String(length=90),nullable=False),
        sa.Column('phase',sa.String(length=20),nullable=False),
        sa.Column('host_id',sa.String(length=40),nullable=True),
        sa.Column('pack_id',sa.String(length=40),nullable=False),
        sa.Column('pack_snapshot',sa.JSON(),nullable=False),
        sa.Column('config',sa.JSON(),nullable=False),
        sa.Column('state',sa.JSON(),nullable=False),
        sa.Column('undo_stack',sa.JSON(),nullable=False))
    op.create_table('players',
        sa.Column('id',sa.String(length=40),primary_key=True),
        sa.Column('room_id',sa.String(length=16),sa.ForeignKey('rooms.id',ondelete='CASCADE'),nullable=False),
        sa.Column('token',sa.String(length=100),nullable=False),
        sa.Column('nickname',sa.String(length=40),nullable=False),
        sa.Column('seat',sa.Integer(),nullable=False),
        sa.Column('spectator',sa.Boolean(),nullable=False),
        sa.Column('alive',sa.Boolean(),nullable=False),
        sa.Column('hand',sa.JSON(),nullable=False),
        sa.Column('used_abilities',sa.JSON(),nullable=False))
    op.create_index('ix_players_token','players',['token'],unique=True)

def downgrade():
    op.drop_index('ix_players_token',table_name='players')
    op.drop_table('players')
    op.drop_table('rooms')
    op.drop_table('packs')
