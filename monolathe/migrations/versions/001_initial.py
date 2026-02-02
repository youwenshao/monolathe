"""Initial migration

Revision ID: 001
Create Date: 2026-02-01 11:00:00.000000

"""
from typing import Sequence, Union
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, Boolean

# revision identifiers
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create channels table
    op.create_table(
        'channels',
        sa.Column('id', String(36), primary_key=True),
        sa.Column('name', String(255), nullable=False),
        sa.Column('platform_account_id', Text, nullable=False),
        sa.Column('niche_category', String(50), nullable=False),
        sa.Column('target_demographic', JSON, default=dict),
        sa.Column('voice_config', JSON, default=dict),
        sa.Column('visual_config', JSON, default=dict),
        sa.Column('posting_window', JSON, default=dict),
        sa.Column('active', Boolean, default=True),
        sa.Column('last_upload_at', DateTime, nullable=True),
        sa.Column('created_at', DateTime, default=datetime.utcnow),
    )
    
    # Create trends table
    op.create_table(
        'trends',
        sa.Column('id', String(36), primary_key=True),
        sa.Column('source', String(50), nullable=False),
        sa.Column('title', String(500), nullable=False),
        sa.Column('raw_data', JSON, default=dict),
        sa.Column('url', String(1000), nullable=True),
        sa.Column('score', Integer, nullable=True),
        sa.Column('status', String(50), default='pending'),
        sa.Column('discovered_at', DateTime, default=datetime.utcnow),
        sa.Column('processed_at', DateTime, nullable=True),
    )
    
    # Create scheduled_content table
    op.create_table(
        'scheduled_content',
        sa.Column('id', String(36), primary_key=True),
        sa.Column('channel_id', String(36), ForeignKey('channels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_trend_id', String(36), ForeignKey('trends.id', ondelete='SET NULL'), nullable=True),
        sa.Column('script_json', JSON, default=dict),
        sa.Column('status', String(50), default='drafted'),
        sa.Column('scheduled_publish_at', DateTime, nullable=True),
        sa.Column('youtube_video_id', String(50), nullable=True),
        sa.Column('metadata_hash', String(64), nullable=True),
        sa.Column('created_at', DateTime, default=datetime.utcnow),
        sa.Column('updated_at', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
    )
    
    # Create upload_jobs table
    op.create_table(
        'upload_jobs',
        sa.Column('id', String(36), primary_key=True),
        sa.Column('content_id', String(36), ForeignKey('scheduled_content.id', ondelete='CASCADE'), nullable=False),
        sa.Column('platform', String(50), nullable=False),
        sa.Column('priority', Integer, default=5),
        sa.Column('retry_count', Integer, default=0),
        sa.Column('error_log', Text, nullable=True),
        sa.Column('reserved_by_worker', String(100), nullable=True),
        sa.Column('reserved_at', DateTime, nullable=True),
        sa.Column('created_at', DateTime, default=datetime.utcnow),
    )
    
    # Create indexes
    op.create_index('idx_trends_source', 'trends', ['source'])
    op.create_index('idx_trends_score', 'trends', ['score'])
    op.create_index('idx_trends_status', 'trends', ['status'])
    op.create_index('idx_content_channel_status', 'scheduled_content', ['channel_id', 'status'])
    op.create_index('idx_content_scheduled', 'scheduled_content', ['scheduled_publish_at'])
    op.create_index('idx_jobs_content', 'upload_jobs', ['content_id'])
    op.create_index('idx_jobs_platform', 'upload_jobs', ['platform'])


def downgrade() -> None:
    op.drop_table('upload_jobs')
    op.drop_table('scheduled_content')
    op.drop_table('trends')
    op.drop_table('channels')
