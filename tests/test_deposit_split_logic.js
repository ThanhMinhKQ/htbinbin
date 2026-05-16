const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('app/static/js/pms/reservation_hub/form.js', 'utf8');
const methods = source.match(/Object\.assign\(BookingHub, \{([\s\S]*)\n\}\);/)[1];
const sandbox = {
  elements: {},
  BookingHub: {
    state: {},
    getRoomCart() { return this.state.roomCart || []; },
    getRoomCartQuantity() { return this.getRoomCart().reduce((sum, item) => sum + Number(item.quantity || 0), 0); },
    value(id) { return this.values[id] || ''; },
    escape(value) { return String(value ?? ''); },
    isOtaBookingForm() { return false; },
    renderPaymentRoomSummary() {},
  },
  document: {
    getElementById(id) {
      if (sandbox.elements[id]) return sandbox.elements[id];
      if (sandbox.BookingHub.values && Object.prototype.hasOwnProperty.call(sandbox.BookingHub.values, id)) {
        return { value: sandbox.BookingHub.values[id] };
      }
      return null;
    },
    querySelectorAll() { return []; },
  },
  pmsMoney(value) { return String(value); },
  pmsToast() {},
  pmsApi() {},
  setTimeout() {},
  window: {},
  console,
};
vm.createContext(sandbox);
vm.runInContext(`Object.assign(BookingHub, {${methods}\n});`, sandbox);

const hub = sandbox.BookingHub;
hub.values = { 'bk-form-deposit': '500000' };
hub.state.roomCart = [
  { room_type_id: 1, room_type: 'Sup', quantity: 1 },
  { room_type_id: 2, room_type: 'Del', quantity: 1 },
];
hub.state.depositSplitAmounts = {};
assert.deepStrictEqual(JSON.parse(JSON.stringify(hub.rebalanceDepositSplitAmounts())), { '1': 250000, '2': 250000 });

hub.values = { 'bk-form-deposit': '5' };
hub.state.depositSplitAmounts = {};
assert.deepStrictEqual(JSON.parse(JSON.stringify(hub.rebalanceDepositSplitAmounts())), { '1': 3, '2': 2 });
hub.values = { 'bk-form-deposit': '500000' };
assert.deepStrictEqual(JSON.parse(JSON.stringify(hub.rebalanceDepositSplitAmounts())), { '1': 250000, '2': 250000 });

hub.state.depositSplitAmounts = { '2': 3, '3': 499997 };
assert.deepStrictEqual(JSON.parse(JSON.stringify(hub.rebalanceDepositSplitAmounts())), { '1': 250000, '2': 250000 });

hub.state.depositSplitAmounts = { '1': 250000, '2': 250000 };
hub.setDepositSplitAmount('1', '300000');
assert.deepStrictEqual(JSON.parse(JSON.stringify(hub.state.depositSplitAmounts)), { '1': 300000, '2': 200000 });
assert.deepStrictEqual(JSON.parse(JSON.stringify(hub.getDepositAllocationPayload())), {
  mode: 'split',
  items: [
    { room_type_id: 1, room_type_index: 1, amount: 300000 },
    { room_type_id: 2, room_type_index: 1, amount: 200000 },
  ],
});

hub.state.roomCart = [
  { room_type_id: 1, room_type: 'Sup', quantity: 2 },
  { room_type_id: 2, room_type: 'Del', quantity: 1 },
];
hub.values = { 'bk-form-deposit': '600000' };
hub.state.depositSplitAmounts = {};
assert.deepStrictEqual(JSON.parse(JSON.stringify(hub.rebalanceDepositSplitAmounts())), { '1': 400000, '2': 200000 });
hub.setDepositSplitAmount('1', '450000');
assert.deepStrictEqual(JSON.parse(JSON.stringify(hub.state.depositSplitAmounts)), { '1': 450000, '2': 150000 });
assert.deepStrictEqual(JSON.parse(JSON.stringify(hub.getDepositAllocationPayload())), {
  mode: 'split',
  items: [
    { room_type_id: 1, room_type_index: 1, amount: 225000 },
    { room_type_id: 1, room_type_index: 2, amount: 225000 },
    { room_type_id: 2, room_type_index: 1, amount: 150000 },
  ],
});

assert.deepStrictEqual(JSON.parse(JSON.stringify(hub.splitDepositAmountByQuantity(5, 2))), [3, 2]);

assert.strictEqual(hub.formatDepositSplitInput(500000), '500.000');
assert.strictEqual(hub.parseDepositSplitInput('500.000'), 500000);

hub.state.roomCart = [
  { room_type_id: 1, room_type: 'Sup', quantity: 1, unit_total: 500000 },
];
sandbox.elements['bk-form-total'] = { value: '450.000', dataset: { bkUserEdited: '1' } };
assert.strictEqual(hub.isBookingTotalManualOverride(450000, 500000), true);
assert.strictEqual(hub.isBookingTotalManualOverride(500000, 500000), false);
sandbox.elements['bk-form-total'] = { value: '450.000', dataset: {} };
assert.strictEqual(hub.isBookingTotalManualOverride(450000, 500000), false);
