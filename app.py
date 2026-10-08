import os
import uuid
import time
import shutil
import numpy as np
import rasterio
import folium
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
import webbrowser
import threading
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image

from core.flood_fill import FloodFiller

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['RESULTS_FOLDER'] = 'results'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)

session_data = {}

def cleanup_folder(folder_path):
    """Удаляет все файлы в папке, оставляя саму папку."""
    if not os.path.exists(folder_path):
        return 0
    file_count = 0
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
                file_count += 1
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
                file_count += 1
        except Exception as e:
            print(f'Ошибка удаления {file_path}: {e}')
    return file_count

def get_cell_size_in_meters(src):
    transform = src.transform
    cell_size_x = abs(transform[0])
    cell_size_y = abs(transform[4])
    if src.crs and src.crs.is_geographic:
        avg_lat = (src.bounds.bottom + src.bounds.top) / 2
        meters_per_degree_lat = 111320
        meters_per_degree_lon = 111320 * np.cos(np.radians(avg_lat))
        cell_size_m_x = cell_size_x * meters_per_degree_lon
        cell_size_m_y = cell_size_y * meters_per_degree_lat
        return (cell_size_m_x + cell_size_m_y) / 2
    else:
        return (cell_size_x + cell_size_y) / 2

@app.route('/get_elevation', methods=['POST'])
def get_elevation():
    data = request.json
    session_id = data.get('session_id')
    lon = data.get('lon')
    lat = data.get('lat')
    if session_id not in session_data:
        return jsonify({'error': 'Session not found'}), 400
    sess = session_data[session_id]
    dem = np.array(sess['dem'])
    bounds = sess['src_bounds']
    transform = sess['src_transform']
    col = int((lon - bounds[0]) / transform[0])
    row = int((lat - bounds[3]) / transform[4])
    if 0 <= row < dem.shape[0] and 0 <= col < dem.shape[1]:
        elevation = float(dem[row, col])
        return jsonify({'elevation': elevation})
    else:
        return jsonify({'error': 'Point outside raster'}), 400

def generate_map_for_point_selection(tiff_path, session_id):
    with rasterio.open(tiff_path) as src:
        bounds = src.bounds
        FIXED_CENTER_LON = 50.1
        FIXED_CENTER_LAT = 53.2
        FIXED_ZOOM = 13  # уровень масштабирования (чем больше, тем ближе)

        m = folium.Map(
            location=[FIXED_CENTER_LAT, FIXED_CENTER_LON],
            zoom_start=FIXED_ZOOM,
            control_scale=True
        )

        folium.TileLayer(
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            attr='Esri',
            name='Спутник'
        ).add_to(m)
        folium.TileLayer('OpenStreetMap', name='Карта').add_to(m)

        folium.Rectangle(
            bounds=[[bounds.bottom, bounds.left], [bounds.top, bounds.right]],
            color='red',
            weight=3,
            fill=False,
            tooltip='Область данных'
        ).add_to(m)

        # HTML-код панели управления + подключение внешних CSS/JS
        html_code = f"""
        <link rel="stylesheet" href="{url_for('static', filename='select_point.css')}">
        <div class="control-panel">
            <div class="panel-title">
                Выберите точку старта 
            </div>
            <div class="mode-buttons">
                <button id="selectBtn" class="mode-btn active">
                    Выбор
                </button>
                <button id="panBtn" class="mode-btn">
                    Навигация
                </button>
            </div>
            <div class="info-card">
                <div class="coord-row">
                    <span>Широта:</span>
                    <span id="latVal" class="coord-value">—</span>
                </div>
                <div class="coord-row">
                    <span>Долгота:</span>
                    <span id="lonVal" class="coord-value">—</span>
                </div>
                <div id="elevationContainer" class="elevation-row" style="display: none;">
                    <span>Высота:</span>
                    <span id="elevVal" class="coord-value">— м</span>
                </div>
            </div>
            <button id="submitBtn" disabled>Подтвердить</button>
        </div>
        <div id="pointSelectionPanel" data-session-id="{session_id}" style="display:none;"></div>
        <script src="{url_for('static', filename='select_point.js')}"></script>
        """
        m.get_root().html.add_child(folium.Element(html_code))
        folium.LayerControl().add_to(m)

        map_path = os.path.join(app.config['RESULTS_FOLDER'], f'select_point_{session_id}.html')
        m.save(map_path)
        return map_path

def generate_result_map(dem, flood_mask, start_point, water_level, stats, src, session_id):
    bounds = src.bounds
    transform = src.transform

    FIXED_CENTER_LON = (bounds.left + bounds.right) / 2
    FIXED_CENTER_LAT = (bounds.top + bounds.bottom) / 2
    FIXED_CENTER_LON = 50.0 #50.1
    FIXED_CENTER_LAT = 53.1 #53.2
    FIXED_ZOOM = 13  # уровень масштабирования (чем больше, тем ближе)
    print(FIXED_CENTER_LAT)
    print(FIXED_CENTER_LON)
    print("123")
    center_lat = (bounds.top + bounds.bottom) / 2
    center_lon = (bounds.left + bounds.right) / 2

    height, width = flood_mask.shape
    depth_map = np.zeros((height, width), dtype=np.float32)
    depth_map[flood_mask] = water_level - dem[flood_mask]
    max_depth = np.max(depth_map[flood_mask]) if np.any(flood_mask) else 0.01
    if max_depth < 0.01:
        max_depth = 0.01

    cmap = LinearSegmentedColormap.from_list('depth_cmap', ['#87CEEB', '#4169E1', '#0000CD', '#00008B'])
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    if np.any(flood_mask):
        norm_depth = depth_map[flood_mask] / max_depth
        colors = cmap(norm_depth)
        rgba[flood_mask, :3] = (colors[:, :3] * 255).astype(np.uint8)
        rgba[flood_mask, 3] = 180
    else:
        rgba[:, :, 3] = 0

    img = Image.fromarray(rgba, mode='RGBA')
    overlay_path = os.path.join(app.config['RESULTS_FOLDER'], f'flood_overlay_{session_id}.png')
    img.save(overlay_path)

    m = folium.Map(location=[FIXED_CENTER_LAT, FIXED_CENTER_LON], zoom_start=FIXED_ZOOM)
    folium.TileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Спутник'
    ).add_to(m)

    folium.TileLayer('OpenStreetMap', name='Карта').add_to(m)

    folium.raster_layers.ImageOverlay(
        image=overlay_path,
        bounds=[[bounds.bottom, bounds.left], [bounds.top, bounds.right]],
        opacity=0.7,
        name='Зона затопления'
    ).add_to(m)

    folium.Rectangle(
        bounds=[[bounds.bottom, bounds.left], [bounds.top, bounds.right]],
        color='red',
        weight=2,
        fill=False,
        popup='Границы ЦМР'
    ).add_to(m)

    def pixel_to_geo(x, y):
        lon = float(bounds.left + x * transform[0])
        lat = float(bounds.top + y * transform[4])
        return [lat, lon]

    start_lat, start_lon = pixel_to_geo(start_point[0], start_point[1])
    folium.Marker(
        location=[start_lat, start_lon],
        popup=f'Стартовая точка<br>Высота: {dem[start_point[1], start_point[0]]:.1f} м',
        icon=folium.Icon(color='red', icon='tint', prefix='fa')
    ).add_to(m)

    flooded_cells = stats.get('flooded_cells', 0)
    cell_area = stats.get('cell_area', 1)
    total_volume = stats.get('total_volume', 0)
    avg_depth = stats.get('avg_depth', 0)
    max_depth_val = stats.get('max_depth', max_depth)

    legend_html = f"""
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 1000; background: white; padding: 15px; border-radius: 12px; box-shadow: 0 0 15px rgba(0,0,0,0.3); min-width: 260px; font-family: 'Segoe UI', Arial, sans-serif;">
        <h4 style="margin: 0 0 10px 0;">📊 Результаты анализа</h4>
        <hr style="margin: 5px 0;">
        <p><b>Уровень воды:</b> {water_level:.1f} м</p>
        <p><b>Средняя глубина:</b> {avg_depth:.1f} м</p>
        <p><b>Макс. глубина:</b> {max_depth_val:.1f} м</p>
        <hr style="margin: 10px 0;">
        <div>
            <b>Шкала глубины</b><br>
            <div style="width: 100%; height: 20px; background: linear-gradient(to right, #87CEEB, #4169E1, #0000CD, #00008B); border-radius: 4px; margin: 8px 0;"></div>
            <div style="display: flex; justify-content: space-between;">
                <span>0 м</span>
                <span>{max_depth_val:.1f} м</span>
            </div>
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    folium.LayerControl().add_to(m)

    result_path = os.path.join(app.config['RESULTS_FOLDER'], f'result_map_{session_id}.html')
    m.save(result_path)
    return result_path

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/set_start_point', methods=['POST'])
def set_start_point():
    data = request.json
    session_id = data.get('session_id')
    lat = data.get('lat')
    lon = data.get('lon')
    if not session_id or session_id not in session_data:
        return jsonify({'status': 'error', 'error': 'Invalid session'}), 400
    session_data[session_id]['start_point'] = (lon, lat)
    return jsonify({'status': 'ok'})

@app.route('/get_start_point', methods=['GET'])
def get_start_point():
    session_id = request.args.get('session_id')
    if not session_id or session_id not in session_data:
        return jsonify({'error': 'Session not found'}), 404
    point = session_data[session_id].get('start_point')
    if point:
        return jsonify({'lat': point[1], 'lon': point[0]})
    else:
        return jsonify({'lat': None, 'lon': None})

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'tiff_file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['tiff_file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if not file.filename.lower().endswith(('.tif', '.tiff')):
        return jsonify({'error': 'Only TIFF files allowed'}), 400

    session_id = str(uuid.uuid4())
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], f'{session_id}.tif')
    file.save(filepath)

    with rasterio.open(filepath) as src:
        dem = src.read(1).astype(np.float32)
        cell_size = get_cell_size_in_meters(src)
        session_data[session_id] = {
            'filepath': filepath,
            'dem': dem.tolist(),
            'cell_size': cell_size,
            'src_bounds': [src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top],
            'src_transform': list(src.transform),
            'src_crs': str(src.crs),
            'shape': dem.shape
        }

    map_path = generate_map_for_point_selection(filepath, session_id)
    return jsonify({'session_id': session_id, 'map_url': url_for('serve_results', filename=f'select_point_{session_id}.html')})

@app.route('/analyze_page')
def analyze_page():
    return render_template('analyze.html')

@app.route('/results/<path:filename>')
def serve_results(filename):
    return send_from_directory(app.config['RESULTS_FOLDER'], filename)

@app.route('/run_analysis', methods=['POST'])
def run_analysis():
    start_time_full = time.time()
    data = request.json
    session_id = data.get('session_id')
    start_lon = data.get('lon')
    start_lat = data.get('lat')
    water_level = data.get('water_level')

    if session_id not in session_data:
        return jsonify({'error': 'Session expired'}), 400
    if water_level is None:
        return jsonify({'error': 'water_level is required'}), 400

    sess = session_data[session_id]
    dem = np.array(sess['dem'], dtype=np.float32)
    cell_size = sess['cell_size']
    bounds = sess['src_bounds']
    transform = sess['src_transform']

    col = int((start_lon - bounds[0]) / transform[0])
    row = int((start_lat - bounds[3]) / transform[4])

    if not (0 <= row < dem.shape[0] and 0 <= col < dem.shape[1]):
        return jsonify({'error': 'Start point out of raster bounds'}), 400

    try:
        start_time = time.time()
        filler = FloodFiller(dem, cell_size)
        result = filler.compute_flood(start_x=col, start_y=row, water_level=float(water_level))
        execution_time = time.time() - start_time
        print(f"Flood time: {execution_time:.3f}s")

        class FakeSrc: pass
        fake_src = FakeSrc()
        fake_src.bounds = type('Bounds', (), {
            'left': bounds[0], 'bottom': bounds[1],
            'right': bounds[2], 'top': bounds[3]
        })()
        fake_src.transform = transform
        fake_src.crs = sess['src_crs']

        result_map_path = generate_result_map(
            dem, result.flood_mask, (col, row), result.water_level,
            {
                'flooded_cells': result.flooded_cells,
                'cell_area': cell_size * cell_size,
                'total_volume': result.total_volume,
                'avg_depth': result.avg_depth,
                'max_depth': result.max_depth
            },
            fake_src, session_id
        )
        execution_time_full = time.time() - start_time_full
        print(f"Flood time FOOL: {execution_time_full:.3f}s")

        return jsonify({
            'stats': {
                'flooded_cells': result.flooded_cells,
                'area_ha': float(result.flooded_cells * cell_size * cell_size / 10000),
                'volume_m3': float(result.total_volume),
                'avg_depth': float(result.avg_depth),
                'max_depth': float(result.max_depth),
                'water_level': float(result.water_level)
            },
            'iterations': result.iterations,
            'result_map_url': url_for('serve_results', filename=f'result_map_{session_id}.html')
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    cleanup_folder(app.config['UPLOAD_FOLDER'])
    cleanup_folder(app.config['RESULTS_FOLDER'])
    session_data.clear()
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        threading.Timer(1.5, lambda: webbrowser.open('http://127.0.0.1:5000')).start()
    app.run(debug=True, port=5000)