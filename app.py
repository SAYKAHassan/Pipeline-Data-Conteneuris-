import os
import sys
import subprocess
import base64
from dash import Dash, dcc, html, Input, Output, State
import dash_bootstrap_components as dbc

# ─── Config ───────────────────────────────────────────────────
UPLOAD_DIR = "/app/data_source"
os.makedirs(UPLOAD_DIR, exist_ok=True)
PYTHON_EXEC = sys.executable

app = Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])
app.title = "OCP Jorf Lasfar — ETL"

# ─── CSS ──────────────────────────────────────────────────────
custom_css = """
body { background-color: #0d0f1a !important; }
.glass-card {
    background: linear-gradient(135deg, #1a1d2e 0%, #1e2235 100%) !important;
    border: 1px solid #2a3050 !important;
    border-radius: 18px !important;
    box-shadow: 0 20px 40px rgba(0,0,0,0.7) !important;
}
.upload-zone { transition: all 0.3s ease !important; }
.upload-zone:hover {
    border-color: #00d2ff !important;
    background-color: rgba(0,210,255,0.05) !important;
    transform: scale(1.01) !important;
}
.btn-neon {
    background: linear-gradient(135deg, #0052D4, #4364F7, #6FB1FC) !important;
    border: none !important; color: white !important;
    transition: all 0.3s ease !important;
}
.btn-neon:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 20px rgba(67,100,247,0.5) !important;
}
.stat-box {
    background: rgba(255,255,255,0.04);
    border: 1px solid #2a3050;
    border-radius: 10px;
    padding: 14px;
    text-align: center;
}
"""

app.index_string = f"""<!DOCTYPE html>
<html>
    <head>
        {{%metas%}}
        <title>OCP Jorf Lasfar — ETL</title>
        {{%favicon%}}
        {{%css%}}
        <style>{custom_css}</style>
    </head>
    <body>
        {{%app_entry%}}
        <footer>{{%config%}}{{%scripts%}}{{%renderer%}}</footer>
    </body>
</html>"""

# ─── Layout ───────────────────────────────────────────────────
app.layout = dbc.Container([

    html.Br(),

    # ── Header ──
    dbc.Row(dbc.Col(html.Div([
        html.H2(" OCP Jorf Lasfar", className="fw-bold mb-1",
                style={"color": "#00d2ff", "letterSpacing": "1px"}),
        html.P("Plateforme d'Import ETL — Data Warehouse SFE",
               style={"color": "#7a8ba8", "fontSize": "14px"}),
    ], className="text-center mb-4"))),

    # ── Main Card ──
    dbc.Row(
        dbc.Col(
            dbc.Card([
                dbc.CardBody([

                    # Zone upload
                    dcc.Upload(
                        id='upload-data',
                        children=html.Div([
                            html.Span("📂", style={"fontSize": "36px"}),
                            html.Br(), html.Br(),
                            html.Span("Glissez vos fichiers Excel ici  ", style={"color": "#8a9bb8"}),
                            html.Span("ou Parcourir", style={"color": "#00d2ff", "fontWeight": "bold",
                                                              "textDecoration": "underline", "cursor": "pointer"})
                        ]),
                        className="upload-zone",
                        style={
                            'width': '100%', 'height': '150px',
                            'lineHeight': 'normal',
                            'borderWidth': '2px', 'borderStyle': 'dashed',
                            'borderColor': '#3a4560', 'borderRadius': '12px',
                            'textAlign': 'center', 'paddingTop': '30px',
                            'backgroundColor': '#141729', 'cursor': 'pointer',
                            'marginBottom': '16px'
                        },
                        multiple=True
                    ),

                    # Fichiers sélectionnés
                    html.Div(id='output-data-upload', className="mb-3 text-center"),

                    # Bouton ETL
                    dbc.Button(
                        [html.Span("🚀"), "  LANCER L'INTÉGRATION ETL"],
                        id='run-etl',
                        className="w-100 fw-bold btn-neon",
                        size="lg", n_clicks=0,
                        style={"borderRadius": "30px", "padding": "14px",
                               "letterSpacing": "1.5px", "fontSize": "15px"}
                    ),

                    # Loading + résultat
                    dcc.Loading(
                        id="loading-etl", type="dot", color="#00d2ff",
                        children=html.Div(id='status-message', className="mt-4")
                    ),

                    # Stats dernière exécution
                    html.Div(id='stats-section', className="mt-3"),

                ])
            ], className="glass-card"),
            width=12, lg=8, xl=6
        ),
        justify="center"
    ),

    # ── Fichiers existants ──
    dbc.Row(
        dbc.Col([
            html.Hr(style={"borderColor": "#2a3050", "marginTop": "32px"}),
            html.H6("📁 Fichiers dans data_source", style={"color": "#7a8ba8"},
                    className="mb-3"),
            html.Div(id='existing-files'),
            dbc.Button("🔄 Actualiser", id='refresh-btn', color="secondary",
                       size="sm", className="mt-2", n_clicks=0),
        ], width=12, lg=8, xl=6),
        justify="center"
    ),

    # Interval pour refresh auto
    dcc.Interval(id='interval', interval=5000, n_intervals=0),

    html.Div(html.Small("© 2026 OCP Jorf Lasfar — Système ETL Sécurisé",
                        style={"color": "#3a4560"}),
             className="text-center mt-5 mb-3"),

], fluid=True, style={"backgroundColor": "#0d0f1a", "minHeight": "100vh", "paddingTop": "5vh"})


# ─── Helpers ──────────────────────────────────────────────────
def save_file(name, content):
    safe_name = os.path.basename(name)
    if not safe_name:
        raise ValueError(f"Nom invalide: {name!r}")
    header, encoded = content.split(",", 1)
    decoded = base64.b64decode(encoded)
    with open(os.path.join(UPLOAD_DIR, safe_name), "wb") as f:
        f.write(decoded)
    return safe_name


def get_existing_files():
    try:
        files = [f for f in os.listdir(UPLOAD_DIR)
                 if f.lower().endswith(('.xlsx', '.csv')) and not f.startswith('~$')]
        return sorted(files)
    except Exception:
        return []


# ─── Callbacks ────────────────────────────────────────────────

@app.callback(
    Output('output-data-upload', 'children'),
    Input('upload-data', 'contents'),
    State('upload-data', 'filename')
)
def show_selected(contents, names):
    if not contents:
        return ""
    return html.Div([
        dbc.Badge(f"{len(names)} fichier(s) sélectionné(s)", color="info",
                  className="fs-6 mb-2 px-3 py-2"),
        html.Div(", ".join(names),
                 style={"color": "#8a9bb8", "fontSize": "12px", "wordBreak": "break-all"})
    ])


@app.callback(
    Output('existing-files', 'children'),
    Input('interval', 'n_intervals'),
    Input('refresh-btn', 'n_clicks')
)
def show_existing_files(n, clicks):
    files = get_existing_files()
    if not files:
        return html.P("Aucun fichier dans data_source",
                      style={"color": "#3a4560", "fontSize": "13px"})
    return html.Div([
        html.Div([
            html.Span("📊 ", style={"fontSize": "14px"}),
            html.Span(f, style={"fontSize": "13px", "color": "#c8d6f0"})
        ], style={
            "padding": "8px 14px",
            "marginBottom": "6px",
            "background": "rgba(255,255,255,0.03)",
            "borderRadius": "8px",
            "border": "1px solid #2a3050"
        }) for f in files
    ])


@app.callback(
    Output('status-message', 'children'),
    Output('stats-section', 'children'),
    Input('run-etl', 'n_clicks'),
    State('upload-data', 'contents'),
    State('upload-data', 'filename'),
    prevent_initial_call=True
)
def run_pipeline(n_clicks, contents, names):
    if not n_clicks or n_clicks < 1:
        return "", ""

    if not contents or not names:
        return dbc.Alert(
            "⚠️ Sélectionnez au moins un fichier avant de lancer l'ETL.",
            color="warning",
            style={"backgroundColor": "#332701", "color": "#ffda6a",
                   "border": "1px solid #ffda6a"}
        ), ""

    # Sauvegarder les fichiers
    saved, errors = [], []
    for content, name in zip(contents, names):
        try:
            saved.append(save_file(name, content))
        except Exception as e:
            errors.append(f"{name}: {e}")

    if errors:
        return dbc.Alert([
            html.Strong("❌ Erreur sauvegarde: "),
            html.Pre("\n".join(errors),
                     style={"whiteSpace": "pre-wrap", "fontSize": "12px"})
        ], color="danger"), ""

    # Lancer ETL
    try:
        result = subprocess.run(
            [PYTHON_EXEC, '/app/etl_pipeline.py'],
            capture_output=True, text=True, timeout=300,
            env={**os.environ, 'DB_HOST': os.getenv('DB_HOST', 'mysql_db'),
                 'DB_PORT': os.getenv('DB_PORT', '3306')}
        )

        if result.returncode == 0:
            # Parser les stats depuis stdout
            output = result.stdout
            stats = {}
            for line in output.split('\n'):
                for key in ['records_inserted', 'records_read', 'records_rejected',
                            'records_duplicated', 'files_processed', 'files_failed']:
                    if key in line and ':' in line:
                        try:
                            stats[key] = int(line.split(':')[-1].strip())
                        except Exception:
                            pass

            alert = dbc.Alert(
                f"✅ Import réussi — {len(saved)} fichier(s) traité(s)",
                color="success",
                style={"backgroundColor": "#173b24", "color": "#75b798",
                       "border": "1px solid #75b798", "fontWeight": "bold"}
            )

            stats_ui = dbc.Row([
                dbc.Col(html.Div([
                    html.H4(stats.get('records_inserted', '—'),
                            style={"color": "#00d2ff", "marginBottom": "2px"}),
                    html.Small("Insérés", style={"color": "#7a8ba8"})
                ], className="stat-box")),
                dbc.Col(html.Div([
                    html.H4(stats.get('records_read', '—'),
                            style={"color": "#6FB1FC", "marginBottom": "2px"}),
                    html.Small("Lus", style={"color": "#7a8ba8"})
                ], className="stat-box")),
                dbc.Col(html.Div([
                    html.H4(stats.get('records_duplicated', '—'),
                            style={"color": "#ffa502", "marginBottom": "2px"}),
                    html.Small("Doublons", style={"color": "#7a8ba8"})
                ], className="stat-box")),
                dbc.Col(html.Div([
                    html.H4(stats.get('records_rejected', '—'),
                            style={"color": "#ff4757", "marginBottom": "2px"}),
                    html.Small("Rejetés", style={"color": "#7a8ba8"})
                ], className="stat-box")),
            ], className="g-2 mt-1")

            return alert, stats_ui

        else:
            err = result.stderr or result.stdout or "Pas de détails."
            return dbc.Alert([
                html.Strong("❌ Échec ETL"),
                html.Pre(err[:1000], style={"whiteSpace": "pre-wrap",
                                             "fontSize": "11px", "marginTop": "8px"})
            ], color="danger",
               style={"backgroundColor": "#2c1515", "border": "1px solid #ea868f"}), ""

    except subprocess.TimeoutExpired:
        return dbc.Alert("⏱️ Timeout: ETL > 5 minutes. Vérifiez les logs.",
                         color="warning"), ""
    except Exception as e:
        return dbc.Alert(f"❌ Erreur système: {e}", color="danger"), ""


# ─── Run ──────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=False, port=8050)