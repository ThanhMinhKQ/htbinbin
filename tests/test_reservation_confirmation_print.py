import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


TEMPLATE_DIR = Path("app/templates")
ROUTE_PATH = Path("app/api/pms/reservation_api.py")


class ReservationConfirmationPrintTest(unittest.TestCase):
    def render_template(self, booking):
        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        template = env.get_template("pms/reservation_confirmation_print.html")
        return template.render(
            booking=booking,
            current_user={"name": "Alice Reception", "username": "alice"},
            current_time="10/05/2026 12:00",
        )

    def base_booking(self):
        return {
            "id": 12,
            "external_id": "BK-12",
            "branch_name": "Bin Bin Hotel",
            "branch_address": "Branch address",
            "branch_phone": "0123456789",
            "reservation_status": "CONFIRMED",
            "guest_name": "Guest Name",
            "guest_phone": "",
            "guest_email": "",
            "booking_source": "Direct",
            "booking_type": "DIRECT",
            "special_requests": "",
            "assigned_room_number": "101",
            "room_type": "Deluxe",
            "check_in": "10/05/2026",
            "estimated_arrival": "14:00",
            "check_out": "11/05/2026",
            "raw_data": None,
            "num_guests": 1,
            "total_price": 1000000,
            "deposit_amount": 0,
            "currency": "VND",
        }

    def test_template_renders_prepared_by_from_current_user(self):
        html = self.render_template(self.base_booking())

        self.assertIn("Alice Reception", html)

    def test_template_formats_branch_name_for_header(self):
        booking = self.base_booking()
        booking["branch_name"] = "CHI NHÁNH B17"

        html = self.render_template(booking)

        self.assertIn("BIN BIN HOTEL 17", html)
        self.assertNotIn("CHI NHÁNH B17", html)

    def test_template_renders_service_and_surcharge_rows(self):
        booking = self.base_booking()
        booking["total_price"] = 1330000
        booking["raw_data"] = {
            "services": [
                {"name": "Giặt ủi", "description": "Laundry service", "qty": 2, "price": 50000},
                {"service_name": "Minibar", "note": "Nước suối", "quantity": 1, "amount": 30000},
            ],
            "pricing_preview": {
                "breakdown": [
                    {"type": "EARLY_CHECKIN_FEE", "description": "Nhận phòng sớm (2h)", "hours": 2, "amount": 100000, "start_iso": "2026-05-10T12:00:00", "end_iso": "2026-05-10T14:00:00"},
                    {"type": "LATE_CHECKOUT_FEE", "description": "Trả phòng muộn (4h)", "hours": 4, "amount": 200000, "start_iso": "2026-05-11T12:00:00", "end_iso": "2026-05-11T16:00:00"},
                ]
            },
        }

        html = self.render_template(booking)

        self.assertIn("Giặt ủi", html)
        self.assertIn("Laundry service", html)
        self.assertIn("Minibar", html)
        self.assertIn("Phí nhận phòng sớm", html)
        self.assertIn("Phí trả phòng muộn", html)
        self.assertIn("2 tiếng × 50.000", html)
        self.assertIn("4 tiếng × 50.000", html)
        self.assertIn("200.000", html)
        self.assertIn("Thông tin đặt phòng / Reservation Details", html)
        self.assertIn("Số người / Guests", html)
        self.assertIn("Trực tiếp", html)
        self.assertNotIn("Tạm tính / Subtotal", html)
        self.assertIn("bank-line", html)
        self.assertIn("12:00", html)
        self.assertIn("14:00", html)
        self.assertIn("info-date-pair", html)
        self.assertNotIn("<strong>Phòng:", html)
        self.assertNotIn("Ép giá", html)
        self.assertNotIn("lách luật", html)

    def test_template_hides_empty_reservation_detail_fields(self):
        booking = self.base_booking()
        booking.update({
            "guest_phone": "",
            "assigned_room_number": "",
            "room_type": "",
            "raw_data": {},
        })

        html = self.render_template(booking)

        self.assertNotIn("Điện thoại / Phone", html)
        self.assertNotIn("Phòng / Room", html)
        self.assertNotIn("Loại phòng / Room Type", html)
        self.assertIn("info-date-pair", html)

    def test_ota_booking_without_pricing_breakdown_renders_room_charge_row(self):
        booking = self.base_booking()
        booking.update({
            "external_id": "4492374",
            "booking_source": "Go2Joy",
            "booking_type": "OTA",
            "room_type": "Superior room",
            "total_price": 300000,
            "raw_data": {},
        })

        html = self.render_template(booking)

        self.assertIn("Tiền phòng / Room charge", html)
        self.assertIn("1 đêm / night(s)", html)
        self.assertIn("300.000", html)
        self.assertIn("Go2Joy", html)

    def test_edit_submit_reopens_detail_with_updated_booking(self):
        source = Path("app/static/js/pms/reservation_hub/form.js").read_text(encoding="utf-8")
        submit_start = source.index("async submitCreate()")
        submit_end = source.index("async submitReservationFromCi()", submit_start)
        submit_source = source[submit_start:submit_end]

        self.assertIn("if (isEdit && createdBooking?.id) await this.openDetail(createdBooking.id);", submit_source)

    def test_reservation_update_does_not_create_or_link_crm_guest(self):
        source = Path("app/services/booking_service.py").read_text(encoding="utf-8")
        update_start = source.index("def update_reservation")
        update_end = source.index("def confirm_reservation", update_start)
        update_source = source[update_start:update_end]

        self.assertNotIn("_find_or_create_guest", update_source)
        self.assertIn("booking.guest_id = None", update_source)
        self.assertIn('raw.pop("selected_crm_guest_id", None)', update_source)

    def test_reservation_edit_keeps_guest_name_editable(self):
        source = Path("app/static/js/pms/reservation_hub/form.js").read_text(encoding="utf-8")
        fill_start = source.index("async fillBookingForm")
        fill_end = source.index("\n    ensureOtaChannelOption", fill_start)
        fill_source = source[fill_start:fill_end]

        self.assertIn("this.setBookingCrmFieldsLocked(false);", fill_source)
        self.assertNotIn("this.setBookingCrmFieldsLocked(Boolean(booking.guest_id));", fill_source)

    def test_print_route_passes_current_user_to_template(self):
        source = ROUTE_PATH.read_text(encoding="utf-8")
        route_start = source.index("def page_reservation_confirmation_print")
        route_end = source.index("@router.put", route_start)
        route_source = source[route_start:route_end]

        self.assertIn('"current_user": user', route_source)


if __name__ == "__main__":
    unittest.main()
