"""add branch company and bank info columns

Revision ID: add_branch_company_bank
Revises: seed_branch_gps_coords
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_branch_company_bank'
down_revision = 'seed_branch_gps_coords'
branch_labels = None
depends_on = None

BRANCH_DATA = {
    "B1": {
        "phone": "028 3776 0728",
        "company_name": "Cong Ty TNHH MTV Khach san Bin Bin",
        "tax_code": "0312021245",
        "tax_address": "Số 2 đường số 1, Khu dân cư ven sông, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18222238",
        "bank_holder": "Cong Ty TNHH MTV Khach san Bin Bin",
        "personal_bank_name": "ACB",
        "personal_bank_account": "LOCPHAT000251210",
        "personal_bank_holder": "TRAN PHAT NGUYEN",
    },
    "B2": {
        "phone": "028 6298 3685",
        "company_name": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "tax_code": "0313877984",
        "tax_address": "40 Đường số 4, Khu dân cư Him Lam, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111128",
        "bank_holder": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "personal_bank_name": "ACB",
        "personal_bank_account": "LOCPHAT000251210",
        "personal_bank_holder": "TRAN PHAT NGUYEN",
    },
    "B3": {
        "phone": "028 5410 6705",
        "company_name": "Cong Ty TNHH MTV Vy Anh - Khach san Bin Bin",
        "tax_code": "0313562511",
        "tax_address": "Số 58 đường số 2, Khu phố Hưng Gia 5, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111198",
        "bank_holder": "Cong Ty TNHH MTV Vy Anh - Khach san Bin Bin",
        "personal_bank_name": "ACB",
        "personal_bank_account": "LOCPHAT000251210",
        "personal_bank_holder": "TRAN PHAT NGUYEN",
    },
    "B5": {
        "phone": "028 225 35 225",
        "company_name": "Cong Ty TNHH Vo Gia - Khach san Bin Bin",
        "tax_code": "0315232646",
        "tax_address": "42 Đường số 73, Khu dân cư Tân Quy Đông, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111158",
        "bank_holder": "Cong Ty TNHH Vo Gia - Khach san Bin Bin",
        "personal_bank_name": "Sacombank",
        "personal_bank_account": "060333843725",
        "personal_bank_holder": "TRAN PHAT NGUYEN",
    },
    "B6": {
        "phone": "028 5410 3839",
        "company_name": "Cong Ty TNHH Tong Vo - Khach san Bin Bin",
        "tax_code": "0314984869",
        "tax_address": "89 Đường số 6, Khu phố Hưng Phước 4, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111178",
        "bank_holder": "Cong Ty TNHH Tong Vo - Khach san Bin Bin",
        "personal_bank_name": "Sacombank",
        "personal_bank_account": "060333843725",
        "personal_bank_holder": "TRAN PHAT NGUYEN",
    },
    "B7": {
        "phone": "028 225 08 038",
        "company_name": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "tax_code": "0313877984",
        "tax_address": "40 Đường số 4, Khu dân cư Him Lam, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111128",
        "bank_holder": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "personal_bank_name": "Sacombank",
        "personal_bank_account": "060333843725",
        "personal_bank_holder": "TRAN PHAT NGUYEN",
    },
    "B8": {
        "phone": "028 2200 8383",
        "company_name": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "tax_code": "0313877984",
        "tax_address": "40 Đường số 4, Khu dân cư Him Lam, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111128",
        "bank_holder": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "personal_bank_name": "SHB",
        "personal_bank_account": "0916080883",
        "personal_bank_holder": "TONG THI THUY",
    },
    "B9": {
        "phone": "028 6259 9595",
        "company_name": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "tax_code": "0313877984",
        "tax_address": "40 Đường số 4, Khu dân cư Him Lam, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111128",
        "bank_holder": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "personal_bank_name": "Sacombank",
        "personal_bank_account": "0916080883",
        "personal_bank_holder": "TONG THI THUY",
    },
    "B10": {
        "phone": "028 3547 0404",
        "company_name": "Cong Ty TNHH Khanh An - Khach san Bin Bin",
        "tax_code": "0317854635",
        "tax_address": "21 Bạch Đằng, Phường Tân Sơn Hòa, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111138",
        "bank_holder": "Cong Ty TNHH Khanh An - Khach san Bin Bin",
        "personal_bank_name": "SHB",
        "personal_bank_account": "0937471614",
        "personal_bank_holder": "TRAN NGOC ANH",
    },
    "B11": {
        "phone": "028 22 149 150",
        "company_name": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "tax_code": "0313877984",
        "tax_address": "40 Đường số 4, Khu dân cư Him Lam, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111128",
        "bank_holder": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "personal_bank_name": "ACB",
        "personal_bank_account": "PHATLOC808376",
        "personal_bank_holder": "TONG THI THUY",
    },
    "B12": {
        "phone": "028.6271.6274",
        "company_name": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "tax_code": "0313877984",
        "tax_address": "40 Đường số 4, Khu dân cư Him Lam, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111128",
        "bank_holder": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "personal_bank_name": "VPBank",
        "personal_bank_account": "0937471614",
        "personal_bank_holder": "TRAN NGOC ANH",
    },
    "B14": {
        "phone": "028 6271 6264",
        "company_name": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "tax_code": "0313877984",
        "tax_address": "40 Đường số 4, Khu dân cư Him Lam, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111128",
        "bank_holder": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "personal_bank_name": "VPBank",
        "personal_bank_account": "0939725662",
        "personal_bank_holder": "TRAN PHAT NGUYEN",
    },
    "B15": {
        "phone": "028 6271 1753",
        "company_name": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "tax_code": "0313877984",
        "tax_address": "40 Đường số 4, Khu dân cư Him Lam, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111128",
        "bank_holder": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "personal_bank_name": "VPBank",
        "personal_bank_account": "0916080883",
        "personal_bank_holder": "TONG THI THUY",
    },
    "B16": {
        "phone": "028 6271 1754",
        "company_name": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "tax_code": "0313877984",
        "tax_address": "40 Đường số 4, Khu dân cư Him Lam, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111128",
        "bank_holder": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "personal_bank_name": "VPBank",
        "personal_bank_account": "0916080883",
        "personal_bank_holder": "TONG THI THUY",
    },
    "B17": {
        "phone": "028 3622 4546",
        "company_name": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "tax_code": "0313877984",
        "tax_address": "40 Đường số 4, Khu dân cư Him Lam, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111128",
        "bank_holder": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "personal_bank_name": "VPBank",
        "personal_bank_account": "0916080883",
        "personal_bank_holder": "TONG THI THUY",
    },
    "B18": {
        "phone": "(028) 6278 6688",
        "company_name": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "tax_code": "0313877984",
        "tax_address": "40 Đường số 4, Khu dân cư Him Lam, Phường Tân Hưng, TP Hồ Chí Minh, Việt Nam",
        "bank_name": "Ngân hàng ACB - PGD Phú Mỹ",
        "bank_account": "18111128",
        "bank_holder": "Cong Ty TNHH MTV Thuy Moc - Khach san Bin Bin",
        "personal_bank_name": "SHB",
        "personal_bank_account": "0919081995",
        "personal_bank_holder": "NGUYEN DO MINH LUAN",
    },
}


def upgrade():
    # Add columns
    op.add_column('branches', sa.Column('phone', sa.String(50), nullable=True))
    op.add_column('branches', sa.Column('company_name', sa.String(255), nullable=True))
    op.add_column('branches', sa.Column('tax_code', sa.String(50), nullable=True))
    op.add_column('branches', sa.Column('tax_address', sa.Text(), nullable=True))
    op.add_column('branches', sa.Column('bank_name', sa.String(255), nullable=True))
    op.add_column('branches', sa.Column('bank_account', sa.String(100), nullable=True))
    op.add_column('branches', sa.Column('bank_holder', sa.String(255), nullable=True))
    op.add_column('branches', sa.Column('personal_bank_name', sa.String(255), nullable=True))
    op.add_column('branches', sa.Column('personal_bank_account', sa.String(100), nullable=True))
    op.add_column('branches', sa.Column('personal_bank_holder', sa.String(255), nullable=True))

    # Add company_name and company_address to hotel_stays
    op.add_column('hotel_stays', sa.Column('company_name', sa.String(255), nullable=True))
    op.add_column('hotel_stays', sa.Column('company_address', sa.Text(), nullable=True))

    # Add company_name and company_address to hotel_guests
    op.add_column('hotel_guests', sa.Column('company_name', sa.String(255), nullable=True))
    op.add_column('hotel_guests', sa.Column('company_address', sa.Text(), nullable=True))

    # Seed branch data
    conn = op.get_bind()
    for branch_code, data in BRANCH_DATA.items():
        conn.execute(
            sa.text(
                "UPDATE branches SET "
                "phone = :phone, "
                "company_name = :company_name, "
                "tax_code = :tax_code, "
                "tax_address = :tax_address, "
                "bank_name = :bank_name, "
                "bank_account = :bank_account, "
                "bank_holder = :bank_holder, "
                "personal_bank_name = :personal_bank_name, "
                "personal_bank_account = :personal_bank_account, "
                "personal_bank_holder = :personal_bank_holder "
                "WHERE branch_code = :code"
            ),
            {"code": branch_code, **data},
        )


def downgrade():
    op.drop_column('hotel_guests', 'company_address')
    op.drop_column('hotel_guests', 'company_name')
    op.drop_column('hotel_stays', 'company_address')
    op.drop_column('hotel_stays', 'company_name')
    op.drop_column('branches', 'personal_bank_holder')
    op.drop_column('branches', 'personal_bank_account')
    op.drop_column('branches', 'personal_bank_name')
    op.drop_column('branches', 'bank_holder')
    op.drop_column('branches', 'bank_account')
    op.drop_column('branches', 'bank_name')
    op.drop_column('branches', 'tax_address')
    op.drop_column('branches', 'tax_code')
    op.drop_column('branches', 'company_name')
    op.drop_column('branches', 'phone')
