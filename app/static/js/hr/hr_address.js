// static/js/hr/hr_address.js
// HR Employee Form — Address Picker (New/Old mode)
// Loads data from /static/data/ JSON files
'use strict';

window.HrAddress = (function() {
    const _cache = {
        newWards: null,
        oldProvinces: null,
        oldDistricts: null,
        oldWards: null,
    };

    function _getDl(id) { return document.getElementById(id); }

    function _fillDatalist(dlId, items) {
        const dl = _getDl(dlId);
        if (!dl) return;
        dl.innerHTML = items.map(name => `<option value="${name}">`).join('');
    }

    async function _loadNewWards() {
        if (_cache.newWards) return _cache.newWards;
        try {
            const res = await fetch('/static/data/vn_new_wards.json');
            _cache.newWards = await res.json();
        } catch (e) { _cache.newWards = {}; }
        return _cache.newWards;
    }

    async function _loadOldProvinces() {
        if (_cache.oldProvinces) return _cache.oldProvinces;
        try {
            const res = await fetch('/static/data/vn_old_provinces.json');
            _cache.oldProvinces = await res.json();
        } catch (e) { _cache.oldProvinces = []; }
        return _cache.oldProvinces;
    }

    async function _loadOldDistricts() {
        if (_cache.oldDistricts) return _cache.oldDistricts;
        try {
            const res = await fetch('/static/data/vn_old_districts.json');
            _cache.oldDistricts = await res.json();
        } catch (e) { _cache.oldDistricts = {}; }
        return _cache.oldDistricts;
    }

    async function _loadOldWards() {
        if (_cache.oldWards) return _cache.oldWards;
        try {
            const res = await fetch('/static/data/vn_old_wards.json');
            _cache.oldWards = await res.json();
        } catch (e) { _cache.oldWards = {}; }
        return _cache.oldWards;
    }

    async function switchMode(mode) {
        _fillDatalist('hr-dl-province', []);
        _fillDatalist('hr-dl-district', []);
        _fillDatalist('hr-dl-ward', []);

        if (mode === 'new') {
            const data = await _loadNewWards();
            const provinces = Object.keys(data).sort();
            _fillDatalist('hr-dl-province', provinces);
        } else {
            const provinces = await _loadOldProvinces();
            _fillDatalist('hr-dl-province', provinces.map(p => p.name));
        }
    }

    async function onProvinceChange(value, mode) {
        _fillDatalist('hr-dl-district', []);
        _fillDatalist('hr-dl-ward', []);

        if (mode === 'new') {
            const data = await _loadNewWards();
            const wards = data[value] || [];
            _fillDatalist('hr-dl-ward', wards);
        } else {
            const provinces = await _loadOldProvinces();
            const match = provinces.find(p => p.name === value);
            if (!match) return;
            const districts = await _loadOldDistricts();
            const distList = districts[String(match.code)] || [];
            _fillDatalist('hr-dl-district', distList.map(d => d.name));
        }
    }

    async function onDistrictChange(value, provinceName) {
        _fillDatalist('hr-dl-ward', []);

        const provinces = await _loadOldProvinces();
        const provMatch = provinces.find(p => p.name === provinceName);
        if (!provMatch) return;

        const districts = await _loadOldDistricts();
        const distList = districts[String(provMatch.code)] || [];
        const distMatch = distList.find(d => d.name === value);
        if (!distMatch) return;

        const wards = await _loadOldWards();
        const wardList = wards[String(distMatch.code)] || [];
        _fillDatalist('hr-dl-ward', wardList.map(w => w.name));
    }

    return { switchMode, onProvinceChange, onDistrictChange };
})();
