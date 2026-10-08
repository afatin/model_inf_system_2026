(function() {
    let mapObj = null;
    let selectedPoint = null;
    let marker = null;
    let mode = 'select';
    let currentElevation = null;
    let sessionId = null;

    // Получаем session_id из data-атрибута контейнера
    const container = document.getElementById('pointSelectionPanel');
    if (container) {
        sessionId = container.getAttribute('data-session-id');
    }

    function findMap() {
        for (let key in window) {
            if (window[key] instanceof L.Map) {
                return window[key];
            }
        }
        return null;
    }

    async function fetchElevation(lat, lon) {
        try {
            const response = await fetch('/get_elevation', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    session_id: sessionId,
                    lat: lat,
                    lon: lon
                })
            });
            const data = await response.json();
            if (data.elevation !== undefined) {
                currentElevation = data.elevation;
                document.getElementById('elevVal').innerText = currentElevation.toFixed(1) + ' м';
                document.getElementById('elevationContainer').style.display = 'flex';
            } else {
                document.getElementById('elevationContainer').style.display = 'none';
            }
        } catch (err) {
            console.error(err);
            document.getElementById('elevationContainer').style.display = 'none';
        }
    }

    function updateMode() {
        if (mode === 'select') {
            if (mapObj) mapObj.getContainer().style.cursor = 'crosshair';
        } else {
            if (mapObj) mapObj.getContainer().style.cursor = 'grab';
        }
    }

    function init() {
        mapObj = findMap();
        if (!mapObj) {
            setTimeout(init, 300);
            return;
        }
        setup();
    }

    function setup() {
        mapObj.on('click', async function(e) {
            if (mode !== 'select') return;

            if (marker) mapObj.removeLayer(marker);
            marker = L.circleMarker(e.latlng, {
                radius: 5,
                color: '#3b82f6',
                fillColor: '#3b82f6',
                fillOpacity: 0.7,
                weight: 2
            }).addTo(mapObj);

            selectedPoint = e.latlng;
            document.getElementById('latVal').innerText = selectedPoint.lat.toFixed(6);
            document.getElementById('lonVal').innerText = selectedPoint.lng.toFixed(6);

            await fetchElevation(selectedPoint.lat, selectedPoint.lng);

            document.getElementById('submitBtn').disabled = false;
        });

        document.getElementById('selectBtn').onclick = function() {
            mode = 'select';
            this.classList.add('active');
            document.getElementById('panBtn').classList.remove('active');
            updateMode();
        };

        document.getElementById('panBtn').onclick = function() {
            mode = 'pan';
            this.classList.add('active');
            document.getElementById('selectBtn').classList.remove('active');
            updateMode();
        };

        document.getElementById('submitBtn').onclick = async function() {
            if (!selectedPoint) return;
            this.disabled = true;
            this.innerText = "Отправка...";
            try {
                const res = await fetch('/set_start_point', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        session_id: sessionId,
                        lat: selectedPoint.lat,
                        lon: selectedPoint.lng
                    })
                });
                const data = await res.json();
                if (data.status === 'ok') {
                    window.location.href = '/analyze_page';
                } else {
                    alert("Ошибка сервера");
                    this.disabled = false;
                    this.innerText = "Подтвердить";
                }
            } catch (e) {
                alert("Сетевая ошибка");
                this.disabled = false;
                this.innerText = "Подтвердить";
            }
        };

        updateMode();
    }

    init();
})();