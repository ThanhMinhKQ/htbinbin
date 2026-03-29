// static/js/pms/pms.js
// PMS Main Entry Point - Loads all PMS modules
// This file should be included LAST in the HTML templates
'use strict';

// Load modules in order: common first, then specific modules
// The actual functions are defined in:
// - pms_common.js: Shared utilities (SVG, format, API helpers)
// - pms_dashboard.js: Room map, floor/type view, loading
// - pms_booking.js: Smart search, calendar
// - pms_checkin.js: Check-in modal
// - pms_checkout.js: Check-out modal
// - pms_modals.js: Room detail, add guest, transfer

console.log('PMS modules loaded successfully');

// Export PMS namespace
window.PMS = window.PMS || { floors: {}, branchId: null, roomTypes: [], timer: null, _loading: false };

// Make sure all global functions are available
// These are already exported in each module file