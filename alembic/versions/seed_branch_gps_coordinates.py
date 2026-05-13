"""seed branch gps coordinates from config

Revision ID: seed_branch_gps_coords
Revises:
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa

revision = 'seed_branch_gps_coords'
down_revision = None
branch_labels = None
depends_on = None

BRANCH_COORDINATES = {
    "B1":  (10.727298831515066, 106.6967154830272),
    "B2":  (10.740600,          106.695797),
    "B3":  (10.733902,          106.708781),
    "B5":  (10.73780906347085,  106.70517496567874),
    "B6":  (10.729986861681768, 106.70690372549372),
    "B7":  (10.744230207012244, 106.6965025304644),
    "B8":  (10.741408,          106.699883),
    "B9":  (10.740970,          106.699825),
    "B10": (10.814503,          106.670873),
    "B11": (10.77497650247788,  106.75134333045331),
    "B12": (10.778874744587053, 106.75266727478706),
    "B14": (10.742557513695218, 106.69945313180673),
    "B15": (10.775572501574938, 106.75167172807936),
    "B16": (10.760347394497392, 106.69043939445082),
    "B17": (10.70590976421059,  106.7078826381241),
    "B18": (10.774358971201922, 106.75390442668895),
}


def upgrade():
    conn = op.get_bind()
    for branch_code, (lat, lng) in BRANCH_COORDINATES.items():
        conn.execute(
            sa.text(
                "UPDATE branches SET gps_lat = :lat, gps_lng = :lng "
                "WHERE branch_code = :code AND (gps_lat IS NULL OR gps_lng IS NULL)"
            ),
            {"lat": lat, "lng": lng, "code": branch_code},
        )


def downgrade():
    pass
