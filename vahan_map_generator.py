import folium
from folium import Element
from folium.plugins import MarkerCluster, MiniMap

def create_vahan_map(output_filename="map.html"):
    map_center = [28.541295, 77.387591]

    # 1. Initialize map with interactive controls enabled
    vahan_map = folium.Map(
        location=map_center,
        zoom_start=13,
        tiles=None,
        control_scale=True,
        zoom_control=True,
        scroll_wheel_zoom=True,
        dragging=True
    )

    # 2. HD Google Map Layers
    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        attr="Google Maps",
        name="Google Streets",
        max_zoom=20,
        subdomains=["mt0", "mt1", "mt2", "mt3"]
    ).add_to(vahan_map)

    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        attr="Google Satellite",
        name="Google Satellite (HD)",
        max_zoom=20,
        subdomains=["mt0", "mt1", "mt2", "mt3"]
    ).add_to(vahan_map)

    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=p&x={x}&y={y}&z={z}",
        attr="Google Terrain",
        name="Google Terrain",
        max_zoom=20,
        subdomains=["mt0", "mt1", "mt2", "mt3"]
    ).add_to(vahan_map)

    # 3. Demo Camera Data (C4 updated with 28°33'54.4"N 77°22'47.5"E -> 28.565111, 77.379861)
    camera_nodes = [
        {"id": "Camera 1", "code": "C1", "lat": 28.533652, "lon": 77.385166},
        {"id": "Camera 2", "code": "C2", "lat": 28.535277, "lon": 77.385791},
        {"id": "Camera 3", "code": "C3", "lat": 28.541295, "lon": 77.387591},
        {"id": "Camera 4", "code": "C4", "lat": 28.565111, "lon": 77.379861}
    ]

    # Plot Camera Markers
    for cam in camera_nodes:
        popup_content = f"""
        <div style="font-family: sans-serif; font-size: 12px; color: #0f172a; width: 150px;">
            <b style="color: #1e3a8a; font-size: 14px;">{cam['id']}</b><br>
            <span style="color: #475569;">Lat: {cam['lat']}</span><br>
            <span style="color: #475569;">Lon: {cam['lon']}</span><br>
            <span style="color: #16a34a; font-weight: bold;">● Live Stream</span>
        </div>
        """
        folium.Marker(
            location=[cam['lat'], cam['lon']],
            popup=folium.Popup(popup_content, max_width=200),
            tooltip=f"{cam['id']} Node",
            icon=folium.Icon(color="blue", icon="video-camera", prefix="fa")
        ).add_to(vahan_map)

    # 4. Simulated Live Vehicle Detections
    detected_vehicles = [
        {"plate": "PB54H0997", "owner": "Priya Verma", "cam": "Camera 1", "lat": 28.533652, "lon": 77.385166},
        {"plate": "CH01BL5800", "owner": "Aarav Sharma", "cam": "Camera 2", "lat": 28.535277, "lon": 77.385791},
        {"plate": "HR03V0440", "owner": "Sneha Deshmukh", "cam": "Camera 3", "lat": 28.541295, "lon": 77.387591},
        {"plate": "CH01CJ4751", "owner": "Ananya Hegde", "cam": "Camera 4", "lat": 28.565111, "lon": 77.379861}
    ]

    scan_cluster = MarkerCluster(name="Live Vehicle Detections").add_to(vahan_map)

    for vehicle in detected_vehicles:
        vehicle_popup = f"""
        <div style="font-family: monospace; font-size: 12px; color: #0f172a; width: 170px;">
            <b style="color: #2563eb; font-size: 14px;">{vehicle['plate']}</b><br>
            <hr style="margin: 4px 0;">
            <b>Owner:</b> {vehicle['owner']}<br>
            <b>Detected At:</b> {vehicle['cam']}
        </div>
        """
        folium.CircleMarker(
            location=[vehicle['lat'], vehicle['lon']],
            radius=7,
            popup=folium.Popup(vehicle_popup, max_width=220),
            tooltip=f"Vehicle: {vehicle['plate']}",
            color="#2563eb",
            fill=True,
            fill_color="#3b82f6",
            fill_opacity=0.9
        ).add_to(scan_cluster)

    # 5. Inject Floating Camera Control Panel & JS Pan Logic
    map_name = vahan_map.get_name()
    camera_panel_html = f"""
    <!-- Bottom-Left Camera Navigation Overlay -->
    <div id="cam-nav-panel" style="
        position: absolute;
        bottom: 25px;
        left: 15px;
        z-index: 1000;
        background: rgba(15, 23, 42, 0.90);
        backdrop-filter: blur(8px);
        padding: 10px 14px;
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 0.15);
        box-shadow: 0 4px 15px rgba(0,0,0,0.4);
        font-family: Arial, sans-serif;">
        <div style="color: #94a3b8; font-size: 11px; font-weight: bold; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px;">
            Camera Shortcuts
        </div>
        <div style="display: flex; gap: 8px;">
            <button onclick="panToCam(28.533652, 77.385166)" style="background: #2563eb; color: white; border: none; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 12px; transition: 0.2s;">C1</button>
            <button onclick="panToCam(28.535277, 77.385791)" style="background: #2563eb; color: white; border: none; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 12px; transition: 0.2s;">C2</button>
            <button onclick="panToCam(28.541295, 77.387591)" style="background: #2563eb; color: white; border: none; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 12px; transition: 0.2s;">C3</button>
            <button onclick="panToCam(28.565111, 77.379861)" style="background: #2563eb; color: white; border: none; padding: 6px 12px; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 12px; transition: 0.2s;">C4</button>
        </div>
    </div>

    <script>
        function panToCam(lat, lon) {{
            var mapInstance = {map_name};
            mapInstance.flyTo([lat, lon], 18, {{
                animate: true,
                duration: 1.2
            }});
        }}

        // Universal click to focus anywhere
        document.addEventListener("DOMContentLoaded", function() {{
            setTimeout(function() {{
                var mapInstance = {map_name};
                mapInstance.on('click', function(e) {{
                    mapInstance.flyTo(e.latlng, 18, {{
                        animate: true,
                        duration: 1.0
                    }});
                }});
            }}, 500);
        }});
    </script>
    """
    vahan_map.get_root().html.add_child(Element(camera_panel_html))

    # Controls
    folium.LayerControl(position="topright", collapsed=False).add_to(vahan_map)

    # Save to file
    vahan_map.save(output_filename)
    print(f"[SUCCESS] Interactive map with C1-C4 Navigation Panel saved as '{output_filename}'")

if __name__ == "__main__":
    create_vahan_map("map.html")