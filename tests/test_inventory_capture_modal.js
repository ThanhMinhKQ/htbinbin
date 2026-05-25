const assert = require('assert');
const fs = require('fs');

const sharedSource = fs.readFileSync('app/static/js/inventory/shared/utils.js', 'utf8');
const managerSource = fs.readFileSync('app/static/js/inventory/manager/utils.js', 'utf8');
const receptionSource = fs.readFileSync('app/static/js/inventory/modules/reception_request/utils.js', 'utf8');

assert(
  sharedSource.includes('async captureModal(element)'),
  'shared/utils.js must own the inventory captureModal implementation so all inventory tickets use the same capture pipeline',
);

assert(
  !sharedSource.includes('.capture-mode-active * {\n                    overflow: visible !important;') &&
    !sharedSource.includes('.capture-mode-active,\n                .capture-mode-active * {'),
  'shared capture CSS must not force overflow/max-height on every descendant because it breaks table and status pill layout',
);

assert(
  sharedSource.includes('.capture-mode-active table') &&
    sharedSource.includes('table-layout: fixed') &&
    sharedSource.includes('border-collapse: collapse'),
  'shared capture CSS must preserve stable table layout for captured tickets',
);

assert(
  sharedSource.includes('[data-capture-status-cell]') &&
    sharedSource.includes('.capture-mode-active [data-capture-status-cell] span.inline-flex') &&
    sharedSource.includes('white-space: nowrap') &&
    sharedSource.includes('position: static'),
  'shared capture CSS must target detected status cells instead of assuming the visible status column is the last DOM column',
);

assert(
  !sharedSource.includes('area.style.height = `${area.scrollHeight}px`;'),
  'shared capture must not measure scrollHeight before the detached clone is appended because hidden detached scroll areas collapse to zero',
);

assert(
  sharedSource.includes('expandCaptureScrollAreas') &&
    sharedSource.includes('requestAnimationFrame') &&
    sharedSource.indexOf('document.body.appendChild(wrapper)') < sharedSource.lastIndexOf('expandCaptureScrollAreas(clone)'),
  'shared capture must append the detached clone before expanding scroll areas so full ticket height is measurable',
);

assert(
  sharedSource.includes('font-family: inherit') && sharedSource.includes('letter-spacing: inherit'),
  'shared capture CSS must preserve the original modal font formatting instead of replacing typography globally',
);

assert(
  sharedSource.includes('windowWidth: captureWidth') &&
    sharedSource.includes('windowHeight: captureHeight') &&
    sharedSource.includes('height: captureHeight'),
  'shared capture must render the full expanded detached ticket dimensions',
);

assert(
  sharedSource.includes('createCaptureTarget') && sharedSource.includes('cleanupCaptureTarget'),
  'shared capture must render a detached capture target and clean it up after capture',
);

assert(
  managerSource.includes('...sharedUtils') && !managerSource.includes('async captureModal(element)'),
  'manager/utils.js must use shared captureModal instead of keeping a divergent local implementation',
);

assert(
  receptionSource.includes('...sharedUtils') && !receptionSource.includes('async captureModal(element)'),
  'modules/reception_request/utils.js must use shared captureModal instead of keeping a divergent local implementation',
);

assert(
  sharedSource.includes('normalizeCaptureStatusCells') &&
    sharedSource.includes('textContent.trim()') &&
    sharedSource.includes('replaceChildren(statusBadge)'),
  'shared capture must replace Alpine x-if status-cell contents with a static readable badge before html2canvas renders the clone',
);
