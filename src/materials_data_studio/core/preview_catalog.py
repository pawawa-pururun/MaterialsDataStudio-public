"""Format shared by generated graph previews and their lightweight loader."""

FORMAT = "mds-graph-previews-1"
CELL_WIDTH, CELL_HEIGHT, COLUMNS = 96, 28, 16
IMAGE_FILES = {1: "graph-previews.png", 2: "graph-previews@2x.png"}
INPUT_FILES = (
    "scripts/render_graph_previews.py",
    "src/materials_data_studio/core/preview_catalog.py",
    "src/materials_data_studio/tools/preview_render.py",
    "src/materials_data_studio/tools/pxp_markers.py",
    "src/materials_data_studio/tools/pxp_render.py",
    "src/materials_data_studio/tools/pxp_style.py",
)
